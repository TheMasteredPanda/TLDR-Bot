import copy
import re
from typing import Optional

import config
import discord
from discord.ext.commands import (Context, MemberConverter, RoleConverter,
                                  TextChannelConverter)

from modules import database

db = database.get_connection()


class User:
    """
    Class for holding user data.

    This class is for custom command variables to grant limited access to certain user values.

    Attributes
    ---------------
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
        self.avatar = user.display_avatar.url
        self.discrim = user.discriminator
        self.nick = user.nick

    def __getattribute__(self, item):
        if item in ["id", "name", "mention", "avatar", "discrim", "nick"]:
            return object.__getattribute__(self, item)
        else:
            raise Exception("Accessing forbidden fruit")


class Guild:
    """
    Class for holding guild data.

    This class is for custom command variables to grant limited access to certain guild values.

    Attributes
    ---------------
    id: :class:`int`
        ID of the guild.
    name: :class:`str`
        Name of the guild.
    icon: :class:`str`
        Icon url of the user.
    """

    def __init__(self, guild: discord.Guild):
        self.id = guild.id
        self.name = guild.name
        self.icon = guild.icon.url

    def __getattribute__(self, item):
        if item in ["id", "name", "icon"]:
            return object.__getattribute__(self, item)
        else:
            raise Exception("Accessing forbidden fruit")


class Channel:
    """
    Class for holding channel data.

    This class is for custom command variables to grant limited access to certain channel values.

    Attributes
    ---------------
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
        if item in ["id", "name", "mention"]:
            return object.__getattribute__(self, item)
        else:
            raise Exception("Accessing forbidden fruit")


class Message:
    """
    Class for holding message data.

    This class is for custom command variables to grant limited access to certain message values.

    Attributes
    ---------------
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
        self.link = f"https://discordapp.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"

    def __getattribute__(self, item):
        if item in ["id", "content", "link"]:
            return object.__getattribute__(self, item)
        else:
            raise Exception("Accessing forbidden fruit")


class Role:
    """
    Class for holding role data.

    This class is for custom command variables to grant limited access to certain role values.

    Attributes
    ---------------
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
        if item in ["id", "name", "mention", "colour"]:
            return object.__getattribute__(self, item)
        else:
            raise Exception("Accessing forbidden fruit")


class CustomCommands:
    """
    Handler of custom commands.

    Attributes
    ---------------
    bot: :class:`bot.TLDR`
        Bot instance.
    """

    def __init__(self, bot):
        self.bot = bot
        self.bot.logger.info("CustomCommands module has been initiated")

    @staticmethod
    def match_message(message: discord.Message) -> Optional[dict]:
        """
        Matches discord message against custom commands.

        Parameters
        ----------------
        message: :class:`discord.Message`
            The discord message which's content will be used to match against custom command names.

        Returns
        -------
        :class:`dict`
            A custom command if one is found.
        """
        # using aggregation match custom command "name" value against message content
        custom_commands = db.custom_commands.find({"guild_id": message.guild.id})
        for cc in custom_commands:
            if re.findall(cc["name"], message.content):
                return cc

    async def can_use(self, ctx: Context, command: dict):
        """
        Checks if ctx.author can run custom command.

        Parameters
        ----------------
        ctx: :class:`discord.ext.commands.Context`
            Context
        command: :class:`dict`
            Custom command.

        Returns
        -------
        :class:`dict`
            True if ctx.author can run command, False if not.
        """
        print(command)
        command_channels = (
            command["command-channels"] if command["command-channels"] else []
        )

        # if command is restricted to channel(s), check if command was called in that channel
        channel = ctx.channel.id in command_channels if command_channels else True
        # check if user has clearance for the command
        member_clearance = self.bot.clearance.member_clearance(ctx.author)
        command_clearance = {
            "groups": command["clearance-groups"],
            "roles": command["clearance-roles"],
            "users": command["clearance-users"],
        }
        can_use = (
            self.bot.clearance.member_has_clearance(member_clearance, command_clearance)
            and channel
        )

        return can_use

    async def get_response(self, ctx: Context, command: dict) -> Optional[str]:
        """
        Replaces all the variables and groups in command response with relevant data.

        Parameters
        ----------------
        ctx: :class:`discord.ext.commands.Context`
            Context
        command: :class:`dict`
            Custom command.

        Returns
        -------
        :class:`dict`
            Custom command response if command has response.
        """
        response = command["response"]
        if not response:
            return

        # define default values
        values = {
            "user": User(ctx.author),
            "guild": Guild(ctx.guild),
            "channel": Channel(ctx.channel),
            "message": Message(ctx.message),
        }

        # replace $gN type variables with values
        groups = re.findall(command["name"], ctx.message.content)
        for i, group in enumerate(groups[0] if type(groups[0]) == tuple else groups):
            response = response.replace(f"$g{i + 1}", group)

        # get list of variables with regex
        variables_list = re.findall(r"({([%*&>]?(?:.+\s?)+(?:\..+)?)})", response)
        # loop over found variables, done in a loop, so when an error occurs, the invalid variable can be ignored
        for variable, value in variables_list:
            try:
                # if specific user is called for in variable, add the user to values dict
                if value.startswith("%"):
                    user_identifier = value.split(".")[0]
                    if user_identifier not in values:
                        user = await MemberConverter().convert(ctx, user_identifier[1:])
                        values[user_identifier] = User(user)
                # if specific channel is called for in variable, add the channel to values dict
                elif value.startswith("*"):
                    channel_identifier = value.split(".")[0]
                    if channel_identifier not in values:
                        channel = await TextChannelConverter().convert(
                            ctx, channel_identifier[1:]
                        )
                        values[channel_identifier] = Channel(channel)
                # if specific role is called for in variable, add the role to values dict
                elif value.startswith("&"):
                    role_identifier = value.split(".")[0]
                    if role_identifier not in values:
                        role = await RoleConverter().convert(ctx, role_identifier[1:])
                        values[role_identifier] = Role(role)
                # if variable is for command, run that command
                elif value.startswith(">"):
                    command_name = value.split(" ")[0]
                    if command_name not in values:
                        # this is kind of a bad way of doing this, but fuck it
                        msg = copy.copy(ctx.message)
                        msg.channel = ctx.channel
                        msg.author = ctx.author
                        msg.content = config.PREFIX + value[1:]
                        new_ctx = await self.bot.get_context(msg, cls=type(ctx))
                        await self.bot.invoke(new_ctx)
                        response = response.replace(f"{variable}", "")
                        continue

                # replace variable in response with new value
                response = response.replace(variable, variable.format(**values))
            except Exception as e:
                self.bot.logger.exception(str(e))

        return response
