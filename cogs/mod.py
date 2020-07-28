import discord
import re
import dateparser
import datetime
import config
from time import time
from bson import ObjectId
from cogs.utils import get_member, get_user_clearance
from modules import command, database, embed_maker, format_time
from discord.ext import commands

db = database.Connection()


class Mod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='add (or remove) a user to the watchlist and log all their messages to a channel. You can also add filters to ping mods when a certain thing is said',
                      examples=['watchlist add @hattyot', 'watchlist remove @hattyot', 'watchlist set_channel #watchlist', 'watchlist add_filters @hattyot filter1 | filter2'],
                      clearance='Admin', cls=command.Command, usage='watchlist [action] [user/channel] (filters)')
    async def watchlist(self, ctx, action=None, src=None, *, filters=None):
        watchlist_data = db.watchlist_data.find_one({'guild_id': ctx.guild.id})
        if watchlist_data is None:
            watchlist_data = self.bot.add_collections(ctx.guild.id, 'watchlist_data')

        users_on_list = [d for d in db.watchlist.distinct('user_id', {'guild_id': ctx.guild.id})]
        if action is None:
            colour = config.EMBED_COLOUR
            list_embed = discord.Embed(colour=colour, timestamp=datetime.datetime.now())
            list_embed.set_author(name='Users on the watchlist')

            on_list_str = ''
            for i, user_id in enumerate(users_on_list):
                user = ctx.guild.get_member(int(user_id))
                if user is None:
                    try:
                        user = await ctx.guild.fetch_member(int(user_id))
                    except:
                        db.watchlist.find_one_and_delete({'guild_id': ctx.guild.id, 'user_id': user_id})
                        continue
                on_list_str += f'`#{i + 1}` - {str(user)}\n'
                watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': user_id}, {'filters': 1})
                if watchlist_user['filters']:
                    on_list_str += 'Filters: ' + " | ".join(f"`{f}`" for f in watchlist_user['filters'])
                on_list_str += '\n\n'

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

        if action == 'set_channel':
            if not ctx.message.channel_mentions:
                return await embed_maker.message(ctx, 'Invalid channel', colour='red')
            channel = ctx.message.channel_mentions[0]
            db.watchlist_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'channel_id': channel.id}})

            return await embed_maker.message(ctx, f'The watchlist channel has been set to: <#{channel.id}>', colour='green')

        channel_id = watchlist_data['channel_id']
        if not channel_id:
            return await embed_maker.message(ctx, 'You can\'t add users to the watchlist if you haven\'t set the watchlist channel')

        member = await get_member(ctx, self.bot, src)
        if member is None:
            return await embed_maker.message(ctx, 'Invalid member', colour='red')

        watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})

        if action == 'add':
            if watchlist_user:
                return await embed_maker.message(ctx, 'User is already on the list', colour='red')

            split_filters = [f.strip() for f in filters.split('|')] if filters else []

            watchlist_doc = {
                'guild_id': ctx.guild.id,
                'user_id': member.id,
                'filters': split_filters
            }
            db.watchlist.insert_one(watchlist_doc)

            msg = f'<@{member.id}> has been added to the watchlist'
            if split_filters:
                msg += f'\nWith these filters: {" or ".join(f"`{f}`" for f in split_filters)}'

            return await embed_maker.message(ctx, msg, colour='green')

        elif action == 'remove':
            if watchlist_user is None:
                return await embed_maker.message(ctx, 'User is not on the list', colour='red')

            db.watchlist.find_one_and_delete({'guild_id': ctx.guild.id, 'user_id': member.id})

            return await embed_maker.message(ctx, f'<@{member.id}> has been removed from the watchlist', colour='green')

        elif action == 'add_filters':
            if filters is None:
                return await embed_maker.command_error('Filters missing')

            if not watchlist_user:
                return await embed_maker.message(ctx, 'User is not on the list', colour='red')

            all_filters = watchlist_user['filters']
            split_filters = [f.strip() for f in filters.split('|')] if filters else []
            if all_filters:
                split_filters += all_filters

            return await embed_maker.message(ctx, f'if {member} mentions {" or ".join(f"`{f}`" for f in split_filters)} mods will be @\'d', colour='green')

    @commands.command(help='Daily debate scheduler', usage='dailydebates (action) (arg) -ta (topic author) -o (poll options)',
                      clearance='Mod', cls=command.Command, aliases=['dd', 'dailydebate'],
                      examples=['dailydebates', 'dailydebates add is TLDR ross mega cool? -ta Hattyot -o Yes | Double Yes',
                                'dailydebates remove 1', 'dailydebates set_time 2pm GMT',
                                'dailydebates set_channel #daily-debates', 'dailydebates set_role Debaters',
                                'dailydebates set_poll_channel #daily-debate-voting'])
    async def dailydebates(self, ctx, action=None, *, arg=None):
        daily_debates_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        if daily_debates_data is None:
            daily_debates_data = self.bot.add_collections(ctx.guild.id, 'server_data')

        if action is None:
            # List currently set up daily debate topics
            topics = daily_debates_data['topics']
            if not topics:
                topics_str = f'Currently there are no debate topics set up'
            else:
                # generate topics string
                topics_str = '**Topics:**\n'
                for i, topic_obj in enumerate(topics):
                    topic = topic_obj['topic']
                    topic_author_id = topic_obj['topic_author_id']
                    topic_options = topic_obj['topic_options']
                    topic_author = await ctx.guild.fetch_member(int(topic_author_id)) if topic_author_id else None

                    topics_str += f'`#{i + 1}`: {topic}\n'
                    if topic_options:
                        topics_str += '**Poll Options:**' + ' |'.join([f' `{o}`' for i, o in enumerate(topic_options)]) + '\n'
                    if topic_author:
                        topics_str += f'**Topic Author:** {str(topic_author)}\n'

            dd_time = daily_debates_data['time'] if daily_debates_data['time'] else 'Not set'
            dd_channel = f'<#{daily_debates_data["channel_id"]}>' if daily_debates_data['channel_id'] else 'Not set'
            dd_poll_channel = f'<#{daily_debates_data["poll_channel_id"]}>' if daily_debates_data['poll_channel_id'] else 'Not set'
            dd_role = f'<@&{daily_debates_data["role_id"]}>' if daily_debates_data['role_id'] else 'Not set'

            embed = discord.Embed(title='Daily Debates', colour=config.EMBED_COLOUR, description=topics_str, timestamp=datetime.datetime.now())
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            embed.add_field(name='Attributes', value=f'Time: {dd_time}\nChannel: {dd_channel}\nPoll Channel: {dd_poll_channel}\nRole: {dd_role}')

            return await ctx.send(embed=embed)

        if arg is None:
            return await embed_maker.command_error(ctx, '(topic/time/channel/notification role)')

        if action == 'set_time':
            parsed_arg_time = dateparser.parse(arg, settings={'RETURN_AS_TIMEZONE_AWARE': True})
            if not parsed_arg_time:
                return await embed_maker.message(ctx, 'Invalid time', colour='red')

            parsed_dd_time = dateparser.parse(arg, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(parsed_arg_time.tzinfo)})
            time_diff = parsed_dd_time - datetime.datetime.now(parsed_arg_time.tzinfo)
            time_diff_seconds = round(time_diff.total_seconds())

            if time_diff_seconds < 0:
                return await embed_maker.message(ctx, 'Invalid time', colour='red')

            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'time': arg}})
            await embed_maker.message(ctx, f'Daily debates will now be announced every day at {arg}')

            # cancel old timer if active
            daily_debate_timer = db.timers.find_one({'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})
            if daily_debate_timer:
                db.timers.find_one_and_delete({'_id': ObjectId(daily_debate_timer['_id'])})
                return await self.start_daily_debate_timer(ctx.guild.id, arg)
            else:
                return

        if action == 'set_channel':
            if not ctx.message.channel_mentions:
                return await embed_maker.message(ctx, 'Invalid channel mention', colour='red')

            channel_id = ctx.message.channel_mentions[0].id
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'channel_id': channel_id}})
            return await embed_maker.message(ctx, f'Daily debates will now be announced every day at <#{channel_id}>')

        if action == 'set_poll_channel':
            if arg == 'None':
                db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': 0}})
                return await embed_maker.message(ctx, f'daily debates poll channel has been disabled')

            if not ctx.message.channel_mentions:
                return await embed_maker.message(ctx, 'Invalid channel mention', colour='red')

            channel_id = ctx.message.channel_mentions[0].id
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'poll_channel_id': channel_id}})
            return await embed_maker.message(ctx, f'Daily debate polls will now be sent every day to <#{channel_id}>')

        if action == 'set_role':
            if arg == 'None':
                db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': 0}})
                return await embed_maker.message(ctx, f'daily debates role has been disabled')

            role = discord.utils.find(lambda r: r.name.lower() == arg.lower(), ctx.guild.roles)
            if not role:
                return await embed_maker.message(ctx, 'Invalid role name', colour='red')

            role_id = role.id
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': role_id}})
            return await embed_maker.message(ctx, f'Daily debates will now be announced every day to <@&{role_id}>')

        # check if time has been set up, if not, inform user
        if not daily_debates_data['time']:
            err = f'Time has not been set yet, i dont know when to send the message\n' \
                  f'Set time with `{config.PREFIX}dailydebates set_time [time]` e.g. `{config.PREFIX}dailydebates set_time 2pm GMT+1`'
            return await embed_maker.message(ctx, err, colour='red')

        # check if channel has been set up, if not, inform user
        if not daily_debates_data['channel_id']:
            err = f'Channel has not been set yet, i dont know where to send the message\n' \
                  f'Set time with `{config.PREFIX}dailydebates set_channel [#channel]` e.g. `{config.PREFIX}dailydebates set_channel #daily-debates`'
            return await embed_maker.message(ctx, err, colour='red')

        # check for active timer
        daily_debate_timer = db.timers.find_one({'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})

        if not daily_debate_timer:
            await self.start_daily_debate_timer(ctx.guild.id, daily_debates_data['time'])

        if action not in ['add', 'remove', 'insert']:
            return await embed_maker.command_error(ctx, '(action)')

        if action == 'remove':
            if not arg.isdigit():
                return await embed_maker.message(ctx, 'Invalid index', colour='red')

            index = int(arg)
            if index > len(daily_debates_data['topics']):
                return await embed_maker.message(ctx, 'Index too big', colour='red')

            index = int(arg)
            if index < 1:
                return await embed_maker.message(ctx, 'Index cant be smaller than 1', colour='red')

            topic_to_delete = daily_debates_data['topics'][index - 1]
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$pull': {'topics': topic_to_delete}})

            return await embed_maker.message(
                ctx, f'`{topic_to_delete["topic"]}` has been removed from the list of daily debate topics'
                f'\nThere are now **{len(daily_debates_data["topics"]) - 1}** topics on the list'
            )

        args = self.parse_dd_args(arg)
        print(args)
        topic = args['t']
        topic_author_arg = args['ta']
        topic_options_arg = args['o']
        if topic_author_arg:
            member = await get_member(ctx, self.bot, topic_author_arg)
            if member is None:
                return await embed_maker.message(ctx, 'Invalid topic author', colour='red')
            elif isinstance(member, str):
                return await embed_maker.message(ctx, member, colour='red')
            topic_author_arg = member.id

        topic_obj = {
            'topic': topic,
            'topic_author_id': topic_author_arg,
            'topic_options': topic_options_arg
        }

        if action == 'insert':
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$push': {'topics': {'$each': [topic_obj], '$position': 0}}})

            return await embed_maker.message(
                ctx, f'`{topic}` has been inserted into first place in the list of daily debate topics'
                     f'\nThere are now **{len(daily_debates_data["topics"]) + 1}** topics on the list'
            )

        if action == 'add':
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$push': {'topics': topic_obj}})

            return await embed_maker.message(
                ctx, f'`{topic}` has been added to the list of daily debate topics'
                f'\nThere are now **{len(daily_debates_data["topics"]) + 1}** topics on the list'
            )

    @staticmethod
    def parse_dd_args(args):
        result = {'t': '', 'ta': '', 'o': []}
        _args = list(filter(lambda a: bool(a), re.split(r' ?-(ta|o) ', args)))
        result['t'] = _args[0]
        del _args[0]

        for i in range(int(len(_args) / 2)):
            result[_args[i + (i * 1)]] = _args[i + (i + 1)]

        if result['o']:
            result['o'] = [o.strip() for o in result['o'].split('|')]

        return result

    async def start_daily_debate_timer(self, guild_id, dd_time):
        # creating first parsed_dd_time to grab timezone info
        parsed_dd_time = dateparser.parse(dd_time, settings={'RETURN_AS_TIMEZONE_AWARE': True})

        # second one for actual use
        parsed_dd_time = dateparser.parse(dd_time, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(parsed_dd_time.tzinfo)})

        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        # -1h so mods can be warned when there are no daily debate topics set up
        timer_expires = round(time()) + time_diff_seconds - 3600  # one hour
        utils_cog = self.bot.get_cog('Utils')
        await utils_cog.create_timer(expires=timer_expires, guild_id=guild_id, event='daily_debate', extras={})

    @commands.Cog.listener()
    async def on_daily_debate_timer_over(self, timer):
        guild_id = timer['guild_id']
        guild = self.bot.get_guild(int(guild_id))

        now = round(time())
        dd_time = timer['expires'] + 3600
        tm = dd_time - now

        daily_debate_data = db.daily_debates.find_one({'guild_id': guild.id})
        # check if there are debate topics set up
        topics = daily_debate_data['topics']
        channel_id = daily_debate_data['channel_id']
        if not topics:
            # remind mods that a topic needs to be set up
            msg = f'Daily debate starts in {format_time.seconds(tm)} and no topics have been set up <@&{config.MOD_ROLE_ID}>'
            channel = guild.get_channel(channel_id)

            if channel is None:
                return

            return await channel.send(msg)
        else:
            # start final timer which sends daily debate topic
            timer_expires = dd_time
            utils_cog = self.bot.get_cog('Utils')
            await utils_cog.create_timer(expires=timer_expires, guild_id=guild.id, event='daily_debate_final', extras={})

    @commands.Cog.listener()
    async def on_daily_debate_final_timer_over(self, timer):
        guild_id = timer['guild_id']
        guild = self.bot.get_guild(int(guild_id))

        daily_debate_data = db.daily_debates.find_one({'guild_id': guild_id})
        topic_data = daily_debate_data['topics'][0]
        topic = topic_data['topic']
        topic_options = topic_data['topic_options']
        topic_author_id = topic_data['topic_author_id']
        topic_author = await self.bot.fetch_user(int(topic_author_id)) if topic_author_id else None

        dd_time = daily_debate_data['time']
        dd_channel_id = daily_debate_data['channel_id']
        dd_role_id = daily_debate_data['role_id']
        dd_poll_channel_id = daily_debate_data['poll_channel_id']

        dd_channel = discord.utils.find(lambda c: c.id == int(dd_channel_id), guild.channels) if dd_channel_id else None
        dd_role = discord.utils.find(lambda r: r.id == int(dd_role_id), guild.roles) if dd_role_id else None

        if not dd_channel:
            return

        message = f'Today\'s debate: **“{topic}”**'
        if topic_author:
            message += f' - Topic suggested by <@{topic_author_id}>'
        if dd_role:
            message += f'\n\n<@&{dd_role.id}>'

        msg = await dd_channel.send(message)

        # delete used topic
        db.daily_debates.update_one({'guild_id': guild.id}, {'$pull': {'topics': topic_data}})

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
            if not topic_options:
                poll_emotes = ['👍', '👎', '😐']
                topic_options = ['Yes', 'No', 'Neutral']
            else:
                all_num_emotes = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
                poll_emotes = all_num_emotes[:len(topic_options)]

            dd_poll_channel = discord.utils.find(lambda c: c.id == int(dd_poll_channel_id), guild.channels)

            description = f'**"{topic}"**\n'
            colour = config.EMBED_COLOUR
            embed = discord.Embed(colour=colour, description=description, timestamp=datetime.datetime.now())
            embed.set_author(name='Daily Debate Poll')
            embed.set_footer(text='Started at', icon_url=guild.icon_url)

            description += '\n'.join(f'\n{e} | **{o}**' for e, o in zip(poll_emotes, topic_options))
            embed.description = description

            poll_msg = await dd_poll_channel.send(embed=embed)
            for e in poll_emotes:
                await poll_msg.add_reaction(e)

        # award topic author boost if there is one
        if topic_author:
            boost_dict = {
                'guild_id': guild_id,
                'user_id': topic_author.id,
                'expires': round(time()) + (3600 * 6),
                'multiplier': 0.15,
                'type': 'daily debate topic author'
            }
            db.boosts.insert_one(boost_dict)

        # start daily_debate timer over
        return await self.start_daily_debate_timer(guild.id, dd_time)

    @commands.command(help='Open a ticket for discussion', usage='open_ticket [ticket]', clearance='Mod', cls=command.Command, examples=['open_ticket new mods'])
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

    @commands.command(help='Give user access to ticket', usage='get_user', examples=['get_user'], clearance='Mod', cls=command.Command)
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

            mem = await get_member(ctx, self.bot, src)
            if mem:
                return 'user',  mem

            role = discord.utils.find(lambda r: r.name.lower() == src.lower(), ctx.guild.roles)
            if role:
                return 'role', role

            return '[member/role]', None

        # check if action is member or role
        if action not in ['give', 'neutral', 'take']:
            type, obj = await member_or_role(action)
            if type and obj:
                special_access = db.commands.find({'guild_id': ctx.guild.id, f'{type}_access.{obj.id}': {'$exists': True}})
                access_given = [a['command_name'] for a in special_access if a[f'{type}_access'][f'{obj.id}'] == 'give']
                access_taken = [a['command_name'] for a in special_access if a[f'{type}_access'][f'{obj.id}'] == 'take']

                access_given_str = ' |'.join([f' `{c}`' for c in access_given])
                access_taken_str = ' |'.join([f' `{c}`' for c in access_taken])
                if not access_given_str:
                    access_given_str = f'{type} has no special access to commands'
                if not access_taken_str:
                    access_taken_str = f'No commands have been taken away from this {type}'

                embed_colour = config.EMBED_COLOUR
                embed = discord.Embed(colour=embed_colour, timestamp=datetime.datetime.now(), description='Command Access')
                embed.add_field(name='>Access Given', value=access_given_str, inline=False)
                embed.add_field(name='>Access Taken', value=access_taken_str, inline=False)
                embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)

                return await ctx.send(embed=embed)

        type, obj = await member_or_role(member)
        if obj is None:
            if action not in ['give', 'neutral', 'take']:
                return await embed_maker.command_error(ctx, '[action/(member/role)]')
            if cmd is None:
                return await embed_maker.command_error(ctx, '[command]')
            return await embed_maker.command_error(ctx, type)

        cmd_obj = self.bot.get_command(cmd)
        if not cmd_obj:
            return await embed_maker.message(ctx, f'{cmd} is not a valid command', colour='red')
        command_data = db.commands.find_one({'guild_id': ctx.guild.id, 'command_name': cmd_obj.name})
        in_db = True
        if command_data is None:
            command_data = {
                'guild_id': ctx.guild.id,
                'command_name': cmd_obj.name,
                'disabled': 0,
                'user_access': {},
                'role_access': {}
            }
            in_db = False

        if action not in ['give', 'neutral', 'take']:
            return await embed_maker.message(ctx, 'invalid [action/(member/role)]', colour='red')

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

        filter = {'guild_id': ctx.guild.id, 'command_name': cmd_obj.name}
        if action == 'give':
            if can_access_command and type == 'users':
                return await embed_maker.message(ctx, 'User already has access to that command', colour='red')

            type_access = command_data[f'{type}_access']
            if str(obj.id) in type_access and type_access[f'{obj.id}'] == 'give':
                return await embed_maker.message(ctx, f'{obj} already has been given access to that command', colour='red')

            if in_db:
                db.commands.update_one(filter, {'$set': {f'{type}_access.{obj.id}': 'give'}})
            else:
                command_data[f'{type}_access'][f'{obj.id}'] = 'give'
                db.commands.insert_one(command_data)

            return await embed_maker.message(ctx, f'{obj} has been granted access to: `{cmd}`')

        elif action == 'neutral':
            if str(obj.id) not in command_data[f'{type}_access']:
                return await embed_maker.message(ctx, f'{obj} is already neutral on that command', colour='red')

            db.commands.update_one(filter, {'$unset': {f'{type}_access.{obj.id}': ''}})
            await embed_maker.message(ctx, f'{obj} is now neutral on command `{cmd}`')

            # check if all data is default, if it is delete the data from db
            del command_data[f'{type}_access'][f'{obj.id}']
            if not command_data['disabled'] and not command_data['user_access'] and not command_data['role_access']:
                db.commands.find_one_and_delete(filter)

        elif action == 'take':
            if not can_access_command and type == 'users':
                return await embed_maker.message(ctx, 'User already doesn\'t have access to that command', colour='red')

            type_access = command_data[f'{type}_access']
            if str(obj.id) in type_access and type_access[f'{obj.id}'] == 'take':
                return await embed_maker.message(ctx, f'{obj} has had their access to that command already taken away', colour='red')

            if in_db:
                db.commands.update_one(filter, {'$set': {f'{type}_access.{obj.id}': 'take'}})
            else:
                command_data[f'{type}_access'][f'{obj.id}'] = 'take'
                db.commands.insert_one(command_data)

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


def setup(bot):
    bot.add_cog(Mod(bot))
