import discord
from datetime import datetime
from modules import database

db = database.Connection()


def message(ctx, msg, title=None):
    embed_colour = db.get_server_options(ctx.guild.id, 'embed_colour')
    embed = discord.Embed(colour=embed_colour, description=msg, timestamp=datetime.now())
    embed.set_footer(text=f'{ctx.author.name}#{ctx.author.discriminator}', icon_url=ctx.author.avatar_url)
    if title is not None:
        embed.set_author(name=title, icon_url=ctx.guild.icon_url)

    return embed


async def command_error(ctx, bad_arg=None):
    command = ctx.command
    embed_colour = db.get_server_options(ctx.guild.id, 'embed_colour')

    examples = ', '.join(command.examples)
    if bad_arg is None:
        description = f'**Description:** {command.help}\n**Usage:** {command.usage}\n**Examples:** {examples}'
    else:
        description = f'**Invalid Argument:** {bad_arg}\n\n**Usage:** {command.usage}\n**Examples:** {examples}'

    embed = discord.Embed(colour=embed_colour, description=description, title=f'>{command.name}')
    embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
    await ctx.send(embed=embed)
