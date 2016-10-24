"""Accesses GitHub."""

# To-do list:
# timed digests
# listing/sorting/linking issues/pull requests
# issue submission directly from Discord

import asyncio
import github3
import discord
from discord.ext import commands

class GitHub(object):

    def __init__(self, bot):
        self.bot = bot
        # set up permanant storage for assigned repos later
        self.repos = []
        self.bot.loop.create_task(self.check_for_updates())

    async def check_for_updates(self):
        """Checks for updates from assigned GitHub repos at given interval."""
        while not self.bot.is_closed:
            # do checky stuff
            asyncio.sleep(10) # placeholder

    @commands.command()
    async def addrepo(self, owner: str, repo: str):
        """Adds a repository to the set of repos to be checked regularly, first checking if it is a valid/accessible repo."""
        try:
            # tries to get repo from GitHub
            repo = github3.repository(owner, repo)
        except exception as e:
            await self.bot.reply("Failed to add repository.")
            await self.bot.say("{}: {}".format(e.__name__,e))
        else:
            # if repo doesn't exist, repository() returns NullObject, btw
            if type(repo) is github3.repos.repo.Repository:
                await self.bot.say("Repository verified. Adding to list of sources.")
                self.repos.append("/".join((owner, repo.name)))
            else:
                await self.bot.say("Repository not found.")

    @commands.command()
    async def lsrepo(self):
        """Lists currently added repos."""
        r = "\n".join(["https://github.com/{}".format(s) for s in self.repos])
        # turns list of repos into GitHub links
        await self.bot.say("Currently added repositories: ```{}```".format(r))

def setup(bot):
    bot.add_cog(GitHub(bot))
