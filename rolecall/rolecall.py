import discord
import red
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from cogs.utils import checks
import asyncio
import os
import aiohttp
from random import randint
from random import choice as randchoice
from copy import deepcopy

SETTINGS_PATH = "data/rolecall/settings.json"
DEFAULT_SETTINGS = {
    "ROLEBOARD": None,
    "MSGS": {}
}

# just make a constructor. we're treating it as an object anyway
MSG_STRUCT = {
    "ID": None,
    "ROLE": None
}


def call_factory():
    r = {
        "ID": ctx.message.id,
        #"ROLE":
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
"""


class RoleCall:
    """Self-assign roles via reactions on a roleboard"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(SETTINGS_PATH)

    @commands.group(pass_context=True, no_pm=True)
    async def rolecall(self, ctx):
        """change rolecall settings"""
        server = ctx.message.server

        if ctx.invoked_subcommand is None:
            await self.bot.send_cmd_help(ctx)
        else:
            self.settings.setdefault(server.id, deepcopy(DEFAULT_SETTINGS))

    @rolecall.command(pass_context=True, name="roleboard", no_pm=True)
    async def rolecall_roleboard(self, ctx, channel: discord.Channel=None):
        """Set the roleboard for this server.

        Leave blank to turn off the roleboard
        """
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author

        """
        TODO: limit amount of messages. when over,
            log warning and DM server owner /
            infractor (if he's adding a new invite)
        ^ invalid todo due to updated implementation notes
        """

        settings = self.settings[server.id]
        if channel is None and not \
           await self.prompt(author, "turn off the roleboard? (yes/no)"):
            await self.bot.say('Ok. Roleboard is still {}'
                               .format(settings["ROLEBOARD"] and
                                       settings["ROLEBOARD"].mention))
            return

        settings["ROLEBOARD"] = channel and channel.name
        dataIO.save_json(SETTINGS_PATH, self.settings)
        await self.bot.say('Roleboard is now {}'.channel)

    async def prompt(self, author, *args, **kwargs):
        message = await self.bot.say(*args, **kwargs)
        try:
            await self.bot.add_reaction(message, '✅')
            await self.bot.add_reaction(message, '❌')
        except:
            pass

        mcheck = lambda msg: msg.content.lower().startswith(('yes','no','cancel'))

        tasks = (self.bot.wait_for_message(author=author, timeout=15,
                                           check=mcheck),
                 self.bot.wait_for_reaction(user=author, timeout=15, message=message,
                                            emoji=('✅', '❌') ))

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()

        try:
            r = done.pop().result()
            return r.content.lower().startswith('yes')
        except:
            try:
                return r.reaction.emoji == '✅'
            except:
                return False


def check_folders():
    paths = ("data/rolecall", )
    for path in paths:
        if not os.path.exists(path):
            print("Creating {} folder...".format(path))
            os.makedirs(path)


def check_files():
    default = {}

    if not dataIO.is_valid_json(SETTINGS_PATH):
        print("Creating default rolecall settings.json...")
        dataIO.save_json(SETTINGS_PATH, default)
    else:  # consistency check
        current = dataIO.load_json(SETTINGS_PATH)
        inconsistancy = False
        for server in current.values():
            if server.keys() != DEFAULT_SETTINGS.keys():
                for key in DEFAULT_SETTINGS.keys():
                    if key not in server.keys():
                        server[key] = DEFAULT_SETTINGS[key]
                        print(
                            "Adding " + str(key) + " field to rolecall settings.json")
                        inconsistancy = True
        if inconsistancy:
            dataIO.save_json(SETTINGS_PATH, current)


def setup(bot: red.Bot):
    check_folders()
    check_files()
    n = RoleCall(bot)
    bot.add_cog(n)
