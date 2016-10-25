"""Accesses GitHub."""

# To-do list:
# timed digests
# listing/sorting/linking issues/pull requests
# issue submission directly from Discord

import aiohttp
import asyncio
import discord
from discord.ext import commands

class GitHub:

    def __init__(self, bot):
        self.bot = bot
        # set up permanant storage for assigned repos later
        self.repos = []
        self.bot.loop.create_task(self.check_for_updates())

    async def create_session(self):
        """Creates aiohttp ClientSession to be used in retrieving data from APIs."""
        return await aiohttp.ClientSession()

    async def check_for_updates(self):
        """Checks for updates from assigned GitHub repos at given interval."""
        while not self.bot.is_closed:
            print("Beep!")
            await asyncio.sleep(10) # placeholder

    @commands.command()
    async def addrepo(self, owner: str, repo: str):
        """Adds a repository to the set of repos to be checked regularly, first checking if it is a valid/accessible repo."""
        site = "https://api.github.com/repos/{}/{}".format(owner,repo)
        # creates a session for each request, should probably change
        async with aiohttp.ClientSession() as session:
            async with session.get(site) as response:
                if response.status == 200:
                    await self.bot.say("Repository verified. Adding to list of sources.")
                    self.repos.append("/".join((owner, repo.name)))
                elif response.status == 404:
                    await self.bot.say("Repository not found.")
                else:
                    await self.bot.say("An unknown error occurred. Repository not verified.")

    @commands.command()
    async def lsrepo(self):
        """Lists currently added repos."""
        r = "\n".join(["https://github.com/{}".format(s) for s in self.repos])
        # turns list of repos into GitHub links
        await self.bot.say("Currently added repositories: ```{}```".format(r))

def setup(bot):
    bot.add_cog(GitHub(bot))
