import discord
import ast
import config
import logging
import psutil
import urllib.request
from discord.ext import commands
from config import DEV_IDS
from modules import database, command, embed_maker
from datetime import datetime

db = database.Connection()
logger = logging.getLogger(__name__)


def is_dev(ctx):
    return ctx.author.id in DEV_IDS


def insert_returns(body):
    if isinstance(body[-1], ast.Expr):
        body[-1] = ast.Return(body[-1].value)
        ast.fix_missing_locations(body[-1])

    if isinstance(body[-1], ast.If):
        insert_returns(body[-1].body)
        insert_returns(body[-1].orelse)

    if isinstance(body[-1], ast.With):
        insert_returns(body[-1].body)


class Dev(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(hidden=True, help='Reload an extension, so you dont have to restart the bot',
                      usage='reload_extension [ext]', examples=['reload_extension cogs.levels'],
                      clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def reload_extension(self, ctx, ext):
        if ext in self.bot.extensions.keys():
            self.bot.reload_extension(ext)
            return await embed_maker.message(ctx, f'{ext} has been reloaded', colour='green')
        else:
            return await embed_maker.message(ctx, 'That is not a valid extension', colour='red')

    @commands.command(hidden=True, help='Evaluate code', usage='eval [code]',
                      examples=['eval ctx.author.id'], clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def eval(self, ctx, *, cmd=None):
        if cmd is None:
            return await embed_maker.command_error(ctx)

        fn_name = "_eval_expr"
        cmd = cmd.strip("` ")

        cmd = "\n".join(f"    {i}" for i in cmd.splitlines())

        body = f"async def {fn_name}():\n{cmd}"

        parsed = ast.parse(body)
        body = parsed.body[0].body

        insert_returns(body)

        env = {
            'bot': ctx.bot,
            'discord': discord,
            'commands': commands,
            'ctx': ctx,
            '__import__': __import__,
            'db': db
        }
        exec(compile(parsed, filename="<ast>", mode="exec"), env)

        result = (await eval(f"{fn_name}()", env))
        await ctx.send(result)

    @commands.command(hidden=True, help='Kill the bot', usage='kill_bot', examples=['kill_bot'], clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def kill_bot(self):
        await self.bot.close()

    @commands.command(hidden=True, help='Disable a command', usage='disable_command', examples=['disable_command'], clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def disable_command(self, ctx, cmd=None):
        if command is None:
            return await embed_maker.command_error(ctx)

        if self.bot.get_command(cmd) is None:
            return await embed_maker.command_error(ctx, '[command]')

        cmd_obj = self.bot.get_command(cmd)

        data = db.server_data.find_one({'guild_id': ctx.guild.id})
        if 'commands' in data and cmd_obj.name in data['commands']['disabled']:
            return await embed_maker.message(ctx, f'{cmd} is already disabled', colour='red')

        db.server_data.update_one({'guild_id': ctx.guild.id}, {'$push': {'commands.disabled': cmd_obj.name}})
        return await embed_maker.message(ctx, f'{cmd} has been disabled', colour='green')

    @commands.command(hidden=True, help='Enable a command', usage='enable_command', examples=['enable_command'], clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def enable_command(self, ctx, cmd=None):
        if command is None:
            return await embed_maker.command_error(ctx)

        if self.bot.get_command(cmd) is None:
            return await embed_maker.command_error(ctx, '[command]')

        cmd_obj = self.bot.get_command(cmd)

        data = db.server_data.find_one({'guild_id': ctx.guild.id})
        if 'commands' not in data and cmd_obj.name not in data['commands']['disabled']:
            return await embed_maker.message(ctx, f'{cmd} is already enabled', colour='red')

        db.server_data.update_one({'guild_id': ctx.guild.id}, {'$pull': {'commands.disabled': cmd_obj.name}})
        return await embed_maker.message(ctx, f'{cmd} has been enabled', colour='green')

    # adds anglorex resource usage monitor
    @commands.command(hidden=True, help='monitors bot resource usage', usage='resrc_usage',
                      examples=['resrc_usage'], clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def resource_usage(self, ctx):
        prefix = config.PREFIX
        embed_colour = config.EMBED_COLOUR
        external_ip = urllib.request.urlopen('https://api.ipify.org/').read().decode('utf8')
        disk_usage = psutil.disk_usage('/')
        resource_overview = discord.Embed(
                colour=embed_colour,
                timestamp=datetime.now()
        )
        resource_overview.set_footer(text=f'{ctx.author.name}#{ctx.author.discriminator}', icon_url=ctx.author.avatar_url)
        resource_overview.set_author(name='Resource Usage Overview', icon_url=ctx.guild.icon_url)
        resource_overview.add_field(name='**CPU Usage**', value=(str(psutil.cpu_percent()) + '%'), inline=False)
        resource_overview.add_field(name='**Memory Usage**', value=(str(psutil.virtual_memory().percent) + '%'), inline=False)
        resource_overview.add_field(name='**External IP**', value=str(external_ip), inline=False)
        resource_overview.add_field(name='**Disk Usage**', value=(str(disk_usage.percent) + '%'), inline=False)
        await ctx.send(embed=resource_overview)


def setup(bot):
    bot.add_cog(Dev(bot))
