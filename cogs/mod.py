import discord
import re
import dateparser
import datetime
import time
import asyncio
import config
from cogs.utils import get_member, get_user_clearance
from modules import command, database, embed_maker, format_time
from discord.ext import commands

db = database.Connection()


class Mod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='add (or remove) a user to the watchlist and log all their messages to a channel. You can also add filters to ping mods when a certain thing is said',
                      examples=['watchlist add @hattyot', 'watchlist remove @hattyot', 'watchlist set_channel #watchlist', 'watchlist add_filters @hattyot filter1 | filter2'],
                      clearance='Admin', cls=command.Command, usage='watchlist [action] [user/channel] (extra)')
    async def watchlist(self, ctx, action=None, src=None, *, filters=None):
        data = db.server_data.find_one({'guild_id': ctx.guild.id})
        if 'watchlist' not in data:
            schema = {'on_list': [], 'channel_id': 0}
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'watchlist': schema}})
            data['watchlist'] = schema
        if action is None:
            on_list = data['watchlist']['on_list']
            colour = config.EMBED_COLOUR
            list_embed = discord.Embed(colour=colour, timestamp=datetime.datetime.now())
            list_embed.set_author(name='Users on the watchlist')

            on_list_str = ''
            for i, user_id in enumerate(on_list):
                user = ctx.guild.get_member(int(user_id))
                if user is None:
                    try:
                        user = await ctx.guild.fetch_member(int(user_id))
                    except:
                        db.server_data.update_one({'guild_id': ctx.guild.id}, {'$pull': {f'watchlist.on_list': user_id}})
                        continue
                on_list_str += f'`#{i + 1}` - {str(user)}'

            if not on_list_str:
                list_embed.description = 'Currently no users on the watchlist'
                return await ctx.send(embed=list_embed)
            else:
                list_embed.description = on_list_str
                return await ctx.send(embed=list_embed)

        if action not in ['add', 'remove', 'add_filters', 'set_channel']:
            return await embed_maker.command_error(ctx)

        if src is None:
            return await embed_maker.command_error(ctx)

        server_data = db.server_data.find_one({'guild_id': ctx.guild.id})
        on_list = server_data['watchlist']['on_list']

        if action == 'add':
            member = await get_member(ctx, self.bot, src)
            if member is None:
                return await embed_maker.message(ctx, 'Invalid member', colour='red')

            if member.id in on_list:
                return await embed_maker.message(ctx, 'User is already on the list', colour='red')

            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$push': {'watchlist.on_list': member.id}})
            return await embed_maker.message(ctx, f'<@{member.id}> has been added to the watchlist', colour='green')

        elif action == 'remove':
            member = await get_member(ctx, self.bot, src)
            if member is None:
                return await embed_maker.message(ctx, 'Invalid member', colour='red')

            if member.id not in on_list:
                return await embed_maker.message(ctx, 'User is not on the list', colour='red')

            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$pull': {'watchlist.on_list': member.id}})
            if str(member.id) in filters:
                db.server_data.update_one({'guild_id': ctx.guild.id}, {'$unset': {f'watchlist.filters.{member.id}': ''}})

            return await embed_maker.message(ctx, f'<@{member.id}> has been removed from the watchlist', colour='green')

        elif action == 'add_filters':
            member = await get_member(ctx, self.bot, src)
            if member is None:
                return await embed_maker.message(ctx, 'Invalid member', colour='red')

            if member.id not in on_list:
                return await embed_maker.message(ctx, 'User is not on the list', colour='red')

            if filters is None:
                return await embed_maker.command_error('Filters missing')

            all_filters = server_data['watchlist']['filters']
            split_filters = [f.strip() for f in filters.split('|')]
            if all_filters:
                split_filters += all_filters

            db.server_data.update({'guild_id': ctx.guild.id}, {'$set': {f'watchlist.filters.{member.id}': split_filters}})
            return await embed_maker.message(ctx, f'if member mentions {" or ".join(f"`{f}`" for f in split_filters)} mods will be @\'d', colour='green')

        elif action == 'set_channel':
            if not ctx.message.channel_mentions:
                return await embed_maker.message(ctx, 'Invalid channel', colour='red')
            channel = ctx.message.channel_mentions[0]
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'watchlist.channel_id': channel.id}})

            return await embed_maker.message(ctx, f'The watchlist channel has been set to: <#{channel.id}>', colour='green')

    @commands.command(help='Warn mods when a channel has a message spike (5 messages in a minute)',
                      usage='message_spike [#channel/disable]', examples=['message_spike #staff', 'message_spike disable'],
                      clearance='Dev', cls=command.Command)
    async def message_spike(self, ctx, channel=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        if channel == 'disable':
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$unset': {'message_spike': ''}})
            return await embed_maker.message(ctx, 'Message spike warnings have been disabled')

        if not ctx.message.channel_mentions:
            return await embed_maker.command_error(ctx, '[#channel]')

        channel_obj = ctx.message.channel_mentions[0]
        db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'message_spike.channel': channel_obj.id}})

        return await embed_maker.message(ctx, f'Message spike warning channel has been set to <#{channel_obj.id}>')

    @commands.command(help='Daily debate scheduler', usage='dailydebates (action) (arg) -ta (topic author)',
                      clearance='Mod', cls=command.Command, aliases=['dd', 'dailydebate'],
                      examples=['dailydebates', 'dailydebates add is TLDR ross mega cool? -ta Hattyot',
                                'dailydebates remove is TldR roos mega cool?', 'dailydebates set_time 2pm GMT',
                                'dailydebates set_channel #daily-debates', 'dailydebates set_role Debaters',
                                'dailydebates set_poll_channel #daily-debate-voting',
                                'dailydebates set_poll_options -i 3 -o burger | pizza | pasta'])
    async def dailydebates(self, ctx, action=None, *, arg=None):
        data = db.server_data.find_one({'guild_id': ctx.guild.id})
        timer_data = db.timers.find_one({'guild_id': ctx.guild.id})
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
                    topic_author_id = 0
                    topic_author = 0
                    if isinstance(topic, dict):
                        if 'poll_options' in topic:
                            options = topic['poll_options']
                        if 'topic_author' in topic:
                            topic_author_id = topic['topic_author']
                            try:
                                topic_author = await self.bot.fetch_user(int(topic_author_id))
                            except:
                                topic_author_id = 0

                        topic = topic['topic']

                    topics_str += f'**{i + 1}:** {topic}\n'
                    if options:
                        topics_str += '**Poll Options:**' + ' |'.join([f' `{o}`' for i, o in enumerate(options)]) + '\n'
                    if topic_author:
                        topics_str += f'**Topic Author:** {str(topic_author)}\n'

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
                _args = list(filter(lambda a: bool(a), re.split(r' ?-([i|o|]) ', args)))
                split_args = []
                for i in range(int(len(_args) / 2)):
                    split_args.append(f'{_args[i + (i * 1)]} {_args[i + (i + 1)]}')

                for a in split_args:
                    tup = tuple(map(str.strip, a.split(' ', 1)))
                    if len(tup) <= 1:
                        continue
                    key, value = tup
                    result[key] = value

                if result['o']:
                    result['o'] = [o.strip() for o in result['o'].split('|')]

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
            # check if final timer is active, if it is change to these poll options
            dd_timer = [timer for timer in timer_data['timers'] if timer['event'] == 'daily_debate_final']
            if dd_timer:
                db.timers.update_one({'guild_id': ctx.guild.id, 'timers.extras.topic': dd_timer[0]['extras']['topic']}, {'$set': {f'timers.$.extras.topic': new_topic_obj}})

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
        daily_debate_timer = [timer for timer in timer_data['timers'] if timer['event'] == 'daily_debate' or timer['event'] == 'daily_debate_final']
        if not daily_debate_timer:
            await self.start_daily_debate_timer(ctx.guild.id, data['daily_debates']['time'])

        if action not in ['add', 'remove', 'insert']:
            return await embed_maker.command_error(ctx, '(action)')

        if action == 'insert':
            args = arg.split(' -ta ')
            if len(args) > 1:
                ta_arg = args[1].strip()
                member = await get_member(ctx, self.bot, ta_arg)
                if member is None:
                    return await embed_maker.message(ctx, 'Invalid topic author', colour='red')
                elif isinstance(member, str):
                    return await embed_maker.message(ctx, member, colour='red')

                else:
                    topic_obj = {
                        'topic': args[0].strip(),
                        'topic_author': member.id
                    }
                    push = topic_obj
                    arg = args[0]
            else:
                push = arg

            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$push': {'daily_debates.topics': {'$each': [push], '$position': 0}}})
            # check if final timer is active, if it is change to this topic
            dd_timer = [timer for timer in timer_data['timers'] if timer['event'] == 'daily_debate_final']
            if dd_timer:
                db.timers.update_one({'guild_id': ctx.guild.id, 'timers.extras.topic': dd_timer[0]['extras']['topic']}, {'$set': {f'timers.$.extras.topic': push}})

            return await embed_maker.message(
                ctx, f'`{arg}` has been inserted into first place in the list of daily debate topics'
                     f'\nThere are now **{len(data["daily_debates"]["topics"]) + 1}** topics on the list'
            )

        if action == 'add':
            args = arg.split(' -ta ')
            if len(args) > 1:
                ta_arg = args[1].strip()
                member = await get_member(ctx, self.bot, ta_arg)
                if member is None:
                    return await embed_maker.message(ctx, 'Invalid topic author', colour='red')
                elif isinstance(member, str):
                    return await embed_maker.message(ctx, member, colour='red')

                else:
                    topic_obj = {
                        'topic': args[0].strip(),
                        'topic_author': member.id
                    }
                    push = topic_obj
                    arg = args[0]
            else:
                push = arg

            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$push': {'daily_debates.topics': push}})
            return await embed_maker.message(
                ctx, f'`{arg}` has been added to the list of daily debate topics'
                f'\nThere are now **{len(data["daily_debates"]["topics"]) + 1}** topics on the list'
            )
        if action == 'remove':
            if arg not in data['daily_debates']['topics']:
                topic = [t for t in data['daily_debates']['topics'] if isinstance(t, dict) and t['topic'] == arg]
                if topic:
                    pull = topic[0]
                else:
                    return await embed_maker.message(ctx, f'`{arg}` is not on the list of daily debate topics')
            else:
                pull = arg

            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$pull': {'daily_debates.topics': pull}})
            dd_timer = [timer for timer in timer_data['timers'] if timer['event'] == 'daily_debate_final']
            if dd_timer:
                db.timers.update_one({'guild_id': ctx.guild.id}, {'$pull': {f'timers': {'id': dd_timer[0]['id']}}})
                await self.start_daily_debate_timer(ctx.guild.id, data['daily_debates']['time'])

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

        now = round(time.time())
        dd_time = timer['expires'] + 3600
        tm = dd_time - now

        data = db.server_data.find_one({'guild_id': guild.id})
        # check if there are debate topics set up
        topics = data['daily_debates']['topics']
        if not topics:
            # remind mods that a topic needs to be set up
            msg = f'Daily debate starts in {format_time.seconds(tm)} and no topics have been set up <@&{config.MOD_ROLE_ID}>'
            channel = guild.get_channel(data['daily_debates']['channel'])

            if channel is None:
                return

            return await channel.send(msg)
        else:
            daily_debates = data['daily_debates']
            channel = daily_debates['channel']
            role = daily_debates['role']
            time_str = daily_debates['time']
            if 'poll_channel' in daily_debates:
                poll_channel = daily_debates['poll_channel']
            else:
                poll_channel = ''

            # start final timer which sends daily debate topic
            timer_expires = dd_time
            utils_cog = self.bot.get_cog('Utils')
            await utils_cog.create_timer(
                expires=timer_expires, guild_id=guild.id, event='daily_debate_final',
                extras={'topic': topics[0], 'channel': channel, 'role': role, 'time': time_str, 'poll_channel': poll_channel
                        })

    @commands.Cog.listener()
    async def on_daily_debate_final_timer_over(self, timer):
        guild_id = timer['guild_id']
        guild = self.bot.get_guild(int(guild_id))

        topic = timer['extras']['topic']

        poll_options = []
        topic_author_id = 0
        topic_author = 0

        if isinstance(topic, dict):
            if 'poll_options' in topic:
                poll_options = topic['poll_options']
            if 'topic_author' in topic:
                topic_author_id = topic['topic_author']
                try:
                    topic_author = await self.bot.fetch_user(int(topic_author_id))
                except:
                    topic_author_id = 0

            topic = topic['topic']

        dd_time = timer['extras']['time']
        dd_channel_id = timer['extras']['channel']
        dd_role_id = timer['extras']['role']
        dd_poll_channel_id = timer['extras']['poll_channel']

        dd_channel = discord.utils.find(lambda c: c.id == int(dd_channel_id), guild.channels)
        dd_role = discord.utils.find(lambda r: r.id == int(dd_role_id), guild.roles)

        if dd_channel is None:
            return

        message = f'Today\'s debate: **“{topic}”**'
        if topic_author:
            message += f' - Topic suggested by <@{topic_author_id}>'
        if dd_role:
            message += f'\n\n<@&{dd_role.id}>'

        msg = await dd_channel.send(message)

        # delete used topic
        db.server_data.update_one({'guild_id': guild.id}, {'$pull': {'daily_debates.topics': timer['extras']['topic']}})

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

        # award topic author boost if there is one
        if topic_author:
            boost_object = {
                'expires': round(time.time()) + (3600 * 3),
                'multiplier': 0.05
            }
            db.levels.update_one({'guild_id': int(guild_id)}, {f'$push': {f'boost.users.{topic_author_id}': boost_object}})

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

    @commands.command(help='Open a ticket for discussion', usage='open_ticket [ticket]', clearance='Mod', cls=command.Command,
                      examples=['open_ticket new mods'])
    async def open_ticket(self, ctx, *, ticket=None):
        if ticket is None:
            return await embed_maker.command_error(ctx)

        main_guild = self.bot.get_guild(config.MAIN_SERVER)
        embed_colour = config.EMBED_COLOUR
        ticket_embed = discord.Embed(colour=embed_colour, timestamp=datetime.datetime.now())
        ticket_embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        ticket_embed.set_author(name='New Ticket', icon_url=main_guild.icon_url)
        ticket_embed.add_field(name='>Opened By', value=f'<@{ctx.author.id}>', inline=False)
        ticket_embed.add_field(name='>Ticket', value=ticket, inline=False)

        ticket_category = discord.utils.find(lambda c: c.name == 'Open Tickets', ctx.guild.categories)

        if ticket_category is None:
            # get all staff roles
            staff_roles = filter(lambda r: r.permissions.manage_messages, ctx.guild.roles)

            # staff roles can read channels in category, users cant
            overwrites = dict.fromkeys(staff_roles, discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True))
            overwrites[ctx.guild.default_role] = discord.PermissionOverwrite(read_messages=False)

            ticket_category = await ctx.guild.create_category(name='Open Tickets', overwrites=overwrites)

        today = datetime.date.today()
        date_str = today.strftime('%Y-%m-%d')
        ticket_channel = await ctx.guild.create_text_channel(f'{date_str}-{ctx.author.name}', category=ticket_category)
        await ticket_channel.send(embed=ticket_embed)

    @commands.command(help='Give user access to ticket', usage='get_user', examples=['get_user'],
                      clearance='Mod', cls=command.Command)
    async def get_user(self, ctx, member=None):
        if member is None:
            return await embed_maker.command_error(ctx)

        member = await get_member(ctx, self.bot, member)
        if member is None:
            return await embed_maker.command_error(ctx, '[member]')
        elif isinstance(member, str):
            return await embed_maker.message(ctx, member, colour='red')

        ticket_category = discord.utils.find(lambda c: c.name == 'Open Tickets', ctx.guild.categories)
        if ctx.channel.category != ticket_category:
            return await embed_maker.message(ctx, 'Invalid ticket channel')

        # check if user already has access to channel
        permissions = ctx.channel.permissions_for(member)
        if permissions.read_messages:
            return await embed_maker.message(ctx, 'User already has access to this channel')

        await ctx.channel.set_permissions(member, read_messages=True, send_messages=True, read_message_history=True)
        return await ctx.channel.send(f'<@{member.id}>')

    @commands.command(help='Grant users access to commands that aren\'t available to users or take away their access to a command',
                      usage='command_access [action/(member/role)] [command] [member/role]', clearance='Admin', cls=command.Command,
                      examples=['command_access give poll @Hattyot', 'command_access neutral anon_poll Mayor', 'command_access take rep Hattyot', 'command_access Hatty'])
    async def command_access(self, ctx, action=None, cmd=None, *, member=None):
        if action is None:
            return await embed_maker.command_error(ctx)

        async def member_or_role(src):
            if src is None:
                return '[member/role]', None
            member = await get_member(ctx, self.bot, src)
            role = discord.utils.find(lambda r: r.name.lower() == src.lower(), ctx.guild.roles)
            if role and member is None:
                type = 'roles'
                obj = role
            elif member and role is None:
                type = 'users'
                obj = member
            else:
                return '[member/role]', None

            return type, obj

        data = db.server_data.find_one({'guild_id': ctx.guild.id})

        # check if action is member or role
        type, obj = None, None
        if action not in ['give', 'neutral', 'take']:
            type, obj = await member_or_role(action)

        if obj is None:
            type, obj = await member_or_role(member)
            if obj is None:
                if action not in ['give', 'neutral', 'take']:
                    return await embed_maker.command_error(ctx, '[action/(member/role)]')
                if cmd is None:
                    return await embed_maker.command_error(ctx, '[command]')
                return await embed_maker.command_error(ctx, type)
        else:
            access_given = []
            access_taken = []
            if 'commands' in data and 'users' in data['commands']['access'] and 'roles' in data['commands']['access']:
                command_data = data['commands']['access']
                # check if user has special access
                cmd_access_list = []
                if str(ctx.author.id) in command_data['users']:
                    cmd_access_list += [c for c in command_data['users'][str(ctx.author.id)]]
                if set([str(r.id) for r in ctx.author.roles]) & set(command_data['roles'].keys()):
                    cmd_access_list += [command_data['roles'][c] for c in command_data['roles'] if c in [str(r.id) for r in ctx.author.roles]]

                access_given = [c['command'] for c in cmd_access_list if c['type'] == 'give']
                access_taken = [c['command'] for c in cmd_access_list if c['type'] == 'take']

            access_given_str = ' |'.join([f' `{c}`' for c in access_given])
            access_taken_str = ' |'.join([f' `{c}`' for c in access_taken])
            t = 'user' if type == 'users' else 'role'
            if not access_given_str:
                access_given_str = f'{t} has no special access to commands'
            if not access_taken_str:
                access_taken_str = f'No commands have been taken away from this {t}'

            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(colour=embed_colour, timestamp=datetime.datetime.now(), description='Command Access')
            embed.add_field(name='>Access Given', value=access_given_str, inline=False)
            embed.add_field(name='>Access Taken', value=access_taken_str, inline=False)
            embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)

            return await ctx.send(embed=embed)

        data = db.server_data.find_one({'guild_id': ctx.guild.id})
        if 'commands' not in data:
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'commands': {}}})
            data['commands'] = {}

        command_data = data['commands']['access']
        if type not in command_data:
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {f'commands.{type}': {}}})
            command_data[type] = {}

        if str(obj.id) not in command_data[type]:
            command_data[type][str(obj.id)] = []

        if action not in ['give', 'neutral', 'take']:
            return await embed_maker.message(ctx, 'invalid [action/(member/role)]', colour='red')

        cmd_obj = self.bot.get_command(cmd)

        if cmd_obj is None:
            return await embed_maker.message(ctx, f'{cmd} is not a valid command', colour='red')

        if cmd_obj.clearance == 'Dev':
            return await embed_maker.message(ctx, 'You can not give people access to dev commands', colour='red')
        elif cmd_obj.clearance == 'Admin':
            return await embed_maker.message(ctx, 'You can not give people access to admin commands', colour='red')

        can_access_command = True

        if type == 'users':
            author_perms = ctx.author.guild_permissions
            member_perms = obj.guild_permissions
            if author_perms <= member_perms:
                return await embed_maker.message(ctx, 'You can not manage command access of people who have the same or more permissions as you')
            # can user run command
            member_clearance = get_user_clearance(obj)
            if cmd_obj.clearance not in member_clearance:
                can_access_command = False
        elif type == 'roles':
            top_author_role = ctx.author.roles[-1]
            top_author_role_perms = top_author_role.permissions
            role_perms = obj.permissions
            if top_author_role_perms <= role_perms:
                return await embed_maker.message(ctx, 'You can not manage command access of a role which has the same or more permissions as you')

        if action == 'give':
            if can_access_command and type == 'users':
                return await embed_maker.message(ctx, 'User already has access to that command', colour='red')

            cmds = [c['command'] for c in command_data[type][str(obj.id)] if c['type'] == 'give']
            if cmd in cmds:
                return await embed_maker.message(ctx, f'{obj} already has been given access to that command', colour='red')

            access_dict = {
                'command': cmd,
                'type': 'give'
            }
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$push': {f'commands.access.{type}.{obj.id}': access_dict}})

            return await embed_maker.message(ctx, f'{obj} has been granted access to: `{cmd}`')

        elif action == 'neutral':
            cmds = [c['command'] for c in command_data[type][str(obj.id)]]
            if cmd not in cmds:
                return await embed_maker.message(ctx, f'{obj} is already neutral on that command', colour='red')

            cmd_obj = [c for c in command_data[type][str(obj.id)] if c['command'] == cmd]
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$pull': {f'commands.access.{type}.{obj.id}': cmd_obj[0]}})

            return await embed_maker.message(ctx, f'{obj} is now neutral on command `{cmd}`')

        elif action == 'take':
            if not can_access_command and type == 'users':
                return await embed_maker.message(ctx, 'User already doesn\'t have access to that command', colour='red')

            cmds = [c['command'] for c in command_data[type][str(obj.id)] if c['type'] == 'take']
            if cmd in cmds:
                return await embed_maker.message(ctx, f'{obj} has had their access to that command already taken away', colour='red')

            access_dict = {
                'command': cmd,
                'type': 'take'
            }
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$push': {f'commands.access.{type}.{obj.id}': access_dict}})

            # take away command_access give if it is there
            cmds = [c['command'] for c in command_data[type][str(obj.id)] if c['type'] == 'give']
            if cmd in cmds:
                cmd_obj = [c for c in command_data[type][str(obj.id)] if c['command'] == cmd]
                db.server_data.update_one({'guild_id': ctx.guild.id}, {'$pull': {f'commands.access.{type}.{obj.id}': cmd_obj[0]}})

            return await embed_maker.message(ctx, f'{obj} will now not be able to use: `{cmd}`')

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
            return await embed_maker.message(ctx, f'This emote is restricted to: {", ".join([f"<@&{r.id}>" for r in emoji.roles])}')
        else:
            return await embed_maker.message(ctx, 'This emote is available to everyone')

    @commands.command(help='restrict an emote to specific role(s)', usage='emote_role [role] [action] [emote 1], (emote 2)...',
                      examples=['emote_role Mayor add :TldrNewsUK:, ', 'emote_role Mayor remove :TldrNewsUK: :TldrNewsUS: :TldrNewsEU:'],
                      clearance='Mod', cls=command.Command)
    async def emote_role(self, ctx, role=None, action=None, *, emotes=None):
        if role is None:
            return await embed_maker.command_error(ctx)

        if action is None or action not in ['add', 'remove']:
            return await embed_maker.command_error(ctx, '[action]')

        if emotes is None:
            return await embed_maker.command_error(ctx, '[emotes]')

        regex = re.compile(r'<:.*:(\d*)>')
        emote_list = emotes.split(' ')
        msg = None
        on_list = []
        for emote in emote_list:
            match = re.findall(regex, emote)
            if not match:
                return await embed_maker.message(ctx, 'Invalid emote', colour='red')
            else:
                emoji = discord.utils.find(lambda e: e.id == int(match[0]), ctx.guild.emojis)

            if ctx.message.role_mentions:
                role = ctx.message.role_mentions[0]
            elif role.isdigit():
                role = discord.utils.find(lambda rl: rl.id == role, ctx.guild.roles)
            else:
                role = discord.utils.find(lambda rl: rl.name == role, ctx.guild.roles)

            if role is None:
                return await embed_maker.command_error(ctx, '[role]')

            emote_roles = emoji.roles
            if role in emote_roles:
                on_list.append(emote)
                continue

            if action == 'add':
                emote_roles.append(role)
                await emoji.edit(roles=emote_roles)
                await ctx.guild.fetch_emoji(emoji.id)
                msg = f'<@&{role.id}> has been added to whitelisted roles of emotes {emotes}'

            elif action == 'remove':
                for i, r in enumerate(emote_roles):
                    if r.id == role.id:
                        emote_roles.pop(i)
                        await emoji.edit(roles=emote_roles)
                        await ctx.guild.fetch_emoji(emoji.id)
                        msg = f'<@&{role.id}> has been removed from whitelisted roles of emotes {emotes}'
                else:
                    msg = f'<@&{role.id}> is not whitelisted for emote {emote}'
            else:
                return await embed_maker.command_error(ctx, '[action]')

        if msg:
            return await embed_maker.message(ctx, msg, colour='green')
        elif on_list:
            return await embed_maker.message(ctx, 'That role already has access to all those emotes', colour='red')
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
