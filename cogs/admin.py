import math
import asyncio
import discord
import config
import re
import functools

from io import StringIO
from discord.ext.commands import Cog, command, Context, TextChannelConverter, ChannelNotFound, group
from modules import commands, database, embed_maker, reaction_menus
from modules.utils import ParseArgs, get_custom_emote, get_guild_role
from typing import Union

db = database.get_connection()


class Admin(Cog):
    def __init__(self, bot):
        self.bot = bot

    @command(
        invoke_without_command=True,
        help='command for managing the clearance system through commands for admins.',
        usage='clearance (sub command) (args)',
        examples=[],
        cls=commands.Group
    )
    async def clearance(self, ctx: Context):
        if ctx.subcommand_passed is None:
            return await embed_maker.command_error(ctx)

    @clearance.command(
        name='refresh',
        help='refresh the clearance data held by the bot, re-downloads and parses the clearance spreadsheet',
        usage='clearance refresh',
        examples=['clearance refresh'],
        cls=commands.Command
    )
    async def clearance_refresh(self, ctx: Context):
        await self.bot.clearance.refresh_data()
        return await embed_maker.message(ctx, description='Clearance data has been refreshed', send=True, colour='green')

    @clearance.command(
        name='groups',
        help='Display the clearance groups and what roles they hold',
        usage='clearance groups',
        examples=['clearance groups'],
        cls=commands.Command
    )
    async def clearance_groups(self, ctx: Context):
        groups = self.bot.clearance.groups
        embed = await embed_maker.message(
            ctx,
            description=f'Groups in the clearance spreadsheet: {self.bot.clearance.spreadsheet_link}',
            author={'name': 'Groups'}
        )

        for group_name, group_roles in groups.items():
            embed.add_field(name=f'>{group_name}', value=' | '.join(f'`{role}`' for role in group_roles), inline=False)

        return await ctx.send(embed=embed)

    @clearance.command(
        name='roles',
        help='Display the clearance roles and their ids',
        usage='clearance roles',
        examples=['clearance roles'],
        cls=commands.Command
    )
    async def clearance_roles(self, ctx: Context):
        roles = self.bot.clearance.roles
        longest = max([len(name) for name in roles.keys()])
        description = f'Roles in the clearance spreadsheet: {self.bot.clearance.spreadsheet_link}\n\n'
        for role_name, role_id in roles.items():
            description += f'`{role_name:<{longest + 2}} | {role_id}` [<@&{role_id}>]\n'

        await embed_maker.message(
            ctx,
            description=description,
            author={'name': 'Roles'},
            send=True
        )

    @command(
        name='automember',
        help='Enables or disables giving non-patreon users the member role when they get the citizen role',
        usage='automember',
        examples=['automember'],
        cls=commands.Command
    )
    async def auto_member(self, ctx: Context):
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

    @command(
        help='see what roles are whitelisted for an emote or what emotes are whitelisted for a role',
        usage='emote_roles [emote/role]',
        examples=[
            'emote_roles :TldrNewsUK:',
            'emote_roles Mayor'
        ],
        cls=commands.Command
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

    @command(
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
        cls=commands.Command
    )
    async def emote_role(self, ctx: Context, action: str = None, *, args: Union[ParseArgs, dict] = None):
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
        if 'role' not in args or not args['role']:
            return await embed_maker.error(ctx, "Missing role arg")

        if 'emotes' not in args or not args['emotes']:
            return await embed_maker.error(ctx, "Missing emotes arg")

        role = await get_guild_role(ctx.guild, args['role'])
        emotes = args['emotes']

        if not emotes:
            return await embed_maker.command_error(ctx, '[emotes]')

        if not role:
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

    @command(
        help='Archive a ticket channel. Every message will be recorded and put in a google doc',
        usage='archive_channel',
        examples=['archive_channel'],
        cls=commands.Command
    )
    async def archive_channel(self, ctx: Context):
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

        channel_history_string = await self.history_into_string(ctx.guild, channel_history)

        if config.SERVICE_ACCOUNT_FILE:
            try:
                file_url = self.bot.google_drive.upload(channel_history_string, f'{ctx.channel.name} - archive.txt', 'channel archives')
                error = not bool(file_url)
            except Exception as e:
                self.bot.logger.exception(str(e))
                error = True

            if error:
                await embed_maker.error(ctx, 'Error uploading archive file to google drive')
            else:
                return await embed_maker.message(ctx, description=f'File has been been uploaded to google drive: {file_url}', send=True)

        # send file containing archive
        return await ctx.send(file=discord.File(StringIO(channel_history_string), filename='archive.txt'))

    @staticmethod
    def embed_message_to_text(message: discord.Message):
        embed = message.embeds[0]

        # get either title or author
        title = ''
        if embed.title:
            title = embed.title.name if type(embed.title) != str else embed.title
        elif embed.author:
            title = embed.author.name if type(embed.author) != str else embed.author
        # format description
        description = ('\n' if title else '') + embed.description if embed.description else ''

        # convert fields to text
        fields = ""
        for field in embed.fields:
            if fields or description:
                fields += '\n'

            fields += f'{field.name}\n{field.value}'

        # convert values to a multi line message
        text = f"{title}" \
               f"{description}" \
               f"{fields}"

        return text

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

    async def history_into_string(self, guild: discord.Guild, history: list):
        history_string = ''
        for i, message in enumerate(history):
            # fix for a weird error
            if not message or type(message) == str:
                continue

            history_string += f"{message.created_at.strftime('%H:%M:%S | %Y-%m-%d')} - {message.author}"

            if message.content:
                history_string += f'\n"{message.content}"\n'

            # if message has embed, convert the embed to text and add it to channel_history_string
            if message.embeds:
                history_string += f'\n"{self.embed_message_to_text(message)}"\n'

            # if message has attachments add them to channel_history_string
            if message.attachments:
                # if message has contents it needs to have \n at the end
                if message.content:
                    history_string += '\n'

                # gather urls
                urls = "\n".join([a.url for a in message.attachments])
                history_string += f'Attachments: {urls}'

            history_string += '\n'

        # convert mentions like "<@93824009823094832098>" into names
        history_string = self.replace_mentions(guild, history_string)
        return history_string

    async def construct_cc_embed(self, ctx: Context, custom_commands: dict, max_page_num: int, page_size_limit: int, *, page: int):
        if custom_commands:
            custom_commands_str = ''
            for i, command in enumerate(custom_commands[page_size_limit * (page - 1):page_size_limit * page]):
                if i == 10:
                    break

                custom_commands_str += f'**#{i + 1}:** `/{command["name"]}/`\n'
        else:
            custom_commands_str = 'Currently no custom commands have been created'

        member_clearance = self.bot.command_system.member_clearance(ctx.author)
        highest_member_clearance = self.bot.command_system.highest_member_clearance(member_clearance)
        return await embed_maker.message(
            ctx,
            description=custom_commands_str,
            author={'name': f'Custom Commands - {highest_member_clearance}'},
            footer={'text': f'Page {page}/{max_page_num}'}
        )

    @group(
        invoke_without_command=True,
        name='customcommands',
        help='Manage the servers custom commands',
        usage='customcommands (sub command) (args)',
        examples=['customcommands', 'customcommands 1'],
        aliases=['cc'],
        cls=commands.Group
    )
    async def customcommands(self, ctx: Context, index: Union[int, str] = None):
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

                menu = reaction_menus.BookMenu(
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

    async def validate_custom_command_args(self, ctx: Context, args: dict, *, edit: bool = False):
        if not args['name'] and not edit:
            return await embed_maker.error(ctx, "A name needs to be given to the custom command.")

        member_clearance = self.bot.command_system.member_clearance(ctx.author)
        # check for existing custom command with the same name
        existing = db.custom_commands.find_one({'guild_id': ctx.guild.id, 'name': args['name']})
        if existing:
            return await embed_maker.error(ctx, f"A custom command with the name `{args['name']}` already exists")

        if not args['response'] and not edit and not args['python']:
            return await embed_maker.error(ctx, "Missing response arg")

        if args['python'] and 'Developers' not in member_clearance['groups']:
            return await embed_maker.error(ctx, f'Only devs can {"add" if not edit else "edit"} the python arg')

        # validate clearances
        clearance_groups = args['clearance-groups'] = [g.strip() for g in args['clearance-groups'].split(',')]
        clearance_roles = args['clearance-roles'] = [r.strip() for r in args['clearance-roles'].split(',')]
        clearance_users = args['clearance-users'] = [u.strip() for u in args['clearance-users'].split(',')]

        invalid_groups = set(clearance_groups) - set(self.bot.clearance.groups.keys())
        if invalid_groups:
            return await embed_maker.error(ctx, f'Groups {", ".join(f"`{g}`" for g in invalid_groups)} are not in the clearance spreadsheet.')

        invalid_roles = set(clearance_roles) - set(self.bot.clearance.roles.keys())
        if invalid_roles:
            return await embed_maker.error(ctx, f'Roles {", ".join(f"`{r}`" for r in invalid_roles)} are not in the clearance spreadsheet.')

        for user_id in clearance_users:
            if not user_id.isdigit() or not self.bot.get_user(int(user_id)):
                return await embed_maker.error(ctx, f'`{user_id}` is not a valid user id')

        if not clearance_groups and not clearance_roles and not clearance_users:
            args['clearance-roles'] = ['Users']

        # convert response-channel to id
        if args['response-channel']:
            try:
                response_channel = await TextChannelConverter().convert(ctx, args['response-channel'])
                args['response-channel'] = response_channel.id
            except ChannelNotFound:
                return await embed_maker.error(ctx, f'Invalid response-channel arg: `{args["response-channel"]}`')

        # convert command-channels to ids
        if args['command-channels']:
            args['command-channels'] = args['command-channels'].split()
            for i, channel in enumerate(args['command-channels']):
                try:
                    command_channel = await TextChannelConverter().convert(ctx, channel)
                    args['command-channels'][i] = command_channel.id
                except ChannelNotFound:
                    return await embed_maker.error(ctx, f'Invalid command-channel arg: `{channel}`')

        # split reactions into list
        args['reactions'] = args['reactions'].split() if args['reactions'] else []
        # replace surrounding ``` and newline char in response
        if args['response']:
            # for the love of god do not let an ide change this regex
            args['response'] = re.findall(r'^(?:```\n)?(.*)(?:(?:\n```)$)?', args['response'], re.MULTILINE)[0]

        # set clearance to Dev if python arg is defined
        if args['python']:
            args['clearance-groups'] = ['Developers']
            args['clearance-roles'] = []
            args['clearance-users'] = []

        if args['response']:
            # validate command calls in response
            command_matches = re.findall(r'{>(\w+)', args['response'])
            for command_name in command_matches:
                command = self.bot.get_command(command_name)
                if not command:
                    return await embed_maker.error(ctx, f'Invalid command: `>{command_name}`')

        return args

    @staticmethod
    def custom_command_arg_value_to_string(key: str, value: Union[list, str]) -> str:
        # if value is a list, first convert ids into mentions
        if type(value) == list:
            if key == 'command-channels':
                value = [f'<#{c}>' for c in value]
            elif key == 'clearance-users':
                value = [f'<@{v}>' for v in value]
            elif key != 'reactions':
                value = [f'`{v}`' for v in value]
            value = ' | '.join(value)
        # convert response channel id to channel mention
        elif key == 'response-channel':
            value = f'<#{value}>'
        elif key == 'name':
            value = f'`/{value}/`'
        else:
            value = f'`{value}`'

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
                    attributes_str += f'**{key}**: {value}\n'
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
            (('--clearance-groups', '-cg', str), f'[Optional] Restrict who can use the command to groups in the clearance spreadsheet, values need to be seperated via commas.'),
            (('--clearance-roles', '-cr', str), f'[Optional] Restrict who can use the command to roles in the clearance spreadsheet, values need to be seperated via commas.'),
            (('--clearance-users', '-cu', str), '[Optional] Restrict who can use the command to user, values need to be user ids and seperated via commas.'),
            (('--response-channel', '-rc', str), '[Optional] When set, response will be sent in given channel instead of where custom command was called'),
            (('--command-channels', '-cc', str), '[Optional] Restrict custom command to give channel(s)'),
            (('--reactions', '-rs', str), '[Optional] Reactions that will be added to response, emotes only ofc.'),
            (('--python', '-p', str), r'[Dev only] Run a python script when custom command is called, please put code between \`\`\`'),
        ],
        cls=commands.Command
    )
    async def customcommands_add(self, ctx: Context, *, args: ParseArgs = None):
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
            (('--clearance-groups', '-cg', str), f'[Optional] Restrict who can use the command to groups in the clearance spreadsheet, values need to be seperated via commas.'),
            (('--clearance-roles', '-cr', str), f'[Optional] Restrict who can use the command to roles in the clearance spreadsheet, values need to be seperated via commas.'),
            (('--clearance-users', '-cu', str), '[Optional] Restrict who can use the command to user, values need to be user ids and seperated via commas.'),
            (('--response-channel', '-rc', str), '[Optional] When set, response will be sent in given channel instead of where custom command was called'),
            (('--command-channels', '-cc', str), '[Optional] Restrict custom command to give channel(s)'),
            (('--reactions', '-rs', str), '[Optional] Reactions that will be added to response, emotes only ofc.'),
            (('--python', '-p', str), r'[Dev only] Run a python script when custom command is called, please put code between \`\`\`'),
        ],
        cls=commands.Command
    )
    async def customcommands_edit(self, ctx: Context, *, args: ParseArgs = None):
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
        cls=commands.Command
    )
    async def customcommands_remove(self, ctx: Context, index: Union[int, str] = None):
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
        cls=commands.Command
    )
    async def customcommands_variables(self, ctx: Context):
        with open('static/custom_commands_variables.txt', 'r') as file:
            return await embed_maker.message(ctx, description=f'```{file.read()}```', author={'name': 'Custom Command Variables'}, send=True)


def setup(bot):
    bot.add_cog(Admin(bot))
