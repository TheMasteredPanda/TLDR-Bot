import discord
import config
import re
from datetime import datetime
from time import time
from random import randint
from discord.ext import commands
from modules import database, command, embed_maker

db = database.Connection()
pp_cooldown = {}
hp_cooldown = {}
# Cooldown objects for giving and receiving reactions
receive_cooldown = {}
give_cooldown = {}


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Set or remove perks from parliamentary or honours roles which will be sent to user once they recieve that role',
                      usage='perk [action] -r [role name] -p (perk 1) | (perk 2) | (perk 3)',
                      examples=['perk set -r Party Member -p Access to party emotes | Access to the Ask TLDR channel', 'perk remove -r Party Member'],
                      clearance='Mod', cls=command.Command)
    async def perk(self, ctx, action=None, *, args=None):
        if action is None:
            return await embed_maker.command_error(ctx)

        valid_actions = ['set', 'remove']
        if action not in valid_actions:
            return await embed_maker.command_error(ctx, '[action]')

        if args is None:
            embed = embed_maker.message(ctx, 'Missing args', colour='red')
            return await ctx.send(embed=embed)

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        honours_branch = leveling_routes['honours']
        parliamentary_branch = leveling_routes['parliamentary']

        parsed_args = self.parse_rewards_args(args)
        role_name = parsed_args['r']
        err = ''
        if not role_name:
            err = 'Invalid arg: role name'
        else:
            filtered_parliamentary = list(filter(lambda x: x[0].lower() == role_name.lower(), parliamentary_branch))
            filtered_honours = list(filter(lambda x: x[0].lower() == role_name.lower(), honours_branch))
            if filtered_parliamentary:
                role_index = parliamentary_branch.index(filtered_parliamentary[0])
                branch = 'parliamentary'
            elif filtered_honours:
                role_index = honours_branch.index(filtered_honours[0])
                branch = 'honours'
            else:
                err = 'Invalid arg: role name'

        perks = parsed_args['p']
        if not perks:
            err = 'Invalid arg: perks'

        if err:
            embed = embed_maker.message(ctx, err, colour='red')
            return await ctx.send(embed=embed)

        # edit role instance in leveling routes list by replacing it
        new_role_tuple = (filtered_parliamentary[0][0], filtered_parliamentary[0][1], perks)
        print(leveling_routes)
        leveling_routes[branch][role_index] = new_role_tuple

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': leveling_routes[branch]}})
        db.get_levels.invalidate('leveling_routes', ctx.guild.id)

        perks_str = "\n • ".join(perks)
        msg = f'Added perks to {role_name}:\n • {perks_str}'
        embed = embed_maker.message(ctx, msg, colour='green')
        await ctx.send(embed=embed)

    @commands.command(help='See all the perks that a role has to offer',
                      usage='perks [role name]',
                      examples=['perks Party Member'],
                      clearance='User', cls=command.Command)
    async def perks(self, ctx, *, role_name=None):
        if role_name is None:
            return await embed_maker.command_error(ctx)

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        honours_branch = leveling_routes['honours']
        parliamentary_branch = leveling_routes['parliamentary']

        filtered_parliamentary = list(filter(lambda x: x[0].lower() == role_name.lower(), parliamentary_branch))
        filtered_honours = list(filter(lambda x: x[0].lower() == role_name.lower(), honours_branch))
        if filtered_parliamentary:
            role = filtered_parliamentary[0]
        elif filtered_honours:
            role = filtered_honours[0]
        else:
            embed = embed_maker.message(ctx, 'I couldn\'t find a role by that name', colour='red')
            return await ctx.send(embed=embed)

        # checks if perks list in role tuple
        if len(role) < 3 or not role[2]:
            msg = f'**{role[0]}** currently offers no perks'
        else:
            perks_str = "\n • ".join(role[2])
            msg = f'Perks for {role[0]}:\n • {perks_str}'

        embed = embed_maker.message(ctx, msg)
        await ctx.send(embed=embed)

    def parse_rewards_args(self, args):
        result = {
            'r': '',
            'p': []
        }

        # Filters out empty strings
        split_args = filter(None, args.split('-'))
        for a in split_args:
            # creates tuple of arg and it's value and removes whitespaces where necessary
            match = tuple(map(str.strip, a.split(' ', 1)))

            # returns if arg is missing value
            if len(match) < 2:
                return result

            key, value = match

            # Special case for p (perks)
            if key == 'p':
                perks = list(map(str.strip, value.split('|', 1)))
                result['p'] = perks
                continue

            result[key] = value

        return result

    @commands.command(help='Add a role to a leveling route (honours/parliamentary)',
                      usage='add_role -b [branch] -r [role name] -l [max level]',
                      examples=['add_role -b honours -r Lord -l 5'], clearance='Admin', cls=command.Command)
    async def add_role(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        parsed_args = self.parse_role_args(args)
        branch = parsed_args['b']
        role_name = parsed_args['r']
        role_level = parsed_args['l']

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        if branch not in leveling_routes:
            embed = embed_maker.message(ctx, 'That is not a valid branch. (honours/parliamentary)', colour='red')
            return await ctx.send(embed=embed)

        if not role_name or not role_level:
            embed = embed_maker.message(ctx, 'One or more of the args is invalid', colour='red')
            return await ctx.send(embed=embed)

        new_role = discord.utils.find(lambda r: r.name == role_name, ctx.guild.roles)
        if new_role is None:
            try:
                new_role = await ctx.guild.create_role(name=role_name)
            except discord.Forbidden:
                return await ctx.send('failed to create role, missing permissions')

        new_role_route_list = leveling_routes[branch][:]
        new_role_tuple = (new_role.name, int(role_level), [])
        new_role_route_list.insert(len(leveling_routes[branch]), new_role_tuple)

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': new_role_route_list}})
        db.get_levels.invalidate('leveling_routes', ctx.guild.id)

        await ctx.send(f'added {new_role.name} to {branch} route')
        await self.display_new_leveling_routes(ctx, branch.lower())

        prev_role_name = ''
        for i, r in enumerate(new_role_route_list):
            if r[0] == new_role.name:
                prev_role_name = new_role_route_list[i - 1][0]
                break

        # Checks if users at the top need the new role
        prev_role = discord.utils.find(lambda r: r.name == prev_role_name, ctx.guild.roles)
        pre = 'p' if branch.lower() == 'parliamentary' else 'h'
        for m in prev_role.members:
            user_role_level = await self.user_role_level(ctx, branch, m, 0)

            if user_role_level < 0:
                # Get next role
                role_index = self.get_role_index(branch, ctx.guild.id, prev_role_name)
                new_role = new_role_route_list[role_index + abs(user_role_level)][0]

                role = discord.utils.find(lambda r: r.name == new_role, ctx.guild.roles)
                if role is None:
                    role = await ctx.guild.create_role(name=new_role)

                await m.add_roles(role)
                db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{m.id}.{pre}_role': role.name}})
                db.get_levels.invalidate(f'{pre}_role', ctx.guild.id, m.id)

                user_role_level = await self.user_role_level(ctx, branch, m, 0)
                reward_text = f'Congrats **{m.name}** you\'ve advanced to a level **{user_role_level}** <@&{role.id}>'

                return await self.level_up_message(ctx, m, reward_text, new_role_tuple)

    @commands.command(help='Add a channel to the list of channels, in which honours points can be gained', usage='add_honours_channels [#channel]', examples=['add_honours_channels #court'], clearance='Admin', cls=command.Command)
    async def add_honours_channel(self, ctx, channel=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        channel_list = db.get_levels('honours_channels', ctx.guild.id)

        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]
            if channel.id in channel_list:
                embed = embed_maker.message(ctx, f'That channel is already on the list', colour='red')
                return await ctx.send(embed=embed)
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$push': {f'honours_channels': channel.id}})
            db.get_levels.invalidate('honours_channels', ctx.guild.id)

            embed = embed_maker.message(ctx, f'<#{channel.id}> has been added to the list', colour='green')
            await ctx.send(embed=embed)
        else:
            return await embed_maker.command_error(ctx, '[#channel]')

    @commands.command(help='Remove a channel from the list of channels, in which honours points can be gained', usage='add_honours_channels [#channel]', examples=['add_honours_channels #court'], clearance='Admin', cls=command.Command)
    async def remove_honours_channel(self, ctx, channel=None):
        if channel is None:
            return await embed_maker.command_error(ctx)

        channel_list = db.get_levels('honours_channels', ctx.guild.id)

        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]
            if channel.id not in channel_list:
                embed = embed_maker.message(ctx, f'That channel is not on the list', colour='red')
                return await ctx.send(embed=embed)
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$pull': {f'honours_channels': channel.id}})
            db.get_levels.invalidate('honours_channels', ctx.guild.id)

            embed = embed_maker.message(ctx, f'<#{channel.id}> has been removed from the list', colour='green')
            await ctx.send(embed=embed)
        else:
            return await embed_maker.command_error(ctx, '[#channel]')

    @commands.command(help='See the current list of channels where honours points can be earned', usage='honours_channels', examples=['honours_channels'], clearance='Mod', cls=command.Command)
    async def honours_channels(self, ctx):
        channel_list = db.get_levels('honours_channels', ctx.guild.id)
        channel_list_str = '\n'.join(f'<#{i}>\n' for i in channel_list) if channel_list else 'None'

        embed = embed_maker.message(ctx, channel_list_str)
        return await ctx.send(embed=embed)

    @commands.command(help='Edit attributes of a role',
                      usage='edit_role -b [branch] -r [role name] -nr [new role name] -nl [new max level]',
                      examples=['edit_role -b parliamentary -r Member -nr Citizen -nl 5'], clearance='Admin', cls=command.Command)
    async def edit_role(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        parsed_args = self.parse_role_args(args)
        branch = parsed_args['b']
        role_name = parsed_args['r']
        new_role_name = parsed_args['nr']
        new_role_level = parsed_args['nl']

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        if branch not in leveling_routes:
            embed = embed_maker.message(ctx, 'That is not a valid branch. (honours/parliamentary)', colour='red')
            return await ctx.send(embed=embed)

        if not role_name:
            embed = embed_maker.message(ctx, 'Role arg is empty', colour='red')
            return await ctx.send(embed=embed)

        for r in leveling_routes[branch]:
            if r[0] == role_name:
                break
        else:
            error_embed = embed_maker.message(ctx, f'{role_name} is not a valid role', colour='red')
            return await ctx.send(embed=error_embed)

        if not new_role_name and not new_role_level:
            embed = embed_maker.message(ctx, 'Neither a new role name nor a new max level is defined', colour='red')
            return await ctx.send(embed=embed)

        new_role_list = leveling_routes[branch][:]
        for i, _role in enumerate(leveling_routes[branch]):
            old_role_name, old_role_level = _role
            if old_role_name == role_name:
                role_level = new_role_level if new_role_level else old_role_level

                if new_role_name:
                    role_name = new_role_name
                    role = discord.utils.find(lambda r: r.name == old_role_name, ctx.guild.roles)
                    await role.edit(name=role_name)

                    # Update users in db
                    await self.update_user_roles(ctx, branch, role)
                else:
                    role_name = old_role_name

                new_role_list[i] = (role_name, round(int(role_level)))

                db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': new_role_list}})
                db.get_levels.invalidate('leveling_routes', ctx.guild.id)

                await ctx.send(f'Edited {role_name}')
                return await self.display_new_leveling_routes(ctx, branch.lower())

    async def update_user_roles(self, ctx, branch, role):
        if branch.lower() not in ['parliamentary', 'honours']:
            return embed_maker.command_error(ctx)
        pre = 'p_' if branch.lower() == 'parliamentary' else 'h_'
        for m in role.members:
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{m.id}.{pre}role': role.name}})
            db.get_levels.invalidate(f'{pre}role', ctx.guild.id, m.id)

    def parse_role_args(self, args):
        result = dict.fromkeys(['b', 'r', 'l', 'nr', 'nl'], '')

        split_args = filter(None, args.split('-'))
        for a in split_args:
            match = tuple(map(str.strip, a.split(' ', 1)))
            if len(match) < 2:
                return result
            key, value = match
            result[key] = value

        return result

    # For displaying new leveling routes when they are edited

    async def display_new_leveling_routes(self, ctx, branch='parliamentary'):
        embed = discord.Embed(colour=embed_maker.get_colour('green'), timestamp=datetime.now())
        embed.set_author(name='New Leveling Routes', icon_url=ctx.guild.icon_url)
        embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

        lvl_routes = db.get_levels('leveling_routes', ctx.guild.id)

        value = ''
        for i, _role in enumerate(lvl_routes[branch]):
            role = discord.utils.find(lambda r: r.name == _role[0], ctx.guild.roles)
            if role is None:
                role = await ctx.guild.create_role(name=_role[0])
            value += f'\n**#{i + 1}:** <@&{role.id}> - Max Level: {_role[1]}'
        embed.add_field(name=f'>{branch.title()}', value=value, inline=False)

        return await ctx.send(embed=embed)

    @commands.command(help='See current leveling routes', usage='leveling_routes', examples=['leveling_routes'], clearance='User', cls=command.Command)
    async def leveling_routes(self, ctx, branch='parliamentary'):
        lvl_routes = db.get_levels('leveling_routes', ctx.guild.id)
        embed_colour = config.DEFAULT_EMBED_COLOUR

        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_author(name='Leveling Routes', icon_url=ctx.guild.icon_url)
        embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

        # Look up how many people are in a role
        m_counts = dict.fromkeys([k[0] for k in lvl_routes[branch]], [])
        count = dict.fromkeys([k[0] for k in lvl_routes[branch]], 0)
        for r in reversed(lvl_routes[branch]):
            role = discord.utils.find(lambda _r: _r.name == r[0], ctx.guild.roles)
            for m in role.members:
                if m.id not in m_counts[r[0]]:
                    count[r[0]] += 1
                    m_counts[r[0]].append(m.id)

        value = ''
        for i, _role in enumerate(lvl_routes[branch]):
            role = discord.utils.find(lambda r: r.name == _role[0], ctx.guild.roles)
            if role is None:
                role = await ctx.guild.create_role(name=_role[0])
            value += f'\n**#{i + 1}:** <@&{role.id}> - {count[role.name]} People'
        embed.add_field(name=f'>{branch.title()} - Every 5 levels you advance a role', value=value, inline=False)

        return await ctx.send(embed=embed)

    @commands.command(help='award someone honours points, for contributing to the server or youtube channels', usage='award [@member] [amount]', examples=['award @Hattyot 500'], clearance='Mod', cls=command.Command)
    async def award(self, ctx, member=None, amount=None):
        if member is None:
            return await embed_maker.command_error(ctx)
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            return await embed_maker.command_error(ctx, '[@member]')

        if member.bot:
            embed = embed_maker.message(ctx, 'You can\'t give honours points to bots', colour='red')
            return await ctx.send(embed=embed)
        if member == ctx.author:
            embed = embed_maker.message(ctx, 'You can\'t give honours points to yourself', colour='red')
            return await ctx.send(embed=embed)

        if amount is None:
            return await embed_maker.command_error(ctx, '[amount]')
        if not amount.isdigit():
            return await embed_maker.command_error(ctx, '[amount]')

        amount = round(int(amount))

        user_hp = db.get_levels('hp', ctx.guild.id, member.id)
        new_hp = amount + user_hp

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.hp': new_hp}})
        db.get_levels.invalidate('hp', ctx.guild.id, member.id)

        embed = embed_maker.message(ctx, f'**{member.name}** has been awarded **{amount} honours points**', colour='green')
        await ctx.send(embed=embed)

        if user_hp == 0:
            return await self.hp_init(ctx, member, new_hp)

        return await self.level_up(ctx, member, 'honours', new_hp)

    async def hp_init(self, ctx, member, new_hp):
        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        # gets the name of the first honours role
        h_role_tuple = leveling_routes['honours'][0]
        h_role_name = h_role_tuple[0]
        h_role = discord.utils.find(lambda r: r.name == h_role_name, ctx.guild.roles)

        if h_role is None:
            h_role = await ctx.guild.create_role(name=h_role_name)

        await member.add_roles(h_role)
        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.h_role': h_role.name}})
        db.get_levels.invalidate('h_role', ctx.guild.id, member.id)

        if new_hp < 1000:
            lvl = 0
            reward_text = f'Congrats **{member.name}** you\'ve advanced to a level **{lvl}** <@&{h_role.id}> due to your contributions!'
            return await self.level_up_message(ctx, member, reward_text, h_role_tuple)
        else:
            return await self.level_up(ctx, member, 'honours', new_hp)

    @commands.command(help='Shows the leveling leaderboards (parliamentary(p)/honours(h)) on the server',
                      usage='leaderboard (branch)', aliases=['lb'],
                      examples=['leaderboard parliamentary', 'leaderboard honours'], clearance='User',
                      cls=command.Command)
    async def leaderboard(self, ctx, branch='parliamentary'):
        if branch is None:
            return await embed_maker.command_error(ctx)

        branch = 'honours' if branch in ['h', 'honours'] else 'parliamentary'

        if branch == 'honours':
            pre = 'h'
        elif branch == 'parliamentary':
            pre = 'p'
        else:
            return

        doc = db.levels.find_one({'guild_id': ctx.guild.id})
        # Sorts users and takes out people who's pp or hp is 0
        sorted_users = sorted([(u, doc['users'][u]) for u in doc['users'] if doc['users'][u][f'{pre}p'] > 0], key=lambda x: x[1][f'{pre}p'], reverse=True)

        user = [u for u in sorted_users if u[0] == str(ctx.author.id)]
        if user:
            user_index = sorted_users.index(user[0])
        else:
            user_index = None

        embed_colour = config.DEFAULT_EMBED_COLOUR
        lboard_str = ''

        for i, u in enumerate(sorted_users):
            if i == 10:
                break

            user_id, user_values = u
            user_role_name = user_values[f'{pre}_role']
            user_role = discord.utils.find(lambda r: r.name == user_role_name, ctx.guild.roles)

            if user_role_name == '':
                i -= 1
                continue

            if user_role is None:
                user_role = await ctx.guild.create_role(name=user_role_name)

            member = ctx.guild.get_member(int(user_id))
            if member is None:
                try:
                    member = await ctx.guild.fetch_member(int(user_id))
                except:
                    i -= 1
                    db.levels.update_one({'guild_id': ctx.guild.id}, {'$unset': {f'users.{user_id}': ''}})
                    continue

            role_level = await self.user_role_level(ctx, branch, member)
            progress_percent = self.percent_till_next_level(branch, ctx.guild.id, member.id)

            if user_id == str(ctx.author.id):
                lboard_str += f'***`#{i + 1}`*** - *{member.name} | **Level {role_level}** <@&{user_role.id}> | Progress: **{progress_percent}%***\n'
            else:
                lboard_str += f'`#{i + 1}` - {member.name} | **Level {role_level}** <@&{user_role.id}> | Progress: **{progress_percent}%**\n'

        if lboard_str == '':
            description = 'Damn, this place is empty'
        else:
            description = lboard_str

        lboard_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=description)
        lboard_embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
        lboard_embed.set_author(name=f'{branch.title()} Leaderboard', icon_url=ctx.guild.icon_url)

        # Displays user position under leaderboard
        if user_index is None or user_index <= 9:
            return await ctx.send(embed=lboard_embed)

        your_pos_str = ''
        for i in range(-1, 2):
            if user_index == 10 and i == -1:
                continue

            u = sorted_users[user_index + i]
            u_obj = ctx.guild.get_member(int(u[0]))
            if u_obj is None:
                try:
                    u_obj = await ctx.guild.fetch_member(int(u[0]))
                except:
                    i -= 1
                    db.levels.update_one({'guild_id': ctx.guild.id}, {'$unset': {f'users.{u[0]}': ''}})
                    continue

            user_role_name = u[1][f'{pre}_role']
            user_role = discord.utils.find(lambda r: r.name == user_role_name, ctx.guild.roles)

            if user_role_name == '':
                i -= 1
                continue

            if user_role is None:
                user_role = await ctx.guild.create_role(name=user_role_name)

            role_level = await self.user_role_level(ctx, branch, u_obj)

            progress_percent = self.percent_till_next_level(branch, ctx.guild.id, u_obj.id)
            if u[0] == str(ctx.author.id):
                your_pos_str += f'***`#{user_index + 1 + i}`*** - *{u_obj.name} | **Level {role_level}** <@&{user_role.id}> | Progress: **{progress_percent}%***\n'
            else:
                your_pos_str += f'`#{user_index + 1 + i}` - {u_obj.name} | **Level {role_level}** <@&{user_role.id}> | Progress: **{progress_percent}%**\n'

        lboard_embed.add_field(name='Your Position', value=your_pos_str)

        await ctx.send(embed=lboard_embed)

    @commands.command(help='Shows your (or someone else\'s) rank and level', usage='rank (member)', examples=['rank', 'rank @Hattyot', 'rank Hattyot'], clearance='User', cls=command.Command)
    async def rank(self, ctx, member=None):
        if member and ctx.message.mentions:
            mem = ctx.message.mentions[0]
        elif member:
            regex = re.compile(fr'({member.lower()})')
            mem = discord.utils.find(lambda m: re.findall(regex, m.name.lower()) or re.findall(regex, m.display_name.lower()) or m.id == member, ctx.guild.members)
            if mem is None:
                embed = embed_maker.message(ctx, 'I couldn\'t find a user with that name', colour='red')
                return await ctx.send(embed=embed)
        else:
            mem = ctx.author

        if mem.bot:
            return

        embed_colour = config.DEFAULT_EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_footer(text=f'{mem}', icon_url=mem.avatar_url)
        embed.set_author(name=f'{mem.name} - Rank', icon_url=ctx.guild.icon_url)

        # checks if honours section needs to be added
        member_hp = db.get_levels('hp', ctx.guild.id, mem.id)
        if member_hp > 0:
            member_h_level = await self.user_role_level(ctx, 'honours', mem)
            h_role_name = db.get_levels('h_role', ctx.guild.id, mem.id)
            member_h_role = discord.utils.find(lambda r: r.name == h_role_name, ctx.guild.roles)
            h_rank = self.calculate_user_rank('hp', ctx.guild.id, mem.id)

            if h_role_name != '':
                if member_h_role is None:
                    member_h_role = await ctx.guild.create_role(name=h_role_name)
                    await mem.add_roles(member_h_role)

                hp_progress = self.percent_till_next_level('honours', ctx.guild.id, mem.id)
                hp_value = f'**#{h_rank}** | **Level** {member_h_level} <@&{member_h_role.id}> | Progress: **{hp_progress}%**'
                embed.add_field(name='>Honours', value=hp_value, inline=False)

        member_p_level = await self.user_role_level(ctx, 'parliamentary', mem)
        p_role_name = db.get_levels('p_role', ctx.guild.id, mem.id)
        member_p_role = discord.utils.find(lambda r: r.name == p_role_name, ctx.guild.roles)
        p_rank = self.calculate_user_rank('pp', ctx.guild.id, mem.id)

        if member_p_role is None:
            member_p_role = await ctx.guild.create_role(name=p_role_name)
            await mem.add_roles(member_p_role)

        pp_progress = self.percent_till_next_level('parliamentary', ctx.guild.id, mem.id)
        pp_value = f'**#{p_rank}** | **Level** {member_p_level} <@&{member_p_role.id}> | Progress: **{pp_progress}%**'
        embed.add_field(name='>Parliamentary', value=pp_value, inline=False)

        return await ctx.send(embed=embed)

    def calculate_user_rank(self, branch, guild_id, user_id):
        doc = db.levels.find_one({'guild_id': guild_id})
        sorted_users = sorted(doc['users'].items(), key=lambda x: x[1][branch], reverse=True)
        user = [u for u in sorted_users if u[0] == str(user_id)]
        return sorted_users.index(user[0]) + 1

    async def process_reaction(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        user = guild.get_member(payload.user_id)
        channel = self.bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)

        # Add pp to user who received reaction
        if self.cooldown_expired(receive_cooldown, guild.id, message.author, 60):
            pp_add = 10
            await self.add_reaction_pp(message, message.author, pp_add)

        # Add pp to user who gave reaction
        if self.cooldown_expired(give_cooldown, guild.id, user, 60):
            pp_add = 5
            await self.add_reaction_pp(message, user, pp_add)

    async def add_reaction_pp(self, ctx, user, pp_add):
        new_pp = db.get_levels('pp', ctx.guild.id, user.id) + pp_add

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{user.id}.pp': new_pp}})
        db.get_levels.update('pp', ctx.guild.id, user.id, new_value=new_pp)

        await self.level_up(ctx, user, 'parliamentary', new_pp)

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

    async def process_hp_message(self, ctx):
        if self.cooldown_expired(hp_cooldown, ctx.guild.id, ctx.author.id, 45):
            hp_add = 10
            user_hp = db.get_levels('hp', ctx.guild.id, ctx.author.id)
            new_hp = user_hp + hp_add

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.hp': new_hp}})
            db.get_levels.update('hp', ctx.guild.id, ctx.author.id, new_value=new_hp)

            if user_hp == 0:
                return await self.hp_init(ctx, ctx.author, new_hp)

            await self.level_up(ctx, ctx.author, 'honours', new_hp)

    async def process_message(self, message):
        if self.cooldown_expired(pp_cooldown, message.guild.id, message.author.id, 60):
            pp_add = randint(15, 25)
            author_pp = db.get_levels('pp', message.guild.id, message.author.id)
            new_pp = author_pp + pp_add

            db.levels.update_one({'guild_id': message.guild.id}, {'$set': {f'users.{message.author.id}.pp': new_pp}})
            db.get_levels.update('pp', message.guild.id, message.author.id, new_value=new_pp)

            # Check role
            user_role_name = db.get_levels('p_role', message.guild.id, message.author.id)
            user_role = discord.utils.find(lambda r: r.name == user_role_name, message.guild.roles)
            if user_role and user_role not in message.author.roles:
                await message.author.add_roles(user_role)

            await self.level_up(message, message.author, 'parliamentary', new_pp)

    async def level_up(self, ctx, member, branch, new_value):
        if branch == 'honours':
            pre = 'h_'
            lvls_up = hpi(ctx.guild.id, member.id, new_value)
        else:
            pre = 'p_'
            lvls_up = ppi(ctx.guild.id, member.id, new_value)

        if lvls_up == 0:
            return

        user_role = db.get_levels(f'{pre}role', ctx.guild.id, member.id)

        role = discord.utils.find(lambda r: r.name == user_role, ctx.guild.roles)
        if role is None:
            role = await ctx.guild.create_role(name=user_role)
        if role is not None and role not in ctx.author.roles:
             await member.add_roles(role)

        user_role_level = await self.user_role_level(ctx, branch, member, lvls_up)
        new_role = ''
        if user_role_level < 0:
            # Get next role
            leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
            roles = leveling_routes[branch]
            role_index = self.get_role_index(branch, ctx.guild.id, role.name)
            if len(roles) - 1 < role_index + abs(user_role_level):
                new_role = roles[-1]
            else:
                new_role = roles[role_index + abs(user_role_level)]

            new_role_obj = discord.utils.find(lambda r: r.name == new_role[0], ctx.guild.roles)
            if new_role_obj is None:
                new_role_obj = await ctx.guild.create_role(name=new_role[0])

            await member.add_roles(new_role_obj)
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.{pre}role': new_role_obj.name}})
            db.get_levels.invalidate(f'{pre}role', ctx.guild.id, member.id)

            user_role_level = await self.user_role_level(ctx, branch, member, lvls_up)
            reward_text = f'Congrats **{member.name}** you\'ve advanced to a level **{user_role_level}** <@&{new_role_obj.id}>'

        else:
            role = discord.utils.find(lambda r: r.name == user_role, ctx.guild.roles)

            if role is None:
                role = await ctx.guild.create_role(name=user_role)
                await member.add_roles(role)

            reward_text = f'Congrats **{member.name}** you\'ve become a level **{user_role_level}** <@&{role.id}>'

        if branch == 'honours':
            reward_text += ' due to your contributions!'
        else:
            reward_text += '!'

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{member.id}.{pre}level': lvls_up}})
        db.get_levels.invalidate(f'{pre}level', ctx.guild.id, member.id)

        await self.level_up_message(ctx, member, reward_text, new_role if new_role else ())

    @commands.command(name='@_me', help='Makes the bot @ you when you level up', usage='@_me', examples=['@_me', '@_me'], clearance='User', cls=command.Command)
    async def at_me(self, ctx):
        settings = db.get_levels('settings', ctx.guild.id, ctx.author.id)
        enabled = settings['@_me']
        if enabled:
            msg = 'Disabling @ when you level up'
            colour = 'orange'
            boolean = False
        else:
            msg = 'Enabling @ when you level up'
            colour = 'green'
            boolean = True

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.settings.@_me': boolean}})
        db.get_levels.invalidate('settings', ctx.guild.id, ctx.author.id)
        embed = embed_maker.message(ctx, msg, colour=colour)
        return await ctx.send(embed=embed)

    async def level_up_message(self, ctx, member, reward_text, role_tuple):
        embed_colour = config.DEFAULT_EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, description=reward_text, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name='Level Up!', icon_url=ctx.guild.icon_url)

        channel_id = db.get_levels('level_up_channel', ctx.guild.id)
        channel = self.bot.get_channel(channel_id)

        settings = db.get_levels('settings', ctx.guild.id, ctx.author.id)
        enabled = settings['@_me']

        if channel is None:
            channel = ctx.channel

        if enabled:
            await channel.send(embed=embed, content=f'<@{member.id}>')
        else:
            await channel.send(embed=embed)

        # Sends user info about perks if role has them
        if len(role_tuple) < 3 or not bool(role_tuple[2]):
            return
        else:
            role = discord.utils.find(lambda r: r.name == role_tuple[0], ctx.guild.roles)
            if role is None:
                role = await ctx.guild.create_role(name=role_tuple[0])

            perks_str = "\n • ".join(role_tuple[2])
            msg = f'**Congrats** again on advancing to **{role.name}**!' \
                  f'\nThis role also gives you new **perks:**' \
                  f'\n • {perks_str}' \
                  f'\n\nFor more info on these perks ask one of the TLDR server mods'
            embed = discord.Embed(colour=embed_colour, description=msg, timestamp=datetime.now())
            embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
            embed.set_author(name='New Perks!', icon_url=ctx.guild.icon_url)

            return await member.send(embed=embed)

    # Returns the level of current role
    async def user_role_level(self, ctx, branch, member, lvl_add=0):
        if branch == 'honours':
            pre = 'h_'
        else:
            pre = 'p_'

        user_level = db.get_levels(f'{pre}level', ctx.guild.id, member.id)
        user_role = db.get_levels(f'{pre}role', ctx.guild.id, member.id)

        if user_role == '':
            return user_level

        role_obj = discord.utils.find(lambda r: r.name == user_role, ctx.guild.roles)

        if role_obj is None:
            role_obj = await ctx.guild.create_role(name=user_role)
        if role_obj not in member.roles:
            await member.add_roles(role_obj)

        user_level = int(user_level + lvl_add)

        leveling_routes = db.get_levels('leveling_routes', ctx.guild.id)
        all_roles = leveling_routes[branch]
        role_amount = len(all_roles)

        role_index = self.get_role_index(branch, ctx.guild.id, user_role)
        current_level_total = 5*(role_index+1)
        previous_level_total = 5*role_index

        if role_amount == role_index+1:
            return user_level - previous_level_total
        if current_level_total > user_level:
            return user_level - previous_level_total
        if current_level_total == user_level:
            return 5
        if current_level_total < user_level:
            # calculates how many roles user goes up
            return -(int(((user_level-current_level_total)/5)) + 1)

    def get_role_index(self, branch, guild_id, user_role):
        if user_role == '':
            return None

        leveling_routes = db.get_levels('leveling_routes', guild_id)
        all_roles = leveling_routes[branch]

        for i, role in enumerate(all_roles):
            if role[0] == user_role:
                return i
        else:
            return 0

    def percent_till_next_level(self, branch, guild_id, user_id):
        if branch == 'honours':
            pre = 'h'
        else:
            pre = 'p'

        user_points = db.get_levels(f'{pre}p', guild_id, user_id)
        user_level = db.get_levels(f'{pre}_level', guild_id, user_id)

        if pre == 'p':
            # points needed to gain next level from beginning of current level
            pnu = (5 * (user_level ** 2) + 50 * user_level + 100)
            # total points needed to gain next level from 0 points
            tpu = 0
            for j in range(int(user_level) + 1):
                tpu += (5 * (j ** 2) + 50 * j + 100)

            # point needed to gain next level
            pun = tpu - user_points

            percent = 100 - int((pun * 100)/pnu)

        else:
            pnu = 1000
            tpu = 1000 * (user_level + 1)
            pun = tpu - user_points

            percent = 100 - int((pun * 100)/pnu)

        if percent == 100 and pun != 0:
            return 99.9

        return percent


# How much pp is needed until level up
def ppi(guild_id, member_id, new_pp):
    user_pp = new_pp
    user_level = db.get_levels('p_level', guild_id, member_id)

    for i in range(1000):
        # total pp needed to gain the next level
        total_pp = 0
        for j in range(int(user_level) + i + 1):
            # the formula to calculate how much pp you need for the next level
            total_pp += (5 * ((j) ** 2) + 50 * (j) + 100)

        if total_pp - user_pp >= 0:
            return i


# How much hp is needed until level up, works the same way as ppi
def hpi(guild_id, member_id, new_hp):
    user_hp = new_hp
    user_level = db.get_levels('h_level', guild_id, member_id)

    for i in range(1000):
        total_hp = 1000 * (user_level + i)
        if total_hp - user_hp >= 0:
            return i - 1


def setup(bot):
    bot.add_cog(Levels(bot))
