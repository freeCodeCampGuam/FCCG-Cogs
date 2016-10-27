# To-do list:
# timed digests
# listing/sorting/linking issues/pull requests
# issue submission directly from Discord


import os, os.path
import aiohttp, asyncio
import discord
from datetime import datetime, timedelta
from copy import copy
from discord.ext import commands
from cogs.utils.dataIO import dataIO

class GitHub:
    """Accesses GitHub."""

    def __init__(self, bot):
        self.bot = bot
        self.repoPath = "data/github/repos.json"
        self.settingPath = "data/github/settings.json"
        self.repos = dataIO.load_json(self.repoPath)
        self.settings = dataIO.load_json(self.settingPath)
        self.bot.loop.create_task(self._log_in())
        self.bot.loop.create_task(self._wait_for_updates())

    def _format_issue(self, issue, repo):
        """Formats a GitHub issue nicely so it can be printed in Discord. issue is the dict returned by a GitHub
        API request for a given Issue."""
        string = "New issue on `{}`: **{}**\n```{}```"
        if len(issue["body"]) > 100: # max default body length 100 characters, create setting later
            body = issue["body"][:101]
        fullstring = string.format(repo, issue["title"], body)
        return fullstring

    async def _log_in(self):
        """Attempts to log in to GitHub through the API with the given credentials."""
        usr = self.settings["github_username"]
        token = self.settings["personal_access_token"]
        if self.settings["validated"] is not True:
            print("Please enter GitHub username.")
            usr = input()
            self.settings["github_username"] = usr
            print("Please enter GitHub Personal Access Token.")
            token = input()
            self.settings["personal_access_token"] = token
        try:
            r = await aiohttp.request("GET","https://api.github.com/user",auth=aiohttp.BasicAuth(usr,token))
            data = await r.json()
        except Exception as e:
            print("GitHub login as {} failed.".format(usr))
            print("{}: {}".format(e.__name__,e))
            self.settings["validated"] = False
        else:
            if r.status == 200:
                print("Login succeeded as {}!".format(usr))
                self.settings["validated"] = True
        dataIO.save_json(self.settingPath, self.settings)

    async def _create_digest(self, channel=None):
        """Grabs the most recent happenings for each repo, prints nicely."""
        if channel is None:
            channel = discord.User(id=self.bot.owner)
        # all updates since "last update"
        d = datetime.now() - timedelta(minutes=self.settings["interval"])
        datestring = d.isoformat()
        params = {"since": datestring}
        for repo in self.repos.values():
            print("Checking repo {}...".format(repo))
            site = "https://api.github.com/repos/{}/issues".format(repo, params=params)
            async with aiohttp.get(site.format(repo)) as response:
                status = response.status
                reason = response.reason
                data = await response.json()
            ret = "```{}: {}```".format(status, reason)
            await self.bot.say(ret)
            if status == 200:
                for issue in data:
                    await self.bot.say(self._format_issue(issue, repo))

    async def _wait_for_updates(self):
        """Checks for updates from assigned GitHub repos at given interval."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed:
            print("Scheduled digest firing!")
            await self._create_digest()
            await asyncio.sleep(self.settings["interval"])

    @commands.command(name="gitupdate", pass_context=True)
    async def _force_grab_updates(self, ctx):
        """Produces a digest on command."""
        await self._create_digest(ctx.message.channel)

    @commands.command(name="setin")
    async def _set_interval(self, interval : int):
        """Sets the interval at which the cog checks for updates, in minutes."""
        if interval < 5:
            interval = 5
        self.settings["interval"] = interval * 60
        await self.bot.say("Check delay set to {} minutes.".format(interval))
        dataIO.save_json(self.settingPath, self.settings)

    @commands.command(name="addrepo")
    async def _add_repos(self, owner: str, repo: str):
        """Adds a repository to the set of repos to be checked regularly.
        First checks if it is a valid/accessible repo."""
        site = "https://api.github.com/repos/{}/{}".format(owner,repo)
        async with aiohttp.get(site) as response:
            status = response.status
        if status == 200:
            await self.bot.say("Repository verified. Adding to list of sources.")
            self.repos[repo] = "/".join((owner, repo))
            dataIO.save_json(self.repoPath, self.repos)
        elif status == 404:
            await self.bot.say("Repository not found.")
        else:
            await self.bot.say("An unknown error occurred. Repository not verified.")

    @commands.command(name="lsrepo")
    async def _list_repos(self):
        """Lists currently added repos."""
        r = "\n".join(["https://github.com/{}".format(s) for s in self.repos.values()])
        # turns list of repos into GitHub links
        await self.bot.say("Currently added repositories: ```{}```".format(r))

    @commands.command(name="delrepo")
    async def _delete_repo(self, owner : str, repo : str):
        """Removes repository from set of repos to be checked regularly."""
        path = "/".join((owner,repo))
        repos = self.repos.values()
        go = False
        for r in repos:
            if path == r:
                go = True
        if go:
            await self.bot.say("Removing repo {} from list.".format(repo))
            self.repos.pop(repo, None)
            dataIO.save_json(self.repoPath,self.repos)

def check_folder():
    if not os.path.exists("data/github"):
        print("data/github not detected, creating folder...")
        os.makedirs("data/github")

def check_file():
    defaultSettings = { "interval" : 60,
                        "github_username" : "",
                        "validated" : None,
                        "personal_access_token" : "",
                        "designated_channel" : "owner" }

    s = "data/github/settings.json"
    if not dataIO.is_valid_json(s):
        print("valid github/settings.json not detected, creating...")
        dataIO.save_json(s, defaultSettings)

    repos = {}
    r = "data/github/repos.json"
    if not dataIO.is_valid_json(r):
        print("valid github/repos.json not detected, creating...")
        dataIO.save_json(r, repos)

def setup(bot):
    check_folder()
    check_file()
    bot.add_cog(GitHub(bot))
