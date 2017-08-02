import discord
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from cogs.utils import checks
import asyncio
import os
import aiohttp
from random import randint
from random import choice as randchoice

SETTINGS_PATH = "data/keydistrib/settings.json"


#TODO: 1st phase
#TODO: give a key from admin/mod cmd via PM
#TOOD: only give on confirmation
#TODO: track
#TODO: 	if they were already given a key
#TODO: 	if confirmed
#TODO: 	who gave the key
#TODO:	userinfo: name/id/date

#TODO: 2nd phase
#TODO: hand out key on join from specific invite url
#TODO: different files (key pools)
#TODO: display user-key info. who has gotten what, etc


class KeyDistrib:
    """distributes and tracks keys from a file"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(SETTINGS_PATH)

    @checks.mod_or_permissions()
    @commands.command(pass_context=True, no_pm=True)
    async def givekey(self, ctx, ):
        """description"""
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author
        await self.bot.say("hi")


def check_folders():
    paths = ("data/keydistrib", )
    for path in paths:
      if not os.path.exists(path):
          print("Creating {} folder...".format(path))
          os.makedirs(path)


def check_files():
    default = {}

    if not dataIO.is_valid_json(SETTINGS_PATH):
        print("Creating default keydistrib settings.json...")
        dataIO.save_json(SETTINGS_PATH, default)
    else:  # consistency check
        current = dataIO.load_json(SETTINGS_PATH)
        if current.keys() != default.keys():
            for key in default.keys():
                if key not in current.keys():
                    current[key] = default[key]
                    print(
                        "Adding " + str(key) + " field to keydistrib settings.json")
            dataIO.save_json(SETTINGS_PATH, current)


def setup(bot):
    check_folders()
    check_files()
    n = KeyDistrib(bot)
    bot.add_cog(n)

async with aiohttp.get(url) as response:
  a = await r.text()

print(a)
