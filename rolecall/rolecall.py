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
from random import randint
import re
    
log = logging.getLogger("red.rolecall")

SETTINGS_PATH = "data/rolecall/settings.json"
DEFAULT_SETTINGS = {}

ROLE_RECORD_STRUCT = {
    "ROLE_ID": None,
    "ROLE_NAME": None
    }

RGB_VALUE_LIMIT = 16777215


class Entry:
    """ Entry on the roleboard. Constructor only accepts one role 
    because only a single role can be specified in the add command. 
    Emoji is a string to account for both custom and non-custom emojis """

    def __init__(self, server: discord.Server, roleboard_channel: discord.Channel, 
                 content_or_message_id: str, author: discord.Member, 
                 role: discord.Role=None, emoji: str=None):
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
        self.queue_processor_task = self.bot.loop.create_task(self.queue_processor())

    def _record_entry(self, entry: Entry):
        """ record entry to settings file """
        if isinstance(entry.emoji, discord.Emoji):
            entry.emoji = entry.emoji.name
        server = self.settings[entry.server.id]
        server.setdefault(entry.roleboard_channel.id, {})
        server[entry.roleboard_channel.id].setdefault(entry.content_or_message_id, {})
        keyring = server[entry.roleboard_channel.id][entry.content_or_message_id]
        keyring[entry.emoji] = deepcopy(ROLE_RECORD_STRUCT)
        keyring[entry.emoji]['ROLE_ID'] = entry.role.id
        keyring[entry.emoji]['ROLE_NAME'] = entry.role.name
        self._save()

    def _check_entry(self, entry: Entry):
        """ Checks if entry exists in the settings file and 
        returns true if it does, otherwise, returns false.
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

    def _get_emoji_from_entry(self, entry: Entry):
        """ Accesses entry and retrieves emoji that corresponds to the
        role given """ 

        server_id = entry.server.id
        roleboard_id = entry.roleboard_channel.id
        message_id = entry.content_or_message_id
        keyring = self.settings[server_id][roleboard_id][message_id]
        for emoji,role in keyring.items():
            if entry.role.id == role['ROLE_ID']:
                return emoji

    @commands.group(pass_context=True, no_pm=True)
    @checks.mod()
    async def rolecall(self, ctx):
        """ Add emojis to a message where each emoji corresponds to a chosen role. 
        If emoji is clicked, the corresponding role is assigned to the user. """
        server = ctx.message.server

        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)
        else:
            self.settings.setdefault(server.id, deepcopy(DEFAULT_SETTINGS))

    @rolecall.command(pass_context=True, name="add", no_pm=True)
    async def rolecall_add(self, ctx, channel: discord.Channel, 
                            content_or_message_id: str, role: str, 
                            emoji: str, private_channel: str = None,
                            ):
        """
        Add a role to a message. 
        
        channel

           The channel where the new message will be posted or the channel
           where the existing message is located

        content_or_message_id

           Contents of the message. If the message
           already exists, provide the message id instead.

        role 

           Name of the role. If a non-existing role is provided, 
           it will be created for you.

        emoji 

           Emoji corresponding to the role which users will click
           on.
 
        private_channel(Optional) 

           A private channel that members of the role will be granted access to. 
           If a non-existing channel is provided, it will be created for you.
        """
        server = ctx.message.server
        author = ctx.message.author
        origin_channel = ctx.message.channel

        # check if role was mentioned 
        nums_found = re.findall('\d+', role)
        if nums_found:
            potential_role_id = nums_found[0]
            if potential_role_id in [r.id for r in server.roles]:
                role_object = discord.utils.get(server.roles, id=potential_role_id)

        # if role was not mentioned, check if the role indicated already exists
        # if it doesn't exist, check if the bot has permissions to create a new 
        # role before creating one
        try:
            role_object
        except NameError:
            try:
                role_object = await self.get_or_create("role", role, server)
            except discord.Forbidden:
                err_msg = '❌ Your bot does not have permission to create roles'
                await self.bot.send_message(origin_channel, content=err_msg)
                return

        # check if bot has permissions to assign a role to a user
        if server.me.server_permissions.manage_roles and server.me.top_role \
        > role_object:
            pass
        else:
            err_msg = '❌ Your bot does not have permission to assign roles'
            await self.bot.send_message(origin_channel, content=err_msg)
            return

        # check if channel was mentioned
        if private_channel is None: 
            pass
        else:
            role_channel = private_channel
            nums_found = re.findall('\d+', private_channel)
            if nums_found:
                potential_channel_id = nums_found[0]
                if potential_channel_id in [c.id for c in server.channels]:
                    role_channel = self.bot.get_channel(potential_channel_id)
 
            # create the role's personal channel
            try:
                await self.create_or_edit_role_channel(server, role_object, role_channel)
            except discord.Forbidden:
                err_msg = '❌ Your bot does not have permission to create or edit a \
                channel'
                await self.bot.send_message(origin_channel, err_msg)
                return

        # get emoji name(if unicode emoji) or get emoji object(if custom emoji)
        emoji_name_or_obj = emoji.strip(':')
        try:
            potential_custom_emoji_id = re.findall('\d+', emoji_name_or_obj)[0]
            if potential_custom_emoji_id in [e.id for e in server.emojis]:
                emoji_name_or_obj = discord.utils.get(server.emojis, id=potential_custom_emoji_id)
        except IndexError as e:
            pass # determined to be a unicode emoji

        # make Entry object
        entry = Entry(server, channel, content_or_message_id, author, 
                      role=role_object, emoji=emoji_name_or_obj)

        # check if role or emoji is already used in the entry
        try:
            if self.isduplicate('role', entry):
                bound_emoji = self._get_emoji_from_entry(entry)
                bound_role_msg = "❌ the role {} is already linked to {}".format(entry.role, bound_emoji)
                await self.bot.send_message(origin_channel, content=bound_role_msg)
                return 
            if self.isduplicate('emoji', entry):
                bound_role = await self._get_role_from_entry(entry)
                bound_emoji_msg = "❌ the emoji {} is already linked to {}".format(entry.emoji, bound_role)
                await self.bot.send_message(origin_channel, content=bound_emoji_msg)
                return
        except KeyError as e:
            pass # user provided message content and not a message id

        # check if message ID was provided. If yes, and if the role is not 
        # linked to an emoji yet, post the new role to the message associated 
        # with the ID, if not, post the new entry to the chosen role board
        try:
            await self.post_role(entry)
        except discord.HTTPException as e:
            try:
                msg = await self.post_entry(entry)
                entry.content_or_message_id = msg.id
            except discord.Forbidden:
                err_msg = '❌ You do not have permission to post a message in \
                the channel {}'.format(channel)
                await self.bot.send_message(origin_channel, content=err_msg)

        # record the entry
        self._record_entry(entry)

    def isduplicate(self, otype, entry): 
        """ checks if role or emoji has already been used in the message """
        channel = self.settings[entry.server.id][entry.roleboard_channel.id]
        keyring = channel[entry.content_or_message_id]
        if otype == 'role':
            if entry.role.id in [e['ROLE_ID'] for e in keyring.values()]:
                return True
        else:
            if entry.emoji in [e for e in keyring]:
                return True
        return False

    async def create_or_edit_role_channel(self, server, role, role_channel):
        """ creates a private channel for the role. If provided channel exists,
        edits permissions of the channel in favor of the role provided. """

        if role_channel is not None:
            everyone_perms = discord.PermissionOverwrite(read_messages=False)
            new_role_perms = discord.PermissionOverwrite(read_messages=True)
            if role_channel in server.channels:
                await self.bot.edit_channel_permissions(role_channel, role, new_role_perms)
            else:
                await self.bot.create_channel(server, role_channel, 
                                             (server.default_role, everyone_perms),
                                             (role, new_role_perms))

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
            self.reaction_queue.setdefault(user_id, {})
            emoji_name = reaction['d']['emoji']['name'] 
            self.reaction_queue[user_id][emoji_name] = reaction
            self.reaction_user_queue.add(user_id)

    async def queue_processor(self):
        """ Iterates the reaction queue every  0.1 new_role_permsseconds. If reaction was 
        added to a roleboard entry, corresponding role is assigned to user 
        depending on the emoji pressed. If a reaction was removed, role is 
        unassigned from user 
        """

        while True:
            if self.reaction_user_queue:
                next_key = self.reaction_user_queue.pop()
                reaction_list = self.reaction_queue.pop(next_key)
                await self.process_event(reaction_list)
            await asyncio.sleep(0.1)

    async def process_event(self, reaction_list):

        """ format of raw reaction add message:

        {'d': {'channel_id': '206326891752325122', 'user_id': '208810344729018369', 
        'message_id': '398806773542158357', 'emoji': {'animated': False, 
        'id': '344074096398565376', 'name': 'blobderpy'}}, 's': 269, 
        't': 'MESSAGE_REACTION_ADD', 'op': 0}

        """

        """ format of raw reaction remove message:

        {"t":"MESSAGE_REACTION_REMOVE","s":308,"op":0,"d":{
        "user_id":"208810344729018369","message_id":"399903367175864320",
        "emoji":{"name":"irdumbs","id":"344074096092381184","animated":false},
        "channel_id":"206326891752325122"}}

        """
        for reaction in reaction_list.values():
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

    def __unload(self):
        self.queue_processor_task.cancel()
        

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
                rand_color = discord.Colour(randint(0,RGB_VALUE_LIMIT))
                await self.bot.create_role(server, name=object_name, 
                                           mentionable=True, 
                                           colour=rand_color)

                await asyncio.sleep(0.05)   # sleep while role is cooking
                role = discord.utils.get(server.roles, name=object_name)
                return role  


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
