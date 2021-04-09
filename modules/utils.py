import discord
import re
import asyncio
import config

from typing import Tuple, Union, Optional
from modules import embed_maker, database, cls
from discord.ext import commands

db = database.get_connection()


class Command(commands.Converter):
    """Special class for when used as a type on a command arg, :func:`convert` will be called on the argument."""
    async def convert(self, ctx: commands.Context, argument: str = '') -> Optional[Union[cls.Command, cls.Group]]:
        """
        Converts provided argument to command

        Parameters
        ___________
        ctx: :class:`discord.ext.commands.Context`
            Context, will be used to get member.
        argument: :class:`str`
            Argument passed that will be used as command name when getting command.

        Returns
        -------
        Optional[Union[:class:`modules.cls.Command`, :class:`modules.cls.Group`]]
            Returns command or group command or `None` if nothing is found.
        """
        return ctx.bot.get_command(argument, member=ctx.author)


class ParseArgs(commands.Converter, dict):
    """Special class for when used as a type on a command arg, :func:`convert` will be called on the argument."""
    async def convert(self, ctx: commands.Context, argument: str = '') -> dict:
        """
        Converts provided argument to dictionary of command args and their values.
        Command args are gotten from ctx.command.docs.command_args.

        This uses regex to parse args.

        Parameters
        ___________
        ctx: :class:`discord.ext.commands.Context`
            Context, will be used to command.
        argument: :class:`str`
            Argument passed that will be parsed for args.

        Returns
        -------
        :class:`dict`
            Dictionary of command args and their values.
        """
        result = {}
        # replace short-form args with long-form args
        for arg, _ in ctx.command.docs.command_args:
            argument = re.sub(rf'(?:\s|^)({arg[1]})(?:\s|$)', arg[0], argument)
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


def id_match(identifier: str, extra: str) -> re.Match:
    """
    Matches identifier to discord ID regex and matches given extra regex to identifier

    Parameters
    ___________
    identifier: :class:`str`
        The identifier that will be matched against discord ID regex and given extra regex
    extra: :class:`str`
        Extra regex to match identifier against

    Returns
    -------
    :class:`re.Match`
        Either discord ID match or extra regex match
    """
    id_regex = re.compile(r'([0-9]{15,21})$')
    additional_regex = re.compile(extra)
    return id_regex.match(identifier) or additional_regex.match(identifier)


def get_custom_emote(ctx: commands.Context, emote: str) -> Optional[discord.Emoji]:
    """
    Look up custom emote by id or by name

    Parameters
    ___________
    ctx: :class:`discord.ext.commands.Context`
        Context, used to get emojis.
    emote: :class:`str`
        Either emote name or id.

    Returns
    -------
    Optional[:class:`discord.Emoji`]
        Emoji if one is found, otherwise `None`.
    """
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
            result = discord.utils.get(ctx.guild.emojis, id=int(emoji_id))

        if result is None:
            result = discord.utils.get(ctx.bot.emojis, id=int(emoji_id))

    return result


async def get_guild_role(guild: discord.Guild, role_identifier: str) -> Optional[discord.Role]:
    """
    Get guild's role by its name or id.

    Parameters
    ___________
    guild: :class:`discord.Guild`
        Guild where to search the role from.
    role_identifier: :class:`str`
        Either role name or id.

    Returns
    -------
    Optional[:class:`discord.Role`]
        Role if one is found, otherwise `None`.
    """
    match = id_match(role_identifier, r'<@&([0-9]+)>$')
    if match:
        role = guild.get_role(int(match.group(1)))
    else:
        role = discord.utils.find(lambda rl: rl.name == role_identifier, guild.roles)

    return role


def get_user_clearance(member: discord.Member) -> list:
    """
    Get member's clearance levels.

    Parameters
    ___________
    member: :class:`discord.Member`
        Member's whose clearance levels will be returned

    Returns
    -------
    :class:`list`
        List of member's clearance levels.
    """
    member_clearance = []

    for clearance in config.CLEARANCE:
        if config.CLEARANCE[clearance](member):
            member_clearance.append(clearance)

    return member_clearance


async def get_member_from_string(ctx: commands.Context, string: str) -> Tuple[Optional[discord.Member], str]:
    """
    Get member from the first part of the string and return the remaining string.

    Parameters
    ___________
    ctx: :class:`discord.ext.commands.Context`
        Context.
    string: :class:`str`
        String where the member will be searched from.

    Returns
    -------
    Tuple[Optional[:class:`discord.Member`], :class:`str`]
        Member and remaining string if member is found or `None` and string.
    """
    # check if source is member mention
    if ctx.message.mentions:
        return ctx.message.mentions[0], ' '.join(string.split()[1:])

    member_name = ""
    previous_result = None
    for part in string.split():
        member_match = await get_member(ctx, f'{member_name} {part}'.strip(), multi=False, return_message=False)
        if member_match is None:
            # if both member and previous result are None, nothing can be found from the string, return None and the string
            if previous_result is None:
                return None, string
            # if member is None, but previous result is a list, return Normal get_member call and allow user to choose member
            elif type(previous_result) == list:
                return await get_member(ctx, f'{member_name}'.strip()), string.replace(f'{member_name}'.strip(), '').strip()
            elif previous_result == discord.Member:
                return previous_result, string.replace(f'{member_name}'.strip(), '').strip()
        else:
            # update variables
            previous_result = member_match
            member_name = f'{member_name} {part}'

    return previous_result, string.replace(f'{member_name}'.strip(), '').strip()


async def get_member(ctx: commands.Context, source, *, multi: bool = True, return_message: bool = True) -> Optional[Union[discord.Member, discord.Message, list]]:
    """
    Get member from given source. Source could be id or name.
    Member could also be a mention, so ctx.message.mentions are checked.

    Parameters
    ___________
    ctx: :class:`discord.ext.commands.Context`
        Context.
    source: :class:`str`
        Identifier to which members are matched, can be id or name.
    multi: :class:`bool`
        If true, when multiple matches are found, user will presented with the option and allowed to choose between the members,
        if False, list of matched members will be returned
    return_message :class:`bool`
        If true, when and error is encountered, a message about the error will be returned

    Returns
    -------
    Optional[Union[:class:`discord.Member`, :class`discord.Message`, :class:`list`]]:
        Member if member is found.
        Message if error is encountered and return_message is True.
        List if multiple members are found and multi is False.
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
