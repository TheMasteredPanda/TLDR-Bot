import discord
import os
import aiohttp
import re
from modules import database, context
from discord.ext import commands
from config import BOT_TOKEN

db = database.Connection()


async def get_prefix(bot, message):
    prefix = db.get_server_options('prefix', message.guild.id)
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
            return await ctx.invoke(general_cog.help)

        await self.process_commands(ctx)

        if not message.author.bot:
            levels_cog = self.get_cog('Levels')
            cp_channels = db.get_levels('cp_channels', ctx.guild.id)

            if message.channel.id in cp_channels:
                await levels_cog.process_cp_message(ctx)

            return await levels_cog.process_message(ctx)

    async def on_raw_reaction_add(self, payload):
        channel = self.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        author = message.author
        user = self.get_user(payload.user_id)
        emote = payload.emoji

        # skip if user gave reaction to themselves
        if author.id == payload.user_id:
            return

        if author.bot or user.bot:
            return

        if emote.name not in ('👍', '👎'):
            return

        levels_cog = self.get_cog('Levels')
        return await levels_cog.process_reaction(payload)

    async def process_commands(self, ctx):
        if ctx.command is None or ctx.guild is None:
            return
        if ctx.command.clearance not in ctx.author_clearance:
            return

        await self.invoke(ctx)

    async def on_ready(self):
        bot_game = discord.Game(f'@me')
        await self.change_presence(activity=bot_game)

        print(f'{self.user} is ready')

    async def on_member_join(self, member):
        if member.bot:
            return
        # just adds the member to the database
        db.get_levels('xp', member.guild.id, member.id)

    async def close(self):
        await super().close()
        await self.session.close()

    def run(self):
        super().run(BOT_TOKEN, reconnect=False)


def main():
    TLDR().run()


if __name__ == '__main__':
    main()
