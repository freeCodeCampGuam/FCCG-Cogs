"""Accesses GitHub."""

# To-do list:
# timed digests
# listing/sorting/linking issues/pull requests
# issue submission directly from Discord

import github3
import discord
from discord.ext import commands

class GitHub(object):

    def __init__(self, bot):
        self.bot = bot
        # set up permanant storage for assigned repos later
        self.repos = [ # "centipeda/gh-cog-test-repo"
                     ]

    @commands.command()
    async def addrepo(self, owner: str, repo: str):
        """Adds a repository to the set of repos to be checked regularly, first checking if it is a valid/accessible repo."""
        try:
            repo = github3.repository(owner, repo)
        except exception as e:
            await self.bot.reply("Failed to add repository.")
            await self.bot.say("{}: {}".format(e.__name__,e))
        else:
            await self.bot.say("Repository verified. Adding to list of sources.")
            self.repos.append("/".join((owner, repo.name)))

    @commands.command()
    async def lsrepo(self):
        """Lists currently added repos."""
        r = "\n".join(["https://github.com/{}".format(s) for s in self.repos])
        # turns list of repos into GitHub links
        await self.bot.say("Currently added repositories: ```{}```".format(r))

def setup(bot):
    bot.add_cog(GitHub(bot))
