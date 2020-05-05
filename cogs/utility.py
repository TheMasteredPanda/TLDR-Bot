import time
import discord
import re
import config
import asyncio
import random
from datetime import datetime
from discord.ext import commands
from modules import database, command, embed_maker, format_time

db = database.Connection()


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Get bot\'s latency', usage='ping', examples=['ping'], clearance='User', cls=command.Command)
    async def ping(self, ctx):
        before = time.monotonic()
        message = await ctx.send("Pong")
        ping = (time.monotonic() - before) * 1000
        await message.edit(content=f"\U0001f3d3 Pong   |   {int(ping)}ms")

    @commands.command(help='See command usage data', usage='command_usage (command)', examples=['command_usage', 'command_usage rank'], clearance='User', cls=command.Command)
    async def command_usage(self, ctx, cmd=None):
        data = db.get_data('command_usage', ctx.guild.id)

        embed = discord.Embed(colour=config.DEFAULT_EMBED_COLOUR, timestamp=datetime.today())
        embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)

        if cmd is None:
            cmd_usage_data = [(c, sum(data[c].values())) for c in data]
            embed.set_author(name='Most Used Commands Today', icon_url=ctx.guild.icon_url)
            desc = ''
            for i, c in enumerate(cmd_usage_data):
                if i == 10:
                    break
                desc += f'`#{i + 1}` - {c[0]}: **{c[1]}** Uses\n'

            embed.description = desc
        else:
            if cmd not in data:
                embed = embed_maker.message(ctx, 'That command doesn\'t exist or hasn\'t been used yet')
                return await ctx.send(embed=embed)
            else:
                embed.set_author(name=f'`{cmd}` - Most Used By Today', icon_url=ctx.guild.icon_url)
                desc = ''
                users = sorted(data[cmd], key=lambda x: x[1])
                for i, user_id in enumerate(users):
                    if i == 10:
                        return

                    calls = data[cmd][user_id]

                    user = self.bot.get_user(int(user_id))
                    if user is None:
                        user = await self.bot.fetch_user(user_id)
                    desc += f'`#{i + 1}` - {user.name}: **{calls}** Calls\n'

                embed.description = desc

        return await ctx.send(embed=embed)

    @commands.command(help='See someones profile picture', usage='pfp (@user)', examples=['pfp', 'pfp @Hattyot'], clearance='User', cls=command.Command)
    async def pfp(self, ctx, member=None):
        if member and ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            member = ctx.author

        embed = discord.Embed(description=f'**Profile Picture of {member}**')
        embed.set_image(url=str(member.avatar_url).replace(".webp?size=1024", ".png?size=2048"))

        return await ctx.send(embed=embed)

    @commands.command(help='create a giveaway, announces y amount of winners (default 1) after x amount of time (default 24h)', usage='giveaway -i [item(s) you want to give away] -w [how many winners] -t [time (m/h/d)]',
                      examples=['giveaway -i TLDR pin of choice -w 1 -t 7d', 'giveaway -i 1000xp -w 5 -t 24h'], clearance='Mod', cls=command.Command)
    async def giveaway(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_giveaway_args(args)
        item = args['i']
        winners = str(args['w'])
        giveaway_time = format_time.parse(args['t'])
        time_left = format_time.seconds(giveaway_time)

        expires = round(time.time()) + giveaway_time

        err = ''
        if args['i'] == '':
            err = 'empty items arg'
        if not winners.isdigit():
            err = 'invalid winner count'
        if giveaway_time is None:
            err = 'Invalid time arg'

        if err:
            embed = embed_maker.message(ctx, err, colour='red')
            return await ctx.send(embed=embed)

        description = f'React with :partying_face: to enter the giveaway!\nTime Left: **{time_left}**'
        colour = config.DEFAULT_EMBED_COLOUR
        embed = discord.Embed(title=item, colour=colour, description=description, timestamp=datetime.now())
        embed.set_footer(text='Started at', icon_url=ctx.guild.icon_url)

        msg = await ctx.send(embed=embed)
        await msg.add_reaction('🥳')
        await ctx.message.delete(delay=3)

        timer_cog = self.bot.get_cog('Timer')
        await timer_cog.create_timer(expires=expires, guild_id=ctx.guild.id, event='giveaway',
                                     extras={'winner_count': winners, 'timer_cog': 'Utility', 'timer_function': 'giveaway_timer', 'args': (msg.id, msg.channel.id, embed.to_dict(), giveaway_time)})

    @commands.Cog.listener()
    async def on_giveaway_timer_over(self, timer):
        print('over')
        winner_count = timer['extras']['winner_count']
        message_id, channel_id, embed, _ = timer['extras']['args']
        embed = discord.Embed.from_dict(embed)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)

        msg = await channel.fetch_message(message_id)

        reactions = msg.reactions
        eligible = []
        for r in reactions:
            if r.emoji != '🥳':
                continue
            else:
                eligible = await r.users().flatten()
                eligible.pop(0)

        winners = []
        for i in range(int(winner_count)):
            if len(eligible) == 0:
                break
            user = random.choice(eligible)
            winners.append(user.id)
            eligible.remove(user)

        winners_str = ', '.join([f'<@{w}>' for w in winners])
        if winners_str == '':
            content = ''
            winners_str = 'No one won, no one entered :('
        else:
            content = f'🎊 Congrats to {winners_str} 🎊'

        new_desc = f'Winners: {winners_str}'
        embed.description = new_desc
        embed.set_footer(text='Ended at')
        embed.timestamp = datetime.now()
        embed.color = embed_maker.get_colour('green')
        await msg.clear_reactions()
        await msg.edit(embed=embed, content=content)

    async def giveaway_timer(self, args):
        message_id, channel_id, embed, sleep_duration = args
        embed = discord.Embed.from_dict(embed)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)

        message = await channel.fetch_message(message_id)

        while sleep_duration > 0:
            description = 'React with :partying_face: to enter the giveaway!'
            await asyncio.sleep(10)
            sleep_duration -= 10
            if sleep_duration != 0:
                time_left = format_time.seconds(sleep_duration)
                prev_time_left = format_time.seconds(sleep_duration + 10)
                if time_left == prev_time_left:
                    continue

                description += f'\nTime Left: **{time_left}**'
                embed.description = description
                await message.edit(embed=embed)

        return

    def parse_giveaway_args(self, args):
        result = {
            'i': '',
            'w': 1,
            't': '24h',
        }
        split_args = filter(None, args.split('-'))
        for v in split_args:
            tup = tuple(map(str.strip, v.split(' ', 1)))
            if len(tup) <= 1:
                continue
            key, value = tup
            result[key] = value

        return result

    @commands.command(help='Create an anonymous poll. with options adds numbers as reactions, without it just adds thumbs up and down. after x minutes (default 5) is up, results are displayed',
                      usage='anon_poll [-q question] (-o option1, option2, ...)/(-o [emote: option], [emote: option], ...) (-t [time (m/h/d)',
                      examples=['anon_poll -q best food? -o pizza, burger, fish and chips, salad', 'anon_poll -q Do you guys like pizza? -t 2m', 'anon_poll -q Where are you from? -o [🇩🇪: Germany], [🇬🇧: UK] -t 1d'],
                      clearance='Mod', cls=command.Command)
    async def anon_poll(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_poll_args(args)
        question = args['q']
        options = args['o']
        poll_time = format_time.parse(args['t'])
        option_emotes = args['o_emotes']

        err = ''
        if poll_time is None:
            err = 'Invalid time arg'

        if option_emotes is None:
            err = 'Error with custom option emotes'

        if question == '' or options == '':
            err = 'Empty arg'

        if len(options) > 9:
            err = 'Too many options'

        if err:
            embed = embed_maker.message(ctx, err, colour='red')
            return await ctx.send(embed=embed)

        description = f'**"{question}"**\n\n'
        colour = config.DEFAULT_EMBED_COLOUR
        embed = discord.Embed(title='Anonymous Poll', colour=colour, description=description, timestamp=datetime.now())
        embed.set_footer(text='Started at', icon_url=ctx.guild.icon_url)

        if not options:
            emotes = ['👍', '👎']
        else:
            if option_emotes:
                emotes = list(option_emotes.keys())
                options = list(option_emotes.values())
            else:
                all_num_emotes = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
                emotes = all_num_emotes[:len(options)]

            description += '\n'.join(f'{e} | **{o}**' for o, e in zip(options, emotes))
            embed.description = description

        poll_msg = await ctx.send(embed=embed)
        voted_users = {}

        async def count(user, msg, emote):
            if msg.id != poll_msg.id:
                return

            if user.id in voted_users:
                if voted_users[user.id]['buffer'] >= 5:
                    return await user.send(f'Don\'t spam please')
                voted_users[user.id]['buffer'] += 1

                previous_emote = voted_users[user.id]['emote']
                if emote == previous_emote:
                    return await user.send(f'Your vote has been already counted towards: {emote}')

                db.polls.update_one({'guild_id': ctx.guild.id},
                                    {'$inc': {f'polls.{msg.id}.{emote}': 1,
                                              f'polls.{msg.id}.{previous_emote}': -1}})

                voted_users[user.id]['emote'] = emote

                return await user.send(f'Your vote has been changed to: {emote}')

            voted_users[user.id] = {
                'emote': emote,
                'buffer': 0  # checking for spammers
            }
            db.polls.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'polls.{msg.id}.{emote}': 1}})

        poll = dict.fromkeys(emotes, 0)
        buttons = dict.fromkeys(emotes, count)

        menu_cog = self.bot.get_cog('Menu')
        timer_cog = self.bot.get_cog('Timer')

        expires = round(time.time()) + round(poll_time)
        await timer_cog.create_timer(expires=expires, guild_id=ctx.guild.id, event='anon_poll', extras={'message_id': poll_msg.id, 'channel_id': poll_msg.channel.id, 'question': question, 'options': option_emotes})
        await menu_cog.new_no_expire_menu(poll_msg, buttons)

        db.polls.update_one({'guild_id': ctx.guild.id}, {'$set': {f'polls.{poll_msg.id}': poll}})

        return await ctx.message.delete(delay=3)

    @commands.Cog.listener()
    async def on_anon_poll_timer_over(self, timer):
        message_id = timer['extras']['message_id']
        guild_id = timer['guild_id']
        options = timer['extras']['options']
        poll = db.get_polls(guild_id, message_id)
        if not poll:
            return

        db.polls.update_one({'guild_id': guild_id}, {'$unset': {f'polls.{message_id}': ""}})
        db.get_polls.invalidate(guild_id, message_id)

        question = timer['extras']['question']
        emote_count = poll

        channel = self.bot.get_channel(timer['extras']['channel_id'])
        message = await channel.fetch_message(message_id)

        sorted_emote_count = sorted(emote_count.items(), key=lambda x: x[1], reverse=True)
        total_emotes = sum(emote_count.values())
        description = f'**{question}**\n'

        if total_emotes == 0:
            description += '\n'.join(f'{emote} **- {emote_count}** | **0%**' for emote, emote_count in sorted_emote_count)
        else:
            if options:
                description += '\n'.join(f'{emote} - {options[emote]} - **{emote_count}** | **{round((emote_count * 100) / total_emotes)}%**' for emote, emote_count in sorted_emote_count)
            else:
                description += '\n'.join(f'{emote} - **{emote_count}** | **{round((emote_count * 100)/total_emotes)}%**' for emote, emote_count in sorted_emote_count)

        embed = message.embeds[0]
        embed.description = description
        embed.timestamp = datetime.now()
        embed.set_footer(text='Ended at')

        menu_cog = self.bot.get_cog('Menu')
        if message_id in menu_cog.no_expire_menus:
            del menu_cog.no_expire_menus[message_id]

        await message.edit(embed=embed)
        return await message.clear_reactions()

    @commands.command(help='Create a poll. with options adds numbers as reactions, without it just adds thumbs up and down.',
                      usage='poll [-q question] (-o option1, option2, ...)/(-o [emote: option], [emote: option], ...)',
                      examples=['poll -q best food? -o pizza, burger, fish and chips, salad -l 2', 'poll -q Do you guys like pizza?', 'anon_poll -q Where are you from? -o [🇩🇪: Germany], [🇬🇧: UK]'],
                      clearance='Mod', cls=command.Command)
    async def poll(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_poll_args(args)
        question = args['q']
        options = args['o']
        option_emotes = args['o_emotes']

        err = ''
        if question == '' or options == '':
            err = 'Empty arg'

        if len(options) > 9:
            err = 'Too many options'

        if err:
            embed = embed_maker.message(ctx, err, colour='red')
            return await ctx.send(embed=embed)

        description = f'**"{question}"**\n\n'
        colour = config.DEFAULT_EMBED_COLOUR
        embed = discord.Embed(title='Poll', colour=colour, description=description, timestamp=datetime.now())
        embed.set_footer(text='Started at', icon_url=ctx.guild.icon_url)

        if not options:
            emotes = ['👍', '👎']
        else:
            if option_emotes:
                emotes = list(option_emotes.keys())
                options = list(option_emotes.values())
            else:
                all_num_emotes = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
                emotes = all_num_emotes[:len(options)]

            description += '\n'.join(f'\n{e} | **{o}**' for e, o in zip(emotes, options))
            embed.description = description

        poll_msg = await ctx.send(embed=embed)
        for e in emotes:
            await poll_msg.add_reaction(e)

        return await ctx.message.delete(delay=5)

    def parse_poll_args(self, args):
        result = {
            'q': '',
            'o': [],
            't': '5m',
            'o_emotes': {}
        }
        split_args = filter(None, args.split('-'))
        for a in split_args:
            tup = tuple(map(str.strip, a.split(' ', 1)))
            if len(tup) <= 1:
                continue
            key, value = tup
            result[key] = value

        if result['o']:
            result['o'] = result['o'].replace(' ', '').split(',')
        else:
            return result

        # check for custom option emotes
        oe_regex = re.compile(r'\[(.*):(.*)\]')
        if re.match(oe_regex, result['o'][0]):
            for option in result['o']:
                oe = re.match(oe_regex, option)
                if oe:
                    e, o = oe.groups()
                    result['o_emotes'][e] = o
                    continue

                result['o_emotes'] = None
                break

        return result

    @commands.command(help='Get help smh', usage='help (command)', examples=['help', 'help ping'], clearance='User', cls=command.Command)
    async def help(self, ctx, _cmd=None):
        embed_colour = config.DEFAULT_EMBED_COLOUR
        prefix = config.DEFAULT_PREFIX
        cmds = self.bot.commands
        help_object = {}

        for cmd in cmds:
            if hasattr(cmd, 'dm_only'):
                continue

            if cmd.cog_name not in help_object:
                help_object[cmd.cog_name] = [cmd]
            else:
                help_object[cmd.cog_name].append(cmd)

        utils = self.bot.get_cog('Utils')
        clearance = await utils.get_user_clearance(ctx.guild.id, ctx.author.id)
        if _cmd is None:
            embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(),
                                  description=f'**Prefix** : `{prefix}`\nFor additional info on a command, type `{prefix}help [command]`')
            embed.set_author(name=f'Help - {clearance[0]}', icon_url=ctx.guild.icon_url)
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            for cat in help_object:
                cat_commands = []
                for cmd in help_object[cat]:
                    if cmd.clearance in clearance:
                        cat_commands.append(f'`{cmd}`')

                if cat_commands:
                    embed.add_field(name=f'>{cat}', value=" \| ".join(cat_commands), inline=False)

            return await ctx.send(embed=embed)
        else:
            if self.bot.get_command(_cmd):
                cmd = self.bot.get_command(_cmd)
                if cmd.hidden:
                    return
                examples = f' | {prefix}'.join(cmd.examples)
                cmd_help = f"""
                **Description:** {cmd.help}
                **Usage:** {prefix}{cmd.usage}
                **Examples:** {prefix}{examples}
                """
                embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=cmd_help)
                embed.set_author(name=f'Help - {cmd}', icon_url=ctx.guild.icon_url)
                embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
                return await ctx.send(embed=embed)
            else:
                embed = embed_maker.message(ctx, f'{_cmd} is not a valid command')
                return await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Utility(bot))
