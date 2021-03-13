import discord
import config

from typing import Union
from datetime import datetime
from discord.ext.commands import Context


def get_colour(colour):
    return {
        'red': discord.Colour.red(),
        'orange': discord.Colour.orange(),
        'green': discord.Colour.green(),
    }.get(colour, config.EMBED_COLOUR)


async def message(
        ctx: Union[Context, discord.Message], *,
        description: str = None,
        author: dict = None,
        footer: dict = None,
        colour: str = None,
        title: str = None,
        send: bool = False
):
    embed_colour = config.EMBED_COLOUR if colour is None else get_colour(colour)
    embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())

    if description:
        embed.description = description

    if author:
        # set icon_url to guild icon if one isn't provided
        icon_url = author['icon_url'] if 'icon_url' in author else ctx.guild.icon_url
        embed.set_author(name=author['name'], icon_url=icon_url)

    if footer:
        # set icon_url to None if one isn't provided
        icon_url = footer['icon_url'] if 'icon_url' in footer else ctx.author.avatar_url
        embed.set_footer(text=footer['text'], icon_url=icon_url)
    else:
        embed.set_footer(text=str(ctx.author), icon_url=ctx.author.avatar_url)

    if title:
        embed.title = title

    if send:
        return await ctx.send(embed=embed)

    return embed


async def error(ctx: Context, description, **kwargs):
    return await message(ctx, description=description, colour='red', send=True, **kwargs)


async def command_error(ctx, bad_arg=None):
    examples_str = '\n'.join(ctx.command.docs.examples)
    if bad_arg is None:
        embed_colour = get_colour('orange')
        description = f'**Description:** {ctx.command.docs.help}\n**Usage:** {ctx.command.docs.usage}\n**Examples:** {examples_str}'
    else:
        embed_colour = get_colour('red')
        description = f'**Invalid Argument:** {bad_arg}\n\n**Usage:** {ctx.command.docs.usage}\n**Examples:** {examples_str}'

    if hasattr(ctx.command.docs, 'sub_commands'):
        sub_commands_str = '\n**Sub Commands:** ' + ' | '.join(s for s in ctx.command.docs.sub_commands)
        sub_commands_str += f'\n\nTo view more info about sub commands, type `{ctx.prefix}help {ctx.command.name} [sub command]`'
        description += sub_commands_str

    embed = discord.Embed(colour=embed_colour, description=description, title=f'>{ctx.command.name}', timestamp=datetime.now())
    embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
    return await ctx.send(embed=embed)
