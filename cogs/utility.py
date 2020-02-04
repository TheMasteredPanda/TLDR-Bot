import time
import discord
import re
import config
from datetime import datetime
from discord.ext import commands
from modules import database, command, embed_maker

db = database.Connection()


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.poll_counts = {}

    @commands.command(help='Get bot\'s latency', usage='ping', examples=['ping'], clearance='User', cls=command.Command)
    async def ping(self, ctx):
        before = time.monotonic()
        message = await ctx.send("Pong")
        ping = (time.monotonic() - before) * 1000
        await message.edit(content=f"\U0001f3d3 Pong   |   {int(ping)}ms")

    @commands.command(help='End an anon_poll early. This command doesn\'t work on polls that were interrupted by a bot restart/shutdown',
                      usage='end_poll [#Channel] [message id]', examples=['end_poll #polls 673479831719247925'], clearance='Mod', cls=command.Command)
    async def end_poll(self, ctx, channel=None, message_id=None):
        if channel is None:
            return await embed_maker.command_error(ctx)
        else:
            channel = ctx.message.channel_mentions[0]
        if message_id is None:
            return await embed_maker.command_error(ctx, '[#Channel]')
        else:
            message = await channel.fetch_message(message_id)

        menu_cog = self.bot.get_cog('Menu')
        if message.id not in self.poll_counts or message.id not in menu_cog.no_expire_menus:
            embed = embed_maker.message(ctx, 'That is not a valid poll')
            return await ctx.send(embed=embed)

        # Get question from embed
        poll_embed = message.embeds[0]
        description = poll_embed.description
        question_regex = re.compile(r'(\*\*.*\*\*)\n\n')
        question = re.findall(question_regex, description)[0]

        emote_count = self.poll_counts[message.id]
        sorted_emote_count = sorted(emote_count.items(), key=lambda x: x[1], reverse=True)
        total_emotes = sum(emote_count.values())
        new_description = question
        for e in sorted_emote_count:
            emote, e_count = e
            try:
                percent = (e_count * 100) / total_emotes
            except ZeroDivisionError:
                percent = 0

            new_description += f'\n{emote} **- {e_count}** | **{percent}%**'

        poll_embed.description = new_description
        await message.edit(embed=poll_embed)
        await ctx.message.delete()

        del menu_cog.no_expire_menus[message.id]
        del self.poll_counts[message.id]

    @commands.command(help='Create an anonymous poll. with options adds numbers as reactions, without it just adds thumbs up and down. after x minutes (default 5) is up, results are displayed',
                      usage='anon_poll [length in minutes] [-q question] (-o option1, option2, ...)/(-o [emote: option], [emote: option], ...) (-t time limit (mins))',
                      examples=['anon_poll -q best food? -o pizza, burger, fish and chips, salad', 'anon_poll -q Do you guys like pizza? -t 2', 'anon_poll -q Where are you from? -o [🇩🇪: Germany], [🇬🇧: UK]'],
                      clearance='Mod', cls=command.Command)
    async def anon_poll(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_poll_args(args)
        question = args['question']
        options = args['options']
        poll_time = args['poll_time']
        option_emotes = args['option_emotes']

        if not option_emotes:
            embed = embed_maker.message(ctx, 'Error with custom option emotes', colour='red')
            return await ctx.send(embed=embed)

        if question == '' or options == '':
            embed = embed_maker.message(ctx, 'Empty arg', colour='red')
            return await ctx.send(embed=embed)

        if len(options) > 9:
            embed = embed_maker.message(ctx, 'Too many options', colour='red')
            return await ctx.send(embed=embed)

        description = f'**{question}**\n'
        colour = config.DEFAULT_EMBED_COLOUR
        used_emotes = []
        poll_msg = ''
        if not options:
            emotes = ['👍', '👎']
            embed = discord.Embed(colour=colour, description=description, timestamp=datetime.now())
            embed.set_author(name=ctx.author, icon_url=ctx.author.avatar_url)
            poll_msg = await ctx.send(embed=embed)
            for e in emotes:
                used_emotes.append(e)
                await poll_msg.add_reaction(e)

        elif options:
            if option_emotes:
                emotes = list(option_emotes.keys())
                options = list(option_emotes.values())
            else:
                emotes = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']

            for i, o in enumerate(options):
                description += f'\n{emotes[i]}  {o}'
                used_emotes.append(emotes[i])

            embed = discord.Embed(colour=colour, description=description, timestamp=datetime.now())
            embed.set_author(name=ctx.author, icon_url=ctx.author.avatar_url)
            poll_msg = await ctx.send(embed=embed)
            for e in used_emotes:
                await poll_msg.add_reaction(e)

        self.poll_counts[poll_msg.id] = {}
        voted_users = {}
        buttons = {}

        async def count(user, msg, emote):
            if msg.id != poll_msg.id:
                return

            if user.id in voted_users:
                previous_emote = voted_users[user.id]
                if emote == previous_emote:
                    return await user.send(f'Your vote has been already counted towards: {emote}')

                self.poll_counts[poll_msg.id][emote] += 1
                self.poll_counts[poll_msg.id][previous_emote] -= 1

                voted_users[user.id] = emote

                return await user.send(f'Your vote has been changed to: {emote}')

            voted_users[user.id] = emote
            self.poll_counts[poll_msg.id][emote] += 1

        for e in used_emotes:
            buttons[e] = count
            self.poll_counts[poll_msg.id][e] = 0

        menu_cog = self.bot.get_cog('Menu')
        await menu_cog.new_no_expire_menu(poll_msg, buttons)

        timer_cog = self.bot.get_cog('Timer')
        expires = round(time.time()) + round(poll_time*60)
        await timer_cog.create_timer(expires=expires, guild_id=ctx.guild.id, event='anon_poll', extras={'message_id': poll_msg.id, 'channel_id': poll_msg.channel.id, 'question': question})

        return await ctx.message.delete(delay=5)

    @commands.Cog.listener()
    async def on_anon_poll_timer_over(self, timer):
        message_id = timer['extras']['message_id']
        if message_id not in self.poll_counts:
            return

        menu_cog = self.bot.get_cog('Menu')
        if message_id not in menu_cog.no_expire_menus:
            return

        question = timer['extras']['question']
        emote_count = self.poll_counts[message_id]

        channel = self.bot.get_channel(timer['extras']['channel_id'])
        message = await channel.fetch_message(message_id)

        sorted_emote_count = sorted(emote_count.items(), key=lambda x: x[1], reverse=True)
        total_emotes = sum(emote_count.values())
        description = f'**{question}**\n'
        for e in sorted_emote_count:
            emote, e_count = e
            try:
                percent = (e_count * 100)/total_emotes
            except ZeroDivisionError:
                percent = 0

            description += f'\n{emote} **- {e_count}** | **{percent}%**'

        embed = message.embeds[0]
        embed.description = description
        await message.edit(embed=embed)

        del menu_cog.no_expire_menus[message_id]
        del self.poll_counts[message_id]

        return await message.clear_reactions()

    @commands.command(help='Create a poll. with options adds numbers as reactions, without it just adds thumbs up and down.',
                      usage='poll [-q question] (-o option1, option2, ...)/(-o [emote: option], [emote: option], ...)',
                      examples=['poll -q best food? -o pizza, burger, fish and chips, salad -l 2', 'poll -q Do you guys like pizza?', 'anon_poll -q Where are you from? -o [🇩🇪: Germany], [🇬🇧: UK]'],
                      clearance='Mod', cls=command.Command)
    async def poll(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_poll_args(args)
        question = args['question']
        options = args['options']
        option_emotes = args['option_emotes']

        if question == '' or options == '':
            embed = embed_maker.message(ctx, 'Empty arg', colour='red')
            return await ctx.send(embed=embed)

        if len(options) > 9:
            embed = embed_maker.message(ctx, 'Too many options', colour='red')
            return await ctx.send(embed=embed)

        description = f'**{question}**\n'
        colour = config.DEFAULT_EMBED_COLOUR

        used_emotes = []
        if not options:
            emotes = ['👍', '👎']
            embed = discord.Embed(colour=colour, description=description, timestamp=datetime.now())
            embed.set_author(name=ctx.author, icon_url=ctx.author.avatar_url)
            poll_msg = await ctx.send(embed=embed)
            for e in emotes:
                used_emotes.append(e)
                await poll_msg.add_reaction(e)

        elif options:
            if option_emotes:
                emotes = list(option_emotes.keys())
                options = list(option_emotes.values())
            else:
                emotes = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']

            for i, o in enumerate(options):
                description += f'\n{emotes[i]}  {o}'
                used_emotes.append(emotes[i])

            embed = discord.Embed(colour=colour, description=description, timestamp=datetime.now())
            embed.set_author(name=ctx.author, icon_url=ctx.author.avatar_url)
            poll_msg = await ctx.send(embed=embed)
            for e in used_emotes:
                await poll_msg.add_reaction(e)

        return await ctx.message.delete(delay=5)

    def parse_poll_args(self, args):
        args = args.split('-')
        question = ''
        options = []
        poll_time = 5
        for a in args:
            if a.lower().startswith('q'):
                question = a.replace('q', '', 1).strip()
                continue
            elif a.lower().startswith('o'):
                options = a.replace('o', '', 1).strip().replace(', ', ',').split(',')
                continue
            elif a.lower().startswith('t'):
                poll_time = float(a.replace('t', '', 1).strip())
                continue

        # check for custom option emotes
        option_emotes = {}
        for o in options:
            regex = re.compile(r'\[(.*?)\]')
            if re.match(regex, o):
                o.strip()
                emote_regex = re.compile(r'\[(.*)\s?:')
                option_regex = re.compile(r':\s?(.*)\]')
                emote = re.findall(emote_regex, o)[0]
                option = re.findall(option_regex, o)[0]
                option_emotes[emote] = option
            else:
                option_emotes = False

        return {'question': question,
                'options': options,
                'option_emotes': option_emotes,
                'poll_time': poll_time}


def setup(bot):
    bot.add_cog(Utility(bot))
