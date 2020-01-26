import discord
from datetime import datetime
from time import time
from random import randint
from discord.ext import commands
from modules import database, command, embed_maker

db = database.Connection()
xp_cooldown = {}

leveling_routes = {
    'participation': {
        'Member': 2,
        'role x2': 2
    },
    'contribution': {
        'Public Servant': 2,
        'role y2': 2
    }
}

class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='award someone contribution points, for contributing to the server or youtube channels', usage='award [@member] [amount]', examples=['award @Hattyot 500'], clearance='Mod', cls=command.Command)
    async def award(self, ctx, member=None, amount=None):
        if member is None:
            return await embed_maker.command_error(ctx)
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            return await embed_maker.command_error(ctx, '[@member]')

        if member.bot:
            embed = embed_maker.message(ctx, 'You can\'t give contribution points to bots')
            return await ctx.send(embed=embed)
        if member == ctx.author:
            embed = embed_maker.message(ctx, 'You can\'t give contribution points to yourself')
            return await ctx.send(embed=embed)

        if amount is None:
            return await embed_maker.command_error(ctx, '[@member]')
        if not amount.isdigit():
            return await embed_maker.command_error(ctx, '[amount]')

        amount = round(int(amount))

        if amount > 1000:
            embed = embed_maker.message(ctx, 'The max amount of contributions points you can give is 1000')
            return await ctx.send(embed=embed)

        user_cp = db.get_levels(ctx.guild.id, member.id, 'cp')
        new_cp = amount + user_cp

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.cp': new_cp}})
        db.get_levels.invalidate(ctx.guild.id, member.id, 'cp')

        embed = embed_maker.message(ctx, f'<@{member.id}> has been awarded **{amount} contribution points**')

        if user_cp == 0:
            await ctx.send(embed=embed)
            first_role_name = list(leveling_routes['contribution'])[0]
            first_role = discord.utils.find(lambda r: r.name == first_role_name, ctx.guild.roles)
            if first_role is None:
                first_role = await ctx.guild.create_role(name=first_role_name)
            await member.add_roles(first_role)

            if new_cp < 1000:
                reward_text = f'Congrats <@{member.id}> you\'ve advanced to a level **0** <@&{first_role.id}>!!'
            else:
                reward_text = f'Congrats <@{member.id}> you\'ve advanced to a level **1** <@&{first_role.id}>!!'
                db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{member.id}.c_level': 1}})
                db.get_levels.invalidate(ctx.guild.id, member.id, 'c_level')

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.c_role': first_role.name}})
            db.get_levels.invalidate(ctx.guild.id, member.id, 'c_role')

            embed_colour = db.get_server_options(ctx.guild.id, 'embed_colour')
            embed = discord.Embed(colour=embed_colour, description=reward_text, timestamp=datetime.now())
            embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
            embed.set_author(name='Level Up!', icon_url=ctx.guild.icon_url)

            channel_id = db.get_levels(ctx.guild.id, ctx.author.id, 'level_up_channel')
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                return await ctx.send(embed=embed)
            else:
                return await channel.send(embed=embed)

        await ctx.send(embed=embed)
        return await self.c_level_up(ctx, member, new_cp)

    async def c_level_up(self, ctx, member, new_tp):
        cp_until = cpi(ctx, member, new_tp)
        print(cp_until)
        if cp_until <= 0:

            user_role = db.get_levels(ctx.guild.id, member.id, 'c_role')
            user_role_level = self.user_c_role_level(ctx, member)

            if user_role_level == -1:
                # Get next role
                roles = leveling_routes['contribution']
                role_index = -2
                next_role = ''
                for i, role in enumerate(roles):
                    if role == user_role:
                        role_index = i
                    if role_index == i - 1:
                        next_role = role
                        break
                role = discord.utils.find(lambda r: r.name == next_role, ctx.guild.roles)
                if role is None:
                    role = await ctx.guild.create_role(name=next_role)
                await member.add_roles(role)
                reward_text = f'Congrats <@{member.id}> you\'ve advanced to a level **1** <@&{role.id}>!!'

            else:
                role = discord.utils.find(lambda r: r.name == user_role, ctx.guild.roles)
                reward_text = f'Congrats <@{member.id}> you\'ve become a level **{user_role_level}** <@&{role.id}>!!'

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.c_role': role.name}})
            db.get_levels.invalidate(ctx.guild.id, member.id, 'c_role')

            embed_colour = db.get_server_options(ctx.guild.id, 'embed_colour')
            embed = discord.Embed(colour=embed_colour, description=reward_text, timestamp=datetime.now())
            embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
            embed.set_author(name='Level Up!', icon_url=ctx.guild.icon_url)

            channel_id = db.get_levels(ctx.guild.id, ctx.author.id, 'level_up_channel')
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                await ctx.send(embed=embed)
            else:
                await channel.send(embed=embed)

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{member.id}.c_level': 1}})
            db.get_levels.invalidate(ctx.guild.id, member.id, 'c_level')

    def user_c_role_level(self, ctx, member, current=False):
        user_level = db.get_levels(ctx.guild.id, member.id, 'c_level')
        if not current:
            user_level += 1
        user_role = db.get_levels(ctx.guild.id, member.id, 'c_role')
        if user_role == '':
            return user_level
        all_roles = leveling_routes['contribution']

        role_index = 0
        for role in all_roles:
            if role != user_role:
                role_index += 1
            else:
                break

        current_level_total = 0
        previous_level_total = 0
        for i, role in enumerate(all_roles):
            current_level_total += all_roles[role]
            if role_index > i:
                previous_level_total += all_roles[role]
                continue
            if current_level_total > user_level:
                return user_level - previous_level_total
            if current_level_total == user_level:
                return all_roles[role]
            if current_level_total < user_level:
                return -1

    @commands.command(help='Shows your (or someone else\'s) rank, level and xp', usage='rank (@member)', examples=['rank', 'rank @Hattyot'], clearance='User', cls=command.Command)
    async def rank(self, ctx, member=None):
        if member and ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            member = ctx.author

        if member.bot:
            return

        member_level = self.user_role_level(ctx, member, True)
        member_role = discord.utils.find(lambda r: r.name == db.get_levels(ctx.guild.id, member.id, 'role'), ctx.guild.roles)
        member_c_role = discord.utils.find(lambda r: r.name == db.get_levels(ctx.guild.id, member.id, 'c_role'), ctx.guild.roles)

        member_c_level = self.user_c_role_level(ctx, member, True)
        rank = self.calculate_user_rank(ctx.guild.id, member.id)
        c_rank = self.calculate_user_c_rank(ctx.guild.id, member.id)

        if member_role is None:
            member_role = await ctx.guild.create_role(name=db.get_levels(ctx.guild.id, member.id, 'role'))

        sp_value = f'**#{rank}** | **Level** {member_level} <@&{member_role.id}>'

        if db.get_levels(ctx.guild.id, member.id, 'c_role') == '':
            cp_value = f'**#{c_rank}** | **Level** {member_c_level}'
        else:
            if member_c_role is None:
                member_c_role = await ctx.guild.create_role(name=db.get_levels(ctx.guild.id, member.id, 'c_role'))

            cp_value = f'**#{c_rank}** | **Level** {member_c_level} <@&{member_c_role.id}>'

        embed_colour = db.get_server_options(ctx.guild.id, 'embed_colour')
        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name=f'{member.name} - Rank', icon_url=ctx.guild.icon_url)
        embed.add_field(name='>Server Participation', value=sp_value, inline=False)
        embed.add_field(name='>Contributions', value=cp_value, inline=False)

        return await ctx.send(embed=embed)

    def calculate_user_rank(self, guild_id, user_id):
        doc = db.levels.find_one({'guild_id': guild_id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1]['xp'], reverse=True)
        for i, u in enumerate(sorted_users):
            if u[0] == str(user_id):
                return i + 1

    def calculate_user_c_rank(self, guild_id, user_id):
        doc = db.levels.find_one({'guild_id': guild_id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1]['cp'], reverse=True)
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

        cooldown_expire = round(time())# + 45
        xp_cooldown[ctx.guild.id][ctx.author.id] = cooldown_expire

        xp_add = randint(15, 25)
        new_xp = ctx.author_xp + xp_add
        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.xp': new_xp}})
        db.get_levels.invalidate(ctx.guild.id, ctx.author.id, 'xp')
        await self.level_up(ctx, new_xp)

    async def level_up(self, ctx, new_xp):
        xp_until = xpi(ctx, new_xp)
        if xp_until <= 0:

            user_role = db.get_levels(ctx.guild.id, ctx.author.id, 'role')
            user_role_level = self.user_role_level(ctx, ctx.author)

            if user_role_level == -1:
                # Get next role
                roles = leveling_routes['participation']
                role_index = -2
                next_role = ''
                for i, role in enumerate(roles):
                    if role == user_role:
                        role_index = i
                    if role_index == i - 1:
                        next_role = role
                        break
                role = discord.utils.find(lambda r: r.name == next_role, ctx.guild.roles)
                if role is None:
                    role = await ctx.guild.create_role(name=next_role)
                await ctx.author.add_roles(role)
                reward_text = f'Congrats <@{ctx.author.id}> you\'ve advanced to a level **1** <@&{role.id}>!!'

            else:
                role = discord.utils.find(lambda r: r.name == user_role, ctx.guild.roles)
                reward_text = f'Congrats <@{ctx.author.id}> you\'ve become a level **{user_role_level}** <@&{role.id}>!!'

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.role': role.name}})
            db.get_levels.invalidate(ctx.guild.id, ctx.author.id, 'role')

            embed_colour = db.get_server_options(ctx.guild.id, 'embed_colour')
            embed = discord.Embed(colour=embed_colour, description=reward_text, timestamp=datetime.now())
            embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
            embed.set_author(name='Level Up!', icon_url=ctx.guild.icon_url)

            channel_id = db.get_levels(ctx.guild.id, ctx.author.id, 'level_up_channel')
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                await ctx.send(embed=embed)
            else:
                await channel.send(embed=embed)

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{ctx.author.id}.level': 1}})
            db.get_levels.invalidate(ctx.guild.id, ctx.author.id, 'level')

    # Returns the level of current role
    def user_role_level(self, ctx, member, current=False):
        user_level = db.get_levels(ctx.guild.id, member.id, 'level')
        if not current:
            user_level += 1
        user_role = db.get_levels(ctx.guild.id, member.id, 'role')
        all_roles = leveling_routes['participation']

        role_index = 0
        for role in all_roles:
            if role != user_role:
                role_index += 1
            else:
                break
        current_level_total = 0
        previous_level_total = 0
        role_amount = len(all_roles)
        for i, role in enumerate(all_roles):
            current_level_total += all_roles[role]
            if role_amount - 1 == i:
                return user_level - previous_level_total
            if role_index > i:
                previous_level_total += all_roles[role]
                continue
            if current_level_total > user_level:
                return user_level - previous_level_total
            if current_level_total == user_level:
                return all_roles[role]
            if current_level_total < user_level:
                return -1


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


# How much cp is needed until level up, works the same way as xpi
def cpi(ctx, member, new_cp):
    user_cp = new_cp
    user_level = db.get_levels(ctx.guild.id, member.id, 'c_level')

    total_cp = 1000 * (user_level + 1)
    return total_cp - user_cp




def setup(bot):
    bot.add_cog(Levels(bot))
