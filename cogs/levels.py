from discord.ext import commands


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def process_message(self, ctx):
        pass


def setup(bot):
    bot.add_cog(Levels(bot))
