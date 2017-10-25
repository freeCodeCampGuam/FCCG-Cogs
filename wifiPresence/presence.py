import discord
from discord.ext import commands
import subprocess

class wifiPresence:
    """My custom cog that does stuff!"""

    def __init__(self, bot):
        self.bot = bot
        self.scan_status = False

    @commands.group(name = "presence", pass_context = True)
    async def presnece(self,ctx):
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @commands.group(name = "scan", pass_context = True)
    async def scan(self,ctx):
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @scan.command(pass_context = True)
    """Toggles scan on or off"""
    async def toggle(self, ctx):
        scan_status = not scan_status
        if (scan_status):
            await self.bot.say("Scanning Started.")
            while (scan_status):
                output = subprocess.check_output("sudo arp-scan -l", shell=True)
                await asyncio.sleep(30)
        else:
            await self.bot.say("Scanning Stopped.")

        

def setup(bot):
    bot.add_cog(wifiPresence(bot))