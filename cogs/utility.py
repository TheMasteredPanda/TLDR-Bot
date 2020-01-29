from discord.ext import commands
from modules import database, command

db = database.Connection()


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Get bot\'s latency', usage='ping', examples=['ping'], clearance='User', cls=command.Command)
    async def ping(self, ctx):
        await ctx.send('Pong! {0}ms'.format(round(self.bot.latency, 1)))


def setup(bot):
    bot.add_cog(Utility(bot))
