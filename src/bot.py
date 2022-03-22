import asyncio
import copy
import os
import traceback
from datetime import datetime

import discord
from discord.ext.commands import Bot, when_mentioned_or

import config
import modules.captcha_verification
import modules.commands
import modules.custom_commands
import modules.database
import modules.embed_maker
import modules.google_drive
import modules.invite_logger
import modules.leveling
import modules.moderation
import modules.reaction_menus
import modules.slack_bridge
import modules.tasks
import modules.threading
import modules.timers
import modules.ukparliament
import modules.utils
import modules.watchlist
import modules.webhooks

intents = discord.Intents.all()
db = modules.database.get_connection()


async def get_prefix(bot, message):
    return when_mentioned_or(config.PREFIX)(bot, message)


class TLDR(Bot):
    def __init__(self):
        super().__init__(
            command_prefix=get_prefix,
            case_insensitive=True,
            help_command=None,
            intents=intents,
            chunk_guilds_at_startup=True,
        )
        self.enabled_modules = getattr(config, "MODULES", {})
        self.enabled_cogs = getattr(config, "COGS", {})
        self.settings_handler = modules.utils.SettingsHandler()
        self.left_check = asyncio.Event()
        self.logger = modules.utils.get_logger()
        self.command_system = modules.commands.CommandSystem(self)

        # Load Cogs
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and filename[:-3] != "template_cog":
                if (
                    filename[:-3] in self.enabled_cogs
                    and not self.enabled_cogs[filename[:-3]]
                ):
                    continue

                self.load_extension(f"cogs.{filename[:-3]}")
                self.logger.info(f"Cog {filename[:-3]} is now loaded.")

        self.google_drive = (
            modules.google_drive.Drive()
            if self.enabled_modules.get("google_drive", True)
            else None
        )
        self.webhooks = (
            modules.webhooks.Webhooks(self)
            if self.enabled_modules.get("webhooks", True)
            else None
        )
        self.watchlist = (
            modules.watchlist.Watchlist(self)
            if self.enabled_modules.get("watchlist", True)
            else None
        )
        self.timers = (
            modules.timers.Timers(self)
            if self.enabled_modules.get("timers", True)
            else None
        )
        self.reaction_menus = (
            modules.reaction_menus.ReactionMenus(self)
            if self.enabled_modules.get("reaction_menus", True)
            else None
        )
        self.custom_commands = (
            modules.custom_commands.CustomCommands(self)
            if self.enabled_modules.get("custom_commands", True)
            else None
        )
        self.leveling_system = (
            modules.leveling.LevelingSystem(self)
            if self.enabled_modules.get("leveling_system", True)
            else None
        )
        self.invite_logger = (
            modules.invite_logger.InviteLogger(self)
            if self.enabled_modules.get("invite_logger", True)
            else None
        )
        self.moderation = (
            modules.moderation.ModerationSystem(self)
            if self.enabled_modules.get("moderation", True)
            else None
        )
        self.ukparl_module = (
            modules.ukparliament.UKParliamentModule(self)
            if self.enabled_modules.get("ukparl_module", True)
            else None
        )
        self.clearance = (
            modules.commands.Clearance(self)
            if self.enabled_modules.get("clearance", True)
            else None
        )
        self.slack_bridge = (
            modules.slack_bridge.Slack(self)
            if self.enabled_modules.get("slack_bridge", True)
            else None
        )
        self.tasks = (
            modules.tasks.Tasks(self)
            if self.enabled_modules.get("tasks", True)
            else None
        )
        self.captcha = (
            modules.captcha_verification.CaptchaModule(self)
            if self.enabled_modules.get("captcha", True)
            else None
        )

        self.threading = (
            modules.threading.ThreadingModule(self)
            if self.enabled_modules.get("threading", True)
            else None
        )
        self.twtsc = None
        self.first_ready = False

    def add_cog(self, cog):
        """Overwrites the orginal add_cog method to add a line for the commandSystem"""
        self.command_system.initialize_cog(cog)
        super().add_cog(cog)

    async def critical_error(self, error: str):
        """
        For errors which would cause the bot not to function.
        When called the bot will send a message to the error channel and shutdown.

        Parameters
        ----------
        error: :class:`str`
            The critical error.
        """
        self.logger.critical(error)
        # send error message to certain channel in a guild if error happens during bot runtime
        guild = self.get_guild(config.ERROR_SERVER)
        if guild is None:
            return self.logger.exception("Invalid error server ID")

        channel = self.get_channel(config.ERROR_CHANNEL)
        if channel is None:
            return self.logger.exception("Invalid error channel ID")

        embed = discord.Embed(
            colour=discord.Colour.red(),
            timestamp=datetime.now(),
            description=f"```py\n{error}```",
        )
        embed.set_author(name=f"Critical Error - Shutting down", icon_url=guild.icon)
        await channel.send(embed=embed)
        await self.close()

    async def _run_event(self, coroutine, event_name, *args, **kwargs):
        """Overwritten internal method to send event errors to :func:`on_event_error` with the exception instead
        of just event_name, args and kwargs."""
        try:
            await coroutine(*args, **kwargs)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            try:
                await self.on_event_error(error, event_name, *args, **kwargs)
            except asyncio.CancelledError:
                pass

    async def on_event_error(self, exception: Exception, event_method, *args, **kwarg):
        """Reports all event errors to server and channel given in config."""
        loop = kwarg.get("loop", None)
        trace = exception.__traceback__
        verbosity = 10
        lines = traceback.format_exception(type(exception), exception, trace, verbosity)
        traceback_text = "".join(lines)

        self.logger.exception(traceback_text)
        self.logger.exception(exception)

        # send error message to certain channel in a guild if error happens during bot runtime
        guild = self.get_guild(config.ERROR_SERVER)
        if guild is None:
            return self.logger.exception("Invalid error server ID")

        channel = self.get_channel(config.ERROR_CHANNEL)
        if channel is None:
            return self.logger.exception("Invalid error channel ID")

        embed = discord.Embed(
            colour=config.EMBED_COLOUR,
            timestamp=datetime.now(),
            description=f"```py\n{exception}\n{traceback_text}```",
        )
        embed.set_author(
            name=f"{'Event' if not loop else 'Loop'} Error - {event_method}",
            icon_url=guild.icon,
        )
        if not loop:
            embed.add_field(name="args", value=str(args))
            embed.add_field(name="kwargs", value=str(kwarg))

        return await channel.send(embed=embed)

    async def on_message(self, message: discord.Message):
        await self.wait_until_ready()

        if not self._ready.is_set():
            return

        # no bots allowed
        if message.author.bot:
            return

        # redirect to private messages cog if message was sent in pms
        if message.guild is None:
            pm_cog = self.get_cog("PrivateMessages")
            ctx = await self.get_context(message)
            return await pm_cog.process_pm(ctx)

        # check if message matches any custom commands
        if self.custom_commands:
            custom_command = await self.check_custom_command(message)
            if custom_command:
                return

        # invoke command if message starts with prefix
        if (
            message.content.startswith(config.PREFIX)
            and message.content.replace(config.PREFIX, "").strip()
        ):
            return await self.process_command(message)

    async def check_custom_command(self, message: discord.Message):
        custom_command = self.custom_commands.match_message(message)
        if custom_command:
            # get ctx
            ctx = await self.get_context(message)
            # check if user can run the custom command
            can_run = await self.custom_commands.can_use(ctx, custom_command)
            if can_run:
                # get response for the custom command
                response = await self.custom_commands.get_response(ctx, custom_command)
                if response:
                    # if command channel has set response channel, send response there, otherwise send to channel where command was called
                    if custom_command["response-channel"]:
                        channel = self.get_channel(custom_command["response-channel"])
                        message = await channel.send(response)
                    else:
                        message = await ctx.send(response)

                    # add reactions to message if needed
                    if custom_command["reactions"]:
                        for reaction in custom_command["reactions"]:
                            await message.add_reaction(reaction)

                # execute python script if use has dev clearance
                member_clearance = self.clearance.member_clearance(ctx.author)
                if (
                    "Developers" in member_clearance["groups"]
                    and custom_command["python"]
                ):
                    dev_cog = self.get_cog("Dev")
                    await dev_cog.eval(ctx, cmd=custom_command["python"])

                return custom_command

    async def process_command(self, message: discord.Message):
        ctx = await self.get_context(message)

        if ctx.command is None:
            return

        command = None

        if message.guild.id != config.MAIN_SERVER and config.MAIN_SERVER != 0:
            # This is to prevent commands on Gateway Guilds from being processed.
            return

        if self.clearance:
            # get the object of the command actually being run, so that can be checked instead of just the parent command
            # Discord.py invokes the parent command, then it looks for any sub commands and invokes those directly, instead of processing them like commands
            view = copy.copy(ctx.view)
            full_command_name = ctx.command.name
            view.skip_ws()
            while True:
                add = view.get_word()
                if not add:
                    break
                full_command_name += f" {add}"

            command = self.get_command(full_command_name)

            # create copy of original so values of original aren't modified
            ctx.command = copy.copy(ctx.command)
            ctx.command.docs = ctx.command.get_help(ctx.author)

            # check if command has been disabled
            if ctx.command.disabled or (command and command.disabled):
                return await modules.embed_maker.error(
                    ctx, "This command has been disabled"
                )

            # return if user doesnt have clearance for command
            if not ctx.command.can_use(ctx.author) or (
                command and not command.can_use(ctx.author)
            ):
                return

        # check if the command has a missing dependency
        ctx_dependency = ctx.command.module_dependency()
        command_dependency = command.module_dependency() if command else None
        if ctx_dependency:
            return await modules.embed_maker.error(
                ctx, f"Command missing module dependency [{ctx_dependency}]"
            )
        if command_dependency:
            return await modules.embed_maker.error(
                ctx, f"Command missing module dependency [{command_dependency}]"
            )

        await self.invoke(ctx)


if __name__ == "__main__":
    logger = modules.utils.get_logger()
    logger.info("Starting TLDR Bot.")
    TLDR().run(config.BOT_TOKEN)
