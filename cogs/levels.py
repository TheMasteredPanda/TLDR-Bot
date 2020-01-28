import discord
import asyncio
from datetime import datetime
from time import time
from random import randint
from discord.ext import commands
from modules import database, command, embed_maker, context

db = database.Connection()
xp_cooldown = {}
cp_cooldown = {}
# Cooldown objects for giving and receiving reactions
receive_cooldown = {}
give_cooldown = {}


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        help='Add a role to a leveling route (contribution/participation) - starts the process of adding a role',
        usage='add_role [branch]', examples=['add_role contribution', 'add_role participation'], clearance='Admin',
        cls=command.Command)
    async def add_role(self, ctx, branch=None):
        if branch is None:
            return await embed_maker.command_error(ctx)

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        if branch.lower() not in leveling_routes:
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

            db.levels.update_one({'guild_id': ctx.guild.id},
                                 {'$set': {f'leveling_routes.{branch}': new_role_route_list}})
            db.get_levels.invalidate('leveling_routes', ctx.guild.id)

        new_role = await role()
        role_max_level = await max_level()
        await finish(new_role, role_max_level)

        await ctx.send(f'added {new_role.name} to {branch} route')
        return await self.leveling_routes(ctx, True)

    @commands.command(help='Remove role from a leveling route', usage='remove_role [branch] [role name]',
                      examples=['remove_role participation Council member'], clearance='Admin', cls=command.Command)
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

    @commands.command(help='Add a channel to the list of channels, in which contribution points can be gained',
                      usage='add_cp_channel [#channel]', examples=['add_cp_channel #court'], clearance='Admin',
                      cls=command.Command)
    async def add_cp_channel(self, ctx, channel=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        channel_list = db.get_levels('cp_channels', ctx.guild.id)

        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]
            if channel.id in channel_list:
                embed = embed_maker.message(ctx, f'That channel is already on the list', colour='red')
                return await ctx.send(embed=embed)
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$push': {f'cp_channels': channel.id}})
            db.get_levels.invalidate('cp_channels', ctx.guild.id)

            embed = embed_maker.message(ctx, f'<#{channel.id}> has been added to the list', colour='green')
            await ctx.send(embed=embed)
        else:
            return await embed_maker.command_error(ctx, '[#channel]')

    @commands.command(help='See the current list of channels where contribution points can be earned',
                      usage='cp_channel_list', examples=['add_cp_channel'], clearance='Mod', cls=command.Command)
    async def cp_channel_list(self, ctx):
        channel_list = db.get_levels('cp_channels', ctx.guild.id)

        if channel_list:
            channel_list_str = ''
            for i in channel_list:
                channel_list_str += f'<#{i}>\n'
        else:
            channel_list_str = 'None'

        embed = embed_maker.message(ctx, channel_list_str)
        return await ctx.send(embed=embed)

    @commands.command(help='start the role editing process, edit attributes of a role (max level/name)',
                      usage='edit_role [branch]', examples=['edit_role participation'], clearance='Admin',
                      cls=command.Command)
    async def edit_role(self, ctx, branch=None):
        if branch is None:
            return await embed_maker.command_error(ctx)

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        if branch not in leveling_routes:
            embed = embed_maker.message(ctx, 'That is not a valid branch (contribution/participation)', colour='red')
            return await ctx.send(embed=embed)

        async def role():
            def check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            msg = 'What is the name of the role you want to edit?'
            await ctx.send(msg)
            try:
                role_message = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                return await ctx.send('edit_role function timed out')

            for _role in leveling_routes[branch]:
                if _role[0] == role_message.content:
                    return role_message.content
            else:
                embed = embed_maker.message(ctx, 'That is not a valid role', colour='red')
                await ctx.send(embed=embed)
                return await role()

        async def attribute():
            def check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            msg = 'What attribute of the role do you want to edit? (name/level)'
            await ctx.send(msg)
            try:
                attribute_message = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                return await ctx.send('edit_role function timed out')

            if attribute_message.content not in ('name', 'level'):
                embed = embed_maker.message(ctx, 'That is not a valid attribute', colour='red')
                await ctx.send(embed=embed)
                return await attribute()
            else:
                return attribute_message.content

        async def new_value():
            def check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            msg = 'What do you want the new value of the attribute to be?'
            await ctx.send(msg)
            try:
                new_value_message = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                return await ctx.send('edit_role function timed out')

            return new_value_message.content

        role = await role()
        attribute = await attribute()
        new_value = await new_value()
        new_role_list = leveling_routes[branch][:]
        for i, _role in enumerate(leveling_routes[branch]):
            if _role[0] == role:
                if attribute == 'level':
                    new_role_list[i] = (_role[0], round(int(new_value)))
                elif attribute == 'name':
                    role = discord.utils.find(lambda r: r.name == _role[0], ctx.guild.roles)
                    await role.edit(name=new_value)
                    new_role_list[i] = (new_value, _role[1])

                db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': new_role_list}})
                db.get_levels.invalidate('leveling_routes', ctx.guild.id)

                embed = embed_maker.message(ctx, f'{role} has been updated', colour='green')
                return await ctx.send(embed=embed)

    @commands.command(help='See current leveling routes', usage='leveling_routes', examples=['leveling_routes'],
                      clearance='User', cls=command.Command)
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
                value += f'\n**#{i + 1}:** <@&{role.id}> - Max Level: {_role[1]}'
            embed.add_field(name=f'>{branch.title()}', value=value, inline=False)
        return await ctx.send(embed=embed)

    @commands.command(help='award someone contribution points, for contributing to the server or youtube channels',
                      usage='award [@member] [amount]', examples=['award @Hattyot 500'], clearance='Mod',
                      cls=command.Command)
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
            return await embed_maker.command_error(ctx, '[amount]')
        if not amount.isdigit():
            return await embed_maker.command_error(ctx, '[amount]')

        amount = round(int(amount))

        if amount > 1000:
            embed = embed_maker.message(ctx, 'The max amount of contributions points you can give is 1000',
                                        colour='red')
            return await ctx.send(embed=embed)

        user_cp = db.get_levels('cp', ctx.guild.id, member.id)
        new_cp = amount + user_cp

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.cp': new_cp}})
        db.get_levels.invalidate('cp', ctx.guild.id, member.id)

        embed = embed_maker.message(ctx, f'<@{member.id}> has been awarded **{amount} contribution points**',
                                    colour='green')
        await ctx.send(embed=embed)

        if user_cp == 0:
            return await self.cp_init(ctx, member, new_cp)

        return await self.level_up(ctx, member, 'contribution', new_cp)

    async def cp_init(self, ctx, member, new_cp):
        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        first_role_name = leveling_routes['contribution'][0][0]
        first_role = discord.utils.find(lambda r: r.name == first_role_name, ctx.guild.roles)

        if first_role is None:
            first_role = await ctx.guild.create_role(name=first_role_name)

        await member.add_roles(first_role)

        if new_cp < 1000:
            lvl = 0
        else:
            lvl = 1
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{member.id}.c_level': 1}})
            db.get_levels.invalidate('c_level', ctx.guild.id, member.id)

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.c_role': first_role.name}})
        db.get_levels.invalidate('c_role', ctx.guild.id, member.id)

        reward_text = f'Congrats <@{member.id}> you\'ve advanced to a level **{lvl}** <@&{first_role.id}>, due to your contributions!'
        await self.level_up_message(ctx, member, reward_text)

    @commands.command(help='Shows the leveling leaderboards (participation/contribution) on the server',
                      usage='leaderboard [branch] (page)',
                      examples=['leaderboard participation', 'leaderboard contribution 2'], clearance='User',
                      cls=command.Command)
    async def leaderboard(self, ctx, branch=None, user_page=0):
        if branch is None:
            return await embed_maker.command_error(ctx)

        if branch == 'contribution':
            pre = 'c_'
            points = 'cp'
        else:
            points = 'xp'
            pre = ''

        doc = db.levels.find_one({'guild_id': ctx.guild.id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1][points], reverse=True)
        embed_colour = db.get_server_options('embed_colour', ctx.guild.id)
        page_num = 1
        lboard = {page_num: []}

        for i, u in enumerate(sorted_users):
            if i == 10 * page_num:
                page_num += 1
                lboard[page_num] = []

            member = self.bot.get_user(u[0])
            if member is None:
                member = await self.bot.fetch_user(u[0])

            role_level = self.user_role_level(ctx.guild.id, branch, member.id, True)
            user_role_name = u[1][f'{pre}role']
            if user_role_name == '':
                continue
            user_role = discord.utils.find(lambda r: r.name == user_role_name, ctx.guild.roles)
            page_message = f'**#{i + 1}** - <@{u[0]}> | **Level {role_level}** <@&{user_role.id}>'
            lboard[page_num].append(page_message)

        if user_page not in lboard:
            user_page = 1

        if not lboard[user_page]:
            description = 'Damn, this place is empty'
        else:
            description = '\n'.join(lboard[user_page])

        lboard_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=description)
        lboard_embed.set_footer(text=f'Page {user_page}/{page_num} - {ctx.author}', icon_url=ctx.author.avatar_url)
        lboard_embed.set_author(name=f'{branch.title()} Leaderboard', icon_url=ctx.guild.icon_url)

        await ctx.send(embed=lboard_embed)

    @commands.command(help='Shows your (or someone else\'s) rank, level and xp', usage='rank (@member)',
                      examples=['rank', 'rank @Hattyot'], clearance='User', cls=command.Command)
    async def rank(self, ctx, member=None):
        if member and ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            member = ctx.author

        if member.bot:
            return

        member_level = self.user_role_level(ctx.guild.id, 'participation', member.id, True)
        member_c_level = self.user_role_level(ctx.guild.id, 'contribution', member.id, True)

        role_name = db.get_levels('role', ctx.guild.id, member.id)
        c_role_name = db.get_levels('c_role', ctx.guild.id, member.id)
        member_role = discord.utils.find(lambda r: r.name == role_name, ctx.guild.roles)
        member_c_role = discord.utils.find(lambda r: r.name == c_role_name, ctx.guild.roles)

        rank = self.calculate_user_rank('xp', ctx.guild.id, member.id)
        c_rank = self.calculate_user_rank('cp', ctx.guild.id, member.id)

        if member_role is None:
            member_role = await ctx.guild.create_role(name=role_name)

        sp_value = f'**#{rank}** | **Level** {member_level} <@&{member_role.id}>'

        if c_role_name == '':
            cp_value = f'**#{c_rank}** | **Level** {member_c_level}'
        else:
            if member_c_role is None:
                member_c_role = await ctx.guild.create_role(name=c_role_name)

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

    async def process_reaction(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        user = guild.get_member(payload.user_id)
        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        ctx = await self.bot.get_context(message, cls=context.Context)

        # Add xp to user who received reaction
        if self.cooldown_expired(receive_cooldown, guild.id, message.author, 60):
            xp_add = 10
            await self.add_reaction_xp(ctx, message.author, xp_add)

        # Add xp to user who gave reaction
        if self.cooldown_expired(give_cooldown, guild.id, user, 60):
            xp_add = 5
            await self.add_reaction_xp(ctx, user, xp_add)

    async def add_reaction_xp(self, ctx, user, xp_add):
        new_xp = db.get_levels('xp', ctx.guild.id, user.id) + xp_add

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{user.id}.xp': new_xp}})
        db.get_levels.invalidate('xp', ctx.guild.id, user.id)

        await self.level_up(ctx, user, 'participation', new_xp)

    def cooldown_expired(self, cooldown_dict, guild_id, member_id, cooldown_time):
        if guild_id not in cooldown_dict:
            cooldown_dict[guild_id] = {}
        if member_id in cooldown_dict[guild_id]:
            if round(time()) >= cooldown_dict[guild_id][member_id]:
                del cooldown_dict[guild_id][member_id]
            else:
                return False

        cooldown_expire = round(time()) + cooldown_time
        cooldown_dict[guild_id][member_id] = cooldown_expire
        return True

    async def process_cp_message(self, ctx):
        if self.cooldown_expired(cp_cooldown, ctx.guild.id, ctx.author.id, 60):
            cp_add = 5
            user_cp = ctx.author_cp
            new_cp = user_cp + cp_add

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.cp': new_cp}})
            db.get_levels.invalidate('cp', ctx.guild.id, ctx.author.id)

            if user_cp == 0:
                return await self.cp_init(ctx, ctx.author, new_cp)

            await self.level_up(ctx, ctx.author, 'contribution', new_cp)

    async def process_message(self, ctx):
        if self.cooldown_expired(xp_cooldown, ctx.guild.id, ctx.author.id, 45):
            xp_add = randint(15, 25)
            new_xp = ctx.author_xp + xp_add

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.xp': new_xp}})
            db.get_levels.invalidate('xp', ctx.guild.id, ctx.author.id)

            await self.level_up(ctx, ctx.author, 'participation', new_xp)

    async def level_up(self, ctx, member, branch, new_value):
        if branch == 'contribution':
            pre = 'c_'
            until = cpi(ctx.guild.id, member.id, new_value)
        else:
            pre = ''
            until = xpi(ctx.guild.id, member.id, new_value)

        if until > 0:
            return

        user_role = db.get_levels(f'{pre}role', ctx.guild.id, member.id)
        user_role_level = self.user_role_level(ctx.guild.id, branch, member.id)

        if user_role_level == -1:
            # Get next role
            leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
            roles = leveling_routes[branch]
            role_index = self.get_role_index(branch, ctx.guild.id, member.id)
            next_role = ''
            for i, role in enumerate(roles):
                # finds the next role by index
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

        await self.level_up_message(ctx, member, reward_text)

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{member.id}.{pre}level': 1}})
        db.get_levels.invalidate(f'{pre}level', ctx.guild.id, member.id)

    async def level_up_message(self, ctx, member, reward_text):
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

    # Returns the level of current role
    def user_role_level(self, guild_id, branch, member_id, current=False):
        if branch == 'contribution':
            pre = 'c_'
        else:
            pre = ''

        user_level = db.get_levels(f'{pre}level', guild_id, member_id)
        user_role = db.get_levels(f'{pre}role', guild_id, member_id)

        if user_role == '':
            return user_level

        if not current:
            user_level += 1

        leveling_routes = db.get_levels('leveling_routes', guild_id)
        all_roles = leveling_routes[branch]

        role_index = self.get_role_index(branch, guild_id, user_role)

        current_level_total = 0
        previous_level_total = 0
        role_amount = len(all_roles)
        for i, role in enumerate(all_roles):
            current_level_total += role[1]
            if role_amount == i + 1:
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

    def get_role_index(self, branch, guild_id, user_role):
        leveling_routes = db.get_levels('leveling_routes', guild_id)
        all_roles = leveling_routes[branch]

        for i, role in enumerate(all_roles):
            if role[0] == user_role:
                return i


# How much xp is needed until level up
def xpi(guild_id, member_id, new_xp):
    user_xp = new_xp
    user_level = db.get_levels('level', guild_id, member_id)

    # total xp needed to gain the next level
    total_xp = 0
    for i in range(user_level + 1):
        # the formula to calculate how much xp you need for the next level
        total_xp += (5 * (i ** 2) + 50 * i + 100)

    return total_xp - user_xp


# How much cp is needed until level up, works the same way as xpi
def cpi(guild_id, member_id, new_cp):
    user_cp = new_cp
    user_level = db.get_levels('c_level', guild_id, member_id)

    total_cp = 1000 * (user_level + 1)
    return total_cp - user_cp


def setup(bot):
    bot.add_cog(Levels(bot))
