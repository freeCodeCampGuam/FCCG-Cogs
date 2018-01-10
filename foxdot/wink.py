import discord
from discord.ext import commands
from cogs.utils import checks
from cogs.utils.dataIO import dataIO
from cogs.utils.chat_formatting import pagify
import traceback
from contextlib import redirect_stdout
import io
import re
import sys
import asyncio
import youtube_dl
import threading
import os
from glob import glob
from collections import deque
from cogs.repl import interactive_results
from cogs.repl import wait_for_first_response
from copy import deepcopy


SETTINGS_PATH = "data/foxdot/settings.json"
SAMPLE_PATH = 'data/foxdot/samples/'

USER_SPOT = re.compile(r'<colour=\".*?\">.*</colour>')
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
#   TODO: make this a setting
# x: clients / no-console mode (# of checks means how many clients connected!)
# TODO: local execute only: keyword in msg (easier) or separate button
# TODO: set up paths to work w/ FoxDot (and Troop if needed) in REQUIREMENTS
# x: get tidal working
# TODO: tidal intro text also
# x: display "user: input" if no stdout / result
# x: add a way for users to send permanent msgs if in cleanup mode
# TODO: @mention users if error. (if interpreter-specific regex is matched?)


_reaction_remove_events = set()


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
    def __init__(self, url, options):
        super().__init__()
        self.url = url
        self.done = threading.Event()
        self.song = None
        self._yt = None
        self.error = None
        self.options = options

    def run(self):
        try:
            self.get_info()
        except youtube_dl.utils.DownloadError as e:
            self.error = str(e)
        except OSError as e:
            print("An operating system error occurred while downloading URL "
                  "'{}':\n'{}'".format(self.url, str(e)))

        if not os.path.isfile(self.options['outtmpl']):
            video = self._yt.extract_info(self.url)
            self.video = video
            self.song = Song(**video)
    
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


class Wink:
    """wink"""

    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}
        self.repl_settings = {'REPL_PREFIX': ['`']}
        self.settings = dataIO.load_json(SETTINGS_PATH)
        # load interpreter paths into sys.path
        paths = self.settings['INTERPRETER_PATHS']
        for path in paths.values():
            if path is not None and path not in sys.path:
                sys.path.insert(0, path)
        # Troop
        try:
            from src.interpreter import FoxDotInterpreter, TidalInterpreter, StackTidalInterpreter
        except:
            FoxDotInterpreter = None
            TidalInterpreter = None
            StackTidalInterpreter = None

        self.interpreters = {
            'foxdot': {'class': FoxDotInterpreter,
                'intro': [
                    'Welcome!!\nThis is a collaborative window into FoxDot\n'
                    ' p1 >> piano([0,[-1, 1],(2, 4)])\n'
                    ' p2 >> play("(xo){[--]-}")\n'
                    'execute a reset() or cls() to reposition your terminal\n'
                    'execute a . to stop all sound\n'
                    '[p]foxdot for more on FoxDot!\n'
                    'close this console to reposition it also\n' + '-' * 51 + '\n'
                ],
                'hush': 'Clock.clear()'
            },
            'tidal': {'class': TidalInterpreter,
                'intro': [
                    'Welcome!!\nThis is a collaborative window into TidalCycles\n'
                    ' I have no idea how to use Tidal!\n'
                    ' eeeuhhhhhh tidal example\n'
                    'execute a `reset` or `cls` to reposition your terminal\n'
                    'execute a `.` to stop all sound\n'
                    '[p]tidal for more on TidalCycles!\n'
                    'close this console to reposition it also\n' + '-' * 51 + '\n'
                ],
                'hush': 'hush'
            }
        }
        self.interpreters['stack'] = {'class': StackTidalInterpreter,
                                 'intro': self.interpreters['tidal']['intro'],
                                 'hush':  self.interpreters['tidal']['hush']}

    def save(self):
        dataIO.save_json(SETTINGS_PATH, self.settings)

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

    @commands.command(pass_context=True)
    async def sample(self, ctx, name, search=None):
        """search for and download a sample from youtube

        the name is used as the search parameter if none is given

        TODO: allow urls as well
        TODO: add list option
        TODO: save source url/name

        * for use in FoxDot only atm
        """
        # TODO: limit usage to winkers
        author = ctx.message.author

        if search is None:
            search = name

        default_sample = {'SOURCE': 'unknown source',
                          'REQUESTER': {'NAME_DISCRIM': 'unknown person', 
                                        'ID': None}}
        sample_data = self.settings['SAMPLES'].get(name, default_sample)
        
        prompt = '🔎..'

        path = SAMPLE_PATH + name + '.wav'
        if os.path.exists(path):
            s = name + (' already exists. It comes from {} and was requested by {}.\nreplace it? (yes/no)'
                        ''.format(sample_data['SOURCE'], sample_data['REQUESTER']['NAME_DISCRIM']))
            await self.bot.say(s)
            answer = await self.bot.wait_for_message(timeout=45, author=author)
            
            if answer and answer.content.lower() in ('y', 'yes'):
                prompt = 'ok. replacing ' + path + '\n' + prompt
                os.remove(path)
            else:
                return await self.bot.say("ok. I won't overwrite it.")

        m = await self.bot.say(prompt)

        options = youtube_dl_options.copy()
        options['outtmpl'] = SAMPLE_PATH + name + '.%(ext)s'

        d = Downloader('[SEARCH:]' + search, options)
        #self.d = d
        d.start()

        prompted = False;
        while d.is_alive():
            if "http" in d.url and not prompted:
                await self.bot.edit_message(m, new_content='Downloading: ' + d.url)
                prompted = True
            await asyncio.sleep(1)

        sample_data['SOURCE'] = d.url
        sample_data['REQUESTER'] = {'NAME_DISCRIM': str(author), 
                                    'ID': author.id}
        self.settings['SAMPLES'][name] = sample_data
        self.save()
        await self.bot.say(name + ' downloaded to ' + SAMPLE_PATH + name + '.wav')

    @commands.command(pass_context=True)
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

    @commands.command(pass_context=True)
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

    @commands.group(pass_context=True)
    async def winkset(self, ctx):
        """settings for wink"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)
    
    @winkset.command(pass_context=True, name="path")
    async def winkset_path(self, ctx, interpreter, *, path):
        """set the path(s) to your interpreter(s)"""
        server = ctx.message.server
        channel = ctx.message.channel
        author = ctx.message.author
        supported = ("troop",)
        if interpreter.lower() not in supported:
            await self.bot.say('Only these interpreters are supported atm:\n'
                               '{}'.format(' '.join(supported)))
            return NotImplemented

        interpreter = interpreter.upper()

        self.settings["INTERPRETER_PATHS"][interpreter] = path
        self.save()
        await self.bot.say(interpreter + " path updated to: " + path +
                           "\n`" + ctx.prefix + "reload wink` to take effect.")


    @checks.is_owner()
    @commands.command(pass_context=True, no_pm=True)
    async def cleanwink(self, ctx, seconds: int=None):
        """how long to wait before cleaning up non-wink msgs in the wink channel

        leave blank to toggle between not cleaning and 25 seconds"""
        channel = ctx.message.channel
        try:
            if seconds is None:
                seconds = self.sessions[channel.id]['clean_after']
                seconds = -1 if seconds > 0 else 25
            self.sessions[channel.id]['clean_after'] = seconds
        except KeyError:
            return await self.bot.say('There is no wink session in this channel')
        if seconds == -1:
            return await self.bot.say('will not clean new messages')
        await self.bot.say('will clean new messages after {} seconds')

    @checks.is_owner()
    @commands.command(pass_context=True)
    async def addwink(self, ctx, member: discord.Member):
        """addwink"""
        channel = ctx.message.channel
        author = ctx.message.author

        if channel.id not in self.sessions:
            return await self.bot.say('no winking is taking place in this channel')

        await self.bot.say('stranger danger! you sure you wanna let '
                           '{} wink? (yes/no)'.format(member.display_name), 
                           delete_after=15)
        answer = await self.bot.wait_for_message(timeout=15, author=author)
        if not answer.content.lower().startswith('y'):
            return await self.bot.say('yeah get away from us 😠', delete_after=5)

        if await self.wait_for_interpreter(channel, self.sessions[channel.id],
                                           member):
            await self.bot.say('{} can now wink. man his eyes musta been dry '
                               'as hell'.format(member.display_name),
                               delete_after=10)


    @checks.is_owner()
    @commands.command(pass_context=True)
    async def delwink(self, ctx, member: discord.Member):
        """delwink"""
        channel = ctx.message.channel
        if channel.id not in self.sessions:
            return await self.bot.say('no winking is taking place in this channel')

        try:
            del self.sessions[channel.id]['authors'][member.id]
        except KeyError:
            return await self.bot.say("{} already can't wink!"
                                      "".format(member.display_name))
        await self.bot.say("bad man {}! you're not allowed to wink "
                           "anymore!".format(member.display_name))

    @checks.is_owner()
    @commands.command(pass_context=True, no_pm=True)
    async def unwink(self, ctx):
        """wake up"""
        channel = ctx.message.channel

        try:
            self.kill(channel)
        except KeyError:
            return await self.bot.say("there's no wink session in this channel")
        await self.bot.say('open your eyes')

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

    @checks.is_owner()
    @commands.command(pass_context=True, no_pm=True)
    async def wink(self, ctx, kind: str='FoxDot', console: bool=True, clean: int=-1):
        """start up a collab LiveCoding session
        set the console off if you're joining someone else's wink

        clean is how long to wait before deleting non-wink msgs
        if clean is negative, msgs are not deleted

        if cleaning is on, message starting with * aren't deleted

        available environments: FoxDot, Tidal, Stack (stack install of Tidal)
        """
        channel = ctx.message.channel
        author = ctx.message.author
        server = ctx.message.server

        kind = kind.lower()
        try:
            Interpreter = self.interpreters[kind]['class']
            intro = self.interpreters[kind]['intro'].copy()
            hush = self.interpreters[kind]['hush']
        except KeyError:
            await self.bot.say('Only FoxDot and Tidal interpreters available '
                               '(use `stack` if you use stack for your Tidal)')
            return

        if Interpreter is None:
            await self.bot.say("Troop hasn't been installed or the path hasn't "
                               "been setup yet. Use `{}winkset path troop "
                               "<path>` to add it.".format(ctx.prefix))
            return

        if channel.id in self.sessions:
            await self.bot.say("Already running a wink session in this channel")
            return

        self.sessions[channel.id] = {
            'authors' : {},
            'output'  : intro,
            'console' : None,
            'pages'   : [],
            'page_num': 0,
            'pager_task': None,
            'console-less': not console,
            'repl'    : None,
            'active'  : True,
            'click_wait': None,
            'update_console': False,
            'clean_after': clean,
            'interpreter': Interpreter,
            'hush': hush
        }

        session = self.sessions[channel.id]

        if not await self.wait_for_interpreter(channel, session, author):
            del self.sessions[channel.id]
            return

        # set up session's pager

        session['pages'].append(self.pager(session)())

        session['repl'] = Interpreter()

        if Interpreter is self.interpreters['foxdot']['class']:
            abs_sample_path = os.path.join(os.getcwd(), SAMPLE_PATH)
            session['repl'].evaluate('Samples.addPath'
                                     '("{}")'.format(abs_sample_path))

        await self.bot.say('psst, head into the voice channel')

        if not session['console-less']:
            session['pager_task'] = await self.start_console(ctx, session)

            self.bot.loop.create_task(self.keep_console_updated(ctx, session))

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

            winker = response.author

            cleaned = self.cleanup_code(response.content)

            if cleaned in ('quit', 'exit', 'exit()'):
                self.kill(channel)
                await self.bot.say('open your eyes')
                break

            # refresh user's interpreter
            if cleaned in ('refresh', 'refresh()', 'cls', 'cls()', 'reset', 'reset()'):
                task = self.wait_for_interpreter(channel, session, winker)
                self.bot.loop.create_task(task)
                continue

            if cleaned == '.':
                cleaned = session['hush']


            fmt = None
            stdout = io.StringIO()
            try:
                # foxdot must have turned off output to stdout recently
                with redirect_stdout(stdout):
                    result = session['repl'].evaluate(cleaned)
            except Exception as e:
                value = stdout.getvalue()
                fmt = '{}{}'.format(value, traceback.format_exc())
            else:
                value = stdout.getvalue()
                if value:
                    try:
                        value = re.sub(USER_SPOT, winker.display_name, value)
                    except AttributeError:
                        pass
                if result is not None:
                    fmt = '{}{}'.format(value, result)
                elif value:
                    fmt = '{}'.format(value)
                else:
                    clean_lines = cleaned.split('\n')
                    with_author = ['{}: {}'.format(winker.display_name, ln) 
                                   for ln in clean_lines]
                    fmt = '\n'.join(with_author)
            if fmt is None:
                continue

            if fmt == 'None':
                session['output'].append('\n')
            else:
                session['output'].append(fmt)
            session['page_num'] = -1

            # ensure console update
            session['update_console'] = True

        del self.sessions[channel.id]


    async def keep_console_updated(self, ctx, session):
        channel = ctx.message.channel
        while session['active']:
            if not session['update_console']:
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
        fmt = '{} post a `code` message or a ```code-block``` to start your session'
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

        # msg is a wink msg
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
    paths = ("data/foxdot", SAMPLE_PATH)
    for path in paths:
      if not os.path.exists(path):
          print("Creating {} folder...".format(path))
          os.makedirs(path)

def check_files():
    default = {"SAMPLES": {}, "INTERPRETER_PATHS": {"TROOP": None}}

    if not dataIO.is_valid_json(SETTINGS_PATH):
        print("Creating default foxdot settings.json...")
        dataIO.save_json(SETTINGS_PATH, default)
    else:  # consistency check
        current = dataIO.load_json(SETTINGS_PATH)
        if current.keys() != default.keys():
            for key in default.keys():
                if key not in current.keys():
                    current[key] = default[key]
                    print(
                        "Adding " + str(key) + " field to foxdot settings.json")
            dataIO.save_json(SETTINGS_PATH, current)

def setup(bot):
    check_folders()
    check_files()
    n = Wink(bot)
    bot.add_cog(n)
