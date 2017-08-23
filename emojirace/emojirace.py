import discord
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from cogs.utils import checks
import asyncio
import os
import aiohttp
import datetime
from random import randint
from random import choice as randchoice


SETTINGS_PATH = "data/emojirace/settings.json"
EMOJI_PATH    = "data/emojirace/emojis"

class EmojiRace:
    """description"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(SETTINGS_PATH)

    @checks.mod_or_permissions(administrator=True)
    @commands.command(pass_context=True, no_pm=True)
    async def emojirace(self, ctx, user: discord.Member=None):
        """description"""
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author

        def custom_check():
            chosen=[]
            def check_wrapper(reaction, user):
                if reaction.custom_emoji and reaction.emoji not in chosen:
                    chosen.append(reaction.emoji)
                    return True
                return False
            return check_wrapper

        embed = embed_menu()
        m = await self.bot.say(embed=embed)

        kwargs = {"user": author,          "message": m,
                  "check": custom_check(), "timeout": 120}

        try:
            p1t = self.get_user_emoji(**kwargs)
            del kwargs['user']
            p2t = self.get_user_emoji(**kwargs)
            res = await asyncio.gather(p1t, p2t)
        except TimeoutError:
            return self.bot.edit_message(m, "Time up!")
        # await self.bot.upload(res[0][2], content=res[0][0])
        # await self.bot.upload(res[1][2], content=res[1][0])
        self.set_up_game(m, *(e[1] for e in res))
        await self.bot.say("Let the Games Begin!")
        await asyncio.sleep(120)
        try:
            await self.end_game(self.settings[game_id(m)])
        except KeyError:
            pass

    async def end_game(self, game):
        del self.settings[game_id(game['message'])]

    async def update_game(self, game):
        for e in game['players']:
            if game['emojis'][e] >= 100:
                await self.draw_winner(game, e)
                await self.end_game(game)

    async def draw_game(self, game):
        msg = game['message']
        # pts = [(p, game['emojis'][p]) for p in game['players']]
        emojis = sorted(game['emojis'].items(), key=lambda i: i[1], reverse=True)

        s = ("GUUUUU!!\n|{:^22}"+" "*20+"{:^22}|").format(emojis[0][1], emojis[1][1])
        if emojis[0][0] != game['drawn_lead']:
            e = embed_menu(game['emojis'])
            await self.bot.edit_message(msg, new_content=s, embed=e)
        else:
            await self.bot.edit_message(msg, new_content=s)
        game['drawn_lead'] = emojis[0][0]

    async def draw_winner(self, game, emoji_filename):
        msg = game['message']
        winner = self._get_lead(game)
        embed = embed_menu(winner=winner)
        await self.bot.edit_message(msg, embed=embed)
        await self.bot.upload(os.path.join(EMOJI_PATH, winner[0]))


    def set_up_game(self, msg, p1e, p2e):
        now = datetime.datetime.now()
        time = now + datetime.timedelta(seconds=120)
        p1 = emoji_filename(p1e)
        p2 = emoji_filename(p2e)
        self.settings[game_id(msg)] = {
            "message": msg,
            "channel": msg.channel,
            "emojis" : {p1: 0, p2: 0},
            "players": [p1, p2],
            "time"   : time,
            "updated": now,
            "drawn_lead": None
        }

    def _get_lead(self, game):
        msg = game['message']
        emojis = game['emojis'].items()
        return emojis[0] if emojis[0][1] > emojis[1][1] else emojis[1]

    async def get_user_emoji(self, **kwargs):
        r = await self.bot.wait_for_reaction(**kwargs)
        if r is None:
            raise TimeoutError
        reaction, user = r
        tasks = (dl_emoji(reaction.emoji),
                 self.bot.add_reaction(reaction.message, reaction.emoji))
        path, _ = await asyncio.gather(*tasks)
        return user, reaction.emoji, path

    async def on_reaction_add(self, reaction, user):
        msg = reaction.message
        gid = game_id(msg)
        try:
            game = self.settings[gid]
            game["emojis"][emoji_filename(reaction.emoji)] += 1
        except KeyError:
            return
        now = datetime.datetime.now()
        if (now - game["updated"]).seconds > 2:
            await self.update_game(game)
            await self.draw_game(game)
            game["updated"] = now


def embed_menu(emojis=False, winner=None):
    if winner:
        embed = discord.Embed(title="!!   Winner!  !!")
        embed.set_image(url=build_emoji_url(winner[0]))
        embed.set_thumbnail(url=build_emoji_url(winner[0]))
        return embed

    if emojis:
        emojis = sorted(emojis.items(), key=lambda i: i[1], reverse=True)
        embed = discord.Embed(title="{:-^38}".format("Spam dem 'mojis!"))
        embed.set_image(url=build_emoji_url(emojis[0][0]))
        embed.set_thumbnail(url=build_emoji_url(emojis[1][0]))
    else:
        embed = discord.Embed(title="-  Choose a Racer!  -")

    embed.add_field(name="1st Place", value="V", inline=True)
    embed.add_field(name="2nd Place", value=">", inline=True)

    return embed


def build_emoji_url(emoji_filename):
    return 'https://discordapp.com/api/emojis/' + emoji_filename

def game_id(msg):
    return msg.channel.id + '|' + msg.id

def emoji_filename(emoji):
    return emoji.url[34:]

async def dl_emoji(emoji):
    path = os.path.join(EMOJI_PATH, emoji_filename(emoji))
    if not os.path.exists(path):
        async with aiohttp.get(emoji.url) as r:
            with open(path, 'wb') as f:
                f.write(await r.content.read())
    return path

def check_folders():
    paths = ("data/emojirace", EMOJI_PATH)
    for path in paths:
      if not os.path.exists(path):
          print("Creating {} folder...".format(path))
          os.makedirs(path)

def check_files():
    default = {}

    if not dataIO.is_valid_json(SETTINGS_PATH):
        print("Creating default emojirace settings.json...")
        dataIO.save_json(SETTINGS_PATH, default)
    else:  # consistency check
        current = dataIO.load_json(SETTINGS_PATH)
        if current.keys() != default.keys():
            for key in default.keys():
                if key not in current.keys():
                    current[key] = default[key]
                    print(
                        "Adding " + str(key) + " field to emojirace settings.json")
            dataIO.save_json(SETTINGS_PATH, current)

def setup(bot):
    check_folders()
    check_files()
    n = EmojiRace(bot)
    bot.add_cog(n)
