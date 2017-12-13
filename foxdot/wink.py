import discord
from discord.ext import commands
from cogs.utils import checks
from cogs.utils.chat_formatting import pagify
import traceback
from contextlib import redirect_stdout
import io
import re
import sys
import asyncio
from collections import deque
from cogs.repl import interactive_results
from cogs.repl import wait_for_first_response

sys.path.insert(0, 'PATH_TO_TROOP')
from src.interpreter import FoxDotInterpreter, StackTidalInterpreter

USER_SPOT = re.compile(r'<colour=\".*?\">.*</colour>')
NBS = '​'


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
# TODO: get tidal working
# TODO: tidal intro text also
# x: display "user: input" if no stdout / result
# x: add a way for users to send permanent msgs if in cleanup mode


_reaction_remove_events = set()


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
        self.settings = {'REPL_PREFIX': ['`']}

    def cleanup_code(self, content):
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith('```') and content.endswith('```'):
            return '\n'.join(content.split('\n')[1:-1])

        # remove `foo`
        for p in self.settings["REPL_PREFIX"]:
            if content.startswith(p):
                if p == '`':
                    return content.strip('` \n')
                content = content[len(p):]
                return content.strip(' \n')

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
        """start up a collab FoxDot session
        set the console off if you're joining someone else's wink

        clean is how long to wait before deleting non-wink msgs
        if clean is negative, msgs are not deleted

        if cleaning is on, message starting with * aren't deleted
        """
        channel = ctx.message.channel
        author = ctx.message.author
        server = ctx.message.server

        kind = kind.lower()
        interpreters = {'foxdot': FoxDotInterpreter,
                        'tidal': StackTidalInterpreter}
        try:
            Interpreter = interpreters[kind]
        except KeyError:
            await self.bot.say('Only FoxDot and Tidal interpreters available')
            return

        if channel.id in self.sessions:
            await self.bot.say("Already running a wink session in this channel")
            return

        self.sessions[channel.id] = {
            'authors' : {},
            'output'  : ['Welcome!!\nThis is a collaborative window into FoxDot\n'
                         ' print(SynthDefs) to see the instruments\n'
                         ' print(Player.Attributes()) to see their attributes!\n\n'
                         'Single/Double letter players only. ex:\n'
                         ' p1 >> piano([0,[-1, 1],(2, 4)])\n'
                         ' p2 >> play("(xo){[--]-}")\n'
                         'execute a reset() or cls() to reposition your terminal\n'
                         'execute a . to stop all sound\n'
                         'close this console to reposition it also\n' + '-' * 51 + '\n'],
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
            'interpreter': Interpreter
        }

        session = self.sessions[channel.id]

        if not await self.wait_for_interpreter(channel, session, author):
            del self.sessions[channel.id]
            return

        # set up session's pager

        session['pages'].append(self.pager(session)())

        session['repl'] = Interpreter()
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
                cleaned = 'Clock.clear()'


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
            ps = tuple(self.settings["REPL_PREFIX"])
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


def setup(bot):
    n = Wink(bot)
    bot.add_cog(n)
