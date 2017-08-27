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
from __main__ import send_cmd_help

SETTINGS_PATH = "data/keydistrib/settings.json"
KEYS_PATH = "data/keydistrib/keys"


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
#TODO: formattable msg per keyfile ex: "Welcome to the PICO-8 bootcamp!
#           {sender.display_name} has sent you a PICO-8 key. Please click {key} and
#           register to loxaloffle with an email account you have access to.
#           Once you do that, you should recieve an email with the download link!
#      see customcom.py (welcome.py original) for ex.
#TODO: ^ have a default for that
#TODO: associate file_path with name of key group. (keys.txt => PICO-8)

#TODO: track transactions in process
#TODO: if keyfile changed, remove unused keys even if transaction is in place

#TODO: 2nd phase
#TODO: hand out key on join from specific invite url
#TODO: different files (key pools)
#TODO: display user-key info. who has gotten what, etc
#TODO: also get key-list in DM from mod/admin?
#TODO: msg tied to each file/key (line override)

#TODO: option to limit # of keys

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
#     },
#     "TRANSACTIONS": {
#         "uid": "filepath\nkey"
#     }
# }
#

def update_keys(command, all_keys=False):
    """assumes 3rd arg is name
    updates all keyfiles or only the name (3rd arg)
    """

    def update_wrapper(*args, **kwargs):
        # instance is the cog instance
        settings = command.instance.settings
        self = command.instance
        if all_keys:
            keyfiles = settings['FILES']
        else:
            keyfiles = {args[2]: settings['FILES'][args[2]]}
        for name, keyring in keyfiles:
            try:
                path = _name_to_path(name)
            except FileNotFoundError:
                self._update_keys(name, keys)
            else:
                keys = read_keys(path)
                # what if our mtime is newer than file's?
                #TODO: prompt user?
                mtime = os.path.getmtime(path)
                if mtime != keyring["DATE_MODIFIED"]:
                    # removes non-existing unused keys
                    # adds new keys
                    #TODO: write this
                    self._update_keys(name, keys)

            if server.id not in keyring["SERVERS"]:
                keyring["SERVERS"].append(server.id)
            #TODO: tell user it's done
        self._save()

        return command(*args, **kwargs)

    return update_wrapper


class KeyFileName(commands.Converter):
    def convert(self):
        name = os.path.splitext(self.argument)[0]
        if _name_to_path(name):
            return name
        raise commands.BadArgument("Can't find {} file in the {} folder"
                                   .format(name, KEYS_PATH))


class KeyDistrib:
    """distributes and tracks keys from a file"""

    def __init__(self, bot):
        self.bot = bot
        self.settings = dataIO.load_json(SETTINGS_PATH)

    def _save(self):
        dataIO.save_json(SETTINGS_PATH, self.settings)

    def _update_keys(self, file_path, keys):
        """ this function deletes unused keys in settings file. 
        Otherwise, if it is a newly added key to the
        keys file, it initializes it to None. """
        keys_in_settings = self.settings["FILES"][file_path]["KEYS"]
        keys_difference = set(keys_in_settings).symmetric_difference(set(keys))
        for key in keys_difference:
            if key in keys_in_settings:
                if keys_in_settings[key] is None:
                    del keys_in_settings[key]
                else:
                    status = keys_in_settings[key]["STATUS"]
                    if status == "UNUSED":
                        del keys_in_settings[key]
            else:
                    keys_in_settings[key] = None

    def new_keyring(self, server, file_path):
        with open(file_path) as f:
            contents = f.read()
        keys = filter(None, contents.splitlines())
        mtime = os.path.getmtime(path)

        keyring = self.settings["FILES"].setdefault(file_path, {
            "SERVERS": [server.id],
            "KEYS": {k: None for k in keys},
            "DATE_MODIFIED": mtime
        })

        self._save()
        return keyring

    @checks.admin_or_permissions()
    @commands.group(pass_context=True, no_pm=True)
    async def distribset(self, ctx):
        """#TODO: description"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @checks.is_owner()
    @distribset.command(pass_context=True, name="file", no_pm=True)
    async def distribset_file(self, ctx, name: KeyFileName):
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

    @checks.is_owner()
    @distribset.command(pass_context=True, name="toggle", no_pm=True)
    async def distribset_toggle(self, ctx, name: KeyFileName):
        """#TODO: description"""
        server = ctx.message.server

        file_path = _name_to_path(name)

        try:
            keyring = self.settings["FILES"][file_path]
        except KeyError:  # keyring doesn't exist. this is a new file
            keyring = self.new_keyring(server, file_path)

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

    @distribset.command(pass_context=True, name="msg", aliases=["message"], no_pm=True)
    async def distribset_msg(self, ctx, name: KeyFileName, msg=None):
        """#TODO: description"""
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author
        #TODO: "[p]distribset msg" by itself sets msg to default on confirmation.
        #TODO: write this.

    @update_keys()
    @checks.mod_or_permissions()
    @commands.command(pass_context=True, no_pm=True)
    async def givekey(self, ctx, name: KeyFileName, user: discord.Member):
        """Give a member a key"""
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author
        #TODO: send user confirmation prompt
        await self.bot.whisper("")


def read_keys(path):
    #TODO: Make this a generator?
    with open(path) as f:
        contents = f.read()
    return list(filter(None, contents.splitlines()))


def _name_to_path(name):
    """converts a keyfile name to a path to it
    assume names don't have path included and files have
    .txt extension or no extension

    raises FileNotFoundError if file does not exist
    """
    #TODO: add extra checks to make sure it's within this directory for safety
    name = os.path.join(KEYS_PATH, name)
    if os.path.exists(name):
        return name
    name = name + '.txt'
    if os.path.exists(name):
        return name
    raise FileNotFoundError('No such file: ' + name)


def check_folders():
    paths = ("data/keydistrib", KEYS_PATH)
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

