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

    @commands.command(help='Warn mods when a channel has a message spike (5 messages in a minute)',
                      usage='message_spike [#channel]', examples=['message_spike #staff'],
                      clearance='Mod', cls=command.Command)
    async def message_spike(self, ctx, channel=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        if not ctx.message.channel_mentions:
            return await embed_maker.command_error(ctx, '[#channel]')

        channel_obj = ctx.message.channel_mentions[0]
        db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'message_spike.channel': channel_obj.id}})

        return await embed_maker.message(ctx, f'Message spike warning channel has been set to <#{channel_obj.id}>')

    @commands.command(help='Daily debate scheduler', usage='dailydebates (action) (arg)',
                      clearance='Mod', cls=command.Command,
                      examples=['dailydebates', 'dailydebates add is TLDR ross mega cool?',
                                'dailydebates remove is TldR roos mega cool?', 'dailydebates set_time 2pm GMT',
                                'dailydebates set_channel #daily-debates', 'dailydebates set_role Debaters',
                                'dailydebates set_poll_channel #daily-debate-voting',
                                'dailydebates set_poll_options -i 3 -o burger, pizza, pasta'])
    async def dailydebates(self, ctx, action=None, *, arg=None):
        data = db.server_data.find_one({'guild_id': ctx.guild.id})
        if 'daily_debates' not in data:
            data = self.bot.add_collections(ctx.guild.id, 'server_data')

        if action is None:
            # List currently set up daily debate topics
            topics = data['daily_debates']['topics']
            if not topics:
                topics_str = f'Currently there are no debate topics set up'
            else:
                # generate topics string
                topics_str = '**Topics:**\n'
                for i, topic in enumerate(topics):
                    options = []
                    if isinstance(topic, dict):
                        options = topic['poll_options']
                        topic = topic['topic']
                    topics_str += f'**{i + 1}:** {topic}\n'
                    if options:
                        topics_str += '**Poll Options:**' + ' |'.join([f' `{o}`' for i, o in enumerate(options)]) + '\n'

            return await embed_maker.message(ctx, msg=topics_str)

        if arg is None:
            return await embed_maker.command_error(ctx, '(topic/time/channel/notification role)')

        if action == 'set_time':
            parsed_arg_time = dateparser.parse(
                arg, settings={'RETURN_AS_TIMEZONE_AWARE': True}
            )
            if not parsed_arg_time:
                return await embed_maker.message(ctx, 'Invalid time', colour='red')

            parsed_dd_time = dateparser.parse(arg, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(parsed_arg_time.tzinfo)})
            time_diff = parsed_dd_time - datetime.datetime.now(parsed_arg_time.tzinfo)
            time_diff_seconds = round(time_diff.total_seconds())

            if time_diff_seconds < 0:
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

        if action == 'set_poll_channel':
            if not ctx.message.channel_mentions:
                return await embed_maker.message(ctx, 'Invalid channel mention', colour='red')

            channel_id = ctx.message.channel_mentions[0].id
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'daily_debates.poll_channel': channel_id}})
            return await embed_maker.message(ctx, f'Daily debate polls will now be sent every day to <#{channel_id}>')

        if action == 'set_poll_options':
            def parse_args(args):
                result = {'i': '', 'o': []}
                split_args = filter(None, args.split('-'))
                for a in split_args:
                    tup = tuple(map(str.strip, a.split(' ', 1)))
                    if len(tup) <= 1:
                        continue
                    key, value = tup
                    result[key] = value

                if result['o']:
                    result['o'] = [o.strip() for o in result['o'].split(',')]

                return result

            args = parse_args(arg)
            index = args['i']
            options = args['o']

            if not index or not index.isdigit():
                return await embed_maker.message(ctx, 'invalid index arg', colour='red')
            if not options:
                return await embed_maker.message(ctx, 'invalid options arg', colour='red')
            if len(options) < 2:
                return await embed_maker.message(ctx, 'not enough options set', colour='red')
            if len(options) > 9:
                return await embed_maker.message(ctx, 'Too many poll options set', colour='red')

            index = int(index)

            topics = data['daily_debates']['topics']
            if len(topics) < index:
                return await embed_maker.message(ctx, 'index out of range', colour='red')

            topic = topics[index - 1]
            if isinstance(topic, dict):
                topic = topic['topic']

            new_topic_obj = {
                'topic': topic,
                'poll_options': options
            }
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {f'daily_debates.topics.{index - 1}': new_topic_obj}})
            options_str = ' |'.join([f' `{o}`' for i, o in enumerate(options)])
            if isinstance(topic, dict):
                topic = topic['topic']
            return await embed_maker.message(ctx, f'Along with the daily debate: **"{topic}"**\nwill be sent a poll with these options: {options_str}')

        if action == 'set_role':
            role = discord.utils.find(lambda r: r.name.lower() == arg.lower(), ctx.guild.roles)
            if not role:
                return await embed_maker.message(ctx, 'Invalid role name', colour='red')

            role_id = role.id
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'daily_debates.role': role_id}})
            return await embed_maker.message(ctx, f'Daily debates will now be announced every day to <@&{role_id}>')

        # check if time has been set up, if not, inform user
        if not data['daily_debates']['time']:
            err = f'Time has not been set yet, i dont know when to send the message\n' \
                  f'Set time with `{config.PREFIX}dailydebates set_time [time]` e.g. `{config.PREFIX}dailydebates set_time 2pm GMT+1`'
            return await embed_maker.message(ctx, err, colour='red')

        # check if channel has been set up, if not, inform user
        if not data['daily_debates']['channel']:
            err = f'Channel has not been set yet, i dont know where to send the message\n' \
                  f'Set time with `{config.PREFIX}dailydebates set_channel [#channel]` e.g. `{config.PREFIX}dailydebates set_channel #daily-debates`'
            return await embed_maker.message(ctx, err, colour='red')

        # check for active timer
        timer_data = db.timers.find_one({'guild_id': ctx.guild.id})
        daily_debate_timer = [timer for timer in timer_data['timers'] if timer['event'] == 'daily_debate' or timer['event'] == 'daily_debate_final']
        if not daily_debate_timer:
            await self.start_daily_debate_timer(ctx.guild.id, data['daily_debates']['time'])

        if action not in ['add', 'remove', 'insert']:
            return await embed_maker.command_error(ctx, '(action)')

        if action == 'insert':
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$push': {'daily_debates.topics': {'$each': [arg], '$position': 0}}})
            return await embed_maker.message(
                ctx, f'`{arg}` has been inserted into first place in the list of daily debate topics'
                     f'\nThere are now **{len(data["daily_debates"]["topics"]) + 1}** topics on the list'
            )

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

        timer_expires = round(time.time()) + time_diff_seconds - 3600  # one hour
        utils_cog = self.bot.get_cog('Utils')
        await utils_cog.create_timer(expires=timer_expires, guild_id=guild_id, event='daily_debate', extras={})

    @commands.Cog.listener()
    async def on_daily_debate_timer_over(self, timer):
        guild_id = timer['guild_id']
        guild = self.bot.get_guild(int(guild_id))

        dd_time = timer['expires'] + 3600

        data = db.server_data.find_one({'guild_id': guild.id})
        # check if there are debate topics set up
        topics = data['daily_debates']['topics']
        if not topics:
            # remind mods that a topic needs to be set up
            msg = f'Daily debate starts in {format_time.seconds(dd_time)} and no topics have been set up <@&{config.MOD_ROLE_ID}>'
            channel = guild.get_channel(data['daily_debates']['channel'])

            if channel is None:
                return

            return await channel.send(msg)
        else:
            daily_debates = data['daily_debates']
            channel = daily_debates['channel']
            role = daily_debates['role']
            time = daily_debates['time']
            if 'poll_channel' in daily_debates:
                poll_channel = daily_debates['poll_channel']
            else:
                poll_channel = ''

            # start final timer which sends daily debate topic
            timer_expires = dd_time
            utils_cog = self.bot.get_cog('Utils')
            await utils_cog.create_timer(
                expires=timer_expires, guild_id=guild.id, event='daily_debate_final',
                extras={'topic': topics[0], 'channel': channel, 'role': role, 'time': time, 'poll_channel': poll_channel
                        })

    @commands.Cog.listener()
    async def on_daily_debate_final_timer_over(self, timer):
        guild_id = timer['guild_id']
        guild = self.bot.get_guild(int(guild_id))

        topic = timer['extras']['topic']
        if isinstance(topic, dict):
            poll_options = topic['poll_options']
            topic = topic['topic']
        else:
            poll_options = []

        dd_time = timer['extras']['time']
        dd_channel_id = timer['extras']['channel']
        dd_role_id = timer['extras']['role']
        dd_poll_channel_id = timer['extras']['poll_channel']

        dd_channel = discord.utils.find(lambda c: c.id == int(dd_channel_id), guild.channels)
        dd_role = discord.utils.find(lambda r: r.id == int(dd_role_id), guild.roles)

        if dd_channel is None:
            return

        message = f'Today\'s debate: **“{topic}”**'
        if dd_role:
            message += f'\n\n<@&{dd_role.id}>'

        msg = await dd_channel.send(message)

        # delete used topic
        db.server_data.update_one({'guild_id': guild.id}, {'$pull': {'daily_debates.topics': topic}})

        # change channel topic
        await dd_channel.edit(topic=f"{topic}")

        # unpin old topic message
        pins = [pin for pin in await dd_channel.pins() if pin.author.id == self.bot.user.id]
        if pins:
            last_pin = pins[0]
            await last_pin.unpin()

        # pin new topic message
        await msg.pin()

        # send poll to polls channel if its set
        if dd_poll_channel_id:
            if not poll_options:
                poll_emotes = ['👍', '👎', '😐']
                poll_options = ['Yes', 'No', 'Neutral']
            else:
                all_num_emotes = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
                poll_emotes = all_num_emotes[:len(poll_options)]

            dd_poll_channel = discord.utils.find(lambda c: c.id == int(dd_poll_channel_id), guild.channels)

            description = f'**"{topic}"**\n'
            colour = config.EMBED_COLOUR
            embed = discord.Embed(colour=colour, description=description, timestamp=datetime.datetime.now())
            embed.set_author(name='Daily Debate Poll')
            embed.set_footer(text='Started at', icon_url=guild.icon_url)

            description += '\n'.join(f'\n{e} | **{o}**' for e, o in zip(poll_emotes, poll_options))
            embed.description = description

            poll_msg = await dd_poll_channel.send(embed=embed)
            for e in poll_emotes:
                await poll_msg.add_reaction(e)

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

    @commands.command(help='Grant users access to commands that aren\'t available to users',
                      usage='command_access [member/role] [action] [command]', clearance='Admin', cls=command.Command,
                      examples=['command_access @Hattyot add poll', 'command_access Mayor remove anon_poll'])
    async def command_access(self, ctx, src=None, action=None, cmd=None):
        if src is None:
            return await embed_maker.command_error(ctx)

        member = self.get_member(ctx, src)
        role = discord.utils.find(lambda r: r.name == src, ctx.guild.roles)
        if role and member is None:
            mr = 'roles'
            src = role
        elif member and role is None:
            mr = 'users'
            src = member
        else:
            return await embed_maker.command_error(ctx, '[member/role]')

        data = db.server_data.find_one({'guild_id': ctx.guild.id})
        if mr not in data:
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {mr: {}}})
            data[mr] = {}

        if str(src.id) not in data[mr]:
            data[mr][str(src.id)] = []

        if action is None and cmd is None:
            special_access = data[mr][str(src.id)]
            if not special_access:
                special_access_str = f'{src} has not special access to commmands'
            else:
                special_access_str = f'{src} has special access to: ' + ' '.join([f'|`{cmd}`|' for cmd in special_access])

            return await embed_maker.message(ctx, special_access_str)

        if action not in ['add', 'remove']:
            return await embed_maker.command_error(ctx, '[action]')

        if cmd is None or self.bot.get_command(cmd) is None:
            return await embed_maker.command_error(ctx, '[command]')

        cmd_obj = self.bot.get_command(cmd)

        if action == 'add':
            if cmd in data[mr][str(src.id)]:
                return await embed_maker.message(ctx, f'{src} already has been given access to that command', colour='red')

            if cmd_obj.clearance == 'Dev':
                return await embed_maker.message(ctx, 'You can not give people access to dev commands', colour='red')
            elif cmd_obj.clearance == 'Admin':
                return await embed_maker.message(ctx, 'You can not give people access to admin commands', colour='red')

            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$push': {f'{mr}.{src.id}': cmd}})

            return await embed_maker.message(ctx, f'{src} has been granted access to: `{cmd}`')

        if action == 'remove':
            if cmd not in data[mr][str(src.id)]:
                return await embed_maker.message(ctx, f'{src} does not have access to that command', colour='red')

            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$pull': {f'{mr}.{src.id}': cmd}})

            return await embed_maker.message(ctx, f'{src} no longer has access to: `{cmd}`')

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

    @staticmethod
    def get_member(ctx, source):
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
    bot.add_cog(Mod(bot))
