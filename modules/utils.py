import discord
import re
import asyncio
import config
import time

from typing import Optional, Tuple, Union
from modules import embed_maker, database
from discord.ext import commands

db = database.Connection()


class Command(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str = ''):
        return ctx.bot.get_command(argument, member=ctx.author)


class Role(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str = ''):
        if not ctx.guild:
            return argument

        # check if role is in a leveling route before fetching discord role
        branch, role = get_branch_role(ctx.guild.id, argument)
        if not branch or not role:
            return argument

        # make sure the role actually exists on the guild
        await get_leveling_role(ctx.guild, argument)

        return role


class Branch(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str = ''):
        branch_switch = {'p': 'parliamentary', 'h': 'honours'}
        return branch_switch.get(argument[0], 'parliamentary')


class ParseArgs(commands.Converter, dict):
    async def convert(self, ctx: commands.Context, argument: str = '') -> dict:
        result = {}
        # replace short-form args with long-form args
        for arg, _ in ctx.command.docs.command_args:
            argument = re.sub(arg[1], arg[0], argument)
            result[arg[0][2:]] = None

        # create regex to match command args
        regex = rf'--({"|".join(arg[0][2:] for arg, _, in ctx.command.docs.command_args)})'
        split_argument = re.split(regex, argument)
        result['pre'] = split_argument.pop(0)

        for arg, data in zip(split_argument[::2], split_argument[1::2]):
            data_type = next(filter(lambda x: x[0][0] == f'--{arg}', ctx.command.docs.command_args))[0][2]
            if not result[arg]:
                try:
                    if data_type == list:
                        result[arg] = [data.strip()]
                    else:
                        result[arg] = data_type(data.strip())
                except ValueError:
                    pass
            elif type(result[arg]) == list:
                result[arg].append(data.strip())

        return result


def id_match(identifier, extra):
    id_regex = re.compile(r'([0-9]{15,21})$')
    additional_regex = re.compile(extra)

    # check if role_identifier is id
    return id_regex.match(identifier) or additional_regex.match(identifier)


def get_custom_emote(ctx, emote):
    match = id_match(emote, r'<a?:[a-zA-Z0-9\_]+:([0-9]+)>$')
    result = None

    if match is None:
        # Try to get the emoji by name. Try local guild first.
        if ctx.guild:
            result = discord.utils.get(ctx.guild.emojis, name=emote)

        if result is None:
            result = discord.utils.get(ctx.bot.emojis, name=emote)
    else:
        emoji_id = int(match.group(1))

        # Try to look up emoji by id.
        if ctx.guild:
            result = discord.utils.get(ctx.guild.emojis, id=emoji_id)

        if result is None:
            result = discord.utils.get(ctx.bot.emojis, id=emoji_id)

    return result


def get_user_boost_multiplier(member):
    multiplier = 0

    leveling_user = db.get_leveling_user(member.guild.id, member.id)
    if 'boosts' not in leveling_user:
        return multiplier

    user_boosts = leveling_user['boosts']
    for boost_type, boost_data in user_boosts.items():
        expires = boost_data['expires']
        if round(time.time()) > expires:
            db.leveling_users.update_one(
                {'guild_id': member.guild.id, 'user_id': member.id},
                {'$unset': {f'boosts.{boost_type}': 1}}
            )
            continue

        multiplier += boost_data['multiplier']

    return multiplier


async def get_guild_role(guild: discord.Guild, role_identifier: str):
    match = id_match(role_identifier, r'<@&([0-9]+)>$')
    if match:
        role = guild.get_role(int(match.group(1)))
    else:
        role = discord.utils.find(lambda rl: rl.name == role_identifier, guild.roles)

    return role


async def get_leveling_role(guild: discord.Guild, role_identifier: str, member: discord.Member = None) -> discord.Role:
    # check if role_identifier is id
    role = await get_guild_role(guild, role_identifier)
    if role is None:
        role = await guild.create_role(name=role_identifier)

    if member and role not in member.roles:
        # give member role to non-patreon users if they are given the citizen role
        # also check if this feature has been enabled
        automember = db.get_automember(member.guild.id)
        if automember and role.id == 697184342614474785 and 644182117051400220 not in [r.id for r in member.roles]:
            member_role = discord.utils.find(lambda r: r.id == 662036345526419486, member.guild.roles)
            await member.add_roles(member_role)

        await member.add_roles(role)

    return role


def get_branch_role(guild_id: int, role_name: str) -> tuple:
    leveling_data = db.get_leveling_data(guild_id, {'leveling_routes': 1})
    leveling_routes = leveling_data['leveling_routes']

    all_roles = leveling_routes['parliamentary'] + leveling_routes['honours']

    role = next((role for role in all_roles if role['name'].lower() == role_name.lower()), None)

    if role in leveling_routes['parliamentary']:
        branch = 'parliamentary'
    else:
        branch = 'honours'

    return branch, role


def get_user_clearance(member: discord.Member) -> list:
    member_clearance = []

    for clearance in config.CLEARANCE:
        if config.CLEARANCE[clearance](member):
            member_clearance.append(clearance)

    return member_clearance


async def get_member_from_string(ctx: commands.Context, string: str, *, multi: bool = True) -> Union[Tuple[Union[discord.Member, None], str], None]:
    member_name = ""
    previous_result = None
    for part in string.split():
        member_match = await get_member(ctx, f'{member_name} {part}'.strip(), multi=False, return_message=False)
        if member_match is None:
            # if both member and previous result are None, nothing can be found from the string, return None and the string
            if previous_result is None:
                return None, string
            # if member is None, but previous result is a list, return Normal get_member call and allow user to choose member
            elif type(previous_result) == list and multi:
                return await get_member(ctx, f'{member_name}'.strip()), string.replace(f'{member_name}'.strip(), '').strip()
            # if multi is false, return error message
            elif type(previous_result) == list and not multi:
                return await embed_maker.error(ctx, 'Multiple user matches found.')
            elif previous_result == discord.Member:
                return previous_result, string.replace(f'{member_name}'.strip(), '').strip()
        else:
            # update variables
            previous_result = member_match
            member_name = f'{member_name} {part}'

    return previous_result, string.replace(f'{member_name}'.strip(), '').strip()


async def get_member(ctx: commands.Context, source, *, multi: bool = True, return_message: bool = True) -> Union[discord.Member, discord.Message, list, None]:
    """
    :param ctx: context
    :param source: identifier to which members are matched, can be id, member mention or name
    :param multi: If true, when multiple matches are found, user will presented the option and allowed to choose, if False, list of matched members will be returned
    :param return_message: If true, when and error is encountered, a message about the error will be returned
    """
    # just in case source is empty
    if not source:
        return await embed_maker.error(ctx, 'Input is empty') if return_message else None

    if type(source) == int:
        source = str(source)

    # check if source is member mention
    if ctx.message.mentions:
        return ctx.message.mentions[0]

    # Check if source is member id
    if source.isdigit() and len(source) > 9:
        member = ctx.guild.get_member(int(source))

        # if member isn't found by get, maybe they aren't in the cache, fetch them by making an api call
        if not member:
            try:
                # if member hasnt been cached yet, fetching them should work, if member is inaccessible, it will return None
                member = await ctx.guild.fetch_member(int(source))
                if member is None:
                    return await embed_maker.error(ctx, f'Member not found by ID: `{source}`') if return_message else None
            except discord.Forbidden:
                return await embed_maker.error(ctx, 'Bot does not have access to the guild members') if return_message else None
            except discord.HTTPException:
                return await embed_maker.error(ctx, f'Member not found by id: `{source}`') if return_message else None

        if member:
            return member

    # if source length is less than 3, don't bother searching, too many matches will come
    if len(source) < 3:
        return await embed_maker.error(ctx, 'User name input needs to be at least 3 characters long') if return_message else None

    # checks first for a direct name match
    members = list(
        filter(
            lambda m: m.name.lower() == source.lower() or  # username match
                      m.display_name.lower() == source.lower() or  # nickname match (if user doesnt have a nickname, it'll match the name again)
                      str(m).lower() == source.lower(),  # name and discriminator match
            ctx.guild.members
        )
    )

    # if can't find direct name match, check for a match with regex
    if not members:
        # checks for regex match
        members = list(
            filter(
                lambda m: re.findall(fr'({source.lower()})', str(m).lower()) or  # regex match name and discriminator
                          re.findall(fr'({source.lower()})', m.display_name.lower()),  # regex match nickname
                ctx.guild.members
            )
        )

        if not members:
            return await embed_maker.error(ctx, f'No members found by the name `{source}`') if return_message else None

    # too many matches
    if len(members) > 10 and multi:
        return await embed_maker.error(ctx, 'Too many user matches') if return_message else None

    # only one match, return member
    if len(members) == 1:
        return members[0]
    elif not multi:
        return members

    # send embed containing member matches and let member choose which one they meant
    description = 'Found multiple users, which one did you mean? `type index of member`\n\n'
    for i, member in enumerate(members):
        description += f'`#{i + 1}` | {member.display_name}#{member.discriminator}'

        # also display members nickname, if member has one
        if member.nick:
            description += f' - [{member.name}#{member.discriminator}]'

        description += '\n'

    # generate embed
    users_embed_message = await embed_maker.message(
        ctx,
        description=description,
        author={'name': 'Members'},
        footer={'text': str(ctx.author), 'icon_url': ctx.author.avatar_url},
        send=True
    )

    # function that validates member input
    def input_check(m):
        return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.isdigit()

    # wait for member input
    try:
        user_message = await ctx.bot.wait_for('message', check=input_check, timeout=20)
        await users_embed_message.delete(delay=5)
        index = user_message.content
        if index.isdigit() and len(members) >= int(index) - 1 >= 0:
            return members[int(index) - 1]
        elif not index.isdigit():
            return await embed_maker.error(ctx, 'Input is not a number')
        elif int(index) - 1 > len(members) or int(index) - 1 < 0:
            return await embed_maker.error(ctx, 'Input number out of range')

    except asyncio.TimeoutError:
        await users_embed_message.delete()
        return await embed_maker.error(ctx, 'Timeout')
