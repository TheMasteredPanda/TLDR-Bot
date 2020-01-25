from time import time
from random import randint
from discord.ext import commands
from modules import database

db = database.Connection()
xp_cooldown = {}


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def process_message(self, ctx):
        if ctx.author.id in xp_cooldown:
            if round(time()) >= xp_cooldown[ctx.author.id]:
                del xp_cooldown[ctx.author.id]
            else:
                return

        xp_add = randint(15, 25)
        self.add_xp(ctx, xp_add)

        cooldown_expire = round(time()) + 45
        xp_cooldown[ctx.author.id] = cooldown_expire

    def add_xp(self, ctx, xp):
        db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{ctx.author.id}.xp': xp}})
        db.get_levels.invalidate(ctx.guild.id, ctx.author.id, 'xp')


def setup(bot):
    bot.add_cog(Levels(bot))
