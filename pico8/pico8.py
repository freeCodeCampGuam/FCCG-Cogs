import discord
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from cogs.utils import checks
from bs4 import BeautifulSoup
import asyncio
import os
import aiohttp
import re
from random import randint
from random import choice as randchoice
from __main__ import send_cmd_help

SETTINGS_PATH = "data/pico8/settings.json"


class BBS:
    """BBS Api Wrapper"""
    BASE = "https://www.lexaloffle.com/bbs/"
    PARAMS = {
        "cat": {
            "VOXATRON":      "6",
            "PICO8":         "7",
            "BLOGS":         "8"
        },
        "sub": {
            "DISCUSSIONS":   "1",
            "CARTRIDGES":    "2",
            "WIP":           "3",
            "COLLABORATION": "4",
            "WORKSHOPS":     "5",
            "SUPPORT":       "6",
            "BLOGS":         "7",
            "JAMS":          "8",
            "SNIPPETS":      "9",
            "PIXELS":        "10",
            "ART":           "10",
            "MUSIC":         "11"
        },
        "orderby": {
            "RECENT":        "ts",
            "FEATURED":      "rating",  
            "RATING":        "rating",
            "FAVORITES":     "favourites",
            "FAVOURITES":    "favourites"
        }
    }

    def __init__(self, params={}):
        self.url = BBS.BASE
        self.params = {}
        self.set_param("orderby", "")
        self.posts = []
        for p, v in params.items():
            self.set_param(p, v)

    def set_search(self, term):
        self.params.update({'search': term})

    async def search(self, term, orderby="RECENT"):
        self.set_search(term)
        self._populate_results()
        self.set_param("orderby", orderby)

        return self.posts

    async def _populate_results(self):
        raw = await self._get()
        soup = BeautifulSoup(raw, "html.parser")
        posts = soup.find_all(id=re.compile("pdat_.*"))
        self.posts = [[t.a.text, t.a['href']] for t in posts]

    async def get_post(self, index_or_post):
        try:
            index = self.posts.index(index_or_post)
        except ValueError:
            index = index_or_post
        raw = await self._get_post(index)
        soup = BeautifulSoup(raw, "html.parser")
        # continue

    async def _get_post(self, index):
        post = self.posts[index]
        return self._get(post[1])

    async def _get(self, params=None):
        params = params or self.params
        async with aiohttp.get(self.url, params=params) as r:
            return await r.text()

    def set_param(self, param, value_name):
        self.params[param] = get_value(param, value_name)

    def set_param_by_prefix(self, param, prefix):
        value_name = self.get_value_name_by_prefix(param, prefix)
        return self.add_param(param, value_name)

    def param_exists(self, param):
        return param in BBS.PARAMS

    def value_name_exists(self, param, value_name):
        return self.param_exists(param) and value_name in BBS.PARAMS[param]

    def get_value(self, param, value_name):
        return BBS.PARAMS[param][value_name]

    def get_value_by_prefix(self, param, prefix):
        value_name = self.get_value_name_by_prefix(param, prefix)
        return self.get_value(param, value_name)

    def get_value_name_by_prefix(self, param, prefix):
        group = BBS.PARAMS[param]
        upper_no_s = prefix.upper()[-1]

        for name in group:
            if name.startswith(upper_no_s):
                return name

        raise ValueError('Prefix {} not found in param {}'
                         .format(prefix, param))

# [{'href':t.a['href'], 'text':t.a.text}  for t in s.find_all(id=re.compile("pdat_.*"))]

"""
UI Ideas:

Cart: 
    png for thumbnail
    in code:
        -- cart name
        -- by author

Other:
    link
    author thumbnail somewhere
    author name
    title
    description[:n_chars] + '...'
    stars
    hearts
    CC?
    tags
    date

"""


class Pico8:
    """cog to search Lexaloffle's BBS and notify when new PICO-8 carts are uploaded"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(SETTINGS_PATH)

    @commands.group(pass_context=True, no_pm=True, aliases=['pico8'])
    async def bbs(self, ctx):
        """PICO-8 bbs commands"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @bbs.command(pass_context=True, name="search", no_pm=True)
    async def bbs_search(self, ctx, category="Recent", search_terms=""):
        """Search PICO-8's bbs in a certain category

        Categories (default Recent):
            Recent       Discussion   Blogs
            Carts        Collab       Workshop
            Support      Jam          WIP
            Snippets     Art          Music

        leave search_term blank to list newest topics
        in the category
        """
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
