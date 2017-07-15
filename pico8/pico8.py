import discord
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from cogs.utils import checks
from bs4 import BeautifulSoup
import asyncio
import os
import aiohttp
from random import randint
from random import choice as randchoice

SETTINGS_PATH = "data/pico8/settings.json"


class Pico8:
    """cog to search Lexaloffle's BBS and notify when new PICO-8 carts are uploaded"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(SETTINGS_PATH)

    @checks.mod_or_permissions(administrator=True)
    @commands.command(pass_context=True, no_pm=True)
    async def bbs(self, ctx):
        """search for PICO-8 topics on Lexaloffle's BBS"""
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author


def check_folders():
    paths = ("data/pico8", )
    for path in paths:
        if not os.path.exists(path):
            print("Creating {} folder...".format(path))
            os.makedirs(path)


def check_files():
    default = {}

    if not dataIO.is_valid_json(SETTINGS_PATH):
        print("Creating default pico8 settings.json...")
        dataIO.save_json(SETTINGS_PATH, default)
    else:  # consistency check
        current = dataIO.load_json(SETTINGS_PATH)
        if current.keys() != default.keys():
            for key in default.keys():
                if key not in current.keys():
                    current[key] = default[key]
                    print("Adding " + str(key) +
                          " field to pico8 settings.json")
            dataIO.save_json(SETTINGS_PATH, current)


def setup(bot):
    check_folders()
    check_files()
    n = Pico8(bot)
    bot.add_cog(n)
