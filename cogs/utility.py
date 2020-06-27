import time
import discord
import config
import re
import random
import asyncio
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

    @commands.command(help='See someones profile picture', usage='pfp (user)',
                      examples=['pfp', 'pfp @Hattyot', 'pfp hattyot'], clearance='User', cls=command.Command)
    async def pfp(self, ctx, member=None):
        member = self.get_member(ctx, member)
        if member is None:
            member = ctx.author

        embed = discord.Embed(description=f'**Profile Picture of {member}**')
        embed.set_image(url=str(member.avatar_url).replace(".webp?size=1024", ".png?size=2048"))

        return await ctx.send(embed=embed)

    @commands.command(help='Create or add to a role reaction menu identified by its name.\n You can remove roles from role menu by doing `role_menu -n [name of role menu] -e [emote]`',
                      usage='role_menu -n [name of role menu] -r [role] -e [emote] -m [message after emote]',
                      examples=['role_menu -n opt-in channels -r sports -e :football: -m opt into the tldr-footbal channel'], clearance='Mod', cls=command.Command)
    async def role_menu(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_role_menu_args(args)
        role_menu_name = args['n']
        role_name = args['r']
        emote = args['e']
        message = args['m']

        data = db.server_data.find_one({'guild_id': ctx.guild.id})
        if 'role_menus' not in data:
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_menus': {}}})
            data['role_menus'] = {}

        embed_colour = config.EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_author(name=f'Role Menu: {role_menu_name}')
        embed.set_footer(icon_url=ctx.guild.icon_url)
        description = 'React to give yourself a role\n'

        if emote and role_menu_name and not role_name and not message:
            role_menu = [rm_id for rm_id in data['role_menus'] if data['role_menus'][rm_id]['name'] == role_menu_name and data['role_menus'][rm_id]['channel_id'] == ctx.channel.id]
            if not role_menu:
                return await embed_maker.message(ctx, f'Couldn\'t find a role menu by the name: {role_menu_name}', colour='red')

            msg_id = role_menu[0]
            role_menu = data['role_menus'][msg_id]
            emote_in_menu = [r for r in role_menu['roles'] if r['emote'] == emote]
            if not emote_in_menu:
                return await embed_maker.message(ctx, f'That role menu does not contain that emote', colour='red')

            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$pull': {f'role_menus.{msg_id}.roles': emote_in_menu[0]}})
            role_menu['roles'].remove(emote_in_menu[0])

            channel_id = role_menu['channel_id']
            channel = ctx.guild.get_channel(int(channel_id))
            message = await channel.fetch_message(msg_id)
            await message.add_reaction(emote)
            roles = role_menu['roles']

            # delete message if last one is removed
            if not roles:
                await message.delete()
                return await ctx.message.delete(delay=2000)

            for r in roles:
                description += f'\n{r["emote"]}: `{r["message"]}`'

            embed.description = description
            await message.edit(embed=embed)

            return await ctx.message.delete(delay=2000)

        if not role_menu_name or not role_name or not emote or not message:
            return await embed_maker.message(ctx, 'One or more of the required values is missing', colour='red')

        role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), ctx.guild.roles)
        if role is None:
            return await embed_maker.message(ctx, 'Invalid Role', colour='red')

        if role.permissions.manage_messages:
            return await embed_maker.message(ctx, 'Role Permissions are too high', colour='red')

        in_database = [rm for rm in data['role_menus'] if data['role_menus'][rm]['name'] == role_menu_name and data['role_menus'][rm]['channel_id'] == ctx.channel.id]

        rl_obj = {
            'emote': emote,
            'role_id': role.id,
            'message': message
        }

        if not in_database:
            new_role_menu_obj = {
                'channel_id': ctx.channel.id,
                'name': role_menu_name,
                'roles': [rl_obj]
            }
            description += f'\n{emote}: `{message}`'
            embed.description = description
            msg = await ctx.send(embed=embed)
            await msg.add_reaction(emote)
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {f'role_menus.{msg.id}': new_role_menu_obj}})
        else:
            message_id = in_database[0]
            role_menu = data['role_menus'][str(message_id)]
            emote_duplicate = [r['emote'] for r in data['role_menus'][str(message_id)]['roles'] if r['emote'] == emote]
            if emote_duplicate:
                return await embed_maker.message(ctx, 'Duplicate emote', colour='red')

            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$push': {f'role_menus.{message_id}.roles': rl_obj}})
            role_menu['roles'].append(rl_obj)
            channel_id = role_menu['channel_id']
            channel = ctx.guild.get_channel(int(channel_id))
            message = await channel.fetch_message(message_id)
            await message.add_reaction(emote)
            roles = role_menu['roles']
            for r in roles:
                description += f'\n{r["emote"]}: `{r["message"]}`'

            embed.description = description
            await message.edit(embed=embed)

        return await ctx.message.delete(delay=2000)

    @staticmethod
    def parse_role_menu_args(args):
        result = {
            'n': '',
            'r': '',
            'e': '',
            'm': ''
        }
        split_args = filter(None, args.split('-'))
        for v in split_args:
            tup = tuple(map(str.strip, v.split(' ', 1)))
            if len(tup) <= 1:
                continue
            key, value = tup
            result[key] = value

        return result

    @commands.command(help='See the list of your current reminders', usage='reminders (action) (reminder index)',
                      examples=['reminders', 'reminders remove kill demons'], clearance='User', cls=command.Command)
    async def reminders(self, ctx, action=None, *, index=None):
        timer_data = db.timers.find_one({'guild_id': ctx.guild.id})
        user_reminders = [timer for timer in timer_data['timers'] if timer['event'] == 'reminder' and timer['extras']['member_id'] == ctx.author.id]
        if action is None:
            if not user_reminders:
                msg = 'You currently have no reminders'
            else:
                msg = ''
                for i, r in enumerate(user_reminders):
                    expires = r["expires"] - round(time.time())
                    msg += f'`#{i + 1}` - {r["extras"]["reminder"]} in **{format_time.seconds(expires)}**\n'

            return await embed_maker.message(ctx, msg)
        elif action not in ['remove']:
            return await embed_maker.command_error(ctx, '(action)')
        elif index is None or int(index) <= 0 or int(index) > len(user_reminders):
            return await embed_maker.command_error(ctx, '(reminder index)')
        else:
            timer = user_reminders[int(index) - 1]
            db.timers.update_one({'guild_id': ctx.guild.id}, {'$pull': {'timers': {'id': timer['id']}}})
            return await embed_maker.message(ctx, f'`{timer["extras"]["reminder"]}` has been removed from your list of reminders', colour='red')

    @commands.command(help='Create a reminder', usage='remindme [time] [reminder]',
                      examples=['remindme 24h check state of mental health', 'remindme 30m slay demons', 'remindme 10h 30m 10s stay alive'],
                      clearance='User', cls=command.Command)
    async def remindme(self, ctx, *, reminder=None):
        if reminder is None:
            return await embed_maker.command_error(ctx)

        # check for time
        remind_times = []
        remind_time_str = ''
        for i, r in enumerate(reminder.split(' ')):
            if format_time.parse(r) is not None:
                if remind_times:
                    prev_remind_time = remind_times[i - 1]
                    if prev_remind_time <= format_time.parse(r):
                        break

                remind_times.append(format_time.parse(r))
                reminder = reminder.replace(r, '', 1)
                remind_time_str += f' {r}'
            else:
                break

        if not reminder.replace(remind_time_str, '').strip():
            return await embed_maker.message(ctx, 'You cannot have an empty reminder', colour='red')

        reminder = reminder.strip()
        parsed_time = int(format_time.parse(remind_time_str.strip()))
        if parsed_time is None:
            return await embed_maker.command_error(ctx, '[time]')

        expires = round(time.time()) + parsed_time
        utils_cog = self.bot.get_cog('Utils')
        await utils_cog.create_timer(expires=expires, guild_id=ctx.guild.id, event='reminder', extras={'reminder': reminder, 'member_id': ctx.author.id})

        return await embed_maker.message(ctx, f'Alright, in {format_time.seconds(parsed_time)} I will remind you: {reminder}')

    @commands.Cog.listener()
    async def on_reminder_timer_over(self, timer):
        guild_id = timer['guild_id']
        guild = self.bot.get_guild(int(guild_id))

        member_id = timer['extras']['member_id']
        member = guild.get_member(int(member_id))
        if member is None:
            member = await guild.fetch_member(int(member_id))
            if member is None:
                return

        reminder = timer['extras']['reminder']
        embed_colour = config.EMBED_COLOUR

        embed = discord.Embed(colour=embed_colour, description=f'Reminder: {reminder}', timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)

        return await member.send(embed=embed)

    @commands.command(
        help='create a giveaway, announces y amount of winners (default 1) after x amount of time (default 24h)',
        usage='giveaway -i [item(s) you want to give away] -w [how many winners] -t [time (m/h/d)] -r (restrict giveaway to a certain role)',
        examples=['giveaway -i TLDR pin of choice -w 1 -t 7d', 'giveaway -i 1000xp -w 5 -t 24h -r Party Member'],
        clearance='Mod', cls=command.Command)
    async def giveaway(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_giveaway_args(args)
        item = args['i']
        winners = str(args['w'])
        restrict_to_role = args['r']
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
        if restrict_to_role:
            role = discord.utils.find(lambda r: r.name.lower() == restrict_to_role.lower(), ctx.guild.roles)
            if not role:
                err = f'I couldn\'t find a role by the name {restrict_to_role}'
        else:
            role = ''

        if err:
            return await embed_maker.message(ctx, err, colour='red')

        role_id = '' if not role else role.id

        s = 's' if int(winners) > 1 else ''
        winner_role_str = f'\nWinner{s} will be chosen from users who have the <@&{role.id}> role' if role else ''
        description = f'React with :partying_face: to enter the giveaway!{winner_role_str}\nTime Left: **{time_left}**'
        colour = config.EMBED_COLOUR
        embed = discord.Embed(title=item, colour=colour, description=description, timestamp=datetime.now())
        embed.set_footer(text='Started at', icon_url=ctx.guild.icon_url)

        msg = await ctx.send(embed=embed)
        await msg.add_reaction('🥳')
        await ctx.message.delete(delay=3)

        utils_cog = self.bot.get_cog('Utils')
        await utils_cog.create_timer(
            expires=expires, guild_id=ctx.guild.id, event='giveaway',
            extras={
                'timer_cog': 'Utility', 'timer_function': 'giveaway_timer',
                'args': (msg.id, msg.channel.id, embed.to_dict(), giveaway_time, winners, role_id)
            }
        )

    @commands.Cog.listener()
    async def on_giveaway_timer_over(self, timer):
        message_id, channel_id, embed, _, winner_count, role_id = timer['extras']['args']
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
                if not role_id:
                    eligible = await r.users().flatten()
                    # removes bot from list
                    eligible.pop(0)
                else:
                    eligible = [user for user in await r.users().flatten() if role_id in [role.id for role in user.roles]]

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
            if role_id:
                winners_str = 'No one won, no one eligible entered :('
            else:
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
        message_id, channel_id, embed, sleep_duration, winner_count, role_id = args
        embed = discord.Embed.from_dict(embed)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)

        message = await channel.fetch_message(message_id)

        while sleep_duration > 0:
            s = 's' if int(winner_count) > 1 else ''
            winner_role_str = f'\nWinner{s} will be chosen from users who have the <@&{role_id}> role' if role_id else ''
            description = f'React with :partying_face: to enter the giveaway!{winner_role_str}'
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

    @staticmethod
    def parse_giveaway_args(args):
        result = {
            'i': '',
            'w': 1,
            't': '24h',
            'r': ''
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
            return await embed_maker.message(ctx, err, colour='red')

        description = f'**"{question}"**\n\n'
        colour = config.EMBED_COLOUR
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

            description += '\n\n'.join(f'{e} | **{o}**' for o, e in zip(options, emotes))
            embed.description = description

        poll_msg = await ctx.send(embed=embed)
        voted_users = {}

        embed_colour = config.EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_footer(text=f'{ctx.guild.name}', icon_url=ctx.guild.icon_url)
        embed.title = f'**"{question}"**'

        async def count(user, msg, emote):
            if msg.id != poll_msg.id:
                return

            if user.id in voted_users:
                if voted_users[user.id]['buffer'] >= 5:
                    embed.description = f'Don\'t spam please'
                    return await user.send(embed=embed)
                voted_users[user.id]['buffer'] += 1

                previous_emote = voted_users[user.id]['emote']
                if emote == previous_emote:
                    embed.description = f'Your vote has already been counted towards: {emote}'
                    return await user.send(embed=embed)

                db.polls.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'polls.{msg.id}.{emote}': 1, f'polls.{msg.id}.{previous_emote}': -1}})
                voted_users[user.id]['emote'] = emote

                embed.description = f'Your vote has been changed to: {emote}'
                return await user.send(embed=embed)

            voted_users[user.id] = {'emote': emote, 'buffer': 0}  # checking for spammers
            db.polls.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'polls.{msg.id}.{emote}': 1}})

            embed.description = f'Your vote has been counted towards: {emote}'
            return await user.send(embed=embed)

        poll = dict.fromkeys(emotes, 0)
        buttons = dict.fromkeys(emotes, count)

        utils_cog = self.bot.get_cog('Utils')
        expires = round(time.time()) + round(poll_time)
        await utils_cog.create_timer(
            expires=expires, guild_id=ctx.guild.id, event='anon_poll',
            extras={'message_id': poll_msg.id, 'channel_id': poll_msg.channel.id,
                    'question': question, 'options': dict(zip(emotes, options))}
        )
        await utils_cog.new_no_expire_menu(poll_msg, buttons)

        db.polls.update_one({'guild_id': ctx.guild.id}, {'$set': {f'polls.{poll_msg.id}': poll}})

        return await ctx.message.delete(delay=3)

    @commands.Cog.listener()
    async def on_anon_poll_timer_over(self, timer):
        message_id = timer['extras']['message_id']
        channel_id = timer['extras']['channel_id']
        guild_id = timer['guild_id']
        options = timer['extras']['options']
        data = db.polls.find_one({'guild_id': guild_id})
        if data is None:
            data = self.bot.add_collections(guild_id, 'polls')

        if str(message_id) not in data['polls']:
            return

        db.polls.update_one({'guild_id': guild_id}, {'$unset': {f'polls.{message_id}': ''}})

        question = timer['extras']['question']
        poll = data['polls'][str(message_id)]
        emote_count = poll
        channel = self.bot.get_channel(channel_id)
        message = await channel.fetch_message(message_id)
        total_emotes = sum(emote_count.values())
        description = f'**"{question}"**\n\n'

        if total_emotes == 0:
            # just incase nobody participated
            description += '\n\n'.join(f'{emote} **- {emote_count}** | **0%**' for emote, emote_count in emote_count.items())
        else:
            description += '\n\n'.join(f'{emote} - {options[emote]} - **{emote_count}** | **{round((emote_count * 100) / total_emotes)}%**' for emote, emote_count in emote_count.items())

        embed = message.embeds[0]
        embed.description = description
        embed.timestamp = datetime.now()
        embed.set_footer(text='Ended at')

        utils_cog = self.bot.get_cog('Utils')
        if message_id in utils_cog.no_expire_menus:
            del utils_cog.no_expire_menus[message_id]

        await message.edit(embed=embed)
        await message.clear_reactions()

        # send message about poll being completed
        return await channel.send(f'Poll finished: https://discordapp.com/channels/{guild_id}/{channel_id}/{message_id}')

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
            return await embed_maker.message(ctx, err, colour='red')

        description = f'**"{question}"**\n'
        colour = config.EMBED_COLOUR
        embed = discord.Embed(colour=colour, description=description, timestamp=datetime.now())
        embed.set_author(name='Poll')
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

    @staticmethod
    def parse_poll_args( args):
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
            result['o'] = [r.strip() for r in result['o'].split(',')]
        else:
            return result

        # check for custom option emotes
        oe_regex = re.compile(r'\[(.*):(.*)\]')
        if re.match(oe_regex, result['o'][0]):
            for option in result['o']:
                oe = re.match(oe_regex, option)
                if oe:
                    e, o = oe.groups()
                    e = e.strip()
                    result['o_emotes'][e] = o
                    continue

                result['o_emotes'] = None
                break

        return result

    @commands.command(help='Get help smh', usage='help (command)', examples=['help', 'help ping'],
                      clearance='User', cls=command.Command)
    async def help(self, ctx, _cmd=None):
        embed_colour = config.EMBED_COLOUR
        prefix = config.PREFIX
        all_commands = self.bot.commands
        help_object = {}
        data = db.server_data.find_one({'guild_id': ctx.guild.id})

        for cmd in all_commands:
            if hasattr(cmd, 'dm_only'):
                continue

            if 'commands' in data and 'disabled' in data['commands'] and cmd.name in data['commands']['disabled']:
                continue

            # Check if cog is levels and if cmd requires mod perms
            if cmd.cog_name == 'Leveling' and 'Leveling - Staff' not in help_object:
                help_object['Leveling - Staff'] = []
            if cmd.cog_name == 'Leveling' and cmd.clearance != 'User':
                help_object['Leveling - Staff'].append(cmd)
                continue

            if cmd.cog_name not in help_object:
                help_object[cmd.cog_name] = [cmd]
            else:
                help_object[cmd.cog_name].append(cmd)

        utils = self.bot.get_cog('Utils')
        clearance = await utils.get_user_clearance(ctx.guild.id, ctx.author.id)

        # check if user has special access
        data = db.server_data.find_one({'guild_id': ctx.guild.id})
        if 'users' not in data:
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'users': {}}})
            data['users'] = {}
        if 'roles' not in data:
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'roles': {}}})
            data['roles'] = {}

        if str(ctx.author.id) not in data['users']:
            data['users'][str(ctx.author.id)] = []

        if _cmd is None:
            embed = discord.Embed(
                colour=embed_colour, timestamp=datetime.now(),
                description=f'**Prefix** : `{prefix}`\nFor additional info on a command, type `{prefix}help [command]`'
            )
            embed.set_author(name=f'Help - {clearance[0]}', icon_url=ctx.guild.icon_url)
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

            # get special access commands
            special_access_cmds = []

            # find common roles
            common = set([str(r.id) for r in ctx.author.roles]) & set(data['roles'].keys())
            if common:
                for r in common:
                    special_access_cmds += data['roles'][r]

            # add special access field
            if data['users'][str(ctx.author.id)]:
                special_access_cmds += data['users'][str(ctx.author.id)]

            # remove duplicates
            special_access_cmds = list(dict.fromkeys(special_access_cmds))

            for cat in help_object:
                cat_commands = []
                for cmd in help_object[cat]:
                    if cmd.clearance in clearance:
                        cat_commands.append(cmd.name)

                if cat_commands:
                    # remove command from special_access_cmds if user already has access to it
                    common = set(special_access_cmds) & set(cat_commands)
                    if common:
                        for r in common:
                            special_access_cmds.remove(r)

                    embed.add_field(name=f'>{cat}', value=" \| ".join([f'`{c}`' for c in cat_commands]), inline=False)

            if special_access_cmds:
                embed.add_field(name=f'>Special Access', value=" \| ".join([f'`{c}`' for c in special_access_cmds]), inline=False)

            return await ctx.send(embed=embed)
        else:
            if self.bot.get_command(_cmd):
                cmd = self.bot.get_command(_cmd)
                if cmd.hidden:
                    return

                if 'commands' in data and 'disabled' in data['commands'] and cmd.name in data['commands']['disabled']:
                    return

                if ctx.command.clearance not in clearance and \
                   ctx.command.name not in data['users'][str(ctx.author.id)] and \
                   not set([str(r.id) for r in ctx.author.roles]) & set(data['roles'].keys()):
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
                return await embed_maker.message(ctx, f'{_cmd} is not a valid command')

    @staticmethod
    def get_member(ctx, source):
        if source is None:
            return None
        # check if source is member mention
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
        # Check if source is user id
        elif source.isdigit():
            member = discord.utils.find(lambda m: m.id == source, ctx.guild.members)
        # Check if source is member's name
        else:
            regex = re.compile(fr'({source.lower()})')
            member = discord.utils.find(
                lambda m: re.findall(regex, m.name.lower()) or re.findall(regex, m.display_name.lower()),
                ctx.guild.members
            )

        return member


def setup(bot):
    bot.add_cog(Utility(bot))
