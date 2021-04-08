import datetime
import math
import re
import time
import config
import dateparser
import discord
import asyncio
import functools

from io import StringIO
from bson import ObjectId
from modules.reaction_menus import BookMenu
from discord.ext import commands
from typing import Union
from bot import TLDR
from cogs import utility
from modules import cls, database, embed_maker
from modules.utils import (
    ParseArgs,
    Command,
    get_custom_emote,
    get_guild_role,
    get_member,
    get_user_clearance
)

db = database.get_connection()


class Mod(commands.Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @staticmethod
    async def construct_cc_embed(ctx: commands.Context, custom_commands: dict, max_page_num: int, page_size_limit: int, *, page: int):
        if custom_commands:
            custom_commands_str = ''
            for i, command in enumerate(custom_commands[page_size_limit * (page - 1):page_size_limit * page]):
                if i == 10:
                    break

                custom_commands_str += f'**#{i + 1}:** `/{command["name"]}/`\n'
        else:
            custom_commands_str = 'Currently no custom commands have been created'

        return await embed_maker.message(
            ctx,
            description=custom_commands_str,
            author={'name': f'Custom Commands - {get_user_clearance(ctx.author)[-1]}'},
            footer={'text': f'Page {page}/{max_page_num}'}
        )

    @commands.group(
        invoke_without_command=True,
        name='customcommands',
        help='Manage the servers custom commands',
        usage='customcommands (sub command) (args)',
        examples=['customcommands', 'customcommands 1'],
        sub_commands=['variables', 'add', 'remove', 'edit'],
        clearance='Mod',
        aliases=['cc'],
        cls=cls.Group
    )
    async def customcommands(self, ctx: commands.Context, index: Union[int, str] = None):
        if not ctx.subcommand_passed:
            custom_commands = [*db.custom_commands.find({'guild_id': ctx.guild.id})]
            if index is None:
                page = 1
                page_size_limit = 20

                # calculate max page number
                max_page_num = math.ceil(len(custom_commands) / page_size_limit)
                if max_page_num == 0:
                    max_page_num = 1

                if page > max_page_num:
                    return await embed_maker.error(ctx, 'Exceeded maximum page number')

                page_constructor = functools.partial(
                    self.construct_cc_embed,
                    ctx,
                    custom_commands,
                    max_page_num,
                    page_size_limit,
                )

                embed = await page_constructor(page=page)
                cc_message = await ctx.send(embed=embed)

                menu = BookMenu(
                    cc_message,
                    author=ctx.author,
                    page=page,
                    max_page_num=max_page_num,
                    page_constructor=page_constructor,
                )

                self.bot.reaction_menus.add(menu)
            elif type(index) == int:
                command = {i: c for i, c in enumerate(custom_commands)}.get(index - 1, None)
                if not command:
                    return await embed_maker.error(ctx, 'Invalid command index')

                return await embed_maker.message(
                    ctx,
                    description=self.custom_command_args_to_string(command),
                    author={'name': command['name']},
                    send=True
                )
            else:
                return await embed_maker.error(ctx, 'Invalid command index')

    async def validate_custom_command_args(self, ctx: commands.Context, args: dict, *, edit: bool = False):
        if not args['name'] and not edit:
            return await embed_maker.error(ctx, "A name needs to be given to the command.")

        # check for existing custom command with the same name
        existing = db.custom_commands.find_one({'guild_id': ctx.guild.id, 'name': args['name']})
        if existing:
            return await embed_maker.error(ctx, f"A custom command with the name `{args['name']}` already exists")

        if not args['response'] and not edit and not args['python']:
            return await embed_maker.error(ctx, "Missing response arg")

        if args['python'] and 'Dev' not in get_user_clearance(ctx.author):
            return await embed_maker.error(ctx, f'Only devs can {"add" if not edit else "edit"} the python arg')

        # convert roles to ids
        if args['role']:
            for i, role_identifier in enumerate(args['role']):
                try:
                    role = await commands.RoleConverter().convert(ctx, role_identifier)
                    args['role'][i] = role.id
                except:
                    return await embed_maker.error(ctx, f'Invalid role arg: `{role_identifier}`')

        # convert response_channel to id
        if args['response_channel']:
            try:
                response_channel = await commands.TextChannelConverter().convert(ctx, args['response_channel'])
                args['response_channel'] = response_channel.id
            except commands.ChannelNotFound:
                return await embed_maker.error(ctx, f'Invalid response_channel arg: `{args["response_channel"]}`')

        # convert command_channels to ids
        if args['command_channels']:
            args['command_channels'] = args['command_channels'].split()
            for i, channel in enumerate(args['command_channels']):
                try:
                    command_channel = await commands.TextChannelConverter().convert(ctx, channel)
                    args['command_channels'][i] = command_channel.id
                except commands.ChannelNotFound:
                    return await embed_maker.error(ctx, f'Invalid command_channel arg: `{channel}`')

        # split reactions into list
        args['reactions'] = args['reactions'].split() if args['reactions'] else []
        # replace surrounding ``` and newline char in response
        if args['response']:
            args['response'] = re.findall(r'^(?:```\n)?(.*)(?:(?:\n```)$)?', args['response'], re.MULTILINE)[0]

        # check if clearance is valid
        if args['clearance'] and args['clearance'] not in [*config.CLEARANCE.keys()]:
            return await embed_maker.error(ctx, f'Clearance needs to be one of these: {" | ".join(config.CLEARANCE.keys())}')
        # default clearance to User
        elif not args['clearance']:
            args['clearance'] = 'User'

        # set clearance to Dev if python arg is defined
        if args['python']:
            args['clearance'] = 'Dev'

        # check if set clearance is higher than user clearance
        clearances = [*config.CLEARANCE.keys()]
        if args['clearance'] not in get_user_clearance(ctx.author):
            return await embed_maker.error(ctx, 'You cant create a custom command with higher clearance than you have.')

        if args['response']:
            # validate command calls in response and check if command has higher clearance than custom command
            command_matches = re.findall(r'{>(\w+)', args['response'])
            for command_name in command_matches:
                command = self.bot.get_command(command_name, member=ctx.author)
                if not command:
                    return await embed_maker.error(ctx, f'Invalid command: `>{command_name}`')
                if clearances.index(command.docs.clearance) > clearances.index(args['clearance']):
                    return await embed_maker.error(ctx, f'Command called in variable cant have higher clearance than custom command clearance: `>{command_name}`')
        return args

    @staticmethod
    def custom_command_arg_value_to_string(key: str, value: Union[list, str]) -> str:
        # if value is a list, first convert ids into mentions
        if type(value) == list:
            if key == 'command_channels':
                value = [f'<#{c}>' for c in value]
            elif key == 'role':
                value = [f'<@&{r}>' for r in value]

            value = ' '.join(value)
        # convert response channel id to channel mention
        elif key == 'response_channel':
            value = f'<#{value}>'

        return value

    def custom_command_args_to_string(self, args: dict, *, old: dict = None) -> str:
        attributes_str = ''
        for key, value in args.items():
            # check if value exists key isnt in list of values that dont need to be presented
            if value and key not in ['pre', 'guild_id', '_id']:
                value = self.custom_command_arg_value_to_string(key, value)
                # replace underscore with space and make key into title
                if old is None:
                    key = key.replace('_', ' ').title()
                    attributes_str += f'**{key}**: `{value}`\n'
                else:
                    old_value = self.custom_command_arg_value_to_string(key, old[key])
                    key = key.replace('_', ' ').title()
                    attributes_str += f'**{key}**: `{old_value}` --> `{value}`\n'

        return attributes_str

    @customcommands.command(
        name='add',
        help='Add a custom command',
        usage='customcommands add (args)',
        examples=[
            'customcommands add -n ^Suggestion:(.*) -r Suggestion By {user.mention}: $g1 -c User -rl Member -rl 697184342614474785 -rc suggestion-voting -cc daily-debate-suggestions 696345548453707857 -rs 👍 👎'
        ],
        command_args=[
            (('--name', '-n', str), 'The name given to the command, matched with regex.'),
            (('--response', '-r', str), r'Response that will be sent when custom command is called, If you want to do multiline response, please put response between \`\`\`'),
            (('--clearance', '-c', str), f'[Optional] Restrict who can run the command by clearance, {" | ".join([*config.CLEARANCE.keys()])}, Defaults to User'),
            (('--role', '-rl', list), '[Optional] Restrict custom command to role(s)'),
            (('--response_channel', '-rc', str), '[Optional] When set, response will be sent in given channel instead of where custom command was called'),
            (('--command_channels', '-cc', str), '[Optional] Restrict custom command to give channel(s)'),
            (('--reactions', '-rs', str), '[Optional] Reactions that will be added to response, emotes only ofc.'),
            (('--python', '-p', str), r'[Dev only] Run a python script when custom command is called, please put code between \`\`\`'),
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def customcommands_add(self, ctx: commands.Context, *, args: ParseArgs = None):
        if args is None:
            return await embed_maker.command_error(ctx)

        # TODO: embed responses

        # validate args
        args = await self.validate_custom_command_args(ctx, args)
        # return value is a message if an error has occured
        if type(args) == discord.Message:
            return

        # add guild id to args
        args['guild_id'] = ctx.guild.id
        # insert into database
        db.custom_commands.insert(args)

        # convert args into string that can be presented to user who created the command
        attributes_str = self.custom_command_args_to_string(args)

        return await embed_maker.message(
            ctx,
            description=f'A new custom command has been added with these attributes:\n{attributes_str}',
            colour='green',
            send=True
        )

    @customcommands.command(
        name='edit',
        help='Edit a custom command',
        usage='customcommands edit [command name] [args]',
        examples=[],
        command_args=[
            (('--name', '-n', str), 'The name given to the command, matched with regex.'),
            (('--response', '-r', str), r'Response that will be sent when custom command is called, If you want to do multiline response, please put response between \`\`\`'),
            (('--clearance', '-c', str), f'[Optional] Restrict who can run the command by clearance, {" | ".join([*config.CLEARANCE.keys()])}, Defaults to User'),
            (('--role', '-rl', list), '[Optional] Restrict custom command to role(s)'),
            (('--response_channel', '-rc', str), '[Optional] When set, response will be sent in given channel instead of where custom command was called'),
            (('--command_channels', '-cc', str), '[Optional] Restrict custom command to give channel(s)'),
            (('--reactions', '-rs', str), '[Optional] Reactions that will be added to response, emotes only ofc.'),
            (('--python', '-p', str), r'[Dev only] Run a python script when custom command is called, please put code between \`\`\`'),
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def customcommands_edit(self, ctx: commands.Context, *, args: ParseArgs = None):
        if args is None:
            return await embed_maker.command_error(ctx)

        old_command_name = args['pre']

        # check if command user wants to edit actually exists
        existing = db.custom_commands.find_one({'guild_id': ctx.guild.id, 'name': old_command_name})
        if not existing:
            return await embed_maker.error(ctx, f'A command with the name `{old_command_name}` doesn\'t exist')

        # validate args
        args = await self.validate_custom_command_args(ctx, args, edit=True)
        # return value is a message if an error has occurred
        if type(args) == discord.Message:
            return

        # add guild id to args
        args['guild_id'] = ctx.guild.id

        # filter out args that have not been defined
        args = {key: value for key, value in args.items() if value and value != existing[key]}
        # insert into database
        db.custom_commands.update_one({'guild_id': ctx.guild.id, 'name': old_command_name}, {'$set': args})

        # convert args into string that can be presented to user who created the command
        attributes_str = self.custom_command_args_to_string(args, old=existing)

        return await embed_maker.message(
            ctx,
            description=f'Custom command `{old_command_name}` has been edited:\n{attributes_str}',
            colour='green',
            send=True
        )

    @customcommands.command(
        name='remove',
        help=f'Remove a custom command by its index, can be seen by calling `{config.PREFIX}customcommands`',
        usage='customcommands remove [command index]',
        examples=[],
        clearance='Mod',
        cls=cls.Command
    )
    async def customcommands_remove(self, ctx: commands.Context, index: Union[int, str] = None):
        if index is None:
            return await embed_maker.command_error(ctx)

        if type(index) != int:
            return await embed_maker.error(ctx, 'Invalid index')

        custom_commands = [*db.custom_commands.find({'guild_id': ctx.guild.id})]
        command = {i: c for i, c in enumerate(custom_commands)}.get(index - 1, None)

        # check if command user wants to edit actually exists
        if not command:
            return await embed_maker.error(ctx, 'Invalid index')

        db.custom_commands.delete_one({'guild_id': ctx.guild.id, 'name': command['name']})

        return await embed_maker.message(
            ctx,
            description=f'Custom command `{command["name"]}` has been deleted.',
            colour='green',
            send=True
        )

    @customcommands.command(
        name='variables',
        help='List all the variables that can be used in custom command responses or scripts',
        usage='customcommands variables',
        examples=['customcommands variables'],
        aliases=['vars'],
        clearance='Mod',
        cls=cls.Command
    )
    async def customcommands_variables(self, ctx: commands.Context):
        with open('static/custom_commands_variables.txt', 'r') as file:
            return await embed_maker.message(ctx, description=f'```{file.read()}```', author={'name': 'Custom Command Variables'}, send=True)

    @commands.group(
        invoke_without_command=True,
        name='watchlist',
        help='Manage the watchlist, which logs all the users message to a channel',
        usage='watchlist (sub command) (args)',
        examples=['watchlist'],
        sub_commands=['add', 'remove', 'add_filters'],
        clearance='Mod',
        cls=cls.Group
    )
    async def watchlist(self, ctx: commands.Context):
        if ctx.subcommand_passed is None:
            users_on_list = [d for d in db.watchlist.distinct('user_id', {'guild_id': ctx.guild.id})]

            list_embed = await embed_maker.message(
                ctx,
                author={'name': 'Users on the watchlist'}
            )

            on_list_str = ''
            for i, user_id in enumerate(users_on_list):
                user = ctx.guild.get_member(int(user_id))
                if user is None:
                    try:
                        user = await ctx.guild.fetch_member(int(user_id))
                    except:
                        # remove user from the watchlist if user isnt on the server anymore
                        db.watchlist.delete_one({'guild_id': ctx.guild.id, 'user_id': user_id})
                        continue

                on_list_str += f'`#{i + 1}` - {str(user)}\n'
                watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': user_id}, {'filters': 1})
                if watchlist_user['filters']:
                    on_list_str += 'Filters: ' + " | ".join(f"`{f}`" for f in watchlist_user['filters'])
                on_list_str += '\n\n'

            list_embed.description = 'Currently no users are on the watchlist' if not on_list_str else on_list_str

            return await ctx.send(embed=list_embed)

    @watchlist.command(
        name='add',
        help='add a user to the watchlist, with optionl filters (mathces are found with regex)',
        usage='watchlist add [user] (args)',
        examples=[r'watchlist add hattyot -f hattyot -f \sot\s -f \ssus\s'],
        command_args=[
            (('--filter', '-f', list), 'A regex filter that will be matched against the users message, if a match is found, mods will be @\'d'),
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def watchlist_add(self, ctx: commands.Context, *, args: Union[ParseArgs, dict] = None):
        if not args:
            return await embed_maker.command_error(ctx)

        user_identifier = args['pre']

        if not user_identifier:
            return await embed_maker.error(ctx, 'Missing user')

        filters = args['filter']

        member = await get_member(ctx, user_identifier)
        if type(member) == discord.Message:
            return

        watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})
        if watchlist_user:
            return await embed_maker.error(ctx, 'User is already on the watchlist')

        watchlist_category = discord.utils.find(lambda c: c.name == 'Watchlist', ctx.guild.categories)
        if watchlist_category is None:
            # get all staff roles
            staff_roles = filter(lambda r: r.permissions.manage_messages, ctx.guild.roles)

            # staff roles can read channels in category, users cant
            overwrites = dict.fromkeys(staff_roles, discord.PermissionOverwrite(read_messages=True, send_messages=True,
                                                                                read_message_history=True))
            overwrites[ctx.guild.default_role] = discord.PermissionOverwrite(read_messages=False)

            watchlist_category = await ctx.guild.create_category(name='Watchlist', overwrites=overwrites)

        watchlist_channel = await ctx.guild.create_text_channel(f'{member.name}', category=watchlist_category)

        watchlist_doc = {
            'guild_id': ctx.guild.id,
            'user_id': member.id,
            'filters': filters,
            'channel_id': watchlist_channel.id
        }
        db.watchlist.insert_one(watchlist_doc)

        msg = f'<@{member.id}> has been added to the watchlist'
        if filters:
            msg += f'\nWith these filters: {" or ".join(f"`{f}`" for f in filters)}'

        return await embed_maker.message(ctx, description=msg, colour='green', send=True)

    @watchlist.command(
        name='remove',
        help='remove a user from the watchlist',
        usage='watchlist remove [user]',
        examples=['watchlist remove hattyot'],
        clearance='Mod',
        cls=cls.Command
    )
    async def watchlist_remove(self, ctx: commands.Context, *, user: str = None):
        if user is None:
            return await embed_maker.command_error(ctx)

        member = await get_member(ctx, user)
        if type(member) == discord.Message:
            return

        watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})

        if watchlist_user is None:
            return await embed_maker.error(ctx, 'User is not on the list')

        # remove watchlist channel
        channel_id = watchlist_user['channel_id']
        channel = self.bot.get_channel(int(channel_id))
        if channel:
            await channel.delete()

        db.watchlist.delete_one({'guild_id': ctx.guild.id, 'user_id': member.id})

        return await embed_maker.message(
            ctx,
            description=f'<@{member.id}> has been removed from the watchlist',
            colour='green',
            send=True
        )

    @watchlist.command(
        name='add_filters',
        help='Add filters to a user on the watchlist, when a user message matches the filter, mods are pinged.',
        usage='watchlist add_filters [user] (args)',
        examples=[r'watchlist add_filters hattyot -f filter 1 -f \sfilter 2\s'],
        command_args=[
            (('--filter', '-f', list), 'A regex filter that will be matched against the users message, if a match is found, mods will be @\'d'),
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def watchlist_add_filters(self, ctx: commands.Context, *, args: Union[ParseArgs, dict] = None):
        if not args:
            return await embed_maker.command_error(ctx)

        user_identifier = args['pre']
        filters = args['f']

        if not filters:
            return await embed_maker.error(ctx, 'Missing filters')

        if not user_identifier:
            return await embed_maker.error(ctx, 'Missing user')

        member = await get_member(ctx, user_identifier)
        if type(member) == discord.Message:
            return

        watchlist_user = db.watchlist.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})
        if watchlist_user is None:
            return await embed_maker.error(ctx, 'User is not on the list')

        all_filters = watchlist_user['filters']
        if all_filters:
            filters += all_filters

        db.watchlist.update_one({'guild_id': ctx.guild.id, 'user_id': member.id}, {'$set': {f'filters': filters}})

        return await embed_maker.message(
            ctx,
            description=f'if {member} mentions {" or ".join(f"`{f}`" for f in filters)} mods will be @\'d',
            colour='green',
            send=True
        )

    @staticmethod
    async def construct_dd_embed(ctx: commands.Context, daily_debates_data: dict, max_page_num: int, page_size_limit: int, topics: list, *, page: int):
        if not topics:
            topics_str = f'Currently there are no debate topics set up'
        else:
            # generate topics string
            topics_str = '**Topics:**\n'
            for i, topic in enumerate(topics[page_size_limit * (page - 1):page_size_limit * page]):
                if i == 10:
                    break

                topic_str = topic['topic']
                topic_author_id = topic['topic_author_id']
                topic_options = topic['topic_options']

                topic_author = None
                if topic_author_id:
                    topic_author = ctx.guild.get_member(int(topic_author_id))
                    if not topic_author:
                        try:
                            topic_author = await ctx.guild.fetch_member(int(topic_author_id))
                        except Exception:
                            topic_author = None

                topics_str += f'`#{page_size_limit * (page - 1) + i + 1}`: {topic_str}\n'
                if topic_author:
                    topics_str += f'**Topic Author:** {str(topic_author)}\n'

                if topic_options:
                    topics_str += '**Poll Options:**' + ' |'.join(
                        [f' `{o}`' for i, o in enumerate(topic_options.values())]) + '\n'

        dd_time = daily_debates_data['time'] if daily_debates_data['time'] else 'Not set'
        dd_channel = f'<#{daily_debates_data["channel_id"]}>' if daily_debates_data['channel_id'] else 'Not set'
        dd_poll_channel = f'<#{daily_debates_data["poll_channel_id"]}>' if daily_debates_data[
            'poll_channel_id'] else 'Not set'
        dd_role = f'<@&{daily_debates_data["role_id"]}>' if daily_debates_data['role_id'] else 'Not set'
        embed = await embed_maker.message(
            ctx,
            description=topics_str,
            author={'name': 'Daily Debates'},
            footer={'text': f'Page {page}/{max_page_num}'}
        )
        embed.add_field(
            name='Attributes',
            value=f'**Time:** {dd_time}\n**Channel:** {dd_channel}\n**Poll Channel:** {dd_poll_channel}\n**Role:** {dd_role}'
        )
        return embed

    @commands.group(
        invoke_without_command=True,
        help='Daily debate scheduler/manager',
        usage='dailydebates (sub command) (arg(s))',
        clearance='Mod',
        aliases=['dd', 'dailydebate'],
        examples=['dailydebates'],
        sub_commands=['add', 'insert', 'remove', 'set_time', 'set_channel', 'set_role', 'set_poll_channel', 'set_poll_options', 'disable'],
        cls=cls.Group,
    )
    async def dailydebates(self, ctx: commands.Context, page: str = 1):
        if ctx.subcommand_passed is None:
            daily_debates_data = db.get_daily_debates(ctx.guild.id)

            if type(page) == str and page.isdigit():
                page = int(page)
            else:
                page = 1

            page_size_limit = 10

            # List currently set up daily debate topics
            topics = daily_debates_data['topics']

            # calculate max page number
            max_page_num = math.ceil(len(topics) / page_size_limit)
            if max_page_num == 0:
                max_page_num = 1

            if page > max_page_num:
                return await embed_maker.error(ctx, 'Exceeded maximum page number')

            page_constructor = functools.partial(
                self.construct_dd_embed,
                ctx,
                daily_debates_data,
                max_page_num,
                page_size_limit,
                topics
            )

            embed = await page_constructor(page=page)
            dd_message = await ctx.send(embed=embed)

            menu = BookMenu(
                dd_message,
                author=ctx.author,
                page=page,
                max_page_num=max_page_num,
                page_constructor=page_constructor,
            )

            self.bot.reaction_menus.add(menu)

    @dailydebates.command(
        name='disable',
        help='Disable the daily debates system, time will be set to 0',
        usage='dailydebates disable',
        examples=['dailydebates disable'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_disable(self, ctx: commands.Context):
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'time': 0}})

        # cancel timer if active
        daily_debate_timer = db.timers.find_one(
            {'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}}
        )
        if daily_debate_timer:
            db.timers.delete_one({'_id': ObjectId(daily_debate_timer['_id'])})

        return await embed_maker.message(ctx, description='Daily debates have been disabled', send=True)

    @dailydebates.command(
        name='set_poll_options',
        help='Set the poll options for a daily debate topic',
        usage='dailydebates set_poll_options [index of topic] [args]',
        examples=[
            'dailydebates set_poll_options 1 -o yes -o no -o double yes -o double no',
            'dailydebates set_poll_options 1 -o 🇩🇪: Germany -o 🇬🇧: UK'
        ],
        command_args=[
            (('--option', '-o', list), 'Option for the poll'),
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_set_poll_options(self, ctx: commands.Context, index: str = None, *, args: Union[ParseArgs, dict] = None):
        if index is None:
            return await embed_maker.command_error(ctx)

        if not index.isdigit():
            return await embed_maker.command_error(ctx, '[index of topic]')

        options = args['option']

        if not options:
            return await embed_maker.error(ctx, 'Missing options')

        emote_options = await utility.Utility.parse_poll_options(ctx, options)
        if type(emote_options) == discord.Message:
            return

        daily_debates_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        topics = daily_debates_data['topics']

        index = int(index)
        if len(topics) < index:
            return await embed_maker.error(ctx, 'index out of range')

        topic = topics[index - 1]

        topic_obj = {
            'topic': topic['topic'],
            'topic_author_id': topic['topic_author_id'],
            'topic_options': emote_options
        }

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {f'topics.{index - 1}': topic_obj}})
        options_str = '\n'.join([f'{emote}: {option}' for emote, option in emote_options.items()])
        return await embed_maker.message(
            ctx,
            description=f'Along with the topic: **"{topic["topic"]}"**\nwill be sent a poll with these options: {options_str}',
            send=True
        )

    @dailydebates.command(
        name='add',
        help='add a topic to the list topics along with optional options and topic author',
        usage='dailydebates add [topic] (args)',
        examples=[
            'dailydebates add is ross mega cool? -ta hattyot -o yes -o double yes -o triple yes'
        ],
        command_args=[
            (('--topic_author', '-ta', str), 'Original author of the topic, that will be mentioned when the dd is sent, they will also be given a 15% boost for 6 hours'),
            (('--option', '-o', list), 'Option for the poll'),
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_add(self, ctx: commands.Context, *, args: Union[ParseArgs, dict] = None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = await self.parse_dd_args(ctx, args)
        if type(args) == discord.Message:
            return

        topic = args['pre']
        topic_author = args['topic_author']
        topic_options = args['option']

        topic_obj = {
            'topic': topic,
            'topic_author_id': topic_author,
            'topic_options': topic_options
        }
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$push': {'topics': topic_obj}})

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        await embed_maker.message(
            ctx,
            description=f'`{topic}` has been added to the list of daily debate topics'
                        f'\nThere are now **{len(daily_debate_data["topics"])}** topics on the list',
            send=True
        )

        daily_debate_timer = db.timers.find_one(
            {'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}}
        )
        if not daily_debate_timer:
            return await self.start_daily_debate_timer(ctx.guild.id, daily_debate_data['time'])

    @dailydebates.command(
        name='insert',
        help='insert a topic into the first place on the list of topics along with optional options and topic author',
        usage='dailydebates insert [topic] (args)',
        examples=['dailydebates insert is ross mega cool? -ta hattyot -o yes | double yes | triple yes'],
        clearance='Mod',
        command_args=[
            (('--topic_author', '-ta', str), 'Original author of the topic, that will be mentioned when the dd is sent, they will also be given a 15% boost for 6 hours'),
            (('--option', '-o', list), 'Option for the poll'),
        ],
        cls=cls.Command
    )
    async def _dailydebates_insert(self, ctx: commands.Context, *, args: Union[ParseArgs, dict] = None):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = await self.parse_dd_args(ctx, args)
        if type(args) == discord.Message:
            return

        topic = args['pre']
        topic_author = args['topic_author']
        topic_options = args['option']

        topic_obj = {
            'topic': topic,
            'topic_author_id': topic_author,
            'topic_options': topic_options
        }
        db.daily_debates.update_one(
            {'guild_id': ctx.guild.id},
            {'$push': {'topics': {'$each': [topic_obj], '$position': 0}}}
        )

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})
        await embed_maker.message(
            ctx,
            description=f'`{topic}` has been inserted into first place in the list of daily debate topics'
                        f'\nThere are now **{len(daily_debate_data["topics"])}** topics on the list',
            send=True
        )

        daily_debate_timer = db.timers.find_one(
            {'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}}
        )
        if not daily_debate_timer:
            return await self.start_daily_debate_timer(ctx.guild.id, daily_debate_data['time'])

    @dailydebates.command(
        name='remove',
        help='remove a topic from the topic list',
        usage='dailydebates remove [topic index]',
        examples=['dailydebates remove 2'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_remove(self, ctx: commands.Context, index: str = None):
        if index is None:
            return await embed_maker.command_error(ctx)

        if not index.isdigit():
            return await embed_maker.error(ctx, 'Invalid index')

        daily_debate_data = db.daily_debates.find_one({'guild_id': ctx.guild.id})

        index = int(index)
        if index > len(daily_debate_data['topics']):
            return await embed_maker.error(ctx, 'Index too big')

        if index < 1:
            return await embed_maker.error(ctx, 'Index cant be smaller than 1')

        topic_to_delete = daily_debate_data['topics'][index - 1]
        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$pull': {'topics': topic_to_delete}})

        return await embed_maker.message(
            ctx,
            description=f'`{topic_to_delete["topic"]}` has been removed from the list of daily debate topics'
                        f'\nThere are now **{len(daily_debate_data["topics"]) - 1}** topics on the list',
            send=True
        )

    @dailydebates.command(
        name='set_time',
        help='set the time when topics are announced',
        usage='dailydebates set_time [time]',
        examples=['dailydebates set_time 14:00 GMT+1'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_set_time(self, ctx: commands.Context, *, time_str: str = None):
        if time_str is None:
            return await embed_maker.command_error(ctx)

        parsed_time = dateparser.parse(time_str, settings={'RETURN_AS_TIMEZONE_AWARE': True})
        if not parsed_time:
            return await embed_maker.error(ctx, 'Invalid time')

        parsed_dd_time = dateparser.parse(
            time_str,
            settings={
                'PREFER_DATES_FROM': 'future',
                'RETURN_AS_TIMEZONE_AWARE': True,
                'RELATIVE_BASE': datetime.datetime.now(parsed_time.tzinfo)
            }
        )
        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        if time_diff_seconds < 0:
            return await embed_maker.error(ctx, 'Invalid time')

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'time': time_str}})
        await embed_maker.message(ctx, description=f'Daily debates will now be announced every day at {time_str}', send=True)

        # cancel old timer
        db.timers.delete_many({'guild_id': ctx.guild.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})

        return await self.start_daily_debate_timer(ctx.guild.id, time_str)

    @dailydebates.command(
        name='set_channel',
        help=f'set the channel where topics are announced',
        usage='dailydebates set_channel [#set_channel]',
        examples=['dailydebates set_channel #daily-debates'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_set_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'channel_id': channel.id}})
        return await embed_maker.message(
            ctx,
            description=f'Daily debates will now be announced every day at <#{channel.id}>',
            send=True
        )

    @dailydebates.command(
        name='set_role',
        help=f'set the role that will be @\'d when topics are announced, disable @\'s by setting the role to `None`',
        usage='dailydebates set_role [role]',
        examples=['dailydebates set_role Debater'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_set_role(self, ctx: commands.Context, *, role: Union[discord.Role, str] = None):
        if role is None:
            return await embed_maker.command_error(ctx)

        if type(role) == str and role.lower() == 'none':
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': 0}})
            return await embed_maker.message(ctx, description='daily debates role has been disabled', send=True)
        elif type(role) == str:
            return await embed_maker.command_error(ctx, '[role]')

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': role.id}})
        return await embed_maker.message(
            ctx,
            description=f'Daily debates will now be announced every day to <@&{role.id}>',
            send=True
        )

    @dailydebates.command(
        name='set_poll_channel',
        help=f'Set the poll channel where polls will be sent, disable polls by setting poll channel to `None``',
        usage='dailydebates set_poll_channel [#channel]',
        examples=['dailydebates set_poll_channel #daily_debate_polls'],
        clearance='Mod',
        cls=cls.Command
    )
    async def dailydebates_set_poll_channel(self, ctx: commands.Context, channel: Union[discord.TextChannel, str] = None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        if type(channel) == str and channel.lower() == 'none':
            db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'role_id': 0}})
            return await embed_maker.message(ctx, description='daily debates poll channel has been disabled', send=True)

        db.daily_debates.update_one({'guild_id': ctx.guild.id}, {'$set': {'poll_channel_id': channel.id}})
        return await embed_maker.message(
            ctx,
            description=f'Daily debate polls will now be sent every day to <#{channel.id}>',
            send=True
        )

    @staticmethod
    async def parse_dd_args(ctx: commands.Context, args: dict):
        if not args['pre']:
            return await embed_maker.error(ctx, 'Missing topic')

        args['option'] = await utility.Utility.parse_poll_options(ctx, args['option']) if args['option'] else ''
        if type(args['option']) == discord.Message:
            return

        if args['topic_author']:
            member = await get_member(ctx, args['topic_author'])
            if type(member) == discord.Message:
                return member

            args['topic_author'] = member.id

        return args

    async def start_daily_debate_timer(self, guild_id, dd_time):
        # delete old timer
        db.timers.delete_many({'guild_id': guild_id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})

        # creating first parsed_dd_time to grab timezone info
        parsed_dd_time = dateparser.parse(dd_time, settings={'RETURN_AS_TIMEZONE_AWARE': True})

        # second one for actual use
        parsed_dd_time = dateparser.parse(dd_time, settings={'PREFER_DATES_FROM': 'future', 'RETURN_AS_TIMEZONE_AWARE': True, 'RELATIVE_BASE': datetime.datetime.now(parsed_dd_time.tzinfo)})

        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        # -1h so mods can be warned when there are no daily debate topics set up
        timer_expires = round(time.time()) + time_diff_seconds - 3600  # one hour
        self.bot.timers.create(guild_id=guild_id, expires=timer_expires, event='daily_debate', extras={})

    @commands.group(
        invoke_without_command=True,
        help='Grant users access to commands that aren\'t available to users or take away their access to a command',
        usage='command_access [<member/role>/sub command] (args)',
        clearance='Admin',
        examples=[
            'command_access Hatty',
            'command_access Mayor'
        ],
        sub_commands=['give', 'take', 'default'],
        cls=cls.Group
    )
    async def command_access(self, ctx: commands.Context, user_input: Union[discord.Role, str] = None):
        if user_input is None:
            return await embed_maker.command_error(ctx)

        if ctx.subcommand_passed is None:
            return

        if type(user_input) == str:
            # check if user input is member
            user_input = await get_member(ctx, user_input)
            if type(user_input) == discord.Message:
                return

        if type(user_input) == discord.Role:
            access_type = 'role'
        elif type(user_input) == discord.Member:
            access_type = 'user'

        special_access = [c for c in db.commands.find(
            {'guild_id': ctx.guild.id, f'{access_type}_access.{user_input.id}': {'$exists': True}}
        )]

        access_given = [a['command_name'] for a in special_access if a[f'{access_type}_access'][f'{user_input.id}'] == 'give']
        access_taken = [a['command_name'] for a in special_access if a[f'{access_type}_access'][f'{user_input.id}'] == 'take']

        access_given_str = ' |'.join([f' `{c}`' for c in access_given])
        access_taken_str = ' |'.join([f' `{c}`' for c in access_taken])

        if not access_given_str:
            access_given_str = f'{access_type.title()} has no special access to commands'
        if not access_taken_str:
            access_taken_str = f'No commands have been taken away from this {access_type.title()}'

        embed = await embed_maker.message(
            ctx,
            author={'name': f'Command Access - {user_input}'}
        )

        embed.add_field(name='>Access Given', value=access_given_str, inline=False)
        embed.add_field(name='>Access Taken', value=access_taken_str, inline=False)

        return await ctx.send(embed=embed)

    @staticmethod
    async def command_access_check(
            ctx: commands.Context,
            command: cls.Command,
            user_input: Union[discord.Role, str],
            change: str
    ):
        if type(user_input) == str:
            # check if user input is member
            user_input = await get_member(ctx, user_input)
            if type(user_input) == discord.Message:
                return

        if command is None:
            return await embed_maker.command_error(ctx)

        if user_input is None:
            return await embed_maker.error(ctx, '[user/role]')

        command_data = db.get_command_data(ctx.guild.id, command.name, insert=True)

        if command.docs.clearance in ['Dev', 'Admin']:
            return await embed_maker.error(ctx, 'You can not manage access of admin or dev commands')

        can_access_command = True

        if type(user_input) == discord.Role:
            access_type = 'role'
        elif type(user_input) == discord.Member:
            access_type = 'user'

        if access_type == 'user':
            author_perms = ctx.author.guild_permissions
            member_perms = user_input.guild_permissions
            if author_perms <= member_perms:
                return await embed_maker.error(
                    ctx,
                    'You can not manage command access of people who have the same or more permissions as you'
                )

            # can user run command
            can_access_command = command.docs.can_run

        elif access_type == 'role':
            top_author_role = ctx.author.roles[-1]
            top_author_role_perms = top_author_role.permissions
            role_perms = user_input.permissions
            if top_author_role_perms <= role_perms:
                return await embed_maker.error(
                    ctx,
                    'You can not manage command access of a role which has the same or more permissions as you'
                )

            access = command_data[f'role_access']
            can_access_command = str(user_input.id) in access and access[str(user_input.id)] == 'give'

        if can_access_command and change == 'give':
            return await embed_maker.error(ctx, f'{user_input} already has access to that command')

        if not can_access_command and change == 'take':
            return await embed_maker.error(ctx, f"{user_input} already doesn't have access to that command")

        return access_type, user_input

    @command_access.command(
        name='give',
        help='Grant a users or a role access to commands that aren\'t available them usually',
        usage='command_access give [command] [user/role]',
        clearance='Admin',
        examples=[
            'command_access give anon_poll Hattyot',
            'command_access give daily_debates Mayor'
        ],
        cls=cls.Command
    )
    async def command_access_give(self, ctx: commands.Context, command: Union[Command, cls.Command] = None,
                                  user_input: Union[discord.Role, str] = None):
        data = await self.command_access_check(ctx, command, user_input, change='give')
        if type(data) == discord.Message:
            return

        access_type, user_input = data

        db.commands.update_one(
            {'guild_id': ctx.guild.id, 'command_name': command.name},
            {'$set': {f'{access_type}_access.{user_input.id}': 'give'}}
        )

        return await embed_maker.message(
            ctx,
            description=f'{user_input} has been granted access to: `{command.name}`',
            send=True
        )

    @command_access.command(
        name='take',
        help="'Take away user's or role's access to a command",
        usage='command_access take [command] [user/role]',
        clearance='Admin',
        examples=[
            'command_access take anon_poll Hattyot',
            'command_access take daily_debates Mayor'
        ],
        cls=cls.Command
    )
    async def command_access_take(self, ctx: commands.Context, command: Union[Command, cls.Command] = None,
                                  user_input: Union[discord.Role, str] = None):
        data = await self.command_access_check(ctx, command, user_input, change='take')
        if type(data) == discord.Message:
            return

        access_type, user_input = data

        db.commands.update_one(
            {'guild_id': ctx.guild.id, 'command_name': command.name},
            {'$set': {f'{access_type}_access.{user_input.id}': 'take'}}
        )

        return await embed_maker.message(
            ctx,
            description=f'{user_input} access has been taken away from: `{command.name}`',
            send=True
        )

    @command_access.command(
        name='default',
        help="Sets role's or user's access to a command back to default",
        usage='command_access default [command] [user/role]',
        clearance='Admin',
        examples=[
            'command_access default anon_poll Hattyot',
            'command_access default daily_debates Mayor'
        ],
        cls=cls.Command
    )
    async def command_access_default(self, ctx: commands.Context, command: Union[Command, cls.Command] = None,
                                     user_input: Union[discord.Role, str] = None):
        data = await self.command_access_check(ctx, command, user_input, change='default')
        if type(data) == discord.Message:
            return

        access_type, user_input = data

        db.commands.update_one(
            {'guild_id': ctx.guild.id, 'command_name': command.name},
            {'$unset': {f'{access_type}_access.{user_input.id}': 1}}
        )

        return await embed_maker.message(
            ctx,
            description=f'{user_input} access has been set to default for: `{command.name}`',
            send=True
        )

    @commands.command(
        help='see what roles are whitelisted for an emote or what emotes are whitelisted for a role',
        usage='emote_roles [emote/role]',
        examples=[
            'emote_roles :TldrNewsUK:',
            'emote_roles Mayor'
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def emote_roles(self, ctx, user_input: str = None):
        if user_input is None:
            return await embed_maker.command_error(ctx)

        # check if user_input is emote
        role = None

        emote = get_custom_emote(ctx, user_input)
        if not emote:
            role = await get_guild_role(ctx.guild, user_input)

        if emote:
            if emote.roles:
                return await embed_maker.message(
                    ctx,
                    description=f'This emote is restricted to: {", ".join([f"<@&{r.id}>" for r in emote.roles])}',
                    send=True
                )
            else:
                return await embed_maker.message(ctx, description='This emote is available to everyone', send=True)
        elif role:
            emotes = []
            for emote in ctx.guild.emojis:
                if role in emote.roles:
                    emotes.append(emote)

            if emotes:
                return await embed_maker.message(
                    ctx,
                    description=f'This role has access to: {", ".join([f"<:{emote.name}:{emote.name}> " for emote in emotes])}',
                    send=True
                )
            else:
                return await embed_maker.message(
                    ctx,
                    description='This role doesn\'t have special access to any emotes',
                    send=True
                )

    @commands.command(
        help='restrict an emote to specific role(s)',
        usage='emote_role (action) [args]',
        examples=[
            'emote_role',
            'emote_role add -r Mayor -e :TldrNewsUK:',
            'emote_role remove -r Mayor -e :TldrNewsUK: :TldrNewsUS: :TldrNewsEU:'
        ],
        command_args=[
            (('--role', '-r', str), 'The role you want to add the emote to'),
            (('--emotes', '-e', str), 'The emotes you want to be added to the role'),
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def emote_role(self, ctx: commands.Context, action: str = None, *, args: Union[ParseArgs, dict] = None):
        if action and action.isdigit():
            page = int(action)
        else:
            page = 1

        if action not in ['add', 'remove']:
            emotes = ctx.guild.emojis
            max_pages = math.ceil(len(emotes) / 10)

            if page > max_pages or page < 1:
                return await embed_maker.error(ctx, 'Invalid page number given')

            emotes = emotes[10 * (page - 1):10 * page]

            description = ''
            index = 0
            for emote in emotes:
                if not emote.roles:
                    continue

                emote_roles = " | ".join(f'<@&{role.id}>' for role in emote.roles)
                description += f'\n<:{emote.name}:{emote.id}> -> {emote_roles}'
                index += 1

                if index == 10:
                    break

            return await embed_maker.message(
                ctx,
                description=description,
                send=True,
                footer={'text': f'Page {page}/{max_pages}'}
            )

        # return error if required variables are not given
        if 'r' not in args or not args['r']:
            return await embed_maker.error(ctx, "Missing role arg")

        if 'e' not in args or not args['e']:
            return await embed_maker.error(ctx, "Missing emotes arg")

        role = await get_guild_role(ctx.guild, args['r'][0])
        emotes = args['e'][0]

        if emotes is None:
            return await embed_maker.command_error(ctx, '[emotes]')

        if role is None:
            return await embed_maker.command_error(ctx, '[role]')

        emote_list = [*filter(lambda e: e is not None, [get_custom_emote(ctx, emote) for emote in emotes.split(' ')])]
        if not emote_list:
            return await embed_maker.command_error(ctx, '[emotes]')

        msg = None
        for emote in emote_list:
            emote_roles = emote.roles

            if action == 'add':
                emote_roles.append(role)
                # add bot role to emote_roles
                if ctx.guild.self_role not in emote_roles:
                    emote_roles.append(ctx.guild.self_role)

                emote_roles = [*set(emote_roles)]

                await emote.edit(roles=emote_roles)

            elif action == 'remove':
                for i, r in enumerate(emote_roles):
                    if r.id == role.id:
                        emote_roles.pop(i)
                        await emote.edit(roles=emote_roles)
                else:
                    msg = f'<@&{role.id}> is not whitelisted for emote {emote}'
                    break

        if not msg:
            if action == 'add':
                msg = f'<@&{role.id}> has been added to whitelisted roles of emotes {emotes}'
            elif action == 'remove':
                msg = f'<@&{role.id}> has been removed from whitelisted roles of emotes {emotes}'

        return await embed_maker.message(ctx, description=msg, colour='green', send=True)

    @commands.command(
        help='Open a ticket for discussion',
        usage='open_ticket [ticket]',
        clearance='Mod',
        examples=['open_ticket new mods'],
        cls=cls.Command
    )
    async def open_ticket(self, ctx: commands.Context, *, ticket=None):
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

    @commands.command(
        help='Archive a ticket channel. Every message will be recorded and put in a google doc',
        usage='archive_channel',
        clearance='Mod',
        examples=['archive_channel'],
        cls=cls.Command
    )
    async def archive_channel(self, ctx: commands.Context):
        # ask the user if they actually want to start the process of archiving a channel
        confirm_message = await embed_maker.message(
            ctx,
            description='React with 👍 if you are sure you want to archive this channel.',
            colour='red',
            send=True
        )

        def check(reaction: discord.Reaction, user: discord.User):
            return user == ctx.author and str(reaction.emoji) == '👍'

        try:
            await ctx.bot.wait_for('reaction_add', timeout=60, check=check)
        except asyncio.TimeoutError:
            await confirm_message.delete()
            return await ctx.message.delete()

        # get embed that confirms users reaction
        confirmed_embed = await embed_maker.message(
            ctx,
            description='Starting archive process, this might take a while, please wait.',
            colour='green',
        )

        # edit original message
        await confirm_message.edit(embed=confirmed_embed)

        # get all the messages for channel and reverse the list
        channel_history = await ctx.channel.history(limit=None).flatten()
        channel_history = channel_history[::-1]

        channel_history_string = ''
        for i, message in enumerate(channel_history):
            # fix for a weird error
            if not message or type(message) == str:
                continue

            channel_history_string += f"\n{message.author} - {message.created_at.strftime('%H:%M:%S | %Y-%m-%d')}"

            if message.content:
                channel_history_string += f'\n"{message.content}"'

            # if message has embed, convert the embed to text and add it to channel_history_string
            if message.embeds:
                channel_history_string += f'\n"{self.embed_message_to_text(message)}"'

            # if message has attachments add them to channel_history_string
            if message.attachments:
                # if message has contents it needs to have \n at the end
                if message.content:
                    channel_history_string += '\n'

                # gather urls
                urls = "\n".join([a.url for a in message.attachments])
                channel_history_string += f'Attachments: {urls}'

            channel_history_string += '\n'

        # convert mentions like "<@93824009823094832098>" into names
        channel_history_string = self.replace_mentions(ctx.guild, channel_history_string)

        # send file containing archive
        return await ctx.send(file=discord.File(StringIO(channel_history_string), filename='archive.txt'))

    def embed_message_to_text(self, message: discord.Message):
        # convert fields to text
        fields = ""
        for field in message.embeds[0].fields:
            fields += f'\n{field.name}\n{field.value}'

        # get either title or author
        title = self.get_title(message.embeds[0])

        # format description
        description = '\n' + message.embeds[0].description if message.embeds[0].description else ''

        # convert values to a multi line message
        text = f"{title}" \
               f"{description}" \
               f"{fields}"

        return text

    @staticmethod
    def get_title(embed: discord.Embed):
        title = ''
        if embed.title:
            title = embed.title.name if type(embed.title) != str else embed.title
        elif embed.author:
            title = embed.author.name if type(embed.author) != str else embed.author

        return title

    @staticmethod
    def replace_mentions(guild: discord.Guild, string):
        # replace mentions in values with actual names
        mentions = re.findall(r'(<(@|@&|@!|#)\d+>)', string)
        for mention in mentions:
            # get type, ie. @, @&, @! or #
            mention_type = mention[1]
            # get id from find
            mention_id = re.findall(r'(\d+)', mention[0])[0]

            # turn type into iterable
            iterable_switch = {
                '@': guild.members,
                '@!': guild.members,
                '@&': guild.roles,
                '#': guild.channels
            }
            iterable = iterable_switch.get(mention_type, None)
            if not iterable:
                continue

            # get object from id
            mention_object = discord.utils.find(lambda o: o.id == int(mention_id), iterable)
            # if object actually exists replace mention in string
            if mention_object:
                string = string.replace(f'{mention[0]}', mention_object.name)

        return string

    @commands.command(
        name='automember',
        help='Enables or disables giving non-patreon users the member role when they get the citizen role',
        usage='automember',
        clearance='Mod',
        examples=['automember'],
        cls=cls.Command
    )
    async def auto_member(self, ctx: commands.Context):
        new_automember = db.get_automember(ctx.guild.id)

        if new_automember:
            msg = 'Disabling automember'
            colour = 'orange'
        else:
            msg = 'Enabling automember'
            colour = 'green'

        leveling_guild = self.bot.leveling_system.get_guild(ctx.guild.id)
        leveling_guild.toggle_automember()

        return await embed_maker.message(ctx, description=msg, colour=colour, send=True)


def setup(bot):
    bot.add_cog(Mod(bot))
