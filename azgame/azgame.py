
import random
import discord
from discord.ext import commands
import sqlite3
import asyncio
import os.path
from cogs.utils.dataIO import dataIO

db_name = "logic.db"
class Azgame(object):
    """AZGame. A range of words is given, with one chosen as the "winning". Your
    objective is to find the word, and the word range gets smaller with every
    guess."""

    def __init__(self, bot):
        self.bot = bot
        self.path = "data/azgame/settings.json"
        self.settings = dataIO.load_json(self.path)
        self.memory = {"playing": False}

    @commands.command(pass_context=True)
    async def az(self, ctx, option: str):
        """Controls the AZ game."""
        if option == "start":
            print("Starting game of AZ.")
            if not self.memory["playing"]:
                await self.bot.say("Warming up...")
                await self.begin_az()
                await self.bot.say("Current range: {} --{}".format(
                                      self.memory["wordlist"][0],
                                      self.memory["wordlist"][-1]))
            else:
                await self.bot.say("A game of AZ has already been started!")
        else:
            print("Applying attempt {}.".format(option))
            status = await self.play_az(option)
            if status: # if the game is won
               await self.end_az(ctx.message.author,self.memory["solution"])

    @commands.command(pass_context=True)
    async def azquit(self, ctx):
        if not self.memory["playing"]:
            await self.bot.reply("Start a game with $az start first.")
        else:
            await self.bot.say("Ending the game, the winning word was {}.\nBlame {}!".format(self.memory["solution"],
              ctx.message.author.mention))
            self.memory["playing"] = False
            del self.memory["solution"]
            del self.memory["wordlist"]

    # @self.bot.command
    async def begin_az(self):
        """Loads the word database into memory."""
        c = self.bot.db.cursor()
        print("Loading words from database...")
        c.execute("SELECT word FROM wordlist;")
        self.memory["wordlist"] = []
        print("Loading words into memory...")
        for row in c.fetchall():
            self.memory["wordlist"].append(row[0])
        print("Loaded.")
        self.memory["solution"] = random.choice(self.memory["wordlist"])
        print("Solution word is {}.".format(self.memory["solution"]))
        self.memory["playing"] = True

    async def play_az(self, word):
        """Tries to redefine the current word range by seeing if a given word is in the range.
        If the solution is given, the winner is recognized and the game ends.
        Usage: $az word"""
        wlist = self.memory["wordlist"][::]
        solution = self.memory["solution"]
        if word == solution:
            return True
        elif word in wlist:
            if wlist.index(word) < wlist.index(solution):
                wlist = wlist[wlist.index(word)::]
                await self.bot.say("Close, but no cigar. Range is {} -- {}".format(word,wlist[-1]))
            elif wlist.index(word) > wlist.index(solution):
                wlist = wlist[:(wlist.index(word) + 1):]
                await self.bot.say("Close, but no cigar. Range is {} -- {}".format(
                                                                wlist[0],
                                                                word))
            self.memory["wordlist"] = wlist[::]

    async def end_az(self, winner, solution):
        """Ends a game of AZ."""
        await self.bot.say("Congratulations! {} won with {}!".format(winner,solution))
        self.memory["playing"] = False
        print("Removing necessary game data...")
        del self.memory["wordlist"]
        del self.memory["solution"]

def check_folder():
    if not os.path.exists("data/azgame"):
        print("data/azgame not detected, creating folder...")
        os.makedirs("data/github")

def check_file():
    defaults = { "wordlist_file" : "words.txt"
               }
    path = "data/azgame/settings.json"
    if not dataIO.is_valid_json(path):
        print("valid azgame/settings.json not detected, creating default...")
        dataIO.save_json(path, defaults)

def setup(bot):
    check_folder()
    check_file()
    bot.add_cog(AZGame(bot))
