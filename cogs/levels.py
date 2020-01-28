import discord
import asyncio
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

    @commands.command(help='Add a role to a leveling route (contribution/participation) - starts the process of adding a role', usage='add_role [branch]', examples=['add_role contribution', 'add_role participation'], clearance='Admin', cls=command.Command)
    async def add_role(self, ctx, branch=None):
        if branch is None:
            return await embed_maker.command_error(ctx)

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        if branch not in leveling_routes:
            embed = embed_maker.message(ctx, 'That is not a valid branch (contribution/participation)', colour='red')
            return await ctx.send(embed=embed)

        async def role():
            def role_check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            msg = 'What would you like the name of the new role to be?\nValid input: Any name that can be used as a role name'
            await ctx.send(msg)
            try:
                role_message = await self.bot.wait_for('message', check=role_check, timeout=60)
                try:
                    new_role = await ctx.guild.create_role(name=role_message.content)
                except discord.Forbidden:
                    return await ctx.send('failed to create role, missing permissions')
            except asyncio.TimeoutError:
                return await ctx.send('add_role function timed out')

            return new_role

        async def max_level():
            def level_check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.isdigit()

            msg = 'How many levels will a user have to be in this role, before they advance onto the next role?\nValid input: any number'
            await ctx.send(msg)

            try:
                level_message = await self.bot.wait_for('message', check=level_check, timeout=60)
            except asyncio.TimeoutError:
                return await ctx.send('add_role function timed out')

            return round(int(level_message.content))

        async def finish(new_role, role_max_level):
            def after_check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.isdigit()

            role_list_msg = ''
            for i, _role in enumerate(leveling_routes[branch]):
                role_list_msg += f'#{i + 1} | {_role[0]} - Max Level: {_role[1]}\n'
            msg = f'What role should the new role come after?\nValid input: any role in this ordered list (number in list):\n{role_list_msg}'
            await ctx.send(msg)

            try:
                after_message = await self.bot.wait_for('message', check=after_check, timeout=60)
            except asyncio.TimeoutError:
                return await ctx.send('add_role function timed out')

            new_role_position = int(after_message.content)
            if new_role_position > len(leveling_routes[branch]) + 1 or new_role_position < 1:
                await ctx.send('Invalid number')
                return await finish(new_role, role_max_level)
            new_role_route_list = leveling_routes[branch][:]
            new_role_route_list.insert(new_role_position, (new_role.name, role_max_level))

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': new_role_route_list}})
            db.get_levels.invalidate('leveling_routes', ctx.guild.id)

        new_role = await role()
        role_max_level = await max_level()
        await finish(new_role, role_max_level)

        await ctx.send(f'added {new_role.name} to {branch} route')
        return await self.leveling_routes(ctx, True)

    @commands.command(help='Remove role from a leveling route', usage='remove_role [branch] [role name]', examples=['remove_role participation Council member'], clearance='Admin', cls=command.Command)
    async def remove_role(self, ctx, branch=None, *, role_name=None):
        if branch is None:
            return await embed_maker.command_error(ctx)

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        if branch not in leveling_routes:
            embed = embed_maker.message(ctx, 'That is not a valid branch (contribution/participation)', colour='red')
            return await ctx.send(embed=embed)

        if role_name is None:
            return await embed_maker.command_error(ctx, '[role name]')

        for role in leveling_routes[branch]:
            if role[0] == role_name:
                await ctx.send(f'removed {role[0]} from {branch} route')
                new_branch = leveling_routes[branch][:]
                new_branch.remove(role)
                db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': new_branch}})
                db.get_levels.invalidate('leveling_routes', ctx.guild.id)
                return await self.leveling_routes(ctx, True)
        else:
            return await embed_maker.command_error(ctx, '[role name]')

    @commands.command(help='See current leveling routes', usage='leveling_routes', examples=['leveling_routes'], clearance='User', cls=command.Command)
    async def leveling_routes(self, ctx, new=False):
        lvl_routes = db.get_levels('leveling_routes', ctx.guild.id)
        embed_colour = db.get_server_options('embed_colour', ctx.guild.id)

        if new:
            embed_colour = embed_maker.get_colour('green')
            author = 'New Leveling Routes'
        else:
            author = 'Leveling Routes'

        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_author(name=author, icon_url=ctx.guild.icon_url)
        embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

        for branch in lvl_routes:
            value = ''
            for i, _role in enumerate(lvl_routes[branch]):
                role = discord.utils.find(lambda r: r.name == _role[0], ctx.guild.roles)
                if role is None:
                    role = await ctx.guild.create_role(name=_role[0])
                value += f'\n**#{i+1}:** <@&{role.id}> - Max Level: {_role[1]}'
            embed.add_field(name=f'>{branch.title()}', value=value, inline=False)
        return await ctx.send(embed=embed)

    @commands.command(help='award someone contribution points, for contributing to the server or youtube channels', usage='award [@member] [amount]', examples=['award @Hattyot 500'], clearance='Mod', cls=command.Command)
    async def award(self, ctx, member=None, amount=None):
        if member is None:
            return await embed_maker.command_error(ctx)
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            return await embed_maker.command_error(ctx, '[@member]')

        if member.bot:
            embed = embed_maker.message(ctx, 'You can\'t give contribution points to bots', colour='red')
            return await ctx.send(embed=embed)
        if member == ctx.author:
            embed = embed_maker.message(ctx, 'You can\'t give contribution points to yourself', colour='red')
            return await ctx.send(embed=embed)

        if amount is None:
            return await embed_maker.command_error(ctx, '[@member]')
        if not amount.isdigit():
            return await embed_maker.command_error(ctx, '[amount]')

        amount = round(int(amount))

        if amount > 1000:
            embed = embed_maker.message(ctx, 'The max amount of contributions points you can give is 1000', colour='red')
            return await ctx.send(embed=embed)

        user_cp = db.get_levels('cp', ctx.guild.id, member.id)
        new_cp = amount + user_cp

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.cp': new_cp}})
        db.get_levels.invalidate('cp', ctx.guild.id, member.id)

        embed = embed_maker.message(ctx, f'<@{member.id}> has been awarded **{amount} contribution points**', colour='green')

        if user_cp == 0:
            await ctx.send(embed=embed)
            leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
            first_role_name = leveling_routes['contribution'][0][0]
            first_role = discord.utils.find(lambda r: r.name == first_role_name, ctx.guild.roles)
            if first_role is None:
                first_role = await ctx.guild.create_role(name=first_role_name)
            await member.add_roles(first_role)

            if new_cp < 1000:
                reward_text = f'Congrats <@{member.id}> you\'ve advanced to a level **0** <@&{first_role.id}>, due to your contributions!'
            else:
                reward_text = f'Congrats <@{member.id}> you\'ve advanced to a level **1** <@&{first_role.id}>, due to your contributions!'
                db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{member.id}.c_level': 1}})
                db.get_levels.invalidate('c_level', ctx.guild.id, member.id)

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.c_role': first_role.name}})
            db.get_levels.invalidate('c_role', ctx.guild.id, member.id)

            embed_colour = db.get_server_options('embed_colour', ctx.guild.id)
            embed = discord.Embed(colour=embed_colour, description=reward_text, timestamp=datetime.now())
            embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
            embed.set_author(name='Level Up!', icon_url=ctx.guild.icon_url)

            channel_id = db.get_levels('level_up_channel', ctx.guild.id)
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                return await ctx.send(embed=embed)
            else:
                return await channel.send(embed=embed)

        await ctx.send(embed=embed)
        return await self.level_up(ctx, member, 'contribution')

    @commands.command(help='Shows your (or someone else\'s) rank, level and xp', usage='rank (@member)', examples=['rank', 'rank @Hattyot'], clearance='User', cls=command.Command)
    async def rank(self, ctx, member=None):
        if member and ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            member = ctx.author

        if member.bot:
            return

        member_level = self.user_role_level(ctx, 'participation', member, True)
        member_role = discord.utils.find(lambda r: r.name == db.get_levels('role', ctx.guild.id, member.id), ctx.guild.roles)
        member_c_role = discord.utils.find(lambda r: r.name == db.get_levels('c_role', ctx.guild.id, member.id), ctx.guild.roles)

        member_c_level = self.user_role_level(ctx, 'contribution', member, True)
        rank = self.calculate_user_rank('xp', ctx.guild.id, member.id)
        c_rank = self.calculate_user_rank('cp', ctx.guild.id, member.id)

        if member_role is None:
            member_role = await ctx.guild.create_role(name=db.get_levels('role', ctx.guild.id, member.id))

        sp_value = f'**#{rank}** | **Level** {member_level} <@&{member_role.id}>'

        if db.get_levels('c_role', ctx.guild.id, member.id, ) == '':
            cp_value = f'**#{c_rank}** | **Level** {member_c_level}'
        else:
            if member_c_role is None:
                member_c_role = await ctx.guild.create_role(name=db.get_levels('c_role', ctx.guild.id, member.id))

            cp_value = f'**#{c_rank}** | **Level** {member_c_level} <@&{member_c_role.id}>'

        embed_colour = db.get_server_options('embed_colour', ctx.guild.id)
        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name=f'{member.name} - Rank', icon_url=ctx.guild.icon_url)
        embed.add_field(name='>Server Participation', value=sp_value, inline=False)
        embed.add_field(name='>Contributions', value=cp_value, inline=False)

        return await ctx.send(embed=embed)

    def calculate_user_rank(self, branch, guild_id, user_id):
        doc = db.levels.find_one({'guild_id': guild_id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1][branch], reverse=True)
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

        cooldown_expire = round(time()) + 45
        xp_cooldown[ctx.guild.id][ctx.author.id] = cooldown_expire

        xp_add = randint(15, 25)
        new_xp = ctx.author_xp + xp_add

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.xp': new_xp}})
        db.get_levels.invalidate('xp', ctx.guild.id, ctx.author.id)

        xp_until = xpi(ctx.guild, ctx.author, new_xp)
        if xp_until <= 0:
            await self.level_up(ctx, ctx.author, 'participation')

    async def level_up(self, ctx, member, branch):
        if branch == 'contribution':
            pre = 'c_'
        else:
            pre = ''

        user_role = db.get_levels(f'{pre}role', ctx.guild.id, member.id)
        user_role_level = self.user_role_level(ctx, branch, member)

        if user_role_level == -1:
            # Get next role
            leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
            roles = leveling_routes[branch]
            role_index = -2
            next_role = ''
            for i, role in enumerate(roles):
                if role[0] == user_role:
                    role_index = i
                if role_index == i - 1:
                    next_role = role[0]
                    break

            role = discord.utils.find(lambda r: r.name == next_role, ctx.guild.roles)

            if role is None:
                role = await ctx.guild.create_role(name=next_role)

            reward_text = f'Congrats <@{member.id}> you\'ve advanced to a level **1** <@&{role.id}>'

            await member.add_roles(role)
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.{pre}role': role.name}})
            db.get_levels.invalidate(f'{pre}role', ctx.guild.id, member.id)

        else:
            role = discord.utils.find(lambda r: r.name == user_role, ctx.guild.roles)
            reward_text = f'Congrats <@{member.id}> you\'ve become a level **{user_role_level}** <@&{role.id}>'

        if branch == 'contribution':
            reward_text += 'due to your contributions!'
        else:
            reward_text += '!'

        embed_colour = db.get_server_options('embed_colour', ctx.guild.id)
        embed = discord.Embed(colour=embed_colour, description=reward_text, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name='Level Up!', icon_url=ctx.guild.icon_url)

        channel_id = db.get_levels('level_up_channel', ctx.guild.id)
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            await ctx.send(embed=embed)
        else:
            await channel.send(embed=embed)

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{member.id}.{pre}level': 1}})
        db.get_levels.invalidate(f'{pre}level', ctx.guild.id, member.id)

    # Returns the level of current role
    def user_role_level(self, ctx, branch, member, current=False):
        if branch == 'contribution':
            pre = 'c_'
        else:
            pre = ''

        user_level = db.get_levels(f'{pre}level', ctx.guild.id, member.id)
        user_role = db.get_levels(f'{pre}role', ctx.guild.id, member.id)

        if user_role == '':
            return user_level

        if not current:
            user_level += 1

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        all_roles = leveling_routes[branch]

        role_index = 0
        for role in all_roles:
            if role[0] != user_role:
                role_index += 1
            else:
                break

        current_level_total = 0
        previous_level_total = 0
        role_amount = len(all_roles)
        for i, role in enumerate(all_roles):
            current_level_total += role[1]
            if role_amount - 1 == i:
                return user_level - previous_level_total
            if role_index > i:
                previous_level_total += role[1]
                continue
            if current_level_total > user_level:
                return user_level - previous_level_total
            if current_level_total == user_level:
                return role[1]
            if current_level_total < user_level:
                return -1


# How much xp is needed until level up
def xpi(guild, member, new_xp):
    user_xp = new_xp
    user_level = db.get_levels('level', guild.id, member.id)

    # total xp needed to gain the next level
    total_xp = 0
    for i in range(user_level + 1):
        # the formula to calculate how much xp you need for the next level
        total_xp += (5 * (i ** 2) + 50 * i + 100)

    return total_xp - user_xp


# How much cp is needed until level up, works the same way as xpi
def cpi(ctx, member, new_cp):
    user_cp = new_cp
    user_level = db.get_levels('c_level', ctx.guild.id, member.id)

    total_cp = 1000 * (user_level + 1)
    return total_cp - user_cp




def setup(bot):
    bot.add_cog(Levels(bot))
