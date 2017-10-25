import discord
from discord.ext import commands
import subprocess
from cogs.utils import checks

class wifiPresence:
    """My custom cog that does stuff!"""

    def __init__(self, bot):
        self.bot = bot
        self.scan_status = False

    @commands.group(name = "presence", pass_context = True)
    async def presence(self,ctx):
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @commands.group(name = "scan", pass_context = True)
    async def scan(self,ctx):
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @scan.command(pass_context = True)
    async def toggle(self, ctx):
        """Toggles scan on or off"""
        scan_status = not scan_status
        if (scan_status):
            await self.bot.say("Scanning Started.")
            while (scan_status):
                output = subprocess.check_output("sudo arp-scan -l", shell=True)
                await asyncio.sleep(30)
        else:
            await self.bot.say("Scanning Stopped.")

    @checks.is_owner()
    @scan.command(pass_context = True)
    async def log(self,ctx):
        """Prints out a log of connected devices"""
        readable_output = output.decode("utf-8")
        await self.bot.whisper("```" + readable_output + "```")
        await self.bot.say("Sent you a PM")
        

def setup(bot):
    bot.add_cog(wifiPresence(bot))