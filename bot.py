import discord
import os
import aiohttp
import re
from modules import database, context
from discord.ext import commands
from config import BOT_TOKEN

db = database.Connection()


async def get_prefix(bot, message):
    prefix = db.get_prefix(message.guild.id)
    return commands.when_mentioned_or(prefix)(bot, message)


class TLDR(commands.AutoShardedBot):
    def __init__(self):
        super().__init__(command_prefix=get_prefix, case_insensitive=True, help_command=None)

        self.session = aiohttp.ClientSession(loop=self.loop)

        # Load Cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                self.load_extension(f'cogs.{filename[:-3]}')
                print(f'{filename[:-3]} is now loaded')

    async def on_message(self, message):
        ctx = await self.get_context(message, cls=context.Context)

        regex = re.compile(rf'<@!?{self.user.id}>')
        match = re.findall(regex, message.content)
        if match:
            general_cog = self.get_cog('General')
            print(self.cogs)
            return await ctx.invoke(general_cog.help)

        await self.process_commands(message)

    async def process_commands(self, message):
        ctx = await self.get_context(message, cls=context.Context)

        if ctx.command is None or ctx.guild is None:
            return

        await self.invoke(ctx)

    async def on_ready(self):
        bot_game = discord.Game(f'@me')
        await self.change_presence(activity=bot_game)

        print(f'{self.user} is ready')

    async def close(self):
        await super().close()
        await self.session.close()

    def run(self):
        super().run(BOT_TOKEN, reconnect=False)


def main():
    TLDR().run()


if __name__ == '__main__':
    main()
