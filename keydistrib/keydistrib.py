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
DEFAULT_MSG = "{presenter} gave you a {file} key: {key}"


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
#
#TODO: option to limit # of keys
#TODO: update transactions in _update_keys
#
#---- settings format -----
# Diagram: settings->(FILES->filepath->(SERVERS,KEYS->key), USERS->uid)
# 
# Actual: 
#
#settings = {
#     "FILES": {
#         "keyfile_name": {
#             "SERVERS": ["sid"],
#             "KEYS": {
#                 "key": {
#                     "STATUS": "IN-PROGRESS"/"USED",
#                     "DATE": timestamp (update to last action)
#                     "RECIPIENT": {"NAME": "bob", "UID": "uid"},
#                     "SENDER": "uid"
#                 }
#             },
#             "DATE_MODIFIED": timestamp,
#             "MESSAGE": "msg"  # later restructure SERVERS with this
#         }
#     },
#     "USERS": {
#         "uid": ["filepath\nkey"]  # key indexes
#     },
#     "TRANSACTIONS": {
#         "uid": {
#               "SERVERID": "id",
#               "SENDERID": "id",
#                "SENDER":   "name"
#               "FILE":   "name",
#                "KEY":    "key"
#
#                }
#      }
# }
#

class KeyringExists(Exception):
    pass


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

    def _update_file(self, server, keyfile_name=None):
        """Update memory to match keyfile, given its keyfile_name.

        if none given, updates for every keyfile in memory
        """
        settings = self.settings
        if keyfile_name is None:
            keyfiles = settings['FILES']
        else:
            keyfiles = {keyfile_name: settings['FILES'][keyfile_name]}
        for name, keyring in keyfiles.items():
            # only update the keys if they are available in this server
            if server.id not in keyring['SERVERS']:
                continue
            try:
                path = _name_to_path(name)
            except FileNotFoundError as e:
                # if it was a bogus name, just quit
                # if name not in settings['FILES']:
                #     raise e
                # actually, it'll raise a keyerror before this

                # otherwise, make sure to remove the unused keys
                # I guess for now this will keep running until a file
                # gets added. change that later
                self._update_keys(name)
                self._save()
            else:
                mtime = os.path.getmtime(path)
                # if mtime is different, we update.
                # what if our mtime is newer than file's?
                #TODO: prompt user?
                # even if our memory is newer than the file at the path now, 
                # still update (to remove the unused keys)
                if mtime != keyring["DATE_MODIFIED"]:
                    # removes non-existing unused keys
                    # adds new keys
                    #TODO: write this
                    self._update_keys(name)
                    self._save()
            #TODO: tell user it's done

    def _update_keys(self, keyfile_name):
        """ deletes unused keys in settings. 
        Otherwise, if it is a newly added key to the
        keys file, it initializes it to None. """
        keys_in_settings = self.settings["FILES"][keyfile_name]["KEYS"]
        keys = self._get_keys_from_file(keyfile_name)
        keys_difference = set(keys_in_settings).symmetric_difference(set(keys))
        for key in keys_difference:
            if key in keys_in_settings:
                if keys_in_settings[key] is None:
                    del keys_in_settings[key]
                elif keys_in_settings[key]["STATUS"] != "USED":
                    del keys_in_settings[key]
            else:  # add it
                keys_in_settings[key] = None

    def _update_key_info(self, keyfile_name, recipient, recipient_id, sender_id, key):
        """ updates information about the specified key after a
        give_key() instance. """
        self.settings["FILES"][keyfile_name]["KEYS"][key] = {}
        key_info = self.settings["FILES"][keyfile_name]["KEYS"][key]
        key_info["STATUS"] = "USED"
        key_info["DATE"] = os.path.getmtime(_name_to_path(keyfile_name))
        key_info["RECIPIENT"] = {}
        key_info["RECIPIENT"]["NAME"] = recipient
        key_info["RECIPIENT"]["UID"] = recipient_id
        key_info["SENDER"] = sender_id
        self._save()


    def _get_key(self, name, server):
        """ retrieves an available key within the settings file. 
        Raises KeyError if not allowed or no keys available."""
        self._update_file(server, name)
        if not self._can_get_key(name, server):
            raise KeyError("The {} keyfile isn't turned on in this server."
                           .format(name))
        keys = self.settings["FILES"][name]["KEYS"]
        for key, meta in keys.items():
            if meta is None:
                return key
        raise KeyError("No available keys. Please add more keys to {} file").format(name)

    def _can_get_key(self, name, server):
        """whether or not a keyfile is accessible to this server"""
        try:
            keyring = self.settings['FILES'][name]
        except:
            return False
        return server.id in keyring['SERVERS']

    def new_keyring(self, server, keyfile_name):
        if keyfile_name in self.settings["FILES"]:
            raise KeyringExists('{} is already registered as a keyring'
                                .format(keyfile_name))
        keys = self._get_keys_from_file(keyfile_name)
        path = _name_to_path(keyfile_name)
        mtime = os.path.getmtime(path)

        keyring = self.settings["FILES"].setdefault(keyfile_name, {
            "SERVERS": [server.id],
            "KEYS": {k: None for k in keys},
            "DATE_MODIFIED": mtime,
            "MESSAGE": DEFAULT_MSG
        })

        self._save()
        return keyring

    def _get_keys_from_file(self, keyfile_name):
        path = _name_to_path(keyfile_name)
        with open(path) as f:
            contents = f.read()
        return list(filter(None, contents.splitlines()))

    def _generate_key_msg(self, presenter, file, key):
        """
        generates the msg to send to the recipient
        given the presenter, file, and key

        doesn't check if server is allowed to generate a key"""
        return (self.settings['FILES'][file]['MESSAGE']
                .format(presenter=presenter, file=file, key=key))

    def check_repeat(self, user, file):
        """ checks if user received a key already in the past from the keyfile """
        keydata = self.settings["FILES"][file]["KEYS"]
        for key in keydata:
            if keydata[key] is None:
                continue
            elif keydata[key]["RECIPIENT"]["UID"] == user.id:
                return True
        return False

    def _del_transact(self, user_id):
        del self.settings["TRANSACTIONS"][user_id]
        self._save()

    @checks.admin_or_permissions()
    @commands.group(pass_context=True, no_pm=True)
    async def distribset(self, ctx):
        """Key distribution settings"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @checks.is_owner()
    @distribset.command(pass_context=True, name="toggle", no_pm=True)
    async def distribset_toggle(self, ctx, name: KeyFileName):
        """Toggle availability of a key file in this server"""
        server = ctx.message.server

        try:
            keyring = self.settings["FILES"][name]
        except KeyError:  # keyring doesn't exist. this is a new file
            keyring = self.new_keyring(server, name)
            return await self.bot.reply("New keyfile, {}, added. Keys from that file "
                                        "can now be distributed in this server"
                                        .format(name))
        try:
            keyring["SERVERS"].remove(server.id)
            msg = "Keys from that file can no longer be distributed in this server"
        except ValueError: p
        keyring["SERVERS"].append(server.id)
        msg = "Keys from that file can now be distributed in this server"

        self._save()
        await self.bot.reply(msg)

    @distribset.command(pass_context=True, name="msg", aliases=["message"], no_pm=True)
    async def distribset_msg(self, ctx, name: KeyFileName, msg=None):
        """Set the message to be given to whispered to the user."""
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author
        #TODO: Make server-specific
        #TODO: Make customizable agreement msg too
        if not self._can_get_key(name, server):
            return await self.bot.say("This server isn't allowed to "
                                      "generate keys for that keyfile")

        msg = msg or DEFAULT_MSG
        keyring = self.settings['FILES'][name]

        keyring["MESSAGE"], oldmsg = msg, keyring["MESSAGE"]

        if msg is None:
            msg = self._generate_key_msg(author, name, "1TEST2THIS3IS4A5FAKE6KEY")
        await self.bot.say(msg)
        await self.bot.say("**^ This is what the user will receive. "
                           "Is this what you want? (yes/no)**")

        answer = await self.bot.wait_for_message(timeout=60, author=author, channel=channel)
        if answer and answer.content.lower()[0] == 'y':
            await self.bot.say("Message set for {}".format(name))
            self._save()
        else:
            keyring["MESSAGE"] = oldmsg
            msg = "Message unchanged" if answer else "No response.. Message unchanged"
            await self.bot.say(msg)


    @checks.mod_or_permissions()
    @commands.command(pass_context=True, no_pm=True)
    async def give_key(self, ctx, name: KeyFileName, user: discord.Member):
        """ opens a transaction to give a key to a member """
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author

        #if author is user:
         #   return await self.bot.say("What are you doing :neutral_face:")

        self.settings["TRANSACTIONS"][user.id] = {}
        transaction = self.settings["TRANSACTIONS"][user.id]

        transaction["SERVERID"] = server.id
        transaction["SENDERID"] = author.id
        transaction["SENDER"] = author.display_name
        transaction["FILE"] = name
        transaction["KEY"] = self._get_key(name, server)

        self._save()

        if self.check_repeat(user, name):
            return await self.bot.say("{} received a key already!".format(user.name))
        else:
            #TODO: send user confirmation prompt
            message = await self.bot.send_message(user, "{} in the {} server is giving you a "
                                            "{} key. Accept it?(yes/no)"
                                            .format(author.display_name, server.name, name))

    async def on_message(self, message):
        """ await user's response to key offer. If 'yes', send key """
        author = message.author
        transactions = self.settings["TRANSACTIONS"]
        if any(author.id in transaction for transaction in transactions):
            data = transactions[author.id]
            if message.channel.is_private and message.content.lower().startswith("y"):
                file = data["FILE"]
                key = data["KEY"]
                server_id = data["SERVERID"]
                sender_id = data["SENDERID"]
                sender = data["SENDER"]

                await self.bot.send_message(author, self._generate_key_msg(sender, file, key))
                self._update_key_info(file, author.display_name, author.id, sender_id, key)
            elif message.content.lower().startswith("n"):
                await self.bot.send_message(author, "You chose not to accept the key.")
        #self._del_transact(author.id)


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
    default = {"FILES": {}, "USERS": {}, "TRANSACTIONS": {}}

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

