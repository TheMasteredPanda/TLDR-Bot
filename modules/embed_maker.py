import discord
import config
from datetime import datetime


def get_colour(colour):
    return {
        'red': discord.Colour.red(),
        'orange': discord.Colour.orange(),
        'green': discord.Colour.green(),
    }.get(colour, config.EMBED_COLOUR)


async def message(ctx, msg, *, title=None, footer=None, colour=None):
    embed_colour = config.EMBED_COLOUR if colour is None else get_colour(colour)

    embed = discord.Embed(colour=embed_colour, description=msg, timestamp=datetime.now())
    embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

    if title:
        embed.set_author(name=title, icon_url=ctx.guild.icon_url)
    if footer:
        embed.set_footer(text=footer)

    return await ctx.send(embed=embed)


async def command_error(ctx, bad_arg=None):
    command = ctx.command
    examples_str = '\n'.join(command.examples)
    if bad_arg is None:
        embed_colour = get_colour('orange')
        description = f'**Description:** {command.help}\n**Usage:** {command.usage}\n**Examples:** {examples_str}'
    else:
        embed_colour = get_colour('red')
        description = f'**Invalid Argument:** {bad_arg}\n\n**Usage:** {command.usage}\n**Examples:** {examples_str}'

    embed = discord.Embed(colour=embed_colour, description=description, title=f'>{command.name}', timestamp=datetime.now())
    embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
    return await ctx.send(embed=embed)
