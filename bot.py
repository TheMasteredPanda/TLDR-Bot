import discord
import os
import config
import asyncio
import traceback
import modules.utils
import modules.cls
import modules.database
import modules.embed_maker
import modules.google_drive
import modules.reaction_menus
import modules.timers
import modules.custom_commands

from datetime import datetime
from discord.ext import commands

intents = discord.Intents.all()
db = modules.database.Connection()


async def get_prefix(bot, message):
    return commands.when_mentioned_or(config.PREFIX)(bot, message)


class TLDR(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=get_prefix, case_insensitive=True, help_command=None,
            intents=intents, chunk_guilds_at_startup=True
        )

        self.left_check = asyncio.Event()

        # Load Cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                self.load_extension(f'cogs.{filename[:-3]}')
                print(f'{filename[:-3]} is now loaded')

        self.google_drive = modules.google_drive.Drive()
        self.timers = modules.timers.Timers(self)
        self.reaction_menus = modules.reaction_menus.ReactionMenus(self)
        self.custom_commands = modules.custom_commands.CustomCommands(self)

    async def _run_event(self, coroutine, event_name, *args, **kwargs):
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
        trace = exception.__traceback__
        verbosity = 4
        lines = traceback.format_exception(type(exception), exception, trace, verbosity)
        traceback_text = ''.join(lines)

        print(traceback_text)
        print(exception)

        # send error message to certain channel in a guild if error happens during bot runtime
        guild = self.get_guild(config.ERROR_SERVER)
        if guild is None:
            return print('Invalid error server id')

        channel = self.get_channel(config.ERROR_CHANNEL)
        if channel is None:
            return print('Invalid error channel id')

        embed = discord.Embed(
            colour=config.EMBED_COLOUR,
            timestamp=datetime.now(),
            description=f'```{exception}\n{traceback_text}```',
        )
        embed.set_author(name=f'Event Error - {event_method}', icon_url=guild.icon_url)

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
            pm_cog = self.get_cog('PrivateMessages')
            ctx = await self.get_context(message)
            return await pm_cog.process_pm(ctx)

        # check if message matches any custom commands
        custom_command = self.custom_commands.match_message(message)
        if custom_command:
            # get ctx
            ctx = await self.get_context(message)
            # check if user can run the custom command
            can_run = await self.custom_commands.can_run(ctx, custom_command)
            if can_run:
                # get response for the custom command
                response = await self.custom_commands.get_response(ctx, custom_command)
                if response:
                    # if command channel has set response channel, send response there, otherwise send to channel where command was called
                    if custom_command['response_channel']:
                        channel = self.get_channel(custom_command['response_channel'])
                        message = await channel.send(response)
                    else:
                        message = await ctx.send(response)

                    # add reactions to message if needed
                    if custom_command['reactions']:
                        for reaction in custom_command['reactions']:
                            await message.add_reaction(reaction)

                # execute python script if use has dev clearance
                if 'Dev' in modules.utils.get_user_clearance(ctx.author) and custom_command['python']:
                    dev_cog = self.get_cog('Dev')
                    await dev_cog.eval(ctx, cmd=custom_command['python'])

                return

        # invoke command if message starts with prefix
        if message.content.startswith(config.PREFIX) and message.content.replace(config.PREFIX, '').strip():
            return await self.process_command(message)

    async def process_command(self, message: discord.Message):
        ctx = await self.get_context(message)

        if not ctx.command:
            return

        ctx.command.docs = ctx.command.get_help(ctx.author)
        # check if command has been disabled
        if ctx.command.docs.disabled:
            return await modules.embed_maker.error(ctx, 'This command has been disabled')

        # return if user doesnt have clearance for command
        if not ctx.command.docs.can_run:
            return

        # return error if user's access to command has been taken away
        if ctx.command.docs.access_taken:
            return await modules.embed_maker.error(ctx, f'Your access to this command has been taken away')

        await self.invoke(ctx)


if __name__ == '__main__':
    TLDR().run(config.BOT_TOKEN)
