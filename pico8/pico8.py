import discord
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from cogs.utils import checks
from bs4 import BeautifulSoup
import asyncio
import os
import aiohttp
import re
import json
from asyncio import Lock
from random import randint
from random import choice as randchoice
from collections.abc import MutableSequence
from __main__ import send_cmd_help
from cogs import repl


SETTINGS_PATH = "data/pico8/settings.json"


class ReactiveList(MutableSequence):
    """calls a callback with the list item when it is accessed
    """

    def __init__(self, *args, callback, **kwargs):
        self.callback = callback
        self._list = list(args[0]) if len(args) else []

    def __getitem__(self, key):
        self.callback(key)
        return self._list[key]

    def __setitem__(self, key, value):
        self._list[key] = value

    def __delitem__(self, key):
        del self._list[key]

    def __len__(self):
        return len(self._list)

    def insert(self, key, value):
        return self._list.insert(key, value)


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
    RE_POSTS = re.compile(r"var pdat=(.*?);\r\n\t\tvar updat", re.DOTALL)

    def __init__(self, loop, search, orderby="RECENT", params={}):
        self.url = BBS.BASE
        self.search_term = search
        self.loop = loop
        self.orderby = orderby
        self.params = {}
        for p, v in self.params.items():
            self.set_param(p, v)
        self.posts = []
        self.current_post = 0
        self.queue = []
        self.embeds = []
        self.load_tasks = ReactiveList(callback=self.queue_area)
        self.locks = []

    def queue_area(self, i):
        self.posts[i]
        self.queue.extend([i, (i + 1) % len(self.posts), 
                              (i - 1) % len(self.posts)])

    async def __aenter__(self):
        self.runner = self.loop.create_task(self._queue_runner())
        await self.search(self.search_term, self.orderby)
        return self

    async def __aexit__(self, *args):
        self.runner.cancel()

    def set_search(self, term):
        self.params.update({'search': term})

    async def search(self, term, orderby="RECENT"):
        self.set_search(term)
        self.set_param("orderby", orderby)
        await self._populate_results()
        return self.posts

    async def _populate_results(self):
        raw = await self._get()
        soup = BeautifulSoup(raw, "html.parser")
        js_posts = re.search(BBS.RE_POSTS, raw).group(1)
        cleanse = {'\r': '', '\n': '', '\t': '', '`': '"', 
                   ',]': ']', ',,': ',null,'}
        for p, r in cleanse.items():
            js_posts = js_posts.replace(p, r)
        posts = json.loads(js_posts)
        # [38386, 28997, `Poop Blaster`,"thumbs/pico38385.png",
        #  0:pid 1:tid 2:title 3:thumb
        # 64,64,"2017-03-18",15018,"chase","2017-03-19",9551,
        # 4:w 5:h 6:date 7:aid 8:author 9:date2 10:uid
        # "kittenm4ster",0,2,0,
        # 11:last 12:likes 13:comments 14:?
        # 7,3,38385,[],0]
        # 15:cat 16:subcat 17:cid 18:tags 19:resolved

        self.posts = [{"OSOUP": soup,
                       "PID": p[0],
                       "TID": p[1],
                       "TITLE": p[2],
                       "DESC": None,  # temp
                       "THUMB": self.url + ('..' + p[3] if p[3][0] == '/' else p[3]),
                       "DATE": p[6],
                       "AID": p[7],
                       "AUTHOR": p[8],
                       "AUTHOR_URL": self.url + "?uid={}".format(p[7]),
                       "AUTHOR_PIC": "https://www.lexaloffle.com/bimg/pi/pi28.png",  # temp
                       "STARS": p[12],
                       "CC": False,  # temp
                       "COMMENTS": p[13],
                       # "FAV": p[14]  # used in generate_cart_preview.
                       # apparently is also the cart id sometimes?
                       "CAT": p[15],
                       "SUB": p[16],
                       "CID": p[17],
                       "PNG": None if ((p[15] not in (6,7)) or p[17] is None) else
                              self.url + ('cposts/{}/{}.p8.png' if p[15] == 7 else 
                                          'cposts/{}/cpost{}.png').format(p[17] // 10000, p[17]),
                       "CART_TITLE": None,  # temp
                       "CART_AUTHOR": None,  # temp
                       "TAGS": p[18],
                       "STATUS": "",
                       "URL": "{}?tid={}".format(self.url, p[1]),
                       "PARAM": {"tid": p[1]}} for p in posts]

        for p in self.posts:
            embed=discord.Embed(title=p["TITLE"], url=p["URL"],
                                description="Loading...")
            embed.set_author(name=p["AUTHOR"], url=p["AUTHOR_URL"],
                             icon_url=p["AUTHOR_PIC"])
            if p['PNG']:
                embed.set_thumbnail(url=p['PNG'])
            embed.add_field(name="Loading...", value="by Loading...", inline=True)
            embed.set_footer(text="{} ⭐{} | {}".format(p["DATE"], p["STARS"],
                                                        ','.join(p['TAGS'])))
            if p['THUMB']:
                embed.set_image(url=p["THUMB"])
            self.embeds.append(embed)
            self.locks.append(Lock())

        async def gen_embed(i):
            await self._populate_post(i)
            return self.embeds[i]

        self.load_tasks.extend(gen_embed(i) for i in range(len(self.embeds)))

        await self._populate_post(0)
        self.queue_area(0)

    async def _populate_post(self, index_or_id, post=None):
        # hope this doesn't fail
        index = self._get_post_index(index_or_id)
        post = post or self.posts[index]
        embed = self.embeds[index]
        # needlessly complicated
        if post['STATUS'] == 'success':
            return True
        async with self.locks[index]:
            if post['STATUS'] == 'success':
                return True
            post['STATUS'] = 'processing'
            try:
                index = self._get_post_index(index_or_id)
                raw = await self._get_post(index)
                soup = BeautifulSoup(raw, "html.parser")
                # continue
                post['SOUP'] = soup
                embed.description = 'Done'
            except Exception as e:
                post['STATUS'] = 'failed'
                raise e
            post['STATUS'] = 'success'


    def _get_post_index(self, index_or_id):
        try:
            self.posts[index_or_id]
        except TypeError:
            for n, p in enumerate(self.posts):
                if p["PARAM"]['tid'] == index_or_id:
                    return n
        else:
            return index_or_id
        raise KeyError('index does not exist in posts')

    async def _get_post(self, index_or_id):
        index = self._get_post_index(index_or_id)
        post = self.posts[index]
        param = post["PARAM"]
        return await self._get(param)

    async def _get(self, params=None):
        params = params or self.params
        async with aiohttp.get(self.url, params=params) as r:
            return await r.text()

    async def _queue_runner(self):
        while True:
            if self.queue:
                working_group = []
                for i in self.queue[:]:
                    status = self.posts[i]["STATUS"]
                    if status == 'success':
                        self.queue.remove(i)
                    if status in ('', 'failed'):
                        working_group.append(i)
                for i in working_group:
                    self.loop.create_task(self._populate_post(i))
            await asyncio.sleep(.5) 



    def set_param(self, param, value_name):
        self.params[param] = self.get_value(param, value_name)

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

    def add_to_queue(self, post):
        if post in self.queue:
            return False
        self.queue.append(post)

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


Card:
    [Title](link to post)    author.avatar
    Description

    Cart Name           Tags:
    by author           tags, tags, tags

    Cart thumbnail (or png cart?) or default "no cart" logo

    footer: date, CC, hearts, starts

    controls:
    < x >

"""


class Pico8:
    """cog to search Lexaloffle's BBS and notify when new PICO-8 carts are uploaded"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(SETTINGS_PATH)
        self.searches = []

    @commands.group(pass_context=True, no_pm=True, aliases=['pico8'])
    async def bbs(self, ctx):
        """PICO-8 bbs commands"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @bbs.command(pass_context=True, name="search", no_pm=True)
    async def bbs_search(self, ctx, search_terms=""):  # category="Recent",
        """Search PICO-8's bbs in a certain category

        Categories (default Recent):
            Recent       Discussion   Blogs
            Carts        Collab       Workshop
            Support      Jam          WIP
            Snippets     Art          Music

        leave search_term blank to list newest topics
        in the category
        """
        author = ctx.message.author
        async with BBS(self.bot.loop, search_terms) as bbs:
            self.searches.append(bbs)
            await repl.interactive_results(self.bot, ctx, bbs.load_tasks)
            answer = await self.bot.wait_for_message(timeout=15,
                                                     author=author, content="done")


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
