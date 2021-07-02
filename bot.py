import os
import copy
import config
import asyncio
import discord
import traceback
import modules.utils
import modules.timers
import modules.database
import modules.leveling
import modules.embed_maker
import modules.ukparliament

import modules.google_drive
import modules.reaction_menus
import modules.custom_commands
import modules.invite_logger
import modules.moderation
import modules.commands

from datetime import datetime
from discord.ext.commands import when_mentioned_or, Cog, Bot


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
        self.left_check = asyncio.Event()
        self.logger = modules.utils.get_logger()
        self.command_system = modules.commands.CommandSystem(self)

        # Load Cogs
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and filename[:-3] != "template_cog":
                self.load_extension(f"cogs.{filename[:-3]}")
                self.logger.info(f"Cog {filename[:-3]} is now loaded.")

        self.google_drive = modules.google_drive.Drive()
        self.timers = modules.timers.Timers(self)
        self.reaction_menus = modules.reaction_menus.ReactionMenus(self)
        self.custom_commands = modules.custom_commands.CustomCommands(self)
        self.leveling_system = modules.leveling.LevelingSystem(self)
        self.invite_logger = modules.invite_logger.InviteLogger(self)
        self.moderation = modules.moderation.ModerationSystem(self)
        self.ukparl_module = modules.ukparliament.UKParliamentModule(self)
        self.clearance = modules.commands.Clearance(self)

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
        embed.set_author(
            name=f"Critical Error - Shutting down", icon_url=guild.icon_url
        )
        await channel.send(
            embed=embed, content="<@&685230896466755585>"
        )  # @ the technicians
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
        embed.set_author(name=f"Event Error - {event_method}", icon_url=guild.icon_url)
        embed.add_field(name="args", value=str(args))
        embed.add_field(name="kwargs", value=str(kwarg))

        return await channel.send(embed=embed)

    async def on_message(self, message: discord.Message):
        await self.wait_until_ready()

        if not self.left_check.is_set():
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

        # create copy of original so values of original aren't modified
        ctx.command = copy.copy(ctx.command)
        ctx.command.docs = ctx.command.get_help(ctx.author)

        # check if command has been disabled
        if ctx.command.disabled:
            return await modules.embed_maker.error(
                ctx, "This command has been disabled"
            )

        # return if user doesnt have clearance for command
        if not ctx.command.can_use(ctx.author):
            return

        await self.invoke(ctx)


if __name__ == "__main__":
    logger = modules.utils.get_logger()
    logger.info("Starting TLDR Bot.")
    TLDR().run(config.BOT_TOKEN)
