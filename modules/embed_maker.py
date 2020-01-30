import discord
from datetime import datetime
from modules import database

db = database.Connection()


def get_colour(colour):
    return {
        'red': discord.Colour.red(),
        'orange': discord.Colour.orange(),
        'green': discord.Colour.green(),
    }.get(colour, 0x00a6ad)


def message(ctx, msg, *, title=None, colour=None):
    if colour is None:
        embed_colour = db.get_server_options('embed_colour', ctx.guild.id)
    else:
        embed_colour = get_colour(colour)

    embed = discord.Embed(colour=embed_colour, description=msg, timestamp=datetime.now())
    embed.set_footer(text=f'{ctx.author.name}#{ctx.author.discriminator}', icon_url=ctx.author.avatar_url)
    if title is not None:
        embed.set_author(name=title, icon_url=ctx.guild.icon_url)

    return embed


async def command_error(ctx, bad_arg=None):
    command = ctx.command
    examples = ', '.join(command.examples)

    if bad_arg is None:
        embed_colour = get_colour('orange')
        description = f'**Description:** {command.help}\n**Usage:** {command.usage}\n**Examples:** {examples}'
    else:
        embed_colour = get_colour('red')
        description = f'**Invalid Argument:** {bad_arg}\n\n**Usage:** {command.usage}\n**Examples:** {examples}'

    embed = discord.Embed(colour=embed_colour, description=description, title=f'>{command.name}')
    embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
    await ctx.send(embed=embed)
