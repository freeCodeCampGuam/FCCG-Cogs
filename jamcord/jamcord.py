import discord
from discord.ext import commands
from cogs.utils import checks
from cogs.utils.dataIO import dataIO
from cogs.utils.chat_formatting import pagify
from contextlib import redirect_stdout
import re
import asyncio
import youtube_dl
import threading
import os
import subprocess
from glob import glob
from queue import Queue, Empty
import time
from urllib.parse import urlparse
from cogs.repl import interactive_results
from cogs.repl import wait_for_first_response
from copy import deepcopy
from random import choice
from __main__ import send_cmd_help
try:
    import pyaudio
except:
    pyaudio = None


SETTINGS_PATH = "data/jamcord/settings.json"
INTERPRETERS_PATH = "data/jamcord/interpreters/"
SAMPLE_PATH = 'data/jamcord/samples/'
SAMPLE_PATH_ABS = os.path.join(os.getcwd(), SAMPLE_PATH)

NBS = '​'

youtube_dl_options = {
    'source_address': '0.0.0.0',
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'wav',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'wav',
    }],
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'outtmpl': SAMPLE_PATH+"%(id)s",
    'default_search': 'auto',
    'encoding': 'utf-8'
}


DEFAULT_SAMPLE = {
    'SOURCE': 'unknown source',
    'REQUESTER': {
        'NAME_DISCRIM': 'unknown person',
        'ID': None
    }
}

SUPPORTED_SAMPLE_EXTS = ('.wav',)

DEFAULT_INTERPRETER_CONFIG = {
    "cwd": ".",
    "cmd": "{}",
    "eval_fmt": "{}\n",
    "hush": "",
    "preloads": [],
    "servers": [],
    "intro": ['Welcome!!\nThis is a collaborative window into {}\n'
              'execute a reset() or cls() to reposition your terminal\n'
              'close this console to reposition it.\n'
              '-' * 51 + '\n'],
    "path_requirements": []
}

INTERPRETER_PRESETS = {
    "foxdot": {
        "cwd": ".",
        "cmd": "{foxdotpython} -m {foxdot} --pipe",
        "eval_fmt": "{}\n\n",
        "hush": "Clock.clear()",
        "preloads": ['Samples.addPath("{samples}")'],
        "servers": [{
            "print": False,
            "cwd": "{sclang}",
            "cmd": "./sclang",
            "preloads": ["Server.killAll\n", "FoxDot.start\n"],
            "wait": 3
        }],
        "intro": [
            'Welcome!!\nThis is a collaborative window into FoxDot\n'
            ' p1 >> piano([0,[-1, 1],(2, 4)])\n'
            ' p2 >> play("(xo){[--]-}")\n'
            'execute a reset() or cls() to reposition your terminal\n'
            'execute a . to stop all sound\n'
            '[p]jam help foxdot for more on FoxDot!\n'
            'close this console to reposition it also\n' + '-' * 51 + '\n'
        ],
        "path_requirements": ["sclang", "foxdot", "foxdotpython"]
    },
    "tidal": {
        "cwd": ".",
        "cmd": "{tidal}",
        "eval_fmt": ":{{\n{}\n:}}\n",  # for multipe lines
        "hush": "hush",
        "preloads": [
            "import Sound.Tidal.Context",
            ":set -XOverloadedStrings",
            "(cps, getNow) <- bpsUtils"] +
            ["(d{}, t{}) <- superDirtSetters getNow".format(n, n)
             for n in range(1, 10)] +
            ["let hush = mapM ($ silence) [d1,d2,d3,d4,d5,d6,d7,d8,d9]"],
        "servers": [{
            "print": False,
            "cwd": "{sclang}",
            "cmd": "./sclang",
            "preloads": ["Server.killAll\n", "SuperDirt.start\n"],
            "wait": 3
        }],
        "intro": [
            'Welcome!!\nThis is a collaborative window into TidalCycles\n'
            ' I have no idea how to use Tidal!\n'
            ' eeeuhhhhhh tidal example\n'
            'execute a `reset` or `cls` to reposition your terminal\n'
            'execute a `.` to stop all sound\n'
            '[p]jam help tidal for more on TidalCycles!\n'
            'close this console to reposition it also\n' + '-' * 51 + '\n'
        ],
        "path_requirements": ["sclang", "tidal"]
    }
}


# TODO: rewrite that whole pager nonsense
# x: reaction remove fix
# x: addwink can join in right away
# x: page better
# x: move user interpreter down
# TODO: allow paging to go both ways
# x: fix this in FoxDot   
#       File "/usr/local/lib/python3.6/site-packages/FoxDot/lib/Patterns/Generators.py", line 60, in choose
#           return self.data[self.choice(xrange(self.MAX_SIZE))]
#       NameError: name 'xrange' is not defined
# x: delete queue / try_delete after wait and check if session
#   x: make this a setting
# x: clients / no-console mode (# of checks means how many clients connected!)
# TODO: local execute only: keyword in msg (easier) or separate button
# ~x: set up paths to work w/ FoxDot (and Troop if needed) in REQUIREMENTS
# x: get tidal working
# TODO: tidal intro text also
# x: display "user: input" if no stdout / result
# x: add a way for users to send permanent msgs if in cleanup mode
# TODO: @mention users if error. (if interpreter-specific regex is matched?)
# x: split interpreter config in own files
#   data/jamcord/interpreters/
#       foxdot.json
#       tidal.json
# TODO: write generic socket repl for Extempore and like envs


_reaction_remove_events = set()


# heavily based on Troop's interpreter
class Interpreter():
    """Replace Troop w/ a general purpose cmd line 
    livecoding env communication thingamajig.

    add subclasses for specifics needed. 
    maybe move all that self.interpreter stuff into those
    """

    def __init__(self, cwd, command, eval_fmt="{}\n", preloads=[], readable=True):
        self.ready = False
        self.command = command
        self.cwd = cwd
        self.eval_fmt = eval_fmt.format
        self.preloads = preloads
        self.output_q = Queue()
        self.done = False
        self.cli = subprocess.Popen(self.command, shell=True,
                                    universal_newlines=True,
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    cwd=self.cwd)
        for l in self.preloads:
            self.eval(l)
        self.readable = readable
        self.ready = True
        if readable:
            self.output_thread = threading.Thread(target=self._watch_output)
            self.output_thread.start()

    def is_alive(self):
        if self.cli is None or self.cli.returncode is not None or self.done:
            return False
        return True

    def _watch_output(self):
        while self.is_alive():
            time.sleep(.1)
            try:
                for line in iter(self.cli.stdout.readline, ""):
                    self.output_q.put(line)
            except ValueError:  # closed file
                continue

    def eval(self, string):
        self.cli.stdin.write(self.eval_fmt(string))
        self.cli.stdin.flush()

    def read(self):
        result = []
        while True:
            try:
                result.append(self.output_q.get_nowait())
            except Empty:
                return "\n".join(result)

    def kill(self):
        threading.Thread(target=self._block_kill).start()

    def _block_kill(self):
        self.cli.communicate()
        self.cli.kill()


# hmm...
class InterpreterWithServers(Interpreter):
    """just to consolidate interpreter heirarchies"""

    def __init__(self, loop, cwd, command, eval_fmt="{}\n", preloads=[],
                 readable=True, servers=[]):
        self.ready = False
        self.servers = []
        loop.create_task(self._start(cwd, command, eval_fmt, preloads, servers))

    async def _start(self, cwd, command, eval_fmt, preloads, servers):
        for s in servers:
            self.servers.append(Interpreter(s['cwd'], s['cmd'], eval_fmt='{}',
                                            preloads=s['preloads'],
                                            readable=s['print']))
            await asyncio.sleep(s['wait'])
        super().__init__(cwd, command, eval_fmt, preloads)

    def kill(self):
        super().kill()
        for s in self.servers:
            s.kill()

    def read(self):
        result = []
        for s in self.servers:
            if s.readable:
                result.append(s.read())
        result.append(super().read())
        return "\n".join(result)


# TODO
class AudioStream():
    """Stream Jam Audio from the bot to Discord"""
    NotImplemented


class SmallerStream:
    """temporary solution to pyaudio quadrupling samples returned"""
    def __init__(self, stream):
        self.stream = stream

    def read(self, frame_size):
        return self.stream.read(int(frame_size/4))

    def stop(self):
        self.stream.stop_stream()
        self.stream.close()


# ripped from audio.py
class Song:
    def __init__(self, **kwargs):
        self.__dict__ = kwargs
        self.title = kwargs.pop('title', None)
        self.id = kwargs.pop('id', None)
        self.url = kwargs.pop('url', None)
        self.webpage_url = kwargs.pop('webpage_url', "")
        self.duration = kwargs.pop('duration', 60)
        self.start_time = kwargs.pop('start_time', None)
        self.end_time = kwargs.pop('end_time', None)
        self.ext = kwargs.pop('ext', None)


class Downloader(threading.Thread):
    def __init__(self, url, options, download=False):
        super().__init__()
        self.url = url
        self.done = threading.Event()
        self.song = None
        self._yt = None
        self.error = None
        self.options = options
        self._download = download

    def run(self):
        try:
            self.get_info()
        except youtube_dl.utils.DownloadError as e:
            self.error = str(e)
        except OSError as e:
            print("An operating system error occurred while downloading URL "
                  "'{}':\n'{}'".format(self.url, str(e)))

        if not self._download:
            return

        if not os.path.isfile(self.options['outtmpl']):
            self.video = self._yt.extract_info(self.url)
            self.song = Song(**self.video)
    
    def get_info(self):
        if self._yt is None:
            self._yt = youtube_dl.YoutubeDL(self.options)
        if "[SEARCH:]" not in self.url:
            video = self._yt.extract_info(self.url, download=False,
                                          process=False)
        else:
            self.url = self.url[9:]
            yt_id = self._yt.extract_info(
                self.url, download=False)["entries"][0]["id"]
            # Should handle errors here ^
            self.url = "https://youtube.com/watch?v={}".format(yt_id)
            video = self._yt.extract_info(self.url, download=False,
                                          process=False)

        if(video is not None):
            self.song = Song(**video)


# Also ripped from Audio :3
def match_any_url(url):
    url = urlparse(url)
    if url.scheme and url.netloc and url.path:
        return True
    return False

def match_sc_url(url):
    sc_url = re.compile(
        r'^(https?\:\/\/)?(www\.)?(soundcloud\.com\/)')
    if sc_url.match(url):
        return True
    return False

def match_yt_url(url):
    yt_link = re.compile(
        r'^(https?\:\/\/)?(www\.|m\.)?(youtube\.com|youtu\.?be)\/.+$')
    if yt_link.match(url):
        return True
    return False

# Checking only yt/sc now since someone could pull the IP by 
# pointing the bot to their own server
# TODO: add a toggle_any_url or whitelist regex/basepath w/ warning
def valid_playable_url(url):
    yt = match_yt_url(url)
    sc = match_sc_url(url)
    if yt or sc:
        return True
    return False


class ReactionRemoveEvent(asyncio.Event):
    def __init__(self, emojis, author, check=None):
        super().__init__()
        self.emojis = emojis
        self.author = author
        self.reaction = None
        self.check = check

    def set(self, reaction):
        self.reaction = reaction
        return super().set()


class Jamcord:
    """Jamcord - A collaborative window your favorite LiveCoding environments.

    This cog, while still in alpha, lets you write music live in Discord by yourself
    or with any number of your buddies!

    Atm this cog requires you to install and set up your environment on your own.
    Once it's set up, nobody else jamming w/ you will need to install anything 
    or even know about LiveCoding!

    To see what you need to do, use [p]jam setup

    Have any questions, want to jam, or want to help with development?
    Come join us on the LiveCoding Discord! https://discord.gg/49XSK94
    """

    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}
        self.repl_settings = {'REPL_PREFIX': ['`']}
        self.settings = dataIO.load_json(SETTINGS_PATH)
        self.previous_sample_searches = {}
        self.interpreters = {}
        self._load_interpreters()
        self.pyaudio = pyaudio

    def _load_interpreters(self):
        repls = os.listdir(INTERPRETERS_PATH)
        for f in repls:
            repl = dataIO.load_json(os.path.join(INTERPRETERS_PATH, f))
            self.interpreters[os.path.splitext(f)[0].lower()] = repl

    def _save(self):
        dataIO.save_json(SETTINGS_PATH, self.settings)

    def format_paths(self, fmt):
        for name, path in self.settings["INTERPRETER_PATHS"].items():
            fmt = fmt.replace('{' + name + '}', path)
        fmt.replace('{samples}', SAMPLE_PATH_ABS)
        return fmt

    def missing_interpreter_reqs(self, kind):
        reqs = self.interpreters[kind]['path_requirements']
        paths = self.settings["INTERPRETER_PATHS"]
        return set(reqs).difference(paths)

    def cleanup_code(self, content):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith('```') and content.endswith('```'):
            return '\n'.join(content.split('\n')[1:-1])

        # remove `foo`
        for p in self.repl_settings["REPL_PREFIX"]:
            if content.startswith(p):
                if p == '`':
                    return content.strip('` \n')
                content = content[len(p):]
                return content.strip(' \n')

    async def _download_sample(self, search, options, to_download):
        d = Downloader(search, options, download=to_download)
        d.start()
        while d.is_alive():
            await asyncio.sleep(1)
        return d

    async def _get_sample_requester(self, server, name):
        """returns the server member that requested the sample
        or the last name_discrim he was last known by if not found

        updates the last known name if found to be different"""
        data = self.settings['SAMPLES'][name]['REQUESTER']
        # they don't need to know if ppl from other servers change names
        if data['ID'] is None:
            return data['NAME_DISCRIM']

        try:
            member = next(m for m in server.members if m.id == data['ID'])
        except StopIteration:
            return data['NAME_DISCRIM']

        if str(member) != data['NAME_DISCRIM']:
            data['NAME_DISCRIM'] = str(member)
            self._save()

        return member

    def parse_search_or_url(self, url_or_search_term):
        """returns stripped url if it is valid (yt/sc) 
        otherwise returns false if url is given but invalid
        otherwise returns [SEARCH:] prepended search terms"""
        url = url_or_search_term.strip("<>")

        if match_any_url(url):
            if not valid_playable_url(url):
                return False
        else:
            url = url.replace("/", "&#47")
            url = "[SEARCH:]" + url

        return url

    @commands.group(pass_context=True, no_pm=True)
    async def sample(self, ctx):
        """additional samples management"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @sample.command(pass_context=True, name="info")
    async def sample_info(self, ctx, name=None):
        """display info about a sample

        if name left blank, lists all samples"""
        server = ctx.message.server

        ls = [s.split('.')[0] for s in os.listdir(SAMPLE_PATH)
              if s.endswith(SUPPORTED_SAMPLE_EXTS)]
        if name is None:
            await self.bot.say('**Additional samples:**```\n{}```'.format(' '.join(ls)))
            return

        if name not in ls:
            return await self.bot.say('That sample does not exist.')

        default = deepcopy(DEFAULT_SAMPLE)
        data = self.settings['SAMPLES'].setdefault(name, default)
        requester = await self._get_sample_requester(server, name)
        fmt = ("Sample: **{}**\n"
               "Requested by: **{}**\n"
               "Link: {}".format(name, requester, data['SOURCE']))
        await self.bot.say(fmt)

    @sample.command(pass_context=True, name="add")
    async def sample_add(self, ctx, name, *, url_or_search_terms=None):
        """search for and download a sample from youtube

        the name is used as the search parameter if none is given

        WIP please feel free to make PRs :)
        
        * for use in FoxDot only atm
        """

        """
        x: allow urls as well
        TODO: add list option
        x: save source url/name
        TODO: more in-depth controls: delete / add to sample subfolder?
        TODO: post search result and ask for confirmation
        TODO: way to sync samples across local clients
        TODO: add duration limit
        TODO: add permissions for overwriting samples
        TODO: limit usage to jammers
        TODO: add sample grab from user upload
        TODO: add sample remove
        TODO: assure we don't trample samples due to async when rapid requests come in
        """
        author = ctx.message.author
        server = ctx.message.server

        # search is name if None
        search = url_or_search_terms or name

        options = youtube_dl_options.copy()
        options['outtmpl'] = SAMPLE_PATH + name + '.%(ext)s'

        path = SAMPLE_PATH + name + '.wav'
        sample_exists = os.path.exists(path)

        # prepare url
        search = self.parse_search_or_url(search)

        if not search: # not yt/sc (later add whitelisting/toggle)
            return await self.bot.say("That is not a valid url")

        # see if we've resolved before
        # and values in case they rename samples I guess
        if (search in self.previous_sample_searches or
                search in self.previous_sample_searches.values()):
            search = self.previous_sample_searches.get(search, search)

        # resolve url
        m = None
        if search.startswith('[SEARCH:]'):
            s = ('Sample name exists! One sec, grabbing link..'
                 if sample_exists else '🔎..')
            m = await self.bot.say(s)
            d = await self._download_sample(search, options, False)
            self.previous_sample_searches[search] = d.url
            search = d.url

        default = deepcopy(DEFAULT_SAMPLE)
        sample_data = self.settings['SAMPLES'].setdefault(name, default)
        requester = await self._get_sample_requester(server, name)

        embed_link = url_or_search_terms != search

        prompt = 'Downloading' + (': ' + search if embed_link else '...')
        if sample_exists:
            s = ('{} already exists.\nIt comes from {}\nRequested by '
                 '**{}**.\n\nreplace it with {} ? (yes/no)'
                 ''.format(name, sample_data['SOURCE'], requester, 
                           search if embed_link else '<{}>'.format(search)))
            if m is None:
                await self.bot.say(s)
            else:
                await self.bot.edit_message(m, new_content=s)
            answer = await self.bot.wait_for_message(timeout=45, author=author)
            
            if answer and answer.content.lower() in ('y', 'yes'):
                prompt = 'ok. replacing ' + path + '\n'
                os.remove(path)
            else:
                return await self.bot.say("ok. I won't overwrite it.")

        m = await self.bot.say(prompt)

        d = await self._download_sample(search, options, True)

        sample_data['SOURCE'] = d.url
        sample_data['REQUESTER'] = {'NAME_DISCRIM': str(author), 
                                    'ID': author.id}
        self.settings['SAMPLES'][name] = sample_data
        self._save()
        await self.bot.say(name + ' downloaded to ' + SAMPLE_PATH + name + '.wav')

    @checks.is_owner()
    @commands.group(pass_context=True)
    async def jamset(self, ctx):
        """settings for jams"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)
    
    @jamset.command(pass_context=True, name="path")
    async def jamset_path(self, ctx, interpreter: str=None, *, path=None):
        """Set the path(s) to your interpreter(s).
        These will be lowercased and allowed to be used in the
        base and server-level cwd, cmd, and preload fields in
        interpreter.json

        * [p]jamset path by itself lists the paths set
        * leave path empty to remove the interpreter
        
        Example:
        You will likely need to set your SuperCollider path like this:
         [p]jamset path SClang /absolute/path/to/SuperCollider/resources/
        
         This would allow you to use "{sclang}" in your server.cwd
         to correctly cd into SuperCollider's binaries and
         spin up ./sclang for each jam session

        Note: If your interpreters are already in your path, just set them as their names
        Examples: 
         [p]jamset path foxdot FoxDot
         [p]jamset path FoxDotPython python3
         [p]jamset path tidal stack ghci"""
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author

        paths = self.settings["INTERPRETER_PATHS"]

        if interpreter is None:
            fmt = "\n".join("  **{{{}}}** => `{}`".format(name, path)
                            for name, path in paths.items())
            return await self.bot.say("Paths set:\n" + fmt)

        interpreter = interpreter.lower()

        if path is None:
            if interpreter not in paths:
                await self.bot.say("{} path not yet set."
                                   "\nUse `{}jamset path` to find out how to "
                                   "set it.".format(interpreter, ctx.prefix))
                return
            del paths[interpreter]
            await self.bot.say(interpreter + "'s path has been removed from the bot")
            return

        paths[interpreter] = path
        self._save()
        await self.bot.say("{0} path is now {1}\n"
                           "it can now be accessed via {{{0}}} "
                           "on interpreter setup".format(interpreter, path))

    @jamset.command(pass_context=True, name="reset")
    async def jamset_reset(self, ctx):
        """revert the default interpreters in interpreters.json
        to their default settings"""
        author = ctx.message.author

        keys = INTERPRETER_PRESETS.keys()
        await self.bot.say("Are you sure you want to revert the interpreter "
                           "settings for **{}**? (y/n)".format(", ".join(keys)))
        answer = await self.bot.wait_for_message(timeout=15, author=author)
        if not (answer and answer.content.lower() in ('y', 'yes')):
            return await self.bot.say("Ok. Won't revert.")

        for k in keys:
            path = os.path.join(INTERPRETERS_PATH, k + ".json")
            check_file(path, INTERPRETER_PRESETS[k], revert_defaults=True)
        self.interpreters = dataIO.load_json(INTERPRETERS_PATH)

        await self.bot.say("**{}** reverted to default "
                           "settings".format(", ".join(keys)))

    @jamset.command(pass_context=True, name="reload")
    async def jamset_reload(self, ctx):
        """reload data from interpreters.json"""
        check_interpreters()
        self._load_interpreters()
        await self.bot.say("interpreters reloaded")

    async def start_console(self, ctx, session):
        server = ctx.message.server
        task = interactive_results(self.bot, ctx, session['pages'],
                                   timeout=None, authors=server.members)
        await asyncio.sleep(0.1)
        task = self.bot.loop.create_task(task)
        await asyncio.sleep(0.1)
        answer = await self.bot.wait_for_message(timeout=15, author=server.me,
                                                 check=lambda m: m.content.startswith(NBS))
        session['console'] = answer
        return task

    async def replace_pages(self, session):
        for i in range(len(session['pages'])):
            if i > 0:
                session['pages'].pop()
        if session['pages']:
            page = self.pager(session)()
            session['pages'][0] = page
            return page

    def pager(self, session):
        async def page():
            discord_fmt = NBS + '```py\n{}\n```{}/{}'
            output = '\n'.join([s.strip() for s in session['output']])
            pages = [p for p in line_pagify(output, page_length=1400)]
            res = pages[session['page_num']]
            session['page_num'] -= 1
            session['page_num'] %= len(pages)
            # dirty semi-insurance
            session['pages'].append(page())
            self.bot.loop.create_task(self.replace_pages(session))
            return discord_fmt.format(res.strip(), session['page_num'] + 1,
                                      len(pages))
        return page

    # adjust later. I want a server-mode fork where anybody can start one
    @checks.is_owner()
    @commands.group(pass_context=True, no_pm=True)
    async def jam(self, ctx):
        """all your jamming needs"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)

    @jam.command(pass_context=True, name="bot", no_pm=True)
    async def jam_bot(self, ctx):
        """[EXPERIMENTAL] Have the bot send your default audio input to Discord
        This is only useful if you use Jack or SoundFlower to redirect your out to in

        You must be in a voice channel to start this (so the bot knows where to go 👀) 
        Do [p]jam bot again to stop

        This command will attempt to pip install pyaudio if you don't have it.
        pyaudio requires portaudio to install: http://www.portaudio.com/
        You can install it with:
        On Mac: brew install portaudio
        On Linux: sudo apt install python3-pyaudio

        Please submit a PR if you can figure out how to get it to send default
        output directly :P

        This will probably be replaced with an audio stream beinf served through a web server"""
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author

        if self.pyaudio is None:
            await self.bot.say("Wasn't able to import `pyaudio`. Try to `pip install` it? (y/n)")
            answer = await self.bot.wait_for_message(timeout=30, author=author)
            if answer.content.lower() in ('y', 'yes'):
                m = await self.bot.say("Installing..")
                success = self.bot.pip_install('pyaudio')
                try:
                    import pyaudio
                    self.pyaudio = pyaudio
                except ModuleNotFoundError:
                    success = False
                if not success:
                    await self.bot.say("I wasn't able to install `pyaudio`. Please make sure you "
                                       "have `portaudio` installed: http://www.portaudio.com/"
                                       "\n**MAC**: `brew install portaudio`"
                                       "\n**LINUX**: `sudo apt install python3-pyaudio`")
                    return
                await self.bot.edit_message(m, new_content='Installed!')
            else:
                await self.bot.say("Alright, I won't install it.")
                return
            

        if channel.id not in self.sessions:
            await self.bot.say('There is no jam session in this channel.')
            return

        if author.voice_channel is None:
            await self.bot.say("Please join a voice channel first so "
                               "I know where to go")
            return

        try:
            vc = await self.bot.join_voice_channel(author.voice_channel)
        except discord.ClientException:
            await self.bot.say('Disconnecting from voice.')
            if self.sessions[channel.id]['voice_client']:
                self.sessions[channel.id]['voice_client'].audio_player.stop()
            self.sessions[channel.id]['voice_client'] = None
            await server.voice_client.disconnect()
            return

        await asyncio.sleep(1)  # bot some time to settle after joining

        p = self.pyaudio.PyAudio()
        audio_in = p.get_default_input_device_info()
        stream = p.open(format=p.get_format_from_width(2),
                        channels=int(audio_in['maxInputChannels']),
                        rate=int(audio_in['defaultSampleRate']),
                        input=True,
                        # allow audio device choice later if needed
                        input_device_index=audio_in['index'])
        stream = SmallerStream(stream)
        def stop_and_leave():
            stream.stop()
            try:
                self.bot.loop.create_task(server.voice_client.disconnect())
            except AttributeError:
                pass
        vc.audio_player = vc.create_stream_player(stream, after=stop_and_leave)
        self.sessions[channel.id]['voice_client'] = vc
        vc.audio_player.start()

    @jam.command(pass_context=True, name="setup", no_pm=True)
    async def jam_setup(self, ctx):
        """since this cog is in alpha, you'll need to setup some things first

        You'll need:
        1. Interpreter(s): FoxDot+SC3 Plugins(most supported) / TidalCycles / Extempore(soon)
        2. Troop(soon won't be needed) [https://github.com/Qirky/Troop]
        3. SuperCollider (you will need to make sure this is running w/ FoxDot or Tidal servers on)
        4. A way to redirect audio-out back into audio-in (SoundFlower works on Mac)
        5. Set Troop's path w/ [p]jamset path troop
        """
        s = ("You'll need:\n"
             "1. Interpreter(s): FoxDot+SC3 Plugins(most supported) / TidalCycles / Extempore(soon)\n"
             "2. Troop(soon won't be needed) [https://github.com/Qirky/Troop]\n"
             "3. SuperCollider (you will need to make sure this is running w/ FoxDot or Tidal servers on)\n"
             "4. A way to redirect audio-out back into audio-in (SoundFlower works on Mac)"
             "5. Set Troop's path w/ `{}jamset path troop`")
        await self.bot.say(s.format(ctx.prefix))
    
    @jam.group(pass_context=True, name='help', aliases=['tutorial'],
               invoke_without_command=True)
    async def jam_tutorial(self, ctx):
        """Not sure what this all is or how to start? Here's some info 👍"""
        # TODO: move this allllllll to a Wiki

        s = ("The General Usage of this cog goes like this:\n\n"
             "`{0}jam on` starts a default jam session (type `{0}help jam on` for more info)\n"
             "Once started, you'll be prompted to enter a `code` msg or ```code block```"
             "That will be your terminal. Keep editing that message to change what will be sent, "
             "and click on the ☑ to execute it!\n\n"
             "Executing a `quit` or `exit` will close the session at any time.\n"
             "You can also move your terminal to the bottom of the channel by executing "
             "`cls`, `reset`, or `refresh`,\nalthough if you need to do this often, you probably "
             "want to turn on `{0}jam clean` instead.\n"
             "Like the terminals, you can reset the bot's console by pressing the ❌\n"
             "It will reappear when you send the next block of code.\n\n"
             "Ready to invite people into your jam? Just use `{0}jam invite`, but be very "
             "careful with who you invite.\nYou are giving them permission to execute arbitrary "
             "code on your bot's computer, meaning they can read and destroy pretty much everything.\n"
             "If you want to share the risk, or would just like some better quality audio for "
             "everyone jamming, you can get your jam buddies to install this cog as well and join your "
             "session with their consoles off (`{0}help jam on` for more info). \n"
             "Everyone will have to `reset` their terminals so that the bots have their terminals in sync.\n\n"
             "If you're not sure how to send a code block, check out this link: "
             "https://support.discordapp.com/hc/en-us/articles/210298617\n\n"
             "If you want to use Syntax Highlighting these combos will probably help most\n"
             "**FoxDot**: `py`\n**Tidal**: `haskell`\n**Extempore**: `scheme`\n\n"
             "")
        await self.bot.say(s.format(ctx.prefix))
        await send_cmd_help(ctx)

    @jam_tutorial.command(pass_context=True, name="livecoding")
    async def info_livecoding(self, ctx):
        """What's LiveCoding?"""
        s = ("LiveCoding is a performance art where musicians/participants\n"
             "write software that generates the music live while the music is playing.\n"
             "Here's an example: https://youtu.be/smQOiFt8e4Q\n\n"
             "LiveCoding isn't constrained to only music but it is the most common.\n"
             "Home of LiveCoding: https://toplap.org/\n"
             "They have a Slack too!: http://toplap.org/toplap-on-slack/\n\n"
             "Soon we'll get live coding visuals into Discord too! \o/\n"
             "If you're interested in helping dev that, join the LiveCoding discord "
             "server linked in `{0}help Jamcord` and let me(irdumb) know!\n\n")
        await self.bot.say(s.format(ctx.prefix))

    @jam_tutorial.command(pass_context=True)
    async def foxdot(self, ctx):
        """info about the FoxDot environment"""
        s = ("This is **FoxDot** <http://foxdot.org/>\n"
             "There are some `docs` and `Tutorials` <here: https://github.com/Qirky/FoxDot>\n"
             "Including a description of Effects <https://github.com/Qirky/FoxDot/blob/master/docs/Effects.md>\n"
             "Basics:\n"
             "1. All 1-2 letter variable names have been assigned `Player()` objects. We can assign instruments (SynthDefs) to them like so `p1 >> piano()`\n"
             "2. We can give the synth notes to play in a pattern `p1 >> piano([0,2,4])` (0 is the root, 7 is an octave up)\n"
             "3. We can add attributes (effects) `p1 >> piano([0,2,4], amp=.5, dur=4)`\n"
             "4. Attributes can be given patterns too `p1 >> piano([0,2,4], dur=[.25,.25,1])`\n"
             "5. `[]` in patterns alternate. `()` plays them at the same time (chord) `p1 >> piano([0, [1,-1], (2,4)], amp=[.5,1])`\n"
             "6. the `play` synth is special. it plays samples. <https://github.com/Qirky/FoxDot#sample-player-objects> `p1 >> play('x - - [--] ')` Notice, its \"notes\" are surrounded in quotes.")
        await self.bot.say(s)
        s = ("```py\n"
             "#scales | print(Scale.names())\n"
             "Scale.default='minor'\n"
             "Root.default.set(-1)\n"
             "['chromatic', 'dorian', 'dorian2', 'egyptian', 'freq', 'harmonicMajor', 'harmonicMinor', 'indian', 'justMajor', 'justMinor', 'locrian', 'locrianMajor', 'lydian', 'lydianMinor', 'major', 'majorPentatonic', 'melodicMinor', 'minor', 'minorPentatonic', 'mixolydian', 'phrygian', 'prometheus', 'ryan', 'zhi']\n"
             "\n"
             "#instruments | print(SynthDefs)\n"
             "p1 >> pulse([0,2,4]).stop() # p1.reset() to remove all attributes\n"
             "dict_keys(['loop', 'play1', 'play2', 'audioin', 'pads', 'noise', 'dab', 'varsaw', 'lazer', 'growl', 'bass', 'dirt', 'crunch', 'rave', 'scatter', 'charm', 'bell', 'gong', 'soprano', 'dub', 'viola', 'scratch', 'klank', 'ambi', 'glass', 'soft', 'quin', 'pluck', 'spark', 'blip', 'ripple', 'creep', 'orient', 'zap', 'marimba', 'fuzz', 'bug', 'pulse', 'saw', 'snick', 'twang', 'karp', 'arpy', 'nylon', 'donk', 'squish', 'swell', 'razz', 'sitar', 'star', 'piano', 'sawbass', 'prophet'])\n"
             "\n"
             "#attributes | print(Player.Attributes())\n"
             "p1 >> piano([0,2,4], oct=6)  # must be reset to default or use .reset() to reset all attrs\n"
             "p1.delay = (2,4)  # patterns can be used\n"
             "('degree', 'oct', 'freq', 'dur', 'delay', 'buf', 'blur', 'amplify', 'scale', 'bpm', 'sample', 'env', 'sus', 'fmod', 'pan', 'rate', 'amp', 'midinote', 'channel', 'vib', 'vibdepth', 'slide', 'sus', 'slidedelay', 'slidefrom', 'bend', 'benddelay', 'coarse', 'pshift', 'hpf', 'hpr', 'lpf', 'lpr', 'swell', 'bpf', 'bpr', 'bpnoise', 'bits', 'amp', 'crush', 'dist', 'chop', 'echo', 'decay', 'spin', 'cut', 'room', 'mix', 'formant', 'shape')\n"
             "```")
        await self.bot.say(s)

    @jam_tutorial.command(pass_context=True)
    async def tidal(self, ctx):
        """info about the TidalCycles environment"""
        s = ("This is **TidalCycles** <https://tidalcycles.org/>\n"
             "We have 9 dirt connections to work with (`d1` ... `d9`)\n"
             "You send one to through to the interpreter at a time (`stack` is your friend)\n"
             "You should definitely go through this <https://tidalcycles.org/patterns.html>\n"
             "That's all I got :3 PR more to add here :thumbsup:")
        await self.bot.say(s)
        s = ("```haskell\n"
             "-- dirt samples\n"
             "\"808 808bd 808cy 808hc 808ht 808lc 808lt 808mc 808mt 808oh 808sd 909 ab ade ades2 ades3 ades4 alex alphabet amencutup armora arp arpy auto baa baa2 bass bass0 bass1 bass2 bass3 bassdm bassfoo battles bd bend bev bin birds birds3 bleep blip blue bottle breaks125 breaks152 breaks157 breaks165 breath bubble can casio cb cc chin chink circus clak click clubkick co control cosmicg cp cr crow d db diphone diphone2 dist dork2 dorkbot dr dr2 dr55 dr_few drum drumtraks e east electro1 erk f feel feelfx fest fire flick fm foo future gab gabba gabbaloud gabbalouder glasstap glitch glitch2 gretsch gtr h hand hardcore hardkick haw hc hh hh27 hit hmm ho hoover house ht if ifdrums incoming industrial insect invaders jazz jungbass jungle jvbass kicklinn koy kurt latibro led less lighter linnhats lt made made2 mash mash2 metal miniyeah moan monsterb moog mouth mp3 msg mt mute newnotes noise noise2 notes numbers oc odx off outdoor pad padlong pebbles perc peri pluck popkick print proc procshort psr rave rave2 ravemono realclaps reverbkick rm rs sax sd seawolf sequential sf sheffield short sid sine sitar sn space speakspell speech speechless speedupdown stab stomp subroc3d sugar sundance tabla tabla2 tablex tacscan tech techno tink tok toys trump ul ulgab uxay v voodoo wind wobble world xmas yeah\"\n"
             "```\n")
        await self.bot.say(s)

    @checks.is_owner()
    @jam.command(pass_context=True, name="clean", no_pm=True)
    async def jam_clean(self, ctx, seconds: int=None):
        """how long to wait before cleaning up non-jam msgs in the jam channel
        
        only effects on-going jam sessions
        leave blank to toggle between not cleaning and 25 seconds"""
        channel = ctx.message.channel
        try:
            if seconds is None:
                seconds = self.sessions[channel.id]['clean_after']
                seconds = -1 if seconds > 0 else 25
            self.sessions[channel.id]['clean_after'] = seconds
        except KeyError:
            return await self.bot.say('There is no jam session in this channel')
        if seconds == -1:
            return await self.bot.say('will not clean new messages')
        await self.bot.say('will clean new messages after {} seconds'.format(seconds))

    @checks.is_owner()
    @jam.command(pass_context=True, name="invite", no_pm=True)
    async def jam_invite(self, ctx, member: discord.Member):
        """Invite someone into your jam session

        Note, this lets people run arbitrary code on the computer your bot is on.
        Either make sure there's nothing to lose by putting your bot on a throwaway
        VPS running only this cog, or only invite people you REALLY trust."""
        channel = ctx.message.channel
        author = ctx.message.author

        if channel.id not in self.sessions:
            return await self.bot.say('no jam session is on in this channel')

        await self.bot.say('Stranger danger! This is seriously dangerous. '
                           'Read `{}help jam invite` for info on why. '
                           '\nYou sure you wanna let {} jam? (yes/no)'
                           ''.format(ctx.prefix, member.display_name),
                           delete_after=15)
        answer = await self.bot.wait_for_message(timeout=15, author=author)
        if not answer.content.lower().startswith('y'):
            return await self.bot.say('Yeah get away from us 😠', delete_after=5)

        if await self.wait_for_interpreter(channel, self.sessions[channel.id],
                                           member):
            await self.bot.say('{} has been added to the jam session!'
                               ''.format(member.display_name), delete_after=10)

    @checks.is_owner()
    @jam.command(pass_context=True, name="kick", no_pm=True)
    async def jam_kick(self, ctx, member: discord.Member):
        """Kick someone from the jam session"""
        channel = ctx.message.channel
        if channel.id not in self.sessions:
            return await self.bot.say('There is no jam session on in this channel')

        try:
            del self.sessions[channel.id]['authors'][member.id]
        except KeyError:
            return await self.bot.say("{} isn't in the jam session"
                                      "".format(member.display_name))
        await self.bot.say("{} has been kicked from the jam session"
                           "".format(member.display_name))
    
    @checks.is_owner()
    @jam.command(pass_context=True, name="off", no_pm=True)
    async def jam_off(self, ctx):
        """close the jam session in the current channel"""
        channel = ctx.message.channel

        try:
            self.kill(channel)
        except KeyError:
            return await self.bot.say("there's no jam session in this channel")

        bye = choice(['jam over', 'jam session over', 
                      "that's a wrap", 'jam session closed'])
        await self.bot.say(bye)

    def kill(self, channel):
        self.sessions[channel.id]['repl'].kill()
        if not self.sessions[channel.id]['console-less']:
            console = self.sessions[channel.id]['console']
            try:
                self.sessions[channel.id]['pager_task'].cancel()
            except:
                print("not able to cancel {}'s pager".format(channel))
            self.bot.loop.create_task(try_delete(self.bot, console))
        self.sessions[channel.id]['active'] = False
        self.sessions[channel.id]['click_wait'].cancel()

    @jam.command(pass_context=True, no_pm=True, name="on")
    async def jam_on(self, ctx, kind: str='FoxDot',
                     console: bool=True, clean: int=-1):
        """start up a collab LiveCoding session
        set the console off if you're joining someone else's jam

        clean is how long to wait before deleting non-jam msgs
        if clean is negative, msgs are not deleted

        if cleaning is on, message starting with * aren't deleted

        available environments: FoxDot, Tidal, Stack (stack install of Tidal)

        NOTE: atm the bot doesn't send audio or start up SuperCollider ...
        You'll need to redirect the audio to discord yourself (or have 2 clients connecting)
        and you'll need to start up SuperCollider beforehand by hand
        """
        channel = ctx.message.channel
        author = ctx.message.author

        # interpreter don't exist
        kind = kind.lower()
        if kind not in self.interpreters:
            await self.bot.say("{} is not an available interpreter.\n"
                               "You could add it in interpreters.json")
            return

        # missing path reqs
        missing = self.missing_interpreter_reqs(kind)
        if missing:
            await self.bot.say("Requirements not met.\n"
                               "You will need to use `{}jamset path` "
                               "to set up paths for {}"
                               "".format(ctx.prefix, ", ".join(missing)))
            return

        repl_data = deepcopy(self.interpreters[kind])

        # format paths
        servers = []
        for s in repl_data['servers']:
            s['cwd'] = self.format_paths(s['cwd'])
            s['cmd'] = self.format_paths(s['cmd'])
            s['preloads'] = [self.format_paths(p) for p in s['preloads']]
            servers.append(s)

        cwd = self.format_paths(repl_data['cwd'])
        cmd = self.format_paths(repl_data['cmd'])
        preloads = [self.format_paths(p) for p in repl_data['preloads']]

        if channel.id in self.sessions:
            await self.bot.say("Already running a jam session in this channel")
            return

        repl = InterpreterWithServers(self.bot.loop, cwd, cmd,
                                      eval_fmt=repl_data['eval_fmt'],
                                      preloads=preloads,
                                      servers=servers)

        self.sessions[channel.id] = {
            'authors' : {},
            'output'  : repl_data['intro'],
            'console' : None,
            'pages'   : [],
            'page_num': 0,
            'pager_task': None,
            'console-less': not console,
            'repl'    : repl,
            'active'  : True,
            'click_wait': None,
            'update_console': False,
            'clean_after': clean,
            'interpreter': kind,
            'hush': repl_data['hush'],
            'voice_client': None
        }

        session = self.sessions[channel.id]

        if not await self.wait_for_interpreter(channel, session, author):
            del self.sessions[channel.id]
            return

        # set up session's pager

        session['pages'].append(self.pager(session)())


        if not session['console-less']:
            session['pager_task'] = await self.start_console(ctx, session)

            self.bot.loop.create_task(self.keep_console_updated(ctx, session))


        msg = await self.bot.say('loading..')

        while not repl.ready:
            await asyncio.sleep(.5)

        await self.bot.edit_message(msg, new_content='psst, head into the voice channel')

        while session['active']:

            messages = [m for m in session['authors'].values()]
            session['click_wait'] = self.bot.loop.create_task(wait_for_click(self.bot, messages, '☑'))
            try:
                response = await session['click_wait']
            except asyncio.CancelledError:
                response = None

            if not session['active']:
                break

            if not response:
                continue

            jammer = response.author

            cleaned = self.cleanup_code(response.content)

            if cleaned in ('quit', 'exit', 'exit()'):
                await ctx.invoke(self.jam_off)
                break

            # refresh user's interpreter
            if cleaned in ('refresh', 'refresh()', 'cls', 'cls()', 'reset', 'reset()'):
                task = self.wait_for_interpreter(channel, session, jammer)
                self.bot.loop.create_task(task)
                continue

            if cleaned == '.':
                cleaned = session['hush']

            with_author = ['{}: {}'.format(jammer.display_name, ln) 
                           for ln in cleaned.split('\n')]
            fmt = '\n'.join(with_author)

            session['output'].append(fmt)
            session['page_num'] = -1

            repl.eval(cleaned)

            # ensure console update
            session['update_console'] = True

        del self.sessions[channel.id]


    async def keep_console_updated(self, ctx, session):
        channel = ctx.message.channel
        while session['active']:
            output = session['repl'].read().strip()
            if output:
                session['output'].append(output)
                session['page_num'] = -1
            if not session['update_console'] and not output:
                await asyncio.sleep(.5)
                continue
            try:
                await self.bot.get_message(channel, session['console'].id)
            except discord.NotFound:
                session['pager_task'].cancel()
                session['pager_task'] = await self.start_console(ctx, session)

            try:
                page = await self.replace_pages(session)
                await self.bot.edit_message(session['console'],
                                            new_content=await page)
                await self.replace_pages(session)

            except discord.Forbidden:
                pass
            except discord.HTTPException as e:
                await self.bot.send_message(channel, 'Unexpected error: `{}`'.format(e))
            session['update_console'] = False


    async def wait_for_interpreter(self, channel, session, member):
        fmt = ('{}, to start your session, post a `code` message or a ```code-block```'
               'This message will serve as your terminal window into the LiveCoding env.\n'
               '**Edit** the message and **press the ☑** to send it to the env (execute it).')
        prompt = await self.bot.send_message(channel,
                                             fmt.format(member.mention))
        def check(m):
            ps = tuple(self.repl_settings["REPL_PREFIX"])
            return m.content.startswith(ps)
        answer = await self.bot.wait_for_message(timeout=60*5, author=member,
                                                 check=check, channel=channel)
        if answer:
            await self.bot.add_reaction(answer, '☑')
            session['authors'][member.id] = answer
            if self.sessions[channel.id]['click_wait']:
                self.sessions[channel.id]['click_wait'].cancel()
            await try_delete(self.bot, prompt)
            return True
        else:
            after = await self.bot.send_message(channel, "{} didn't start a prompt soon "
                                                         "enough".format(member.display_name))
            await try_delete(self.bot, prompt)
            await asyncio.sleep(1)
            await try_delete(self.bot, after)
            return False

    async def on_reaction_remove(self, reaction, user):
        """Handles watching for reactions for wait_for_reaction_remove"""
        for event in _reaction_remove_events:
            if (event and not event.is_set() and
                event.check(reaction, user) and
                reaction.emoji in event.emojis):
                event.set(reaction)

    async def on_message(self, message):
        channel = message.channel

        # session doesn't exist
        if channel.id not in self.sessions:
            return

        # told not to clean
        stale_session = self.sessions[channel.id]
        if stale_session['clean_after'] < 0:
            return

        # terminals
        ids = [m.id for m in stale_session['authors'].values()]

        # console
        if stale_session['console']:
            ids.append(stale_session['console'].id)

        # msg is a jam msg
        if message.id in ids:
            return

        # don't delete these
        if message.content.startswith('*'):
            return

        # wait awhile
        await asyncio.sleep(stale_session['clean_after'])

        # check again to see if this message is still valid
        stale_session = self.sessions.get(channel.id)
        if not stale_session:
            return

        ids = [m.id for m in stale_session['authors'].values()]

        if stale_session['console']:
            ids.append(stale_session['console'].id)

        if message.id in ids:
            return

        if message.content.startswith('*'):
            return

        await try_delete(self.bot, message)

    


async def try_delete(bot, message):
    try:
        await bot.delete_message(message)
    except:
        return False
    return True


def line_pagify(s, lines_per_page=14, page_length=1960):
    lines = s.split('\n')
    i = 0
    page = ''
    lines_consumed = 0
    while i < len(lines):
        npage = page + '\n' + lines[i]
        if len(npage) > page_length:  # go back to prev page
            npage = page
            if len(npage) == 0:
                # if the next page is bigger than page_length on its own
                # split on rightmost space
                rightmost_space = lines[i][:page_length].rfind(' ')
                # ensure it's below page_length if no space found
                npage = lines[i][:rightmost_space][:page_length]
                # adjust the next page and remove the space
                lines[i] = lines[i][len(npage):].strip()
            lines_consumed = 0
            page = ''
            yield npage
            continue

        npage = npage.strip()
        i += 1
        if lines_consumed != lines_per_page:
            page = npage
            lines_consumed += 1
        else:
            lines_consumed = 0
            page = ''
            yield npage
    yield page


async def wait_for_click(bot, messages, emoji):
    def check(reaction, user):
        user_allowed = user.id in [m.author.id for m in messages]
        correct_msg = reaction.message.id in [m.id for m in messages]
        return correct_msg and user_allowed

    kwargs = {'emoji': [emoji], 'check': check}

    tasks = (bot.wait_for_reaction(**kwargs),
             wait_for_reaction_remove(bot, **kwargs))

    def conv(r):
        if not r:
            return None
        return r.reaction.message

    return await wait_for_first_response(tasks, (conv, conv))


async def wait_for_reaction_remove(bot, emoji=None, *, user=None,
                                   timeout=None, message=None, check=None):
    """Waits for a reaction to be removed by a user from a message within a time period.
    Made to act like other discord.py wait_for_* functions but is not fully implemented.

    Because of that, wait_for_reaction_remove(self, emoji: list, user, message, timeout=None)
    is a better representation of this function's def

    returns the actual event or None if timeout
    """
    if not emoji or isinstance(emoji, str):
        raise NotImplementedError("wait_for_reaction_remove(self, emoji, "
                                  "message, user=None, timeout=None, "
                                  "check=None) is a better representation "
                                  "of this function definition")
    remove_event = ReactionRemoveEvent(emoji, user, check=check)
    _reaction_remove_events.add(remove_event)
    done, pending = await asyncio.wait([remove_event.wait()],
                                       timeout=timeout)
    still_in = remove_event in _reaction_remove_events
    _reaction_remove_events.remove(remove_event)
    try:
        return done.pop().result() and still_in and remove_event
    except:
        return None


def check_folders():
    paths = ("data/jamcord", SAMPLE_PATH, INTERPRETERS_PATH)
    for path in paths:
        if not os.path.exists(path):
            print("Creating {} folder...".format(path))
            os.makedirs(path)

def check_file(path, default, revert_defaults=False):
    if not dataIO.is_valid_json(path):
        print("Creating default jamcord {}...".format(path))
        dataIO.save_json(path, default)
    elif revert_defaults:
        current = dataIO.load_json(path)
        current.update(default)
        print("Reverting {} in {} to default values"
              "".format(", ".join(default.keys()), path))
        dataIO.save_json(path, current)
    else:  # consistency check
        current = dataIO.load_json(path)
        if current.keys() != default.keys():
            for key in default.keys():
                if key not in current.keys():
                    current[key] = default[key]
                    print("Adding " + str(key) +
                          " field to jamcord {}".format(path))
            dataIO.save_json(path, current)

def check_interpreters():
    repls = os.listdir(INTERPRETERS_PATH)
    repls = set(repls + [d + '.json' for d in INTERPRETER_PRESETS])
    for f in repls:
        name = os.path.splitext(f)[0]
        path = os.path.join(INTERPRETERS_PATH, f)
        if name in INTERPRETER_PRESETS:
            check_file(path, INTERPRETER_PRESETS[name])
            continue
        default = deepcopy(DEFAULT_INTERPRETER_CONFIG)
        default['cmd'] = default['cmd'].format(name)
        default['intro'][0] = default['intro'][0].format(name)
        check_file(path, default)

def setup(bot):
    check_folders()
    check_file(SETTINGS_PATH,
               {"SAMPLES": {}, "INTERPRETER_PATHS": {"SCLANG": None}})
    check_interpreters()
    n = Jamcord(bot)
    bot.add_cog(n)
