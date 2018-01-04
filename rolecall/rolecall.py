import red
import discord
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from cogs.utils import checks
import asyncio
import logging
import os
from copy import deepcopy

log = logging.getLogger("red.rolecall")

SETTINGS_PATH = "data/rolecall/settings.json"
DEFAULT_SETTINGS = {}

# just make a constructor. we're treating it as an object anyway
ROLEBOARD_STRUCT = {
    "MESSAGE": None,
    "ROLES": {}
}

"""
Implementation notes:

Set up each role through the bot. That way the bot has record of all message ids.
Don't have to search through history or parse and can reconstruct roleboard elsewhere.

Must listen for reaction add on each message. maybe just poll each message.
keep track of changes yourself

!rolecall roleboard #announcements
!rolecall add @Website-Team Join if you'd like to follow the development of the FCCG Website.
@Artists, @Writers, @Frontend, and @Backend, you may be interested if you are looking for a project to work on.

bot: @Website-Team Join if you'd like to follow the development of the FCCG Website.
@Artists, @Writers, @Frontend, and @Backend, you may be interested if you are looking for a project to work on.
(@irdumb please add a reaction)

if on mobile,
!rolecall react Website-Team :emoji:
 try: add_reaction
 except: don't have perms or don't have access to that emoji, react it yourself or use a different emoji

don't let people add themselves to a role if they mention it? to avoid mention spam

WATCH_FOR: message members get stale. always check on a fresh copy from bot.get_message
WATCH_FOR: you will need to go through and find the 1st role mention yourself or better yet, have it be an argument and don't require it to be in the message

TODO: Make Entry/Call a class that handles the data for me (what is an entry on a roleboard called?)
"""

class Entry:
    """Entry on the roleboard"""

    def __init__(self, bot, server: discord.Server, channel: discord.Channel, message: discord.Message, role: discord.Role, author: discord.Member):
        self.server = server
        self.channel = channel
        self.message = message
        self.role = role
        self.author = author

class RoleCall:
    """Self-assign roles via reactions on a roleboard
    or via command (for mobile users)"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(SETTINGS_PATH)

    def _record_entry(self, msg_id: str, channel_id: str, role):
        """ record entry to settings file """

        settings = self.settings
        settings['ENTRIES'][msg_id] = ENTRY_STRUCT
        keyring = settings['ENTRIES']['msg_id']
        keyring['CHANNEL'] = channel_id
        keyring['ROLES']

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
    async def roleboard_add(self, ctx, role_name: str, content_or_message_id: str,  reaction: discord.Emoji, role_board: discord.Channel, channel: str
                            ):
        """Add an entry to the roleboard. If a message ID is provided, post a role to the existing message/entry"""
        server = ctx.message.server
        author = ctx.message.author

        role = await self.get_or_create("role", role_name, server)

        # retrieve channel mentions in the command message
        channels = ctx.message.raw_channel_mentions

        # check if two channel arguments were provided or only one
        if len(channels) == 1:
            role_channel = await self.get_or_create("channel", channel, server)
        else:
            role_channel = self.bot.get_channel(channels[1]) 
        
        # check if message ID was provided. If yes, post the new role to the message associated with the ID, if not, post the new entry to the chosen role board
        try:
            await self.post_role(role_board, reaction, content_or_message_id)
        except Exception as e:
            await self.post_entry(content_or_message_id, reaction, role_board)
      
    async def post_entry(self, message: str, role_reaction: discord.Emoji, role_board: discord.Channel):
        """ post entry to chosen roleboard(channel) """

        entry = await self.bot.send_message(role_board, content=message)
        await self.bot.add_reaction(entry, role_reaction)

    async def post_role(self, role_board: discord.Channel, role_reaction: discord.Emoji, entry_id: str):
        """ post role to chosen entry(message) """

        entry = await self.bot.get_message(role_board, entry_id)
        await self.bot.add_reaction(entry, role_reaction)

    async def on_reaction_add(self, reaction, user):
        pass

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
                    role = await self.bot.create_role(server, name=object_name)
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
        if inconsistancy:
            dataIO.save_json(SETTINGS_PATH, current)


def setup(bot: red.Bot):
    check_folders()
    check_files()
    n = RoleCall(bot)
    bot.add_cog(n)
