import discord
import ast
import config
import copy
import time
import traceback

from discord.ext import commands
from modules import database, cls, embed_maker
from modules.utils import get_member
from bot import TLDR

db = database.Connection()


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
    def __init__(self, bot: TLDR):
        self.bot = bot

    @commands.command(
        help='Time a command',
        usage='time_cmd [command]',
        examples=['time_cmd lb'],
        clearance='Dev',
        cls=cls.Command
    )
    async def time_cmd(self, ctx: commands.Context, *, command_name: str = None):
        if command_name is None:
            return await embed_maker.command_error(ctx)

        command = self.bot.get_command(command_name)
        if command is None:
            return await embed_maker.error(ctx, 'Invalid command')

        msg = copy.copy(ctx.message)
        msg.content = ctx.prefix + command_name
        new_ctx = await self.bot.get_context(msg, cls=type(ctx))

        start = time.perf_counter()
        try:
            await new_ctx.command.invoke(new_ctx)
        except commands.CommandError:
            end = time.perf_counter()
            success = False
            try:
                await ctx.send(f'```py\n{traceback.format_exc()}\n```')
            except discord.HTTPException:
                pass
        else:
            end = time.perf_counter()
            success = True

        colour = 'green' if success else 'red'
        await embed_maker.message(ctx, description=f'Success: {success} | Time: {(end - start) * 1000:.2f}ms', colour=colour, send=True)

    @commands.command(
        help='Run any command as another user',
        usage='sudo [user] [command]',
        examples=['sudo hattyot lb'],
        clearance='Dev',
        cls=cls.Command
    )
    async def sudo(self, ctx: commands.Context, user: str = None, *, cmd: str = None):
        if user is None or cmd is None:
            return await embed_maker.command_error(ctx)

        member = await get_member(ctx, user)
        if member is None:
            return await embed_maker.error(ctx, 'Invalid user')

        msg = copy.copy(ctx.message)
        msg.channel = ctx.channel
        msg.author = member
        msg.content = config.PREFIX + cmd
        new_ctx = await self.bot.get_context(msg, cls=type(ctx))
        await self.bot.invoke(new_ctx)

    @commands.command(
        help='Reload an extension, so you dont have to restart the bot',
        usage='reload_extension [ext]',
        examples=['reload_extension cogs.levels'],
        clearance='Dev',
        aliases=['re'],
        cls=cls.Command,
    )
    async def reload_extension(self, ctx: commands.Context, ext: str):
        if ext in self.bot.extensions.keys():
            self.bot.reload_extension(ext)
            return await embed_maker.message(ctx, description=f'`{ext}` has been reloaded', colour='green', send=True)
        else:
            return await embed_maker.error(ctx, 'That is not a valid extension')

    @commands.command(
        help='Evaluate code',
        usage='eval [code]',
        examples=['eval ctx.author.id'],
        clearance='Dev',
        cls=cls.Command
    )
    async def eval(self, ctx: commands.Context, *, cmd: str = None):
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

        result = repr(await eval(f"{fn_name}()", env))
        # return done if result is empty, so it doesnt cause empty message error
        if result == '':
            result = 'Done'

        await ctx.send(result)

    @commands.command(
        help='Disable a command',
        usage='disable_command',
        examples=['disable_command'],
        clearance='Dev',
        cls=cls.Command
    )
    async def disable_command(self, ctx: commands.Context, command: str = None):
        if command is None:
            return await embed_maker.command_error(ctx)

        cmd_obj = self.bot.get_command(command)
        if cmd_obj is None:
            return await embed_maker.command_error(ctx, '[command]')

        command_data = db.get_command_data(ctx.guild.id, command, insert=True)

        if command_data['disabled']:
            return await embed_maker.error(ctx, f'`{command}` is already disabled')

        db.commands.update_one({'guild_id': ctx.guild.id, 'command_name': cmd_obj.name}, {'$set': {'disabled': 1}})
        return await embed_maker.message(ctx, description=f'`{command}` has been disabled', colour='green', send=True)

    @commands.command(
        help='Enable a command',
        usage='enable_command',
        examples=['enable_command'],
        clearance='Dev',
        cls=cls.Command
    )
    async def enable_command(self, ctx: commands.Context, command: str = None):
        if command is None:
            return await embed_maker.command_error(ctx)

        cmd_obj = self.bot.get_command(command)
        if cmd_obj is None:
            return await embed_maker.command_error(ctx, '[command]')

        command_data = db.get_command_data(ctx.guild.id, command, insert=True)

        if not command_data['disabled']:
            return await embed_maker.error(ctx, f'`{command}` is already enabled')

        db.commands.update_one({'guild_id': ctx.guild.id, 'command_name': cmd_obj.name}, {'$set': {'disabled': 0}})
        command_data['disabled'] = 0
        await embed_maker.message(ctx, description=f'`{command}` has been enabled', colour='green', send=True)

        # check if all data is default, if it is delete the data from db
        if not command_data['disabled'] and not command_data['user_access'] and not command_data['role_access']:
            db.commands.delete_one({'guild_id': ctx.guild.id, 'command_name': cmd_obj.name})


def setup(bot):
    bot.add_cog(Dev(bot))
