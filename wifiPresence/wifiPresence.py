import discord
from discord.ext import commands
import asyncio

from cogs.utils import checks
from __main__ import send_cmd_help

import subprocess

#TODO: Use JSON to store settings for toggling

#TODO: Create function to assign names to MAC Addresses
#TODO: Create function to peridically scan and notify when a specified name
#      appears in the network

class WifiPresence:
    """My custom cog that does stuff!"""

    def __init__(self, bot):
        self.bot = bot
        self.scan_status = None

    def scan_arp(self, ctx):
        output = subprocess.check_output("sudo arp-scan -l", shell=True)
        return 

    @commands.group(name = "presence", pass_context = True)
    async def presence(self, ctx):
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @commands.group(name = "scan", pass_context =  True)
    async def scan(self, ctx):
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @scan.command(pass_context = True)
    async def toggle(self, ctx):
        """Toggles scan on or off"""
        self.scan_status = not self.scan_status
        if self.scan_status:
            await self.bot.say("Scanning Started.")
            while self.scan_status:
                await scan_arp()
                await asyncio.sleep(30)
        else:
            await self.bot.say("Scanning Stopped.")

    @checks.is_owner()
    @scan.command(pass_context = True)
    async def log(self, ctx):
        """Prints out a log of connected devices"""
        await scan_arp()
        readable_output = self.output.decode("utf-8")
        await self.bot.whisper("```" + readable_output + "```")
        await self.bot.say("Sent you a PM")
        

def setup(bot):
    bot.add_cog(wifiPresence(bot))