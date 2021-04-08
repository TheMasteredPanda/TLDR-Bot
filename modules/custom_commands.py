import discord
import re
import config
import copy

from typing import Optional
from discord.ext import commands
from modules import database
from modules.utils import get_user_clearance

db = database.get_connection()


class User:
    """
    Class for holding user data.

    Attributes
    __________
    id: :class:`int`
        ID of the user.
    name: :class:`str`
        Name of the user.
    mention: :class:`str`
        User's mention: "<@id>".
    avatar: :class:`str`
        Avatar url of the user.
    discrim: :class:`str`
        Discriminator of the user: "#4234".
    nick: :class:`str`
        Nickname of the user.
    """
    def __init__(self, user: discord.Member):
        self.id = user.id
        self.name = user.display_name
        self.mention = user.mention
        self.avatar = user.avatar_url
        self.discrim = user.discriminator
        self.nick = user.nick

    def __getattribute__(self, item):
        if item in ['id', 'name', 'mention', 'avatar', 'discrim', 'nick']:
            return object.__getattribute__(self, item)
        else:
            raise Exception('Accessing forbidden fruit')


class Guild:
    """
    Class for holding guild data.

    Attributes
    __________
    id: :class:`int`
        ID of the guild.
    name: :class:`str`
        Name of the guild.
    avatar: :class:`str`
        Icon url of the user.
    """
    def __init__(self, guild: discord.Guild):
        self.id = guild.id
        self.name = guild.name
        self.icon = guild.icon_url

    def __getattribute__(self, item):
        if item in ['id', 'name', 'icon']:
            return object.__getattribute__(self, item)
        else:
            raise Exception('Accessing forbidden fruit')


class Channel:
    """
    Class for holding channel data.

    Attributes
    __________
    id: :class:`int`
        ID of the channel.
    name: :class:`str`
        Name of the channel.
    mention: :class:`str`
        Mention of the channel: <#id>.
    """
    def __init__(self, channel: discord.TextChannel):
        self.id = channel.id
        self.name = channel.name
        self.mention = channel.mention

    def __getattribute__(self, item):
        if item in ['id', 'name', 'mention']:
            return object.__getattribute__(self, item)
        else:
            raise Exception('Accessing forbidden fruit')


class Message:
    """
    Class for holding message data.

    Attributes
    __________
    id: :class:`int`
        ID of the message.
    content: :class:`str`
        Content of the message.
    link: :class:`str`
        Link to the channel.
    """
    def __init__(self, message: discord.Message):
        self.id = message.id
        self.content = message.content
        self.link = f'https://discordapp.com/channels/{message.guild.id}/{message.channel.id}/{message.id}'

    def __getattribute__(self, item):
        if item in ['id', 'content', 'link']:
            return object.__getattribute__(self, item)
        else:
            raise Exception('Accessing forbidden fruit')


class Role:
    """
    Class for holding role data.

    Attributes
    __________
    id: :class:`int`
        ID of the role.
    name: :class:`str`
        Name of the role.
    colour: :class:`str`
        Colour of the role.
    colour: :class:`str`
        Mention of the role: "<@&id>".
    """
    def __init__(self, role: discord.Role):
        self.id = role.id
        self.name = role.name
        self.colour = role.colour
        self.mention = role.mention

    def __getattribute__(self, item):
        if item in ['id', 'name', 'mention', 'colour']:
            return object.__getattribute__(self, item)
        else:
            raise Exception('Accessing forbidden fruit')


class CustomCommands:
    """
    Handler of custom commands.

    Attributes
    __________
    bot: :class:`bot.TLDR`
        Bot instance.
    """
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def match_message(message: discord.Message) -> Optional[dict]:
        """
        Matches discord message against custom commands.

        Parameters
        ___________
        message: :class:`discord.Message`
            The discord message which's content will be used to match against custom command names.

        Returns
        -------
        :class:`dict`
            A custom command if one is found.
        """
        # using aggregation match custom command "name" value against message content
        match = [*db.custom_commands.aggregate([
            {
                '$addFields': {
                    'regex_match': {
                        '$regexMatch': {
                            'regex': "$name",
                            'input': message.content
                        }
                    }
                },
            },
            {'$match': {'guild_id': message.guild.id, 'regex_match': True}}
        ])]
        if match:
            del match[0]['regex_match']
            return match[0]

    @staticmethod
    async def can_run(ctx: commands.Context, command: dict):
        """
        Checks if ctx.author can run custom command.

        Parameters
        ___________
        ctx: :class:`discord.ext.commands.Context`
            Context
        command: :class:`dict`
            Custom command.

        Returns
        -------
        :class:`dict`
            True if ctx.author can run command, False if not.
        """
        command_channels = command['command_channels'] if command['command_channels'] else []
        roles = command['role'] if command['role'] else []

        # if command is restricted to channel(s), check if command was called in that channel
        channel = ctx.channel.id in command_channels if command_channels else True
        # if command is restricted to role(s), check if author has one of those roles
        role = bool(set(roles) & set([r.id for r in ctx.author.roles])) if roles else True
        # check if user has clearance for the command
        clearance = command['clearance'] in get_user_clearance(ctx.author)

        return channel and role and clearance

    async def get_response(self, ctx: commands.Context, command: dict) -> Optional[str]:
        """
        Replaces all the variables and groups in command response with relevant data.

        Parameters
        ___________
        ctx: :class:`discord.ext.commands.Context`
            Context
        command: :class:`dict`
            Custom command.

        Returns
        -------
        :class:`dict`
            Custom command response if command has response.
        """
        response = command['response']
        if not response:
            return

        # define default values
        values = {
            'user': User(ctx.author),
            'guild': Guild(ctx.guild),
            'channel': Channel(ctx.channel),
            'message': Message(ctx.message)
        }

        # replace $gN type variables with values
        groups = re.findall(command['name'], ctx.message.content)
        for i, group in enumerate(groups[0]):
            response = response.replace(f'$g{i + 1}', group)

        # get list of variables with regex
        variables_list = re.findall(r'({([%*&>]?(?:.\w+\s?)+(?:\.\w+)?)})', response)
        # loop over found variables, done in a loop, so when an error occurs, the invalid variable can be ignored
        for variable, value in variables_list:
            try:
                # if specific user is called for in variable, add the user to values dict
                if value.startswith('%'):
                    user_identifier = value.split('.')[0]
                    if user_identifier not in values:
                        user = await commands.MemberConverter().convert(ctx, user_identifier[1:])
                        values[user_identifier] = User(user)
                # if specific channel is called for in variable, add the channel to values dict
                elif value.startswith('*'):
                    channel_identifier = value.split('.')[0]
                    if channel_identifier not in values:
                        channel = await commands.TextChannelConverter().convert(ctx, channel_identifier[1:])
                        values[channel_identifier] = Channel(channel)
                # if specific role is called for in variable, add the role to values dict
                elif value.startswith('&'):
                    role_identifier = value.split('.')[0]
                    if role_identifier not in values:
                        role = await commands.RoleConverter().convert(ctx, role_identifier[1:])
                        values[role_identifier] = Role(role)
                # if variable is for command, run that command
                elif value.startswith('>'):
                    command_name = value.split(' ')[0]
                    if command_name not in values:
                        # this is kind of a bad way of doing this, but fuck it
                        msg = copy.copy(ctx.message)
                        msg.channel = ctx.channel
                        msg.author = ctx.author
                        msg.content = config.PREFIX + value[1:]
                        new_ctx = await self.bot.get_context(msg, cls=type(ctx))
                        await self.bot.invoke(new_ctx)
                        response = re.sub(rf'\n?{variable}\n?', '', response)

                # replace variable in response with new value
                response = response.replace(variable, variable.format(**values))
            except Exception as e:
                print(e)

        return response
