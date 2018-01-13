import red
import discord
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from cogs.utils import checks
import asyncio
import logging
import os
from copy import deepcopy
import json
import threading
from random import randint

log = logging.getLogger("red.rolecall")

SETTINGS_PATH = "data/rolecall/settings.json"
DEFAULT_SETTINGS = {}

ROLE_RECORD_STRUCT = {
    "ROLE_ID": None,
    "ROLE_NAME": None
    }

RGB_VALUE_LIMIT = 16777215


class Entry:
    """ Entry on the roleboard. Constructor only accepts one role because only a single role can be specified in the add command. Emoji is a string to 
    account for both custom and non-custom emojis """

    def __init__(self, server: discord.Server, roleboard_channel: discord.Channel, content_or_message_id: str, author: discord.Member, role: discord.Role=None, emoji: str=None):
        self.server = server
        self.roleboard_channel = roleboard_channel
        self.content_or_message_id = content_or_message_id
        self.author = author
        self.role = role or None
        self.emoji = emoji or None

class RoleCall:
    """Self-assign roles via reactions on a roleboard
    or via command (for mobile users)"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(SETTINGS_PATH)
        self.reaction_queue = {}
        self.reaction_user_queue = set()
        self.queue_processor_task = bot.loop.create_task(self.queue_processor())

    def _record_entry(self, entry: Entry):
        """ record entry to settings file """

        server = self.settings[entry.server.id]
        server.setdefault(entry.roleboard_channel.id, {})
        server[entry.roleboard_channel.id].setdefault(entry.content_or_message_id, {})
        keyring = server[entry.roleboard_channel.id][entry.content_or_message_id]
        keyring[entry.emoji] = deepcopy(ROLE_RECORD_STRUCT)
        keyring[entry.emoji]['ROLE_ID'] = entry.role.id
        keyring[entry.emoji]['ROLE_NAME'] = entry.role.name
        self._save()

    def _check_entry(self, entry: Entry):
        """ Checks if entry exists in the settings file. 

        Returns true if it does, otherwise, returns false.
        """ 

        entries = self.settings[entry.server.id][entry.roleboard_channel.id]
        if entry.content_or_message_id in entries:
            return True
        else:
            return False

    async def _get_role_from_entry(self, entry: Entry):
        """ Accesses board entry and retrieves role that corresponds 
        to the emoji given """

        server_id = entry.server.id
        roleboard_id = entry.roleboard_channel.id
        message_id = entry.content_or_message_id
        keyring = self.settings[server_id][roleboard_id][message_id]
        role_name = keyring[entry.emoji]['ROLE_NAME']
        role = await self.get_or_create('role', role_name, entry.server)
        return role

    @commands.group(pass_context=True, no_pm=True)
    async def roleboard(self, ctx):
        """change roleboard settings"""
        server = ctx.message.server

        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)
        else:
            self.settings.setdefault(server.id, deepcopy(DEFAULT_SETTINGS))

    @roleboard.command(pass_context=True, name="channel", no_pm=True)
    async def roleboard_channel(self, ctx, channel: discord.Channel=None):
        """Set the roleboard for this server.

        Leave blank to turn off the roleboard
        """
        server = ctx.message.server
        #channel = ctx.message.channel
        author = ctx.message.author


        """
        TODO: limit amount of messages. when over,
            log warning and DM server owner /
            infractor (if he's adding a new invite)
        ^ invalid todo due to updated implementation notes
        """

        settings = self.settings[server.id]

        if channel is None and not \
           await self.prompt(ctx, "turn off the roleboard? (yes/no)"):
            if settings["ROLEBOARD"] is None:
                rb_channel = None
            else:
                rb_channel = get_channel_by_name(server, settings["ROLEBOARD"])
            await self.bot.say('Ok. Roleboard is still {}'
                               .format(rb_channel and rb_channel.   mention))
            return

        settings["ROLEBOARD"] = channel and channel.name
        self._save()
        await self.bot.say('Roleboard is now {}'.format(channel))

    @roleboard.command(pass_context=True, name="add", no_pm=True)
    async def roleboard_add(self, ctx, role_board: discord.Channel, 
                            content_or_message_id: str, role_name: str, 
                            role_emoji: str, 
                            role_channel_name: str = None,
                            ):
        """
        Add an entry to a roleboard. If a message ID is provided, 
        post a role to the existing message/entry.
            
        Optional role_channel_name will be the name of a private
        channel that will be created for the members who hold the role. 
        Specified name must be of a non-existing channel.
        """
        server = ctx.message.server
        author = ctx.message.author

        role_obj = await self.get_or_create("role", role_name, server)

        # retrieve channel mentions in the command message
        channels = ctx.message.raw_channel_mentions

        # get emoji name
        role_emoji_name = role_emoji.replace(':','')

        # make Entry object
        entry = Entry(server, role_board, content_or_message_id, author, 
                      role=role_obj, emoji=role_emoji_name)

        # create the role's personal channel
        if role_channel_name is not None:
            everyone = discord.PermissionOverwrite(read_messages=False)
            new_role = discord.PermissionOverwrite(read_messages=True)
            try:
                await self.bot.create_channel(server, role_channel_name, 
                                              (server.default_role, everyone), 
                                              (role_obj,new_role))
            except Exception as e:
                err_msg = 'Invalid role_channel_name specified'
                await self.bot.send_message(role_board, err_msg)
                return
        # check if message ID was provided. If yes, post the new role to the 
        # message associated with the ID, if not, post the new entry to the 
        # chosen role board
        try:
            await self.post_role(entry)
        except Exception as e:
            msg = await self.post_entry(entry)
            entry.content_or_message_id = msg.id

        # record the entry
        self._record_entry(entry)

      
    async def post_entry(self, entry: Entry):
        """ post entry to chosen roleboard(channel) """

        msg = await self.bot.send_message(entry.roleboard_channel, content=entry.content_or_message_id)
        await self.bot.add_reaction(msg, entry.emoji)
        return msg

    async def post_role(self, entry: Entry):
        """ post role to chosen entry(message) """

        msg = await self.bot.get_message(entry.roleboard_channel, entry.content_or_message_id)
        await self.bot.add_reaction(msg, entry.emoji)
        return msg

    async def prompt(self, ctx, *args, **kwargs):
        """prompts author with a message (yes/no)
        the prompt is sent via bot.say with the additional args,kwargs passed

        returns True/False/None depending on the user's answer
        """
        channel = ctx.message.channel
        author = ctx.message.author
        message = await self.bot.say(*args, **kwargs)
        try:
            await self.bot.add_reaction(message, '✅')
            await self.bot.add_reaction(message, '❌')
        except:
            pass

        mcheck = lambda msg: msg.content.lower().startswith(('yes', 'no', 'cancel'))

        tasks = (self.bot.wait_for_message(author=author, timeout=15, channel=channel,
                                           check=mcheck),
                 self.bot.wait_for_reaction(user=author, timeout=15, message=message,
                                            emoji=('✅', '❌') ))

        converters = (lambda r: r.content.lower().startswith('yes'),
                      lambda r: r.reaction.emoji == '✅')

        return await wait_for_first_response(tasks, converters)

    async def on_socket_raw_receive(self, msg):
        """ Listens to reaction adds/removes and adds them to the reaction 
        queue """

        reaction = json.loads(msg)

        if reaction['t'] == 'MESSAGE_REACTION_ADD' or reaction['t'] == 'MESSAGE_REACTION_REMOVE':
            user_id = reaction['d']['user_id']
            self.reaction_queue[user_id] = reaction
            self.reaction_user_queue.add(user_id)

    async def queue_processor(self):
        """ Iterates the reaction queue every  0.0001 seconds. If reaction was added to a roleboard entry, corresponding role is assigned to user depending on the emoji pressed. If a reaction was removed, role is unassigned from user 
        """

        while True:
            if self.reaction_user_queue:
                next_key = self.reaction_user_queue.pop()
                reaction = self.reaction_queue.pop(next_key)
                await self.process_event(reaction)
            await asyncio.sleep(0.0001)

    async def process_event(self, reaction):

        """ format of raw reaction add message:

        {'d': {'channel_id': '206326891752325122', 'user_id': '208810344729018369', 'message_id': '398806773542158357', 'emoji': {'animated': False, 'id': '344074096398565376', 'name': 'blobderpy'}}, 's': 269, 't': 'MESSAGE_REACTION_ADD', 'op': 0}

        """

        """ format of raw reaction remove message:

        {"t":"MESSAGE_REACTION_REMOVE","s":308,"op":0,"d":{"user_id":"208810344729018369","message_id":"399903367175864320","emoji":{"name":"irdumbs","id":"344074096092381184","animated":false},"channel_id":"206326891752325122"}}

        """

        channel = self.bot.get_channel(reaction['d']['channel_id'])
        server = channel.server
        message_id = reaction['d']['message_id']
        message = await self.bot.get_message(channel, message_id)
        author = message.author
        emoji_name = reaction['d']['emoji']['name']

        # make Entry object to handle data
        entry = Entry(server, channel, message_id, author, 
            emoji=emoji_name)

        # check if Entry exists in settings file. 
        if self._check_entry(entry):

            # get role and user
            role = await self._get_role_from_entry(entry)
            reactor = entry.server.get_member(reaction['d']['user_id'])

            # assign role to user who added the reaction 
            if reaction['t'] == 'MESSAGE_REACTION_ADD':
                
                # assign role if client is not a bot
                if not reactor.bot:
                    await self.bot.add_roles(reactor, role)

            # unassign role from user who removed the reaction
            if reaction['t'] == 'MESSAGE_REACTION_REMOVE':
               await self.bot.remove_roles(reactor, role)
        

    def _save(self):
        return dataIO.save_json(SETTINGS_PATH, self.settings)

    def _get_object_by_name(self, otype, server, name, ignore_case=True):
        """returns object of specified type from server of specified name
        otype is discord.Role or discord.Channel
        """
        types = {
            discord.Role: 'roles',
            discord.Channel: 'channels'
        }
        li = getattr(server, types[otype])
        if ignore_case:
            match = [i for i in li if i.name.lower() == name.lower()]
        else:
            match = [i for i in li if i.name == name]
        if len(match) > 1:
            raise Exception("More than one {} found".format(types[otype][:-1]))
        return match[0]

    async def get_or_create(self, object_type: str, object_name: str, server):
        """ returns object if it exists, otherwise create the object """
        if object_type == "role":               # for roles
            role = discord.utils.get(server.roles, name=object_name)
            try:                                # try in case role = None
                if role.name == object_name:
                    return role
            except Exception as e:              # if it is None, create new role
                try:                            # try in case permission is needed

                    rand_color = discord.Colour(randint(0,RGB_VALUE_LIMIT))
                    await self.bot.create_role(server, name=object_name, 
                                               mentionable=True, 
                                               colour=rand_color)

                    await asyncio.sleep(0.05)   # sleep while role is cooking
                    role = discord.utils.get(server.roles, name=object_name)
                    return role  
                except Exception as e:
                    await self.bot.say(e)

        elif object_type == "channel":          # for channels
            channel = discord.utils.get(server.channels, name=object_name)
            try:                
                if channel.name == object_name:
                    return channel
            except Exception as e:
                try:
                    channel = await self.bot.create_channel(server, object_name)
                    return channel
                except Exception as e:
                    await self.bot.say(e)


async def wait_for_first_response(tasks, converters):
    """given a list of unawaited tasks and non-coro result parsers to be called on the results,
    this function returns the 1st result that is returned and converted

    if it is possible for 2 tasks to complete at the same time,
    only the 1st result deteremined by asyncio.wait will be returned

    returns None if none successfully complete
    returns 1st error raised if any occur (probably)
    """
    primed = [wait_for_result(t, c) for t, c in zip(tasks, converters)]
    done, pending = await asyncio.wait(primed, return_when=asyncio.FIRST_COMPLETED)
    for p in pending:
        p.cancel()

    try:
        return done.pop().result()
    except:
        return None


async def wait_for_result(task, converter):
    """await the task call and return its results parsed through the converter"""
    # why did I do this?
    return converter(await task)


def check_folders():
    paths = ("data/rolecall", )
    for path in paths:
        if not os.path.exists(path):
            print("Creating {} folder...".format(path))
            os.makedirs(path)


def check_files():
    if not dataIO.is_valid_json(SETTINGS_PATH):
        print("Creating default rolecall settings.json...")
        dataIO.save_json(SETTINGS_PATH, DEFAULT_SETTINGS)
    else:  # consistency check
        current = dataIO.load_json(SETTINGS_PATH)
        inconsistency = False
        if current.keys() != DEFAULT_SETTINGS.keys():
            for key in DEFAULT_SETTINGS.keys():
                if key not in current.keys():
                    current[key] = DEFAULT_SETTINGS[key]
                    print(
                        "Adding " + str(key) + " field to rolecall settings.json")
                    inconsistency = True
        if inconsistency:
            dataIO.save_json(SETTINGS_PATH, current)


def setup(bot: red.Bot):
    check_folders()
    check_files()
    n = RoleCall(bot)
    bot.add_cog(n)
