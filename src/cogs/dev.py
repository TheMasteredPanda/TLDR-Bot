import discord
import ast
import config
import copy
import time
import traceback

from discord.ext.commands import Cog, command, Context, CommandError
from modules import database, commands, embed_maker
from modules.utils import get_member
from bot import TLDR

db = database.get_connection()


def insert_returns(body):
    if isinstance(body[-1], ast.Expr):
        body[-1] = ast.Return(body[-1].value)
        ast.fix_missing_locations(body[-1])

    if isinstance(body[-1], ast.If):
        insert_returns(body[-1].body)
        insert_returns(body[-1].orelse)

    if isinstance(body[-1], ast.With):
        insert_returns(body[-1].body)


class Dev(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @command(
        help="Time a command",
        usage="time_cmd [command]",
        examples=["time_cmd lb"],
        cls=commands.Command,
    )
    async def time_cmd(self, ctx: Context, *, command_name: str = None):
        if command_name is None:
            return await embed_maker.command_error(ctx)

        command = self.bot.get_command(command_name)
        if command is None:
            return await embed_maker.error(ctx, "Invalid command")

        msg = copy.copy(ctx.message)
        msg.content = ctx.prefix + command_name
        new_ctx = await self.bot.get_context(msg, cls=type(ctx))

        start = time.perf_counter()
        try:
            await new_ctx.command.invoke(new_ctx)
        except CommandError:
            end = time.perf_counter()
            success = False
            try:
                await ctx.send(f"```py\n{traceback.format_exc()}\n```")
            except discord.HTTPException:
                pass
        else:
            end = time.perf_counter()
            success = True

        colour = "green" if success else "red"
        await embed_maker.message(
            ctx,
            description=f"Success: {success} | Time: {(end - start) * 1000:.2f}ms",
            colour=colour,
            send=True,
        )

    @command(
        help="Run any command as another user",
        usage="sudo [user] [command]",
        examples=["sudo hattyot lb"],
        cls=commands.Command,
    )
    async def sudo(self, ctx: Context, user: str = None, *, cmd: str = None):
        if user is None or cmd is None:
            return await embed_maker.command_error(ctx)

        member = await get_member(ctx, user)
        if member is None:
            return await embed_maker.error(ctx, "Invalid user")

        msg = copy.copy(ctx.message)
        msg.channel = ctx.channel
        msg.author = member
        msg.content = config.PREFIX + cmd
        await self.bot.process_command(msg)

    @command(
        help="Reload an extension, so you dont have to restart the bot",
        usage="reload_extension [ext]",
        examples=["reload_extension cogs.levels"],
        aliases=["re"],
        cls=commands.Command,
    )
    async def reload_extension(self, ctx: Context, ext: str):
        if ext in self.bot.extensions.keys():
            self.bot.reload_extension(ext)

            if ext.lower() == "cogs.uk":
                # Used to accomodate the unique way in which this cog is loaded.
                self.bot.get_cog("UK").load()
            return await embed_maker.message(
                ctx, description=f"`{ext}` has been reloaded", colour="green", send=True
            )
        else:
            return await embed_maker.error(ctx, "That is not a valid extension")

    @command(
        help="Evaluate code",
        usage="eval [code]",
        examples=["eval ctx.author.id"],
        cls=commands.Command,
    )
    async def eval(self, ctx: Context, *, cmd: str = None):
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
            "bot": ctx.bot,
            "discord": discord,
            "commands": commands,
            "ctx": ctx,
            "__import__": __import__,
            "db": db,
        }
        exec(compile(parsed, filename="<ast>", mode="exec"), env)

        result = repr(await eval(f"{fn_name}()", env))
        # return done if result is empty, so it doesnt cause empty message error
        if result == "":
            result = "Done"

        await ctx.send(result)

    @command(
        help="Disable a command",
        usage="disable_command",
        examples=["disable_command"],
        cls=commands.Command,
    )
    async def disable_command(self, ctx: Context, command_name: str = None):
        # TOOD: refresh command_data in commandsystem
        if command_name is None:
            return await embed_maker.command_error(ctx)

        command = self.bot.get_command(command_name)
        if command is None:
            return await embed_maker.command_error(ctx, "[command]")

        command_data = db.get_command_data(command_name, insert=True)

        if command_data["disabled"]:
            return await embed_maker.error(ctx, f"`{command_name}` is already disabled")

        db.commands.update_one(
            {"command_name": command.name}, {"$set": {"disabled": 1}}
        )
        return await embed_maker.message(
            ctx,
            description=f"`{command_name}` has been disabled",
            colour="green",
            send=True,
        )

    @command(
        help="Enable a command",
        usage="enable_command",
        examples=["enable_command"],
        cls=commands.Command,
    )
    async def enable_command(self, ctx: Context, command_name: str = None):
        if command_name is None:
            return await embed_maker.command_error(ctx)

        command = self.bot.get_command(command_name)
        if command is None:
            return await embed_maker.command_error(ctx, "[command]")

        command_data = db.get_command_data(command_name, insert=True)

        if not command_data["disabled"]:
            return await embed_maker.error(ctx, f"`{command_name}` is already enabled")

        db.commands.update_one(
            {"command_name": command.name}, {"$set": {"disabled": 0}}
        )
        command_data["disabled"] = 0
        await embed_maker.message(
            ctx,
            description=f"`{command_name}` has been enabled",
            colour="green",
            send=True,
        )


def setup(bot):
    bot.add_cog(Dev(bot))
