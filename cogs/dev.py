import discord
import ast
import config
import logging
import psutil
import urllib.request
from discord.ext import commands
from config import DEV_IDS
from modules import database, command
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
        
    @commands.command(hidden=True, help='Evaluate code', usage='eval [code]', examples=['eval ctx.author.id'], clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def eval(self, ctx, *, cmd):
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

    @commands.command(hidden=True, help='Pause the bot until further notice', usage='pause', examples=['pause'], clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def pause(self, ctx):
        self.bot.paused = True
        return await ctx.send('bot has been paused and it wont accept commands anymore')

    @commands.command(hidden=True, help='Unpause the bot', usage='unpause', examples=['unpause'], clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def unpause(self, ctx):
        self.bot.paused = False
        return await ctx.send('bot has been unpaused and will continue accepting commands')

    @commands.command(hidden=True, help='Kill the bot', usage='kill_bot', examples=['kill_bot'], clearance='Dev', cls=command.Command)
    @commands.check(is_dev)
    async def kill_bot(self):
        await self.bot.close()

    # adds anglorex resource usage monitor

    @commands.command(hidden=True, help='monitors bot resource usage', usage='resrc_usage', examples=['resrc_usage'], clearance='Dev', cls=command.Command)
    async def resrc_usage(self, ctx):
	    prefix = config.DEFAULT_PREFIX
	    embed_colour = config.DEFAULT_EMBED_COLOUR
	    external_ip = urllib.request.urlopen('https://api.ipify.org/').read().decode('utf8')
	    disk_usage = psutil.disk_usage('/')
	    resource_overview = discord.Embed(
			    title = "Resource Usage Overview",
			    colour = embed_colour, 
			    timestamp = datetime.now()
	    )
	    resource_overview.set_footer(text=f'Updates whenever this command is invoked', icon_url=ctx.author.avatar_url)
	    resource_overview.set_author(name=f'{ctx.author}', icon_url=ctx.author.avatar_url)
	    resource_overview.add_field(name='**CPU Usage**', value=(str(psutil.cpu_percent()) + '%'), inline=False)
	    resource_overview.add_field(name='**Memory Usage**', value=(str(psutil.virtual_memory().percent) + '%'), inline=False)
	    resource_overview.add_field(name='**External IP**', value=str(external_ip), inline=False)
	    resource_overview.add_field(name='**Disk Usage**', value=(str(disk_usage.percent) + '%'), inline=False)
	    await ctx.send(embed=resource_overview)

def setup(bot):
    bot.add_cog(Dev(bot))
