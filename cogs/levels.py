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
        new_xp = ctx.author_xp + xp_add
        await self.xp_add(ctx, new_xp)

        cooldown_expire = round(time()) + 45
        xp_cooldown[ctx.author.id] = cooldown_expire

    async def xp_add(self, ctx, new_xp):
        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.xp': new_xp}})
        db.get_levels.invalidate(ctx.guild.id, ctx.author.id, 'xp')
        return await self.level_up(ctx, new_xp)

    async def level_up(self, ctx, new_xp):
        xp_until = xpi(ctx, new_xp)
        if xp_until <= 0:
            reward_text = f'Congrats <@{ctx.author.id}> you\'ve leveled up to level **{ctx.author_level + 1}**!!'
            await ctx.send(reward_text)

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{ctx.author.id}.level': 1}})
            db.get_levels.invalidate(ctx.guild.id, ctx.author.id, 'level')


# How much xp is needed until level up
def xpi(ctx, new_xp):
    user_xp = new_xp
    user_level = ctx.author_level

    # total xp needed to gain the next level
    total_xp = 0
    for i in range(user_level + 1):
        # the formula to calculate how much xp you need for the next level
        total_xp += (5 * (i ** 2) + 50 * i + 100)

    return total_xp - user_xp


def setup(bot):
    bot.add_cog(Levels(bot))
