import discord
from discord.ext import commands
from config import DEV_IDS
from modules import database, embed_maker, command
from datetime import datetime

db = database.Connection()


def get_user_clearence(ctx):
    user_permissions = ctx.channel.permissions_for(ctx.author)
    clearance = []

    if ctx.author.id in DEV_IDS:
        clearance.append('Dev')
    if user_permissions.administrator:
        clearance.append('Admin')
    if user_permissions.manage_messages:
        clearance.append('Mod')
    clearance.append('User')

    return clearance


class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(descrition='Get help smh', usage='help (command)', examples=['help', 'help ping'], clearence='User', cls=command.Command)
    async def help(self, ctx, command=None):
        embed_colour = db.get_embed_colour(ctx.guild.id)
        prefix = db.get_prefix(ctx.guild.id)
        commands = self.bot.commands
        help_object = {}
        for cmd in commands:
            if cmd.cog_name not in help_object:
                help_object[cmd.cog_name] = [cmd]
            else:
                help_object[cmd.cog_name].append(cmd)

        clearence = get_user_clearence(ctx)
        if command is None:
            embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=f'**Prefix** : `{prefix}`\nFor additional info on a command, type `{prefix}help [command]`')
            embed.set_author(name=f'Help - {clearence[0]}', icon_url=ctx.guild.icon_url)
            embed.set_footer(text=f'{ctx.author.name}#{ctx.author.discriminator}', icon_url=ctx.author.avatar_url)
            for cat in help_object:
                cat_commands = []
                for cmd in help_object[cat]:
                    if cmd.clearence in clearence:
                        cat_commands.append(f'`{cmd}`')

                if cat_commands:
                    embed.add_field(name=f'>{cat}', value=" \| ".join(cat_commands), inline=False)

            return await ctx.send(embed=embed)
        else:
            if self.bot.get_command(command):
                command = self.bot.get_command(command)
                examples = f'\n{prefix}'.join(command.examples)
                cmd_help = f"""
                Description: {command.description}
                Usage: {prefix}{command.usage}
                Examples: {prefix}{examples}
                """
                embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=cmd_help)
                embed.set_author(name=f'Help - {command}', icon_url=ctx.guild.icon_url)
                embed.set_footer(text=f'{ctx.author.name}#{ctx.author.discriminator}',
                                 icon_url=ctx.author.avatar_url)
                return await ctx.send(embed=embed)
            else:
                embed = embed_maker.message(ctx, f'{command} is not a valid command')
                return await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(General(bot))
