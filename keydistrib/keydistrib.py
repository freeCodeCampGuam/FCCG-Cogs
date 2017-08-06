import discord
import red
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from cogs.utils import checks
import asyncio
import os
import aiohttp
from random import randint
from random import choice as randchoice

SETTINGS_PATH = "data/keydistrib/settings.json"


#TODO: 1st phase
#TODO: get file from owner
#TODO:  if from file, reindex on file modification date change
#TODO: give a key from admin/mod cmd via PM
#TOOD: only give on confirmation
#TODO: track
#TODO:  if they were already given a key
#TODO:  if confirmed
#TODO:  who gave the key
#TODO:  userinfo: name/id/date

#TODO: 2nd phase
#TODO: hand out key on join from specific invite url
#TODO: different files (key pools)
#TODO: display user-key info. who has gotten what, etc
#TODO: also get key-list in DM from mod/admin?
#TODO: msg tied to each file/key (line override)


#---- settings format -----
# Diagram: settings->(FILES->filepath->(SERVERS,KEYS->key), USERS->uid)
# 
# Actual: 
#
#settings = {
#     "FILES": {
#         "filepath": {
#             "SERVERS": ["sid"],
#             "KEYS": {
#                 "key": {
#                     "STATUS": "UNUSED"/"USED",
#                     "DATE": timestamp (update to last action)
#                     "RECIPIENT": {"NAME": "bob", "UID": "uid"},
#                     "SENDER": "uid"
#                 }
#             },
#             "DATE_MODIFIED": timestamp
#         }
#     },
#     "USERS": {
#         "uid": ["filepath\nkey"]  # key indexes
#     }
# }
#


class KeyDistrib:
    """distributes and tracks keys from a file"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(SETTINGS_PATH)

    def _save(self):
        dataIO.save_json(SETTINGS_PATH, self.settings)

    def _update_keys(self, file_path, keys):

        keys_in_settings = self.settings["FILES"][file_path]["KEYS"]
        #keys difference is the symmetric difference of keys inside settings file and in the key list
        keys_difference = set(keys_in_settings).symmetric_difference(set(keys))
        # if key from key_difference is in keys_in_settings and
        # status is unused, then delete key_in_setting 
        for key in keys_difference:
            if keys_in_settings[key] is not None:
                status = keys_in_settings[key]["STATUS"]
                if key in set(keys_in_settings.keys()):
                    if status is "UNUSED":
                        del keys_in_settings["KEYS"][key]
                else:
                    keys_in_settings.update({key: None})




    @checks.is_owner()
    @commands.group(pass_context=True, no_pm=True)
    async def distribset(self, ctx):
        """#TODO: description"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)
    
    @checks.is_owner()
    @distribset.command(pass_context=True, name="file", no_pm=True)
    async def distribset_file(self, ctx, file_path):
        """Set file to read keys from.
        Relative from data/keydistrib/
        Absolute filepaths work as well

        #TODO: describe file format here"""
        server = ctx.message.server
        if not os.path.isabs(file_path):
            file_path = 'data/keydistrib/' + file_path
        if not os.path.exists(file_path):
            await self.bot.say("The specified file does not exist.")
            return

        # open file containing keys
        with open(file_path) as f:
            contents = f.read()
        keys = filter(None, contents.splitlines())
        mtime = os.path.getmtime(file_path)
        # Returns indicated file_path dict. If file doesn't exist, it is added
        keyring = self.settings["FILES"].setdefault(file_path, {
            "SERVERS": [server.id],
            "KEYS": {k: None for k in keys},
            "DATE_MODIFIED": mtime
        })
        # what if our mtime is newer than file's?
        #TODO: prompt user?
        if mtime != keyring["DATE_MODIFIED"]:
            # removes non-existing unused keys
            # adds new keys
            self._update_keys(file_path, keys)

        if server.id not in keyring["SERVERS"]:
            keyring["SERVERS"].append(server.id)

        self._save()
        await self.bot.reply("Keys are ready to be sent.")

    @distribset.command(pass_context=True, name="toggle", no_pm=True)
    async def distribset_toggle(self, ctx, file_path):
        """#TODO: description"""
        server = ctx.message.server

        try:
            keyring = self.settings["FILES"][file_path]
        except KeyError:
            await self.bot.say("That file has not been added yet.\n"
                               "Add it with `{}distribset file`"
                               .format(ctx.prefix))
            return

        try:
            keyring["SERVERS"].remove(server.id)
            msg = "Keys from that file can no longer be distributed in this server"
        except ValueError:
            keyring["SERVERS"].append(server.id)
            msg = "Keys from that file can now be distributed in this server"

        self._save()
        await self.bot.reply(msg)




    @checks.mod_or_permissions()
    @commands.command(pass_context=True, no_pm=True)
    async def givekey(self, ctx, user: discord.Member):
        """#TODO: description"""
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author
        #TODO: send user confirmation prompt
        await self.bot.whisper("")



def check_folders():
    paths = ("data/keydistrib", )
    for path in paths:
      if not os.path.exists(path):
          print("Creating {} folder...".format(path))
          os.makedirs(path)


def check_files():
    default = {}

    if not dataIO.is_valid_json(SETTINGS_PATH):
        print("Creating default keydistrib settings.json...")
        dataIO.save_json(SETTINGS_PATH, default)
    else:  # consistency check
        current = dataIO.load_json(SETTINGS_PATH)
        if current.keys() != default.keys():
            for key in default.keys():
                if key not in current.keys():
                    current[key] = default[key]
                    print(
                        "Adding " + str(key) + " field to keydistrib settings.json")
            dataIO.save_json(SETTINGS_PATH, current)


def setup(bot: red.Bot):
    check_folders()
    check_files()
    n = KeyDistrib(bot)
    bot.add_cog(n)


