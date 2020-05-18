import discord
import os
import config
import re
import traceback
from modules import database
from discord.ext import commands

db = database.Connection()


async def get_prefix(bot, message):
    return commands.when_mentioned_or(config.PREFIX)(bot, message)


class TLDR(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=get_prefix, case_insensitive=True, help_command=None)

        # Load Cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                self.load_extension(f'cogs.{filename[:-3]}')
                print(f'{filename[:-3]} is now loaded')

    async def on_command_error(self, ctx, exception):
        trace = exception.__traceback__
        verbosity = 4
        lines = traceback.format_exception(type(exception), exception, trace, verbosity)
        traceback_text = ''.join(lines)

        print(traceback_text)
        print(exception)

        # Returns if bot isn't main bot
        if self.user.id != 669877023753109524:
            return

        # send error message to certain channel in a guild if error happens during bot run
        guild = self.get_guild(669640013666975784)
        if guild is not None:
            channel = self.get_channel(671991712800964620)
            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(colour=embed_colour, title=f'{ctx.command.name} - Command Error', description=f'```{exception}\n{traceback_text}```')
            embed.add_field(name='Message', value=ctx.messsage.content)
            embed.add_field(name='User', value=ctx.messsage.author)

            return await channel.send(embed=embed)

    async def on_message(self, message):
        if message.author.bot:
            return

        # just checks if message was sent in pms
        if message.guild is None:
            pm_cog = self.get_cog('PrivateMessages')
            return await pm_cog.process_pm(message)

        if message.content.startswith(config.PREFIX):
            return await self.process_commands(message)

        # Starts leveling process
        levels_cog = self.get_cog('Leveling')
        await levels_cog.process_message(message)

        # honours leveling
        data = db.levels.find_one({'guild_id': message.guild.id})
        if data is None:
            data = self.bot.add_collections(message.guild.id, 'tickets')

        honours_channels = data['honours_channels']
        if message.channel.id in honours_channels:
            await levels_cog.process_hp_message(message)

        # checks if bot was mentioned, if it was invoke help command
        regex = re.compile(rf'<@!?{self.user.id}>')
        match = re.findall(regex, message.content)

        if match:
            ctx = await self.get_context(message)
            utility_cog = self.get_cog('Utility')
            return await utility_cog.help(ctx)

    async def process_commands(self, message):
        ctx = await self.get_context(message)

        if ctx.command is None:
            return

        if ctx.guild is None:
            return

        await self.invoke(ctx)

    async def on_guild_join(self, guild):
        self.add_collections(guild.id)

    @staticmethod
    def add_collections(guild_id, col=None):
        return_doc = None
        collections = ['levels', 'timers', 'polls', 'tickets']
        for c in collections:
            collection = db.__getattribute__(c)
            doc = collection.find_one({'guild_id': guild_id})

            if not doc:
                new_doc = database.schemas[c]
                new_doc['guild_id'] = guild_id

                # return doc if asked for
                if col == c:
                    return_doc = new_doc

                # .copy() is there to prevent pymongo from creating duplicate "_id"'s
                collection.insert_one(new_doc.copy())

        return return_doc

    async def on_ready(self):
        bot_game = discord.Game(f'@me')
        await self.change_presence(activity=bot_game)

        print(f'{self.user} is ready')

        # Check if guild documents in collections exist if not, it adds them
        for g in self.guilds:
            self.add_collections(g.id)

    async def close(self):
        await super().close()

    def run(self):
        super().run(config.BOT_TOKEN, reconnect=False)


def main():
    TLDR().run()


if __name__ == '__main__':
    main()
