import discord
from discord.ext import commands
from cogs.utils.dataIO import dataIO
from cogs.utils import checks
from copy import deepcopy
import asyncio
import subprocess
import re
import shlex
import os
import time
import psutil

# TODO: psutil in requirements

# mac users may have to:
# brew reinstall ffmpeg --with-ffplay

FFMPEG_DEFAULTS = {'use_avconv': False, 'pipe': False, 'stderr': None,
                   'options': None, 'before_options': None,
                   'headers': None, 'after': None}

SETTINGS_PATH = 'data/ffplay/settings.json'
# technically only 1 should be able to but.. let em
# mixing or something..
DEFAULT_SETTINGS = {"TOGGLE": []}


class Ffplayer:
    """Monkeypatch of StreamPlayer and create_ffmpeg_player"""

    def __init__(self, path, **kwargs):
        default_kwargs = deepcopy(FFMPEG_DEFAULTS)
        default_kwargs.update(kwargs)
        self._path = path
        self._pipe = default_kwargs['pipe']
        self._stderr = default_kwargs['stderr']
        self._subprocess = None
        self._psprocess = None
        self._volume = 1.0
        self._command_list = self._build_command(path,
                                                 default_kwargs['options'],
                                                 self._pipe)
        self._paused = False
        self._timer = None
        self._timer_offset = 0
        self._elapsed_time = 0

    def run(self):
        self.start()

    def start(self):
        if self._subprocess is not None or self._psprocess is not None:
            return
        stdin = None if not self._pipe else self._path
        self._timer = time.perf_counter()
        self._subprocess = subprocess.Popen(self._command_list,
                                            stdin=stdin,
                                            stdout=subprocess.PIPE,
                                            stderr=self._stderr)
        self._psprocess = psutil.Process(pid=self._subprocess.pid)

    def stop(self, *, wait=True):
        if self._subprocess is not None:
            self._subprocess.kill()
            if not self._subprocess_is_complete() and wait:
                self._subprocess.communicate()
            self._subprocess = None
            self._psprocess = None

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value):
        self._volume = min(max(0, value), 2)
        self.stop(wait=False)
        if not self._paused:
            if self._timer is None:
                self._elapsed_time = 0;
            else:
                self._elapsed_time += time.perf_counter() - self._timer
        self._command_list = self._build_command(self._path,
                                                 'volume={}"'.format(self._volume),
                                                 self._pipe,
                                                 offset=self._elapsed_time)
        self.start()
        if self._paused:
            self.pause()

    def pause(self):
        if self.is_done() or self._paused:
            return
        self._paused = True
        self._elapsed_time += time.perf_counter() - self._timer
        self._psprocess.suspend()

    def resume(self):
        if self.is_done() or not self._paused:
            return
        self._psprocess.resume()
        self._timer = time.perf_counter()
        self._paused = False

    def is_playing(self):
        return not (self.is_done() or self._paused)

    def is_done(self):
        return self._subprocess_is_complete()

    def _subprocess_is_complete(self):
        return self._subprocess is None or self._subprocess.poll() is not None

    def _build_command(self, path, options, pipe, *, offset=0):
        # pipe = False  # ignore pipe for now
        # input_path = '-' if pipe else shlex.quote(path)
        input_path = path  # dangerous but can't find out why files with spaces don't work
        m = re.search('volume=(\d.*)"', options or '')
        self._volume = m and m.group(1) or 1
        cmd = ('ffplay -i "{}" -nodisp -autoexit -af volume={} -ss {} -framedrop'
               ' -loglevel warning'.format(input_path, self._volume, offset))
        #print(cmd)
        return shlex.split(cmd)


class Ffplay:
    """ffplay - monkeypatch create_ffmpeg_player to play audio locally. quick solution"""

    def __init__(self, bot):
        self.bot = bot
        self._monkeypatcher = self.bot.loop.create_task(self.monkey_manager())
        self.old_player = discord.voice_client.VoiceClient.create_ffmpeg_player
        self.settings = dataIO.load_json(SETTINGS_PATH)

    @commands.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def speaker(self, ctx, add_server: str=None):
        """Toggles playing music through bot's host computer and discord

        Setting takes effect after the current song
        By default only one server can play through the host computer at a time.
        [p]speaker add   - if you really want to add more servers
        """
        add_server = add_server == 'add'
        server = ctx.message.server
        sids = self.settings['TOGGLE']
        if server.id in sids:  # toggle off
            sids.remove(server.id)
        elif len(sids) > 1 and not add_server:  # warn about adding even more
            await self.bot.say("There are already multiple servers in the "
                               "speaker list.\n`{}speaker add` to add "
                               "more".format(ctx.prefix))
            return
        else:
            if not add_server:
                sids.clear()
            sids.append(server.id)

        dataIO.save_json(SETTINGS_PATH, self.settings)

        if server.id not in sids:  # removed
            if sids:
                await self.bot.say("This server removed from speaker list")
            else:
                await self.bot.say("I will now play music on this server "
                                   "through discord")
        else:
            if len(sids) > 1:
                await self.bot.say("This server has been added to the speaker "
                                   "list.\nYou will be able to hear music "
                                   "being requested from multiple servers now.")
            else:
                await self.bot.say("I will now play music on this server "
                                   "through the host computer ")

    def create_ffplay_player(cogself, old_create):
        def predicate(self, filename, **kwargs):
            default_kwargs = deepcopy(FFMPEG_DEFAULTS)
            default_kwargs.update(kwargs)
            if self.server.id in cogself.settings['TOGGLE']:
                return Ffplayer(filename, **default_kwargs)
            return old_create(self, filename, **default_kwargs)

        predicate.old_player = old_create
        return predicate

    async def monkey_manager(self):
        await self.bot.wait_until_ready()
        try:
            await asyncio.sleep(6)  # be safe
            while True:
                vc = discord.voice_client.VoiceClient
                if not hasattr(vc.create_ffmpeg_player, 'old_player'):
                    print("[WARNING:] Ffplay: -- Overwriting VoiceClient.create_ffmpeg_player --")
                    vc.create_ffmpeg_player = self.create_ffplay_player(vc.create_ffmpeg_player)
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    def __unload(self):
        self._monkeypatcher.cancel()
        # revert
        vc = discord.voice_client.VoiceClient
        if hasattr(vc.create_ffmpeg_player, 'old_player'):
            print('Ffplay [CLEANUP:] -- Trying to revert create_ffmpeg_player --')
            vc.create_ffmpeg_player = vc.create_ffmpeg_player.old_player


def check_folders():
    paths = ("data/ffplay", )
    for path in paths:
        if not os.path.exists(path):
            print("Creating {} folder...".format(path))
            os.makedirs(path)


def check_files():
    settings_path = "data/ffplay/settings.json"

    if not dataIO.is_valid_json(SETTINGS_PATH):
        print("Creating default ffplay settings.json...")
        dataIO.save_json(SETTINGS_PATH, DEFAULT_SETTINGS)
    else:  # consistency check
        current = dataIO.load_json(SETTINGS_PATH)
        if current.keys() != DEFAULT_SETTINGS.keys():
            for key in DEFAULT_SETTINGS.keys():
                if key not in current.keys():
                    current[key] = DEFAULT_SETTINGS[key]
                    print("Adding {} field to ffplay "
                          "settings.json".format(key))
            dataIO.save_json(SETTINGS_PATH, current)


def setup(bot):
    check_folders()
    check_files()
    n = Ffplay(bot)
    bot.add_cog(n)
