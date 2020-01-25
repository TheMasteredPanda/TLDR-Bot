import discord
from datetime import datetime
from time import time
from random import randint
from discord.ext import commands
from modules import database, command

db = database.Connection()
xp_cooldown = {}


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(descrition='See what your (or someone else\'s) level is and how much xp you got',
                      usage='rank (@member)', examples=['rank', 'rank @Hattyot'], clearence='User', cls=command.Command)
    async def rank(self, ctx, member=None):
        if member and ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            member = ctx.author

        member_xp = db.get_levels(ctx.guild.id, member.id, 'xp')
        member_level = db.get_levels(ctx.guild.id, member.id, 'level')
        embed_colour = db.get_server_options(ctx.guild.id, 'embed_colour')
        rank = self.calculate_user_rank(ctx.guild.id, member.id)

        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name=f'{member.name} - Rank', icon_url=ctx.guild.icon_url)
        embed.add_field(name='Rank', value=f'#{rank}', inline=True)
        embed.add_field(name='Level', value=member_level, inline=True)
        embed.add_field(name='XP', value=member_xp, inline=True)

        return await ctx.send(embed=embed)

    def calculate_user_rank(self, guild_id, user_id):
        doc = db.levels.find_one({'guild_id': guild_id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1]['xp'], reverse=True)

        for i, u in enumerate(sorted_users):
            if u[0] == str(user_id):
                return i + 1
        else:
            return False

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
