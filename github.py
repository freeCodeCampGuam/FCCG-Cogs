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
        self.settingPath = "data/github/settings.json"
        self.settings = dataIO.load_json(self.settingPath)
        # async functions can't be called without being in another async function
        # so _log_in and _wait_for_issue are added to the bot's event loop
        self.bot.loop.create_task(self._log_in())
        self.bot.loop.create_task(self._wait_for_updates())

    def _format_issue(self, issue, repo):
        """Formats a GitHub issue nicely so it can be printed in Discord. issue is the dict returned by a GitHub
        API request for a given Issue."""
        string = "New issue on `{}` by {}: **{}**\n{}"
        # ex "New issue on centipeda/gh-cog-test-repo by centipeda: **title** link"
        fullstring = string.format(repo, issue["user"]["login"], issue["title"], issue["html_url"])
        return fullstring

    async def _log_in(self):
        """Attempts to log in to GitHub through the API with the given credentials."""
        # tries to use what's in the settings
        usr = self.settings["github_username"]
        token = self.settings["personal_access_token"]
        # but if hasn't been validated yet, ask for credentials anyway
        # through console/terminal
        if self.settings["validated"] is not True:
            print("Please enter GitHub username.")
            usr = input()
            self.settings["github_username"] = usr
            print("Please enter GitHub Personal Access Token.")
            token = input()
            self.settings["personal_access_token"] = token
        try:
            # basic authentication request
            r = await aiohttp.request("GET","https://api.github.com/user",auth=aiohttp.BasicAuth(usr,token))
        except Exception as e:
            # if exception happened during authentication request, assume validation failed
            print("GitHub login as {} failed.".format(usr))
            print("{}: {}".format(e.__name__,e))
            self.settings["validated"] = False
        else:
            if r.status == 200: # OK
                print("Login succeeded as {}!".format(usr))
                # setting validated to True bypasses asking for credentials on
                # cog startup
                self.settings["validated"] = True
            else:
                self.settings["validated"] = False
        # always save
        dataIO.save_json(self.settingPath, self.settings)

    async def _create_digest(self, channel=None):
        """Grabs the most recent happenings for each repo, prints nicely."""
        if channel is None:
            channel = discord.User(id=self.bot.owner)
        # all updates since "last update"
        # subtracting these datetime objects should give current time "minus" the interval
        # that is, the time interval seconds ago
        d = datetime.utcnow() - timedelta(seconds=self.settings["interval"])
        # GitHub API takes ISO 8601 format for dates/times
        # so we need just a little bit more formatting
        datestring = d.isoformat()[:-7] + "Z"
        # setting the 'since' parameter in a request for issues
        # only retrieves issues after a certain time
        parameters= {"since": datestring}
        for repo in self.settings["repos"]:
            print("Checking repo {}...".format(repo))
            site = "https://api.github.com/repos/{}/issues".format(repo)
            async with aiohttp.get(site.format(repo), params=parameters) as response:
                status = response.status
                reason = response.reason
                data = await response.json()
            # display response code and reason, for debugging
            ret = "```{}: {}```".format(status, reason)
            await self.bot.send_message(ret, channel)
            if status == 200:
                if self.settings["notification_method"][0] == "message":
                    dest = self.settings["notification_method"][1]
                    for issue in data:
                        await self.bot.send_message(self._format_issue(issue, repo), dest)
                elif self.settings["notification_method"][0] == "webhook":
                    await self._fire_hooks()

    async def _wait_for_updates(self):
        """Checks for updates from assigned GitHub repos at given interval."""
        await self.bot.wait_until_ready()
        # loops until bot stops functioning
        while not self.bot.is_closed:
            # print so you can tell the difference between manual updates and scheduled ones
            print("Scheduled digest firing!")
            await self._create_digest()
            await asyncio.sleep(self.settings["interval"])

    @commands.group(pass_context = True, name="notifymethod")
    async def _set_notification_method(self, ctx):
        """Changes whether digests are created using normal messages or webhooks."""

    @_set_notification_method.command()
    async def message(channel_name : str):
        """Changes cog to send digests to specified channel."""
        # check if channel is on server where command is given
        if not channel_name in [c.name for c in ctx.message.server.channels]:
            await self.bot.say("Channel `{}` not found on this server!".format(channel_name))
            return
        serverId = ctx.message.server.id
        self.settings["notification_methods"][server] = ("message", chanId)
        dataIO.save_json(self.settingPath, self.settings)
        await self.bot.say("Set notification method to message #{}.".format(channel))

    @_set_notification_method.command()
    async def webhook(hook_url : str):
        """Changes cog to send digests utilizing specified webhook."""
        beginUrl = "https://canary.discordapp.com/api/webhooks/"
        # pull webhook id from URL
        if hook_url.startswith(beginUrl):
            hookId = hook_url.split("/")[5]
        async with aiohttp.get(beginUrl + hookId) as response:
            status = response.status
            reason = response.reason
        if status == 200: # OK
            await self.bot.say("Webhook validated.")
            serverId = ctx.message.server.id
            self.settings["notification_methods"][serverId] = ("webhook", hook_url)
            dataIO.save_json(self.settingPath, self.settings)
        else:
            script = "Webhook validation failed: {}: {}".format(status, reason)
            await self.bot.say(script)

    @commands.command(name="gitupdate", pass_context=True)
    async def _force_grab_updates(self, ctx):
        """Produces a digest on command."""
        await self._create_digest(ctx.message.channel)

    @commands.command(name="setin")
    async def _set_interval(self, interval : int):
        """Sets the interval at which the cog checks for updates, in minutes."""
        # minimum digest interval is 60 minutes, subject to change
        if interval < 60:
            interval = 60
        self.settings["interval"] = interval * 60
        await self.bot.say("Check delay set to {} minutes.".format(interval))
        dataIO.save_json(self.settingPath, self.settings)

    @commands.command(name="addrepo")
    async def _add_repos(self, repostr : str):
        """Adds a repository to the set of repos to be checked regularly.
        First checks if it is a valid/accessible repo."""
        if "/" in repostr:
            owner, repo = repostr.split("/")
        site = "https://api.github.com/repos/{}/{}".format(owner,repo)
        async with aiohttp.get(site) as response:
            status = response.status
        # if retrieval was success, assume repo is valid
        if status == 200: # OK
            await self.bot.say("Repository verified. Adding to list of sources.")
            self.settings["repos"].append(repostr)
            dataIO.save_json(self.settingPath, self.settings)
        # if repo nonexistent, say so
        elif status == 404: # Not Found
            await self.bot.say("Repository not found.")
        # for anything else that might happen
        else:
            await self.bot.say("An unknown error occurred. Repository not verified.")

    @commands.command(name="lsrepo")
    async def _list_repos(self):
        """Lists currently added repos."""
        # turns list of repos into GitHub links
        r = "\n".join(["https://github.com/{}".format(s) for s in self.settings["repos"]])
        await self.bot.say("```Currently added repositories:\n{}```".format(r))

    @commands.command(name="delrepo")
    async def _delete_repo(self, repostr : str):
        """Removes repository from set of repos to be checked regularly."""
        repos = self.settings["repos"]
        # since you shouldn't delete a value in something you're iterating over
        # searches through added repos for a match, and binds it with `r`
        # then breaks from the loop
        toPop = None
        for r in repos:
            if repostr == r:
                toPop = r
                break
        # if r hasn't been marked, the repo hasn't been added
        if toPop is None:
            await self.bot.reply("Repository not found!")
        else:
            await self.bot.say("Removing repo `{}` from list.".format(repostr))
            self.settings["repos"].pop(r)
            dataIO.save_json(self.settingPath, self.settings)

def check_folder():
    if not os.path.exists("data/github"):
        print("data/github not detected, creating folder...")
        os.makedirs("data/github")

def check_file():
    defaultSettings = { "interval" : 60,
                        "github_username" : "",
                        "validated" : None,
                        "personal_access_token" : "",
                        "notification_methods" : {},
                        "repos" : []
                        }
    s = "data/github/settings.json"
    if not dataIO.is_valid_json(s):
        print("valid github/settings.json not detected, creating...")
        dataIO.save_json(s, defaultSettings)

def setup(bot):
    check_folder()
    check_file()
    bot.add_cog(GitHub(bot))
