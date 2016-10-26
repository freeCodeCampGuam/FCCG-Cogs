
# To-do list:
# timed digests
# listing/sorting/linking issues/pull requests
# issue submission directly from Discord

import os, os.path
import aiohttp, asyncio
import discord
from discord.ext import commands
from cogs.utils import dataIO

class GitHub:
    """Accesses GitHub."""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json("data/github/settings.json")
        self.repoPath = "data/github/repos.json"
        self.repos = dataIO.load_json(self.repoPath)
        self.bot.loop.create_task(self.check_for_updates())

    async def check_for_updates(self):
        """Checks for updates from assigned GitHub repos at given interval."""
        while not self.bot.is_closed:
            print("Beep!") # do checky things here
            await asyncio.sleep(60) # placeholder

    @commands.command()
    async def addrepo(self, owner: str, repo: str):
        """Adds a repository to the set of repos to be checked regularly, first checking if it is a valid/accessible repo."""
        site = "https://api.github.com/repos/{}/{}".format(owner,repo)
            async with aiohttp.get(site) as response:
                status = response.status
            if status == 200:
                await self.bot.say("Repository verified. Adding to list of sources.")
                self.repos[repo] = "/".join(owner, repo)
                dataIO.save_json(self.repoPath, self.repos)
            elif status == 404:
                await self.bot.say("Repository not found.")
            else:
                await self.bot.say("An unknown error occurred. Repository not verified.")

    @commands.command()
    async def lsrepo(self):
        """Lists currently added repos."""
        r = "\n".join(["https://github.com/{}".format(s) for s in self.repos])
        # turns list of repos into GitHub links
        await self.bot.say("Currently added repositories: ```{}```".format(r))

def check_folder():
    if not os.path.exists("data/github"):
        print("data/github not detected, creating folder...")
        os.makedirs("data/github")

def check_files():
    defaultSettings = {}

    s = "data/github/settings.json"
    if not dataIO.is_valid_json(s):
        print("valid github/settings.json not detected, creating...")
        dataIO.save_json(s, defaultSettings)

    repos = {}
    r = "data/github/repos.json"
    if not dataIO.is_valid_json(r):
        print("valid github/repos.json not detected, creating...")
        dataIO.save_json(r, repos)

def setup(bot):
    check_folder()
    check_file()
    bot.add_cog(GitHub(bot))
