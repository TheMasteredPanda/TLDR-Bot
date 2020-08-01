import time
import discord
import config
import re
import random
import asyncio
import os
import requests
import googletrans
from bs4 import BeautifulSoup
from cogs.utils import get_member, get_user_clearance
from datetime import datetime
from discord.ext import commands
from modules import database, command, embed_maker, format_time

db = database.Connection()


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='translate text to english', usage='translate [text]', examples=['translate tere'],
                      clearance='User', cls=command.Command)
    async def translate(self, ctx, *, text=None):
        if text is None:
            return await embed_maker.command_error(ctx)

        loop = self.bot.loop
        trans = googletrans.Translator()
        try:
            ret = await loop.run_in_executor(None, trans.translate, text)
        except Exception as e:
            return await embed_maker.message(ctx, f'An error occurred: {e.__class__.__name__}: {e}', colour='red')

        embed = discord.Embed(colour=config.EMBED_COLOUR, timestamp=datetime.now())
        src = googletrans.LANGUAGES.get(ret.src, '(auto-detected)').title()
        dest = googletrans.LANGUAGES.get(ret.dest, 'Unknown').title()
        embed.set_author(name='Translated', icon_url=ctx.guild.icon_url)
        embed.add_field(name=f'From {src}', value=ret.origin, inline=False)
        embed.add_field(name=f'To {dest}', value=ret.text, inline=False)
        embed.set_footer(text=str(ctx.author), icon_url=ctx.author.avatar_url)
        await ctx.send(embed=embed)

    @commands.command(help='See time in any location in the world', usage='time [location]', examples=['time london'],
                      clearance='User', cls=command.Command, name='time')
    async def time_in(self, ctx, *, location=None):
        if location is None:
            return await embed_maker.command_error(ctx)
        headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.142 Safari/537.36'}
        response = requests.get(f'https://www.time.is/{location}', headers=headers)
        soup = BeautifulSoup(response.content, 'html.parser')
        error = soup.find('h1', attrs={'class': 'error'})
        location_time = soup.find('div', attrs={'id': 'clock0_bg'}).text
        msg = soup.find('div', attrs={'id': 'msgdiv'}).text
        if error:
            return await embed_maker.message(ctx, 'Invalid loaction', colour='red')
        else:
            return await embed_maker.message(ctx, f'{msg}is: `{location_time}`')

    @commands.command(help='Get bot\'s latency', usage='ping', examples=['ping'], clearance='User', cls=command.Command)
    async def ping(self, ctx):
        message_created_at = ctx.message.created_at
        message = await ctx.send("Pong")
        ping = (datetime.utcnow() - message_created_at) * 1000
        await message.edit(content=f"\U0001f3d3 Pong   |   {int(ping.total_seconds())}ms")

    @commands.command(help='See someones profile picture', usage='pfp (user)',
                      examples=['pfp', 'pfp @Hattyot', 'pfp hattyot'], clearance='User', cls=command.Command)
    async def pfp(self, ctx, member=None):
        member = await get_member(ctx, self.bot, member)
        if member is None:
            member = ctx.author

        embed = discord.Embed(description=f'**Profile Picture of {member}**')
        embed.set_image(url=str(member.avatar_url).replace(".webp?size=1024", ".png?size=2048"))

        return await ctx.send(embed=embed)

    @commands.command(help='See info about a user', usage='userinfo (user)', examples=['userinfo', 'userinfo Hattyot'], clearance='User', cls=command.Command)
    async def userinfo(self, ctx, *, user=None):
        if user is None:
            member = ctx.author
        else:
            member = await get_member(ctx, self.bot, user)
            if member is None:
                return await embed_maker.message(ctx, 'User not found', colour='red')
            elif isinstance(member, str):
                return await embed_maker.message(ctx, member, colour='red')

        embed = discord.Embed(colour=config.EMBED_COLOUR, timestamp=datetime.now())
        name = str(member)
        if member.display_name:
            name += f' - {member.display_name}'
        embed.set_author(name=name, icon_url=member.avatar_url)

        embed.add_field(name='ID', value=member.id)
        embed.add_field(name='Avatar', value=f'[link]({member.avatar_url})')
        embed.add_field(name='\u200b', value='\u200b')
        created_at = datetime.now() - member.created_at
        created_at_seconds = created_at.total_seconds()
        embed.add_field(name='Account Created', value=f'{member.created_at.strftime("%b %d %Y %H:%M")}\n{format_time.seconds(created_at_seconds, accuracy=10)} Ago')
        joined_at = datetime.now() - member.joined_at
        joined_at_seconds = joined_at.total_seconds()
        embed.add_field(name='Joined Server', value=f'{member.joined_at.strftime("%b %d %Y %H:%M")}\n{format_time.seconds(joined_at_seconds, accuracy=10)} Ago')
        embed.add_field(name='\u200b', value='\u200b')
        embed.add_field(name='Status', value=str(member.status), inline=False)

        embed.set_thumbnail(url=member.avatar_url)
        embed.set_footer(text=str(member), icon_url=ctx.guild.icon_url)

        return await ctx.send(embed=embed)

    @commands.command(help='Create or add to a role reaction menu identified by its name.\n You can remove roles from role menu by doing `role_menu -n [name of role menu] -e [emote]`',
                      usage='role_menu -n [name of role menu] -r [role] -e [emote] -m [message after emote]',
                      examples=['role_menu -n opt-in channels -r sports -e :football: -m opt into the tldr-footbal channel'], clearance='Mod', cls=command.Command)
    async def role_menu(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_role_menu_args(args)
        role_menu_name = args['n']
        if not role_menu_name:
            return await embed_maker.message(ctx, 'Missing role menu name', colour='red')
        role_name = args['r']
        emote = args['e']
        message = args['m']

        role_menu_data = db.reaction_menus.find_one({'guild_id': ctx.guild.id, 'role_menu_name': role_menu_name})

        embed_colour = config.EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_author(name=f'Role Menu: {role_menu_name}')
        embed.set_footer(icon_url=ctx.guild.icon_url)
        description = 'React to give yourself a role\n'

        if emote and role_menu_name and not role_name and not message:
            if not role_menu_data:
                return await embed_maker.message(ctx, f'I couldn\'t find a role menu by the name: `{role_menu_name}`', colour='red')
            msg_id = role_menu_data['message_id']
            emote_in_menu = emote in role_menu_data['roles'].keys()
            if not emote_in_menu:
                return await embed_maker.message(ctx, f'That role menu does not contain that emote', colour='red')

            db.reaction_menus.update_one({'guild_id': ctx.guild.id, 'role_menu_name': role_menu_name}, {'$unset': {f'roles': emote}})
            del role_menu_data['roles'][emote]

            channel_id = role_menu_data['channel_id']
            channel = ctx.guild.get_channel(int(channel_id))
            if channel is None:
                db.reaction_menus.delete_one({'guild_id': ctx.guild.id, 'role_menu_name': role_menu_name})
                return await embed_maker.message(ctx, f'Role menu has an invalid channel id, role menu `{role_menu_name}` has been deleted from the database')

            message = await channel.fetch_message(msg_id)
            await message.add_reaction(emote)
            roles = role_menu_data['roles']

            # delete message if last role has been removed
            if not roles:
                await message.delete()
                return await ctx.message.delete(delay=2000)

            for emoji in roles:
                description += f'\n{emoji}: `{roles[emoji]["message"]}`'

            embed.description = description
            await message.edit(embed=embed)

            return await ctx.message.delete(delay=2000)

        if not role_name or not emote or not message:
            return await embed_maker.message(ctx, 'One or more of the required values is missing', colour='red')

        role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), ctx.guild.roles)
        if role is None:
            return await embed_maker.message(ctx, f'I couldn\'t find a role by the name: `{role_name}`', colour='red')

        if role.permissions.manage_messages:
            return await embed_maker.message(ctx, 'Role Permissions are too high', colour='red')

        rl_obj = {
            'role_id': role.id,
            'message': message
        }

        if not role_menu_data:
            description += f'\n{emote}: `{message}`'
            embed.description = description
            msg = await ctx.send(embed=embed)
            await msg.add_reaction(emote)

            new_role_menu_doc = {
                'guild_id': ctx.guild.id,
                'role_menu_name': role_menu_name,
                'message_id': msg.id,
                'channel_id': ctx.channel.id,
                'roles': {
                    emote: rl_obj
                }
            }
            db.reaction_menus.insert_one(new_role_menu_doc)
        else:
            emote_duplicate = emote in role_menu_data['roles'].keys()
            if emote_duplicate:
                return await embed_maker.message(ctx, 'Duplicate emote', colour='red')

            db.reaction_menus.update_one({'guild_id': ctx.guild.id, 'role_menu_name': role_menu_name}, {'$set': {f'roles.{emote}': rl_obj}})
            role_menu_data['roles'][emote] = rl_obj

            message_id = role_menu_data['message_id']
            channel_id = role_menu_data['channel_id']
            channel = ctx.guild.get_channel(int(channel_id))
            message = await channel.fetch_message(message_id)
            await message.add_reaction(emote)

            roles = role_menu_data['roles']
            for emoji in roles:
                description += f'\n{emoji}: `{roles[emoji]["message"]}`'

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
        _args = list(filter(lambda a: bool(a), re.split(r' ?-([nrem]) ', args)))
        for i in range(int(len(_args) / 2)):
            result[_args[i + (i * 1)]] = _args[i + (i + 1)]

        return result

    @commands.command(help='See the list of your current reminders', usage='reminders (action) (reminder index)',
                      examples=['reminders', 'reminders remove 1'], clearance='User', cls=command.Command)
    async def reminders(self, ctx, action=None, *, index=None):
        user_reminders = [reminder for reminder in db.timers.find({'guild_id': ctx.guild.id, 'event': 'reminder', 'extras.member_id': ctx.author.id})]
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
                # check if current parsed time is smaller than the last, so user cant just do 10h 10h 10h
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
        parsed_time = format_time.parse(remind_time_str.strip())
        if parsed_time is None:
            return await embed_maker.command_error(ctx, '[time]')

        expires = round(time.time()) + parsed_time
        utils_cog = self.bot.get_cog('Utils')
        await utils_cog.create_timer(expires=expires, guild_id=ctx.guild.id, event='reminder', extras={'reminder': reminder, 'member_id': ctx.author.id})

        return await embed_maker.message(ctx, f'Alright, in {format_time.seconds(parsed_time, accuracy=10)} I will remind you: {reminder}')

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
        result = {'i': '', 'w': 1, 't': '24h', 'r': ''}
        _args = list(filter(lambda a: bool(a), re.split(r' ?-([iwtr]) ', args)))

        for i in range(int(len(_args) / 2)):
            result[_args[i + (i * 1)]] = _args[i + (i + 1)]

        return result

    @commands.command(help='Create an anonymous poll. with options adds numbers as reactions, without it just adds thumbs up and down. after x minutes (default 5) is up, results are displayed',
                      usage='anon_poll [-q question] (-o option1 | option2 | ...)/(-o [emote: option], [emote: option], ...) (-t [time (m/h/d) (-u update interval)',
                      examples=['anon_poll -q best food? -o pizza, burger, fish and chips, salad', 'anon_poll -q Do you guys like pizza? -t 2m', 'anon_poll -q Where are you from? -o [🇩🇪: Germany], [🇬🇧: UK] -t 1d -u 1m'],
                      clearance='Mod', cls=command.Command)
    async def anon_poll(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = self.parse_poll_args(args)
        question = args['q']
        options = args['o']
        poll_time = format_time.parse(args['t'])
        option_emotes = args['o_emotes']
        update_interval = args['u']

        err = ''
        if poll_time is None:
            err = 'Invalid time arg'

        if option_emotes is None:
            err = 'Error with custom option emotes'

        if question == '' or options == '':
            err = 'Empty arg'

        if (len(options) > 9 and not option_emotes) or (option_emotes and len(options) > 15):
            err = 'Too many options'
        if len(options) < 2:
            err = 'Too few options'

        if update_interval and format_time.parse(update_interval) is None:
            err = 'Invalid update interval time'
        else:
            update_interval = format_time.parse(update_interval)
            if update_interval and update_interval < 30:
                err = 'Update interval can\'t be smaller than 30 seconds'

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
        # add reactions to message
        for e in emotes:
            await poll_msg.add_reaction(e)

        utils_cog = self.bot.get_cog('Utils')
        if update_interval:
            expires = 0
        else:
            expires = round(time.time()) + round(poll_time)

        extras = {
            'message_id': poll_msg.id,
            'channel_id': poll_msg.channel.id,
            'options': dict(zip(emotes, options)),
            'update_interval': 0,
            'true_expire': 0
        }
        if update_interval:
            extras['update_interval'] = update_interval
            extras['true_expire'] = round(time.time()) + poll_time

        await utils_cog.create_timer(expires=expires, guild_id=ctx.guild.id, event='anon_poll', extras=extras)

        reaction_menu_doc = {
            'guild_id': ctx.guild.id,
            'message_id': poll_msg.id,
            'question': question,
            'voted': [],
            'poll': dict.fromkeys(emotes, 0)
        }
        db.reaction_menus.insert_one(reaction_menu_doc)

        return await ctx.message.delete(delay=3)

    @commands.Cog.listener()
    async def on_anon_poll_timer_over(self, timer):
        message_id = timer['extras']['message_id']
        channel_id = timer['extras']['channel_id']
        guild_id = timer['guild_id']
        options = timer['extras']['options']
        update_interval = timer['extras']['update_interval']
        true_expire = timer['extras']['true_expire']

        poll_data = db.reaction_menus.find_one({'guild_id': guild_id, 'message_id': message_id})
        if not poll_data:
            return

        question = poll_data['question']
        channel = self.bot.get_channel(channel_id)
        message = await channel.fetch_message(message_id)
        poll = poll_data['poll']
        total_emotes = sum([v for v in poll.values() if isinstance(v, int)])

        description = f'**"{question}"**\n\n'
        if total_emotes == 0:
            # just incase nobody participated
            description += '\n\n'.join(f'{emote} - {options[emote]} - **{emote_count}** | **0%**' for emote, emote_count in poll.items() if emote in options)
        else:
            description += '\n\n'.join(f'{emote} - {options[emote]} - **{emote_count}** | **{round((emote_count * 100) / total_emotes)}%**' for emote, emote_count in poll.items() if emote in options)

        old_embed = message.embeds[0].to_dict()
        embed = message.embeds[0]
        embed.description = description
        embed.timestamp = datetime.fromtimestamp(true_expire)
        if update_interval:
            embed.set_footer(text=f'Results updated every {format_time.seconds(update_interval)} | Ends at')
        else:
            embed.set_footer(text='Ended at')

        if old_embed != embed.to_dict():
            await message.edit(embed=embed)

        utils_cog = self.bot.get_cog('Utils')
        # check if poll passed true expire
        expired = round(time.time()) > true_expire
        if expired:
            db.reaction_menus.delete_one({'guild_id': guild_id, 'message_id': message_id})
            await message.clear_reactions()

            # send message about poll being completed
            return await channel.send(
                f'Poll finished: https://discordapp.com/channels/{guild_id}/{channel_id}/{message_id}')

        # run poll timer again if needed
        elif update_interval:
            expires = round(time.time()) + round(update_interval)
            return await utils_cog.create_timer(expires=expires, guild_id=timer['guild_id'], event='anon_poll', extras=timer['extras'])

    @commands.command(help='Create a poll. with options adds numbers as reactions, without it just adds thumbs up and down.',
                      usage='poll [-q question] (-o option1 | option2 | ...)/(-o [emote: option], [emote: option], ...)',
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
        if len(options) < 2:
            err = 'Too few options'

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
    def parse_poll_args(args):
        result = {
            'q': '',
            'o': [],
            't': '5m',
            'o_emotes': {},
            'u': ''
        }
        _args = list(filter(lambda a: bool(a), re.split(r' ?-([toqu]) ', args)))
        for i in range(int(len(_args)/2)):
            result[_args[i + (i * 1)]] = _args[i + (i + 1)]

        if result['o']:
            result['o'] = [r.strip() for r in result['o'].split('|')]
        else:
            return result

        # check for custom option emotes
        oe_regex = re.compile(r'\[(.*):(.*)\]')
        if re.match(oe_regex, result['o'][0]):
            for option in result['o']:
                oe = re.findall(oe_regex, option)
                if oe:
                    e, o = oe[0]
                    e = e.strip()
                    if e.isdigit():
                        # check if outside emote
                        outside_emote_data = db.outside_emotes.find_one({'emote_id': str(e)})
                        if outside_emote_data:
                            e = outside_emote_data['emote']

                    result['o_emotes'][e] = o
                    continue

                result['o_emotes'] = None
                break

        return result

    @commands.command(help='Get help smh', usage='help (command)', examples=['help', 'help ping'], clearance='User', cls=command.Command)
    async def help(self, ctx, _cmd=None):
        embed_colour = config.EMBED_COLOUR
        prefix = config.PREFIX
        all_commands = self.bot.commands
        help_object = {}

        user_clearance = get_user_clearance(ctx.author)
        for cmd in all_commands:
            if hasattr(cmd, 'dm_only'):
                continue

            command_data = db.commands.find_one({'guild_id': ctx.guild.id, 'command_name': cmd.name})
            if not command_data:
                command_data = {
                    'guild_id': ctx.guild.id,
                    'command_name': cmd.name,
                    'disabled': 0,
                    'user_access': {},
                    'role_access': {}
                }

            user_access = command_data['user_access']
            role_access = command_data['role_access']

            access_to_command_given = False
            access_to_command_taken = False

            # check user_access
            if user_access:
                access_to_command_given = f'{ctx.author.id}' in user_access and user_access[f'{ctx.author.id}'] == 'give'
                access_to_command_taken = f'{ctx.author.id}' in user_access and user_access[f'{ctx.author.id}'] == 'take'

            # check role access
            if role_access:
                role_access_matching_role_ids = set([str(r.id) for r in ctx.author.roles]) & set(role_access.keys())
                if role_access_matching_role_ids:
                    # sort role by permission
                    roles = [ctx.guild.get_role(int(r_id)) for r_id in role_access_matching_role_ids]
                    sorted_roles = sorted(roles, key=lambda r: r.permissions)
                    if sorted_roles:
                        role = sorted_roles[-1]
                        access_to_command_given = access_to_command_given or f'{role.id}' in role_access and role_access[f'{role.id}'] == 'give'
                        access_to_command_taken = access_to_command_taken or f'{role.id}' in role_access and role_access[f'{role.id}'] == 'take'

            if cmd.clearance not in user_clearance and not access_to_command_given:
                continue

            if access_to_command_taken:
                continue

            if command_data['disabled'] and ctx.author.id not in config.DEV_IDS:
                continue

            if access_to_command_given:
                if 'Special Access' not in help_object:
                    help_object['Special Access'] = [cmd]
                else:
                    help_object['Special Access'].append(cmd)

            # Check if cog is levels and if cmd requires mod perms
            if cmd.cog_name == 'Leveling' and 'Leveling - Staff' not in help_object and cmd.clearance != 'User':
                help_object['Leveling - Staff'] = []
                continue
            if cmd.cog_name == 'Leveling' and cmd.clearance != 'User':
                help_object['Leveling - Staff'].append(cmd)
                continue

            if cmd.cog_name not in help_object:
                help_object[cmd.cog_name] = [cmd]
            else:
                help_object[cmd.cog_name].append(cmd)

        if _cmd is None:
            embed = discord.Embed(
                colour=embed_colour, timestamp=datetime.now(),
                description=f'**Prefix** : `{prefix}`\nFor additional info on a command, type `{prefix}help [command]`'
            )
            embed.set_author(name=f'Help - {user_clearance[0]}', icon_url=ctx.guild.icon_url)
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

            # categories are listed in a list so they come out sorted instead of in a random order
            categories = ['Dev', 'Mod', 'Leveling - Staff', 'Settings', 'Leveling', 'Utility', 'Fun']
            for cat in categories:
                if cat not in help_object:
                    continue
                # i need special access to be last
                if cat == 'Special Access':
                    continue

                embed.add_field(name=f'>{cat}', value=" \| ".join([f'`{c}`' for c in help_object[cat]]), inline=False)

            if 'Special Access' in help_object:
                embed.add_field(name=f'>Special Access', value=" \| ".join([f'`{c}`' for c in help_object['Special Access']]), inline=False)

            return await ctx.send(embed=embed)
        else:
            if self.bot.get_command(_cmd):
                cmd = self.bot.get_command(_cmd)
                if cmd.hidden:
                    return

                if cmd.cog_name not in help_object or cmd not in help_object[cmd.cog_name]:
                    return await embed_maker.message(ctx, f'{_cmd} is not a valid command')

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

    @commands.command(hidden=True, help='View source code of any command',
                      usage='source (command)', examples=['source', 'source pfp'],
                      clearance='Dev', cls=command.Command, aliases=['src'])
    async def source(self, ctx, *, command=None):
        u = '\u200b'
        if not command:
            return await embed_maker.message(ctx, 'Check out the full sourcecode on GitHub\nhttps://github.com/Hattyot/TLDR-Bot/tree/1.5.2')

        # pull source code
        src = f"```py\n{str(__import__('inspect').getsource(self.bot.get_command(command).callback)).replace('```', f'{u}')}```"
        # replace @commands.command() section
        src = '```py\n' + re.split(r'@commands.command(.*?)\)\n', src, 1, flags=re.DOTALL | re.MULTILINE)[-1]
        # pull back indentation
        new_src = ''
        for line in src.splitlines():
            new_src += f"{line.replace('    ', '', 1)}\n"
        src = new_src
        if len(src) > 2000:
            cmd = self.bot.get_command(command).callback
            if not cmd:
                return await ctx.send("Command not found.")
            file = cmd.__code__.co_filename
            location = os.path.relpath(file)
            total, fl = __import__('inspect').getsourcelines(cmd)
            ll = fl + (len(total) - 1)
            return await embed_maker.message(ctx, f"This code was too long for Discord, you can see it instead [on GitHub](https://github.com/Hattyot/TLDR-Bot/blob/1.5.2/{location}#L{fl}-L{ll})")
        else:
            await ctx.send(src)


def setup(bot):
    bot.add_cog(Utility(bot))
