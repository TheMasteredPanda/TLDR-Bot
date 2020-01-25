import discord
from datetime import datetime
from modules import database

db = database.Connection()


def message(ctx, msg, title=None):
    embed_colour = db.get_embed_colour(ctx.guild.id)
    embed = discord.Embed(colour=embed_colour, description=msg, timestamp=datetime.now())
    embed.set_footer(text=f'{ctx.author.name}#{ctx.author.discriminator}', icon_url=ctx.author.avatar_url)
    if title is not None:
        embed.set_author(name=title, icon_url=ctx.guild.icon_url)

    return embed


async def command_error(ctx, bad_arg = None):
    command = ctx.command
    cog = command.cog
    command_info = cog.info['Commands'][command.name]
    embed_colour = db.get_embed_colour(ctx.guild.id)

    examples = ', '.join(command_info['Examples'])
    if bad_arg is None:
        description = f"""
        Command: `{command}`
        
        Description: `{command_info['Description']}`
        Usage: `{command_info['Usage']}`
        Examples: `{examples}`
        """
    else:
        description = f"""
        Invalid Argument: `{bad_arg}`
    
        Usage: `{command_info['Usage']}`
        Examples: `{examples}`
        """

    embed = discord.Embed(colour = embed_colour, description = description)
    embed.set_footer(text = f'{ctx.author}', icon_url = ctx.author.avatar_url)
    await ctx.send(embed = embed)
