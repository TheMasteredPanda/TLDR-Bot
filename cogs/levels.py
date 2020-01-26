import discord
from datetime import datetime
from time import time
from random import randint
from discord.ext import commands
from modules import database, command, embed_maker

db = database.Connection()
xp_cooldown = {}


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Award tp to a user (restricted to mod), for their contributions', usage='award_tp [amount] [@member]', examples=['award_tp 500 @Hattyot'], clearance='Mod', cls=command.Command)
    async def award_tp(self, ctx, amount=None, member=None):
        if amount is None:
            return await embed_maker.command_error(ctx)
        if not amount.isdigit():
            return await embed_maker.command_error(ctx, '[amount]')

        amount = round(int(amount))

        if member is None:
            return await embed_maker.command_error(ctx, '[@member]')
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            return await embed_maker.command_error(ctx, '[@member]')

        if member.bot:
            embed = embed_maker.message(ctx, 'You can\'t give tp to bots')
            return await ctx.send(embed=embed)
        # if member == ctx.author:
        #     embed = embed_maker.message(ctx, 'You can\'t give tp to yourself')
        #     return await ctx.send(embed=embed)

        user_tp = ctx.author_tp
        new_tp = amount + user_tp

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.tp': new_tp}})
        db.get_levels.invalidate(ctx.guild.id, member.id, 'tp')

        embed = embed_maker.message(ctx, f'<@{member.id}> has been awarded **{amount} tp**')
        await ctx.send(embed=embed)

        # Check t_level up
        tp_until = tpi(ctx, new_tp)
        if tp_until <= 0:
            reward_text = f'Congrats <@{ctx.author.id}> you\'ve leveled up to **T-Level {ctx.author_t_level + 1}**, due to your contributions!'
            embed_colour = db.get_server_options(ctx.guild.id, 'embed_colour')
            embed = discord.Embed(colour=embed_colour, description=reward_text, timestamp=datetime.now())
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            embed.set_author(name='T-Level Up!', icon_url=ctx.guild.icon_url)
            await ctx.send(embed=embed)

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{ctx.author.id}.t_level': 1}})
            db.get_levels.invalidate(ctx.guild.id, ctx.author.id, 't_level')


    @commands.command(help='Shows your (or someone else\'s) rank, level and xp',
                      usage='rank (@member)', examples=['rank', 'rank @Hattyot'], clearance='User', cls=command.Command)
    async def rank(self, ctx, member=None):
        if member and ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            member = ctx.author

        if member.bot:
            return

        member_xp = ctx.author_xp
        member_level = ctx.author_level
        member_tp = ctx.author_tp
        member_t_level = ctx.author_t_level
        rank = self.calculate_user_rank(ctx.guild.id, member.id)
        t_rank = self.calculate_user_t_rank(ctx.guild.id, member.id)

        sp_value = f'**#{rank}** | **XP:** {member_xp} - **Level:** {member_level}'
        tp_value = f'**#{t_rank}** | **TP:** {member_tp} - **T-Level:** {member_t_level}'

        embed_colour = db.get_server_options(ctx.guild.id, 'embed_colour')
        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name=f'{member.name} - Rank', icon_url=ctx.guild.icon_url)
        embed.add_field(name='>Server Participation', value=sp_value, inline=False)
        embed.add_field(name='>Contributions', value=tp_value, inline=False)

        return await ctx.send(embed=embed)

    @commands.command(help='Shows the levels leaderboard on the server', usage='leaderboard (page)', examples=['leaderboard', 'leaderboard 2'], clearance='User', cls=command.Command)
    async def leaderboard(self, ctx, user_page=0):
        doc = db.levels.find_one({'guild_id': ctx.guild.id})
        # this creates a list of tuples, where [0] is the user's id and [1] is an object where xp and level is located
        # same as in calculate_user_rank
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1]['xp'], reverse=True)
        embed_colour = db.get_server_options(ctx.guild.id, 'embed_colour')
        page_num = 1
        lboard = {page_num: []}

        for i, u in enumerate(sorted_users):
            if i == 10 * page_num:
                page_num += 1
                lboard[page_num] = []

            level = u[1]['level']
            xp = u[1]['xp']
            page_message = f'**#{i + 1}** : <@{u[0]}> | **Level** : {level} - **XP** : {xp}'
            lboard[page_num].append(page_message)

        if user_page not in lboard:
            user_page = 1

        lboard_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description='\n'.join(lboard[user_page]))
        lboard_embed.set_footer(text=f'Page {user_page}/{page_num} - {ctx.author}', icon_url=ctx.author.avatar_url)
        lboard_embed.set_author(name=f'{ctx.guild.name} - Leaderboard', icon_url=ctx.guild.icon_url)

        await ctx.send(embed=lboard_embed)

    def calculate_user_rank(self, guild_id, user_id):
        doc = db.levels.find_one({'guild_id': guild_id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1]['xp'], reverse=True)
        for i, u in enumerate(sorted_users):
            if u[0] == str(user_id):
                return i + 1

    def calculate_user_t_rank(self, guild_id, user_id):
        doc = db.levels.find_one({'guild_id': guild_id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1]['tp'], reverse=True)
        for i, u in enumerate(sorted_users):
            if u[0] == str(user_id):
                return i + 1

    async def process_message(self, ctx):
        if ctx.guild.id not in xp_cooldown:
            xp_cooldown[ctx.guild.id] = {}
        if ctx.author.id in xp_cooldown[ctx.guild.id]:
            if round(time()) >= xp_cooldown[ctx.guild.id][ctx.author.id]:
                del xp_cooldown[ctx.guild.id][ctx.author.id]
            else:
                return

        xp_add = randint(15, 25)
        new_xp = ctx.author_xp + xp_add
        await self.xp_add(ctx, new_xp)

        cooldown_expire = round(time()) + 45

        xp_cooldown[ctx.guild.id][ctx.author.id] = cooldown_expire

    async def xp_add(self, ctx, new_xp):
        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.xp': new_xp}})
        db.get_levels.invalidate(ctx.guild.id, ctx.author.id, 'xp')
        return await self.level_up(ctx, new_xp)

    async def level_up(self, ctx, new_xp):
        xp_until = xpi(ctx, new_xp)
        if xp_until <= 0:
            reward_text = f'Congrats <@{ctx.author.id}> you\'ve leveled up to level **{ctx.author_level + 1}**!!'
            embed_colour = db.get_server_options(ctx.guild.id, 'embed_colour')
            embed = discord.Embed(colour=embed_colour, description=reward_text, timestamp=datetime.now())
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            embed.set_author(name='Level Up!', icon_url=ctx.guild.icon_url)
            await ctx.send(embed=embed)

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


# How much tp is needed until t_level up
def tpi(ctx, new_tp):
    user_tp = new_tp
    user_t_level = ctx.author_t_level

    total_tp = 0
    for i in range(user_t_level + 1):
        total_tp += 1000 * i

    return total_tp - user_tp


def setup(bot):
    bot.add_cog(Levels(bot))
