from discord.ext import commands
from config import DEV_IDS
from modules import database, command

db = database.Connection()


def get_user_clearence(ctx):
    user_permissions = ctx.channel.permissions_for(ctx.author)
    clearance = []

    if ctx.author.id in DEV_IDS:
        clearance.append('Dev')
    if user_permissions.administrator:
        clearance.append('Admin')
    if user_permissions.manage_messages:
        clearance.append('Mod')
    clearance.append('User')

    return clearance


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Get bot\'s latency', usage='ping', examples=['ping'], clearence='User', cls=command.Command)
    async def ping(self, ctx):
        await ctx.send('Pong! {0}ms'.format(round(self.bot.latency, 1)))


def setup(bot):
    bot.add_cog(Utility(bot))
