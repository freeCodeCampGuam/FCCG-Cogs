"""Accesses GitHub."""

# To-do list:
# timed digests
# listing/sorting/linking issues/pull requests
# issue submission directly from Discord

import gitpython
import discord
from discord.ext import commands

class GitHub(object):

    def __init__(self, bot):
        self.bot = bot

def setup(bot):
    bot.add_cog(GitHub(bot))
