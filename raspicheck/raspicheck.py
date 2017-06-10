import discord
from discord.ext import commands
from __main__ import set_cog, send_cmd_help, settings
import asyncio
import psutil
import sys
import os
import time
import datetime
import subprocess
import socket
from cogs.utils import checks

class RasPiCheck:
    """A cog for checking the Raspberry Pi's common stats"""

    def __init__(self, bot):
        self.bot = bot
        # self.subprocess = subprocess
        # self.os = os
        # self.psutil = psutil

        self.bot.loop.create_task(self.infoscroll())

    async def infoscroll(self):
        while not self.bot.is_closed:
            await self.bot.change_presence(game=None)
            await asyncio.sleep(1)
            await self.bot.change_presence(game=discord.Game(name=" {}°C | {}%".format(self.temp, self.cpupercent)))
            await asyncio.sleep(10)

    @commands.group(name = "check", pass_context = True)
    async def check(self,ctx): 
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @check.command(pass_context = True)
    async def uptime(self):
        """Checks the Uptime of the Raspberry Pi"""
        rt = subprocess.check_output(['uptime'])
        rut = rt.decode("utf-8")
        piuptime = rut.replace(",  ", "\n").replace("up", "up for")
        await self.bot.say("Uptime Info:\n" + "```RasPi's Time:" + piuptime + "```")

    @check.command(pass_context = True)
    async def cpu(self):
        """Checks the Raspberry Pi's current cpu usage percentage"""
        cpupercent = str(psutil.cpu_percent(interval=1))
        await self.bot.say("The CPU is at " + cpupercent + "%")

    @check.command(pass_context = True)
    async def temp(self):
        """Checks the Raspberry Pi's core temperature in celsius"""
        res = os.popen('vcgencmd measure_temp').readline()
        temp = res.replace("temp=","").replace("'C\n","")
        await self.bot.say("The RasPi's core temperature is " + temp + "°C")

    @checks.is_owner()
    @check.command(pass_context = True)
    async def ip(self, ctx):
        """Checks the current local IP address of the Raspberry Pi and PMs the owner (Bot Owner ONLY)"""
        if settings.owner == ctx.message.author.id:
            ip = [(s.connect(('8.8.8.8', 53)), s.getsockname()[0], s.close()) for s in [socket.socket(socket.AF_INET, socket.SOCK_DGRAM)]][0][1]
            await self.bot.whisper(ip)
            await self.bot.say("Sent you a PM")
        else:
            await self.bot.say("Sorry I can not do that, you are not my owner.")


def setup(bot):
    bot.add_cog(RasPiCheck(bot))