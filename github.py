"""Accesses GitHub."""

import discord
from discord.ext import commands

class GitHub(object):

    def __init__(self, bot):
        self.bot = bot

def setup(bot):
    bot.add_cog(GitHub(bot))
