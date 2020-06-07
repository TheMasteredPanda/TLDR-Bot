import discord
import re
import dateparser
import datetime
import time
import asyncio
import config
from modules import command, database, embed_maker, format_time
from discord.ext import commands

db = database.Connection()


class Mod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Daily debate scheduler', usage='dailydebates (action) (topic/time/channel/notification role)',
                      clearance='Mod', cls=command.Command,
                      examples=['dailydebates', 'dailydebates add is TLDR ross mega cool?',
                                'dailydebates remove is TldR roos mega cool?', 'dailydebates set_time 2pm GMT',
                                'dailydebates set_channel #daily-debates', 'dailydebates set_role Debaters'])
    async def dailydebates(self, ctx, action=None, *, arg=None):
        data = db.server_data.find_one({'guild_id': ctx.guild.id})
        if 'daily_debates' not in data:
            data = self.bot.add_collections(ctx.guild.id, 'server_data')

        if action == 'set_time':
            parsed_arg_time = dateparser.parse(
                arg, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True}
            )
            if not parsed_arg_time:
                return await embed_maker.message(ctx, 'Invalid time', colour='red')

            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'daily_debates.time': arg}})
            await embed_maker.message(ctx, f'Daily debates will now be announced every day at {arg}')

            # cancel old timer if active
            timer_data = db.timers.find_one({'guild_id': ctx.guild.id})
            daily_debate_timer = [timer for timer in timer_data['timers'] if timer['event'] == 'daily_debate' or timer['event'] == 'daily_debate_final']
            if daily_debate_timer:
                db.timers.update_one({'guild_id': ctx.guild.id}, {'$pull': {'timers': {'id': daily_debate_timer[0]['id']}}})
                return await self.start_daily_debate_timer(ctx.guild.id, arg)
            else:
                return

        if action == 'set_channel':
            if not ctx.message.channel_mentions:
                return await embed_maker.message(ctx, 'Invalid channel mention', colour='red')

            channel_id = ctx.message.channel_mentions[0].id
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'daily_debates.channel': channel_id}})
            return await embed_maker.message(ctx, f'Daily debates will now be announced every day at <#{channel_id}>')

        if action == 'set_role':
            role = discord.utils.find(lambda r: r.name.lower() == arg.lower(), ctx.guild.roles)
            if not role:
                return await embed_maker.message(ctx, 'Invalid role name', colour='red')

            role_id = role.id
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'daily_debates.role': role_id}})
            return await embed_maker.message(ctx, f'Daily debates will now be announced every day to <@&{role_id}>')

        missing = False
        # check if time has been set up, if not, inform user
        if not data['daily_debates']['time']:
            missing = True
            err = f'Time has not been set yet, i dont know when to send the message\n' \
                  f'Set time with `{config.PREFIX}dailydebates set_time [time]` e.g. `{config.PREFIX}dailydebates set_time 2pm GMT+1`'
            return await embed_maker.message(ctx, err, colour='red')

        # check if channel has been set up, if not, inform user
        if not data['daily_debates']['channel']:
            missing = True
            err = f'Channel has not been set yet, i dont know where to send the message\n' \
                  f'Set time with `{config.PREFIX}dailydebates set_channel [#channel]` e.g. `{config.PREFIX}dailydebates set_channel #daily-debates`'
            return await embed_maker.message(ctx, err, colour='red')

        if not missing:
            # check for active timer
            timer_data = db.timers.find_one({'guild_id': ctx.guild.id})
            daily_debate_timer = [timer for timer in timer_data['timers'] if timer['event'] == 'daily_debate' or timer['event'] == 'daily_debate_final']
            if not daily_debate_timer:
                await self.start_daily_debate_timer(ctx.guild.id, data['daily_debates']['time'])

        if action is None:
            # List currently set up daily debate topics
            topics = data['daily_debates']['topics']
            if not topics:
                topics_str = f'Currently there are no debate topics set up\n\nNext one in: {format_time.seconds()}'
            else:
                topics_str = '**Topics:**\n' + '\n'.join(f'**{i + 1}:** {topic}' for i, topic in enumerate(topics))

            # calculate when next daily debate starts
            timer_data = db.timers.find_one({'guild_id': ctx.guild.id})
            daily_debate_timer = [timer for timer in timer_data['timers'] if timer['event'] == 'daily_debate' or timer['event'] == 'daily_debate_final']

            if not daily_debate_timer:
                return

            dd_time = daily_debate_timer[0]['extras']['time']
            parsed_dd_time = dateparser.parse(dd_time, settings={'RETURN_AS_TIMEZONE_AWARE': True})
            parsed_dd_time = dateparser.parse(dd_time, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(parsed_dd_time.tzinfo)})
            time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
            time_diff_seconds = round(time_diff.total_seconds())

            topics_str += f'\n\nNext one in: **{format_time.seconds(time_diff_seconds)}**'

            return await embed_maker.message(ctx, msg=topics_str)

        if action not in ['add', 'remove']:
            return await embed_maker.command_error(ctx, '(action)')

        if arg is None:
            return await embed_maker.command_error(ctx, '(topic/time/channel/notification role)')

        if action == 'add':
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$push': {'daily_debates.topics': arg}})
            return await embed_maker.message(
                ctx, f'`{arg}` has been added to the list of daily debate topics'
                f'\nThere are now **{len(data["daily_debates"]["topics"]) + 1}** topics on the list'
            )
        if action == 'remove':
            if arg not in data['daily_debates']['topics']:
                return await embed_maker.message(ctx, f'`{arg}` is not on the list of daily debate topics')

            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$pull': {'daily_debates.topics': arg}})
            return await embed_maker.message(
                ctx, f'`{arg}` has been removed from the list of daily debate topics'
                f'\nThere are now **{len(data["daily_debates"]["topics"]) - 1}** topics on the list'
            )

    async def start_daily_debate_timer(self, guild_id, dd_time):
        # creating first parsed_dd_time to grab timezone info
        parsed_dd_time = dateparser.parse(dd_time, settings={'RETURN_AS_TIMEZONE_AWARE': True})

        # second one for actual use
        parsed_dd_time = dateparser.parse(dd_time, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(parsed_dd_time.tzinfo)})

        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        # if time_diff is negative try again but add tomorrows

        timer_expires = round(time.time()) + time_diff_seconds - 3600  # one hour
        utils_cog = self.bot.get_cog('Utils')
        await utils_cog.create_timer(expires=timer_expires, guild_id=guild_id, event='daily_debate', extras={'time': dd_time})

    @commands.Cog.listener()
    async def on_daily_debate_timer_over(self, timer):
        guild_id = timer['guild_id']
        guild = self.bot.get_guild(int(guild_id))

        dd_time = timer['extras']['time']
        parsed_dd_time = dateparser.parse(dd_time, settings={'RETURN_AS_TIMEZONE_AWARE': True})
        parsed_dd_time = dateparser.parse(dd_time, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(parsed_dd_time.tzinfo)})
        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        data = db.server_data.find_one({'guild_id': guild.id})
        # check if there are debate topics set up
        topics = data['daily_debates']['topics']
        if not topics:
            # remind mods that a topic needs to be set up
            msg = f'Daily debate starts in {format_time.seconds(time_diff_seconds)} and no topics have been set up <@&{config.MOD_ROLE_ID}>'
            channel = guild.get_channel(data['daily_debates']['channel'])

            if channel is None:
                return

            return await channel.send(msg)
        else:
            # start final timer which sends daily debate topic
            timer_expires = round(time.time()) + time_diff_seconds  # one hour
            utils_cog = self.bot.get_cog('Utils')
            await utils_cog.create_timer(expires=timer_expires, guild_id=guild.id, event='daily_debate_final',
                                         extras={'topic': topics[0], 'channel': data['daily_debates']['channel'],
                                                 'role': data['daily_debates']['role'], 'time': data['daily_debates']['time']})

    @commands.Cog.listener()
    async def on_daily_debate_final_timer_over(self, timer):
        guild_id = timer['guild_id']
        guild = self.bot.get_guild(int(guild_id))

        topic = timer['extras']['topic']
        dd_time = timer['extras']['time']
        dd_channel_id = timer['extras']['channel']
        dd_role_id = timer['extras']['role']

        dd_channel = discord.utils.find(lambda c: c.id == int(dd_channel_id), guild.channels)
        dd_role = discord.utils.find(lambda r: r.id == int(dd_role_id), guild.roles)

        if dd_channel is None:
            return

        message = f'Today\'s debate: **“{topic}”**'
        if dd_role:
            message += '\n\n<@{dd_role.id}>'

        await dd_channel.send(message)

        # delete used topic
        db.server_data.update_one({'guild_id': guild.id}, {'$pull': {'daily_debates.topics': topic}})

        # start daily_debate timer over
        return await self.start_daily_debate_timer(guild.id, dd_time)

    @commands.command(help='Set up reaction based reminder',
                      usage='react_remind [time before event] [message id of event announcement] [time to event and timzone]',
                      examples=['react_remind 30min 716017189093769237 8pm sunday GMT+1'], clearance='Mod', cls=command.Command)
    async def react_remind(self, ctx, remind_time=None, announcement_id=None, *, to_event=None):
        if remind_time is None:
            return await embed_maker.command_error(ctx)

        parsed_remind_time = format_time.parse(remind_time)
        if parsed_remind_time is None:
            return await embed_maker.command_error(ctx, '[time before event]')

        if announcement_id is None or not announcement_id.isdigit():
            return await embed_maker.command_error(ctx, '[message id of event announcement]')

        announcement_msg = await ctx.channel.fetch_message(int(announcement_id))
        if announcement_msg is None:
            return await embed_maker.command_error(ctx, '[message id of event announcement]')

        if to_event is None:
            return await embed_maker.command_error(ctx, '[time to event]')

        tz = dateparser.parse(to_event, settings={'RETURN_AS_TIMEZONE_AWARE': True})

        if tz is None:
            return await embed_maker.command_error(ctx, '[time to event]')

        parsed_to_event = dateparser.parse(to_event, settings={'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(tz.tzinfo)})
        if parsed_to_event < datetime.datetime.now(tz.tzinfo):
            parsed_to_event = dateparser.parse(to_event, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(tz.tzinfo)})

        if parsed_to_event is None:
            return await embed_maker.command_error(ctx, '[time to event]')

        time_diff = parsed_to_event - datetime.datetime.now(parsed_to_event.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        msg = f'React with :bell: to get a dm {format_time.seconds(parsed_remind_time)} before the event'
        remind_msg = await embed_maker.message(ctx, msg)
        await remind_msg.add_reaction('🔔')

        utils_cog = self.bot.get_cog('Utils')
        expires = round(time.time()) + time_diff_seconds - parsed_remind_time
        await utils_cog.create_timer(
            expires=expires, guild_id=ctx.guild.id, event='react_remind',
            extras={'message_id': remind_msg.id, 'channel_id': remind_msg.channel.id,
                    'announcement_id': announcement_id, 'remind_time': parsed_remind_time}
        )

    @commands.Cog.listener()
    async def on_react_remind_timer_over(self, timer):
        message_id, channel_id, announcement_id, remind_time = timer['extras'].values()
        guild_id = timer['guild_id']

        guild = self.bot.get_guild(int(guild_id))
        channel = guild.get_channel(int(channel_id))
        message = await channel.fetch_message(int(message_id))

        if message is None:
            return

        reactions = message.reactions
        users = []
        for r in reactions:
            if r.emoji == '🔔':
                users = await r.users().flatten()
                break

        if users:
            asyncio.create_task(self.notify_users(users, remind_time, guild_id, channel_id, announcement_id))

    @staticmethod
    async def notify_users(users, remind_time, guild_id, channel_id, announcement_id):
        for user in users:
            if user.bot:
                continue
            msg = f'In {format_time.seconds(remind_time)}: ' \
                  f'https://discordapp.com/channels/{guild_id}/{channel_id}/{announcement_id}'
            await user.send(msg)
            await asyncio.sleep(0.3)


    @commands.command(help='see what roles are whitelisted for an emote', usage='emote_roles [emote]',
                      examples=['emote_roles :TldrNewsUK:'], clearance='Mod', cls=command.Command)
    async def emote_roles(self, ctx, emote=None):
        if emote is None:
            return await embed_maker.command_error(ctx)

        regex = re.compile(r'<:.*:(\d*)>')
        match = re.findall(regex, emote)
        if not match:
            return await embed_maker.command_error(ctx, '[emote]')
        else:
            emoji = discord.utils.find(lambda e: e.id == int(match[0]), ctx.guild.emojis)

        if emoji.roles:
            embed = embed_maker.message(ctx, f'This emote is restricted to: {", ".join([f"<@&{r.id}>" for r in emoji.roles])}')
            return await ctx.send(embed=embed)
        else:
            embed = embed_maker.message(ctx, 'This emote is available to everyone')
            return await ctx.send(embed=embed)

    @commands.command(help='restrict an emote to specific role(s)', usage='emote_role [action] [emote] [role]',
                      examples=['emote_role add :TldrNewsUK: @Mayor', 'emote_role add :TldrNewsUK: 697184345903071265', 'emote_role remove :TldrNewsUK: Mayor'],
                      clearance='Mod', cls=command.Command)
    async def emote_role(self, ctx, action=None, emote=None, *, role=None):
        if action is None:
            return await embed_maker.command_error(ctx)

        if emote is None:
            return await embed_maker.command_error(ctx, '[emote]')

        regex = re.compile(r'<:.*:(\d*)>')
        match = re.findall(regex, emote)
        if not match:
            return await embed_maker.command_error(ctx, '[emote]')
        else:
            emoji = discord.utils.find(lambda e: e.id == int(match[0]), ctx.guild.emojis)

        if role is None:
            return await embed_maker.command_error(ctx, '[role]')

        if ctx.message.role_mentions:
            role = ctx.message.role_mentions[0]
        elif role.isdigit():
            role = discord.utils.find(lambda rl: rl.id == role, ctx.guild.roles)
        else:
            role = discord.utils.find(lambda rl: rl.name == role, ctx.guild.roles)

        if role is None:
            return await embed_maker.command_error(ctx, '[role]')

        emote_roles = emoji.roles
        if action == 'add':
            emote_roles.append(role)
            await emoji.edit(roles=emote_roles)
            await ctx.guild.fetch_emoji(emoji.id)
            return await embed_maker.message(ctx, f'<@&{role.id}> has been added to whitelisted roles of emote {emote}', colour='green')

        elif action == 'remove':
            for i, r in enumerate(emote_roles):
                if r.id == role.id:
                    emote_roles.pop(i)
                    await emoji.edit(roles=emote_roles)
                    await ctx.guild.fetch_emoji(emoji.id)
                    embed = embed_maker.message(ctx, f'<@&{role.id}> has been removed from whitelisted roles of emote {emote}', colour='green')
                    return await ctx.send(embed=embed)
            else:
                embed = embed_maker.message(ctx, f'<@&{role.id}> is not whitelisted for emote {emote}', colour='red')
                return await ctx.send(embed=embed)
        else:
            return await embed_maker.command_error(ctx, '[action]')


def setup(bot):
    bot.add_cog(Mod(bot))
