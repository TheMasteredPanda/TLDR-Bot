from datetime import datetime
from typing import Union

import config
import discord
from discord.ext.commands import Context
from discord.ui import View

from modules import commands


def get_colour(colour: str):
    """Converts colour name to :class:`discord.Colour` colour"""
    return {
        "red": discord.Colour.red(),
        "orange": discord.Colour.orange(),
        "green": discord.Colour.green(),
    }.get(colour, config.EMBED_COLOUR)


async def message(
    ctx: Union[Context, discord.Message],
    *,
    description: str = None,
    author: dict = None,
    footer: dict = None,
    colour: str = None,
    title: str = None,
    view: View = None,
    send: bool = False,
) -> Union[discord.Message, discord.Embed]:
    """
    A function to easily create embeds with a certain look.

    Parameters
    ----------------
    ctx: :class:`discord.ext.commands.Context`
        discord context.
    description: :class:`str`
        Description for the embed
    author: :class:`dict`
        Dict with author name and icon_url. If icon_url isn't given, will default to ctx.guild.icon_url
    footer: :class:`dict`
        Dict with footer text and icon_url. If icon_url isn't given, will default to ctx.avatar.icon_url
    colour: :class:`str`
        Colour for the embed
    title: :class:`str`
        Title for the embed
    send: :class:`Bool`
        If true, will send the embed to ctx.channel instead of returning the created embed.

    Returns
    -------
    Union[:class:`discord.Embed`, :class:`discord.Message`]
        Will return either the created embed or message, depending if `send` is true
    """
    embed_colour = config.EMBED_COLOUR if colour is None else get_colour(colour)
    embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())

    if description:
        embed.description = description

    if author:
        # set icon_url to guild icon if one isn't provided
        icon_url = author["icon_url"] if "icon_url" in author else ctx.guild.icon
        embed.set_author(name=author["name"], icon_url=icon_url)

    if footer:
        # set icon_url to None if one isn't provided
        icon_url = footer["icon_url"] if "icon_url" in footer else ctx.author.avatar
        embed.set_footer(text=footer["text"], icon_url=icon_url)
    else:
        embed.set_footer(text=str(ctx.author), icon_url=ctx.author.avatar)

    if title:
        embed.title = title

    if send:
        if view:
            return await ctx.send(embed=embed, view=view)
        else:
            return await ctx.send(embed=embed)

    return embed


async def error(ctx: Context, description, **kwargs):
    """
    A simple function to easily create error embeds with a certain look.
    Default colour is red and send is True.

    Parameters
    ----------------
    ctx: :class:`discord.ext.commands.Context`
        discord context.
    description: :class:`str`
        Description for the error embed
    **kwargs: :class:`dict`
        kwargs that will be passed onto :func:`message`

    Returns
    -------
    :class:`discord.Message`
        Will return message
    """
    return await message(
        ctx, description=description, colour="red", send=True, **kwargs
    )


async def command_error(ctx, bad_arg: str = None):
    """
    A simple function to easily create command error embeds with a certain look and info about ctx.command.

    Parameters
    ----------------
    ctx: :class:`discord.ext.commands.Context`
        discord context.
    bad_arg: :class:`str`
        Arg that can be given that will be displayed as "Invalid Argument: {bad_arg}"

    Returns
    -------
    :class:`discord.Message`
        Will return message
    """
    examples_str = "\n".join(ctx.command.docs.examples)
    if bad_arg is None:
        embed_colour = get_colour("orange")
        description = f"**Description:** {ctx.command.docs.help}\n**Usage:** {ctx.command.docs.usage}\n**Examples:** {examples_str}"
    else:
        embed_colour = get_colour("red")
        description = f"**Invalid Argument:** {bad_arg}\n\n**Usage:** {ctx.command.docs.usage}\n**Examples:** {examples_str}"

    if type(ctx.command) == commands.Group and ctx.command.all_commands:
        sub_commands = ctx.command.sub_commands(member=ctx.author)
        if sub_commands:
            sub_commands_str = "**\nSub Commands:** " + " | ".join(
                sc.name for sc in sub_commands
            )
            sub_commands_str += f"\nTo view more info about sub commands, type `{ctx.prefix}help {ctx.command.name} [sub command]`"
            description += sub_commands_str

    if ctx.command.docs.command_args:
        command_args_str = (
            "**\nCommand Args:**\n```"
            + "\n\n".join(
                f"({arg[0]}, {arg[1]}) - {description}"
                for arg, description in ctx.command.docs.command_args
            )
            + "```"
        )
        description += command_args_str

    embed = discord.Embed(
        colour=embed_colour,
        description=description,
        title=f">{ctx.command.name}",
        timestamp=datetime.now(),
    )
    embed.set_footer(text=f"{ctx.author}", icon_url=ctx.author.avatar)
    return await ctx.send(embed=embed)
