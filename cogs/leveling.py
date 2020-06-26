import discord
import config
import re
from datetime import datetime
from time import time
from discord.ext import commands
from random import randint
from modules import database, embed_maker, command, format_time

pp_cooldown = {}
hp_cooldown = {}
db = database.Connection()


def cooldown_expired(cooldown_dict, guild_id, member_id, cooldown_time):
    if guild_id not in cooldown_dict:
        cooldown_dict[guild_id] = {}

    if member_id in cooldown_dict[guild_id]:
        if round(time()) >= cooldown_dict[guild_id][member_id]:
            del cooldown_dict[guild_id][member_id]
        else:
            return False

    expires = round(time()) + cooldown_time
    cooldown_dict[guild_id][member_id] = expires
    return True


class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Staff Commands

    @commands.command(help='remove latest boost from user or remove boost from role',
                      usage='remove_boost [user/role/everyone]',
                      examples=['remove_boost Hattyot', 'remove_boost Mayor', 'remove_boost everyone'],
                      clearance='Mod', cls=command.Command)
    async def remove_boost(self, ctx, source=None):
        if source is None:
            return await embed_maker.command_error(ctx)

        # get user or role to remove boost from
        if source is None:
            return await embed_maker.command_error(ctx, '[user/role/everyone]')
        else:
            # check if source is member
            boost_remove = self.get_member(ctx, source)
            source_type = 'user'

            # check if source is role or everyone
            if boost_remove is None:
                # role name of everyone is @everyone
                if source == 'everyone':
                    source = f'@{source}'

                boost_remove = discord.utils.find(lambda rl: rl.name.lower() == source.lower(), ctx.guild.roles)
                source_type = 'role'

        if boost_remove is None:
            return await embed_maker.command_error(ctx, '[user/role/everyone]')

        data = db.levels.find_one({'guild_id': ctx.guild.id})
        err = ''
        suc = ''
        if source_type == 'role' and 'roles' in data['boost']:
            if str(boost_remove.id) in data['boost']['roles']:
                db.levels.update_one(
                    {'guild_id': ctx.guild.id},
                    {'$unset': {f'boost.roles.{boost_remove.id}': ''}}
                )
                if source != '@everyone':
                    suc = f'Removed <@&{boost_remove.id}>\'s boost'
                else:
                    suc = 'Removed boost given to everyone'
            else:
                if source != '@everyone':
                    err = f'<@&{boost_remove.id}> has no active boosts'
                else:
                    err = 'No boost is active for everyone'

        elif source_type == 'user' and 'users' in data['boost']:
            if str(boost_remove.id) in data['boost']['users']:
                latest_boost = data['boost']['users'][f'{boost_remove.id}'][-1]
                db.levels.update_one(
                    {'guild_id': ctx.guild.id},
                    {'$pull': {f'boost.users.{boost_remove.id}': {'expires': latest_boost['expires']}}}
                )
                suc = f'Removed latest boost given to <@{boost_remove.id}>'
            else:
                err = f'User <@{boost_remove.id}> has no active boosts'

        if err:
            return await embed_maker.message(ctx, err, colour='red')
        elif suc:
            return await embed_maker.message(ctx, suc, colour='green')


    @commands.command(help='Give a user, a role or everyone x% more parliamentary points gain',
                      usage='boost [percent] [time] [user/role/everyone]',
                      examples=['boost 50% 24h everyone', 'boost 20% 2d Mayor', 'boost 150% 60m Hattyot'],
                      clearance='Mod', cls=command.Command)
    async def boost(self, ctx, percent=None, length=None, source=None):
        if percent is None:
            return await embed_maker.command_error(ctx)

        err = None
        # percent how much to boost by
        percent = percent.replace('%', '')
        if not percent.isdigit():
            err = 'invalid percent value'

        # how long should be boosted for
        if length is None:
            return await embed_maker.command_error(ctx, '[time]')

        length_in_seconds = format_time.parse(length)
        if length_in_seconds is None:
            err = 'invalid time value'

        # get user or role to boost
        if source is None:
            return await embed_maker.command_error(ctx, '[user/role/everyone]')
        else:
            # check if source is member
            to_boost = self.get_member(ctx, source)
            source_type = 'user'

            # check if source is role or everyone
            if to_boost is None:
                # role name of everyone is @everyone
                if source == 'everyone':
                    source = f'@{source}'

                to_boost = discord.utils.find(lambda rl: rl.name.lower() == source.lower(), ctx.guild.roles)
                source_type = 'role'

        if to_boost is None:
            err = f'I couldn\'t find a user or a role by `{source}`'

        data = db.levels.find_one({'guild_id': ctx.guild.id})
        # check if role already has boost
        if source_type == 'role':
            if str(to_boost.id) in data['boost']['roles']:
                expires = data["boost"]["roles"][str(to_boost.id)]["expires"]
                multiplier = data["boost"]["roles"][str(to_boost.id)]["multiplier"]
                percent = round((multiplier - 1) * 100)
                err = f'Role {source} already has an active boost\n' \
                      f'Expires: {format_time.seconds(expires)}\n' \
                      f'Boost: {percent}%'
        if err:
            return await embed_maker.message(ctx, err, colour='red')

        multiplier = int(percent)/100
        expires = round(time()) + int(length_in_seconds)
        boost_object = {
            'expires': expires,
            'multiplier': multiplier
        }
        action = 'push' if source_type == 'user' else 'set'
        db.levels.update_one(
            {'guild_id': ctx.guild.id},
            {f'${action}': {f'boost.{source_type}s.{to_boost.id}': boost_object}}
        )

        formatted_length = format_time.seconds(length_in_seconds)
        if source_type == 'user':
            msg = f'User {to_boost} will now receive a {percent}% boost to levels gain for {formatted_length}'
        elif source_type == 'role' and source != '@everyone':
            msg = f'Users with the role <@&{to_boost.id}> will now receive a {percent}% boost to their levels gain for {formatted_length}'
        else:
            msg = f'Everyone will now receive a {percent}% boost to their levels gain for {formatted_length}'

        return await embed_maker.message(ctx, msg, colour='green')

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

        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        leveling_routes = data['leveling_routes']
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
            return await embed_maker.message(ctx, err, colour='red')

        # edit role instance in leveling routes list by replacing it
        new_role_tuple = (filtered_parliamentary[0][0], filtered_parliamentary[0][1], perks)
        leveling_routes[branch][role_index] = new_role_tuple

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': leveling_routes[branch]}})

        perks_str = "\n • ".join(perks)
        msg = f'Added perks to {role_name}:\n • {perks_str}'
        return await embed_maker.message(ctx, msg, colour='green')

    @commands.command(help='Add a role to a leveling route (honours/parliamentary)',
                      usage='add_role -b [branch] -r [role name] -l [max level]',
                      examples=['add_role -b honours -r Lord -l 5'], clearance='Admin', cls=command.Command)
    async def add_role(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        parsed_args = self.parse_role_args(args)
        branch = parsed_args['b'].lower()
        role_name = parsed_args['r']
        role_level = parsed_args['l']

        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        leveling_routes = data['leveling_routes']

        if branch not in leveling_routes:
            return await embed_maker.message(ctx, 'That is not a valid branch. (honours/parliamentary)', colour='red')

        if not role_name or not role_level:
            return await embed_maker.message(ctx, 'One or more of the args is invalid', colour='red')

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
        data['leveling_routes'][branch] = new_role_route_list

        await ctx.send(f'added {new_role.name} to {branch} route')
        await self.display_new_leveling_routes(ctx, data, branch)

    @commands.command(help='Add or remove a channel from the list, in which honours points can be gained',
                      usage='honours_channel [action] [#channel]',
                      examples=['honours_channel add #court', 'honours_channel remove #Mods'],
                      clearance='Admin', cls=command.Command)
    async def honours_channel(self, ctx, action=None, channel=None):
        if action is None:
            return await embed_maker.command_error(ctx)
        if channel is None:
            return await embed_maker.command_error(ctx, '[#channel]')

        if action not in ['add', 'remove']:
            return await embed_maker.command_error(ctx, '[#action]')

        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        channel_list = data['honours_channels']

        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]

            if action == 'add':
                if channel.id in channel_list:
                    return await embed_maker.message(ctx, f'That channel is already on the list', colour='red')

                db.levels.update_one({'guild_id': ctx.guild.id}, {'$push': {f'honours_channels': channel.id}})
                msg = f'<#{channel.id}> has been added to the list'

            if action == 'remove':
                if channel.id not in channel_list:
                    return await embed_maker.message(ctx, f'That channel is not on the list', colour='red')

                db.levels.update_one({'guild_id': ctx.guild.id}, {'$pull': {f'honours_channels': channel.id}})
                msg = f'<#{channel.id}> has been removed from the list'

            return await embed_maker.message(ctx, msg, colour='green')
        else:
            return await embed_maker.command_error(ctx, '[#channel]')

    @commands.command(help='See the current list of channels where honours points can be earned',
                      usage='honours_channels', examples=['honours_channels'],
                      clearance='Mod', cls=command.Command)
    async def honours_channels(self, ctx):
        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        channel_list = data['honours_channels']
        channel_list_str = '\n'.join(f'<#{i}>\n' for i in channel_list) if channel_list else 'None'

        return await embed_maker.message(ctx, channel_list_str)

    @commands.command(help='Edit attributes of a role',
                      usage='edit_role -b [branch] -r [role name] -nr [new role name] -nl [new max level]',
                      examples=['edit_role -b parliamentary -r Member -nr Citizen -nl 5'],
                      clearance='Admin', cls=command.Command)
    async def edit_role(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        parsed_args = self.parse_role_args(args)
        branch = parsed_args['b']
        role_name = parsed_args['r']
        new_role_name = parsed_args['nr']
        new_role_level = parsed_args['nl']

        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        leveling_routes = data['leveling_routes']

        err = ''
        if branch not in leveling_routes:
            err = 'That is not a valid branch. (honours/parliamentary)'

        if not role_name:
            err = 'Role arg is empty'

        for r in leveling_routes[branch]:
            if r[0] == role_name:
                break
        else:
            err = f'{role_name} is not a valid role'

        if not new_role_name and not new_role_level:
            err = 'Neither a new role name nor a new max level is defined'

        if err:
            return await embed_maker.message(ctx, err, colour='red')

        new_role_list = leveling_routes[branch][:]
        for i, _role in enumerate(leveling_routes[branch]):
            old_role_name, old_role_level, _ = _role[0], _role[1], _role[2:]
            if old_role_name == role_name:
                role_level = new_role_level if new_role_level else old_role_level

                if new_role_name:
                    role_name = new_role_name
                    role = discord.utils.find(lambda rl: rl.name == old_role_name, ctx.guild.roles)
                    await role.edit(name=role_name)

                    # Update users in db
                    await self.update_user_roles(ctx, branch, role)
                else:
                    role_name = old_role_name

                new_role_list[i] = (role_name, int(role_level), [])

                db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': new_role_list}})
                data['leveling_routes'][branch] = new_role_list

                await ctx.send(f'Edited {role_name}')
                return await self.display_new_leveling_routes(ctx, data, branch.lower())

    @commands.command(help='award someone honours points', usage='award [member] [amount]',
                      examples=['award Hattyot 500'], clearance='Mod', cls=command.Command)
    async def award(self, ctx, member=None, amount=None):
        if member is None:
            return await embed_maker.command_error(ctx)

        member = self.get_member(ctx, member)

        if member is None:
            return await embed_maker.command_error(ctx, '[member]')

        err = ''
        if member.bot:
            err = 'You can\'t give honours points to bots'
        if member == ctx.author:
            err = 'You can\'t give honours points to yourself'

        if err:
            return await embed_maker.message(ctx, err, colour='red')

        if amount is None:
            return await embed_maker.command_error(ctx, '[amount]')
        if not amount.isdigit():
            return await embed_maker.command_error(ctx, '[amount]')

        amount = int(amount)
        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        # Check if user in database, if not, add them
        if str(member.id) not in data['users']:
            schema = database.schemas['levels_user']
            db.levels.update_one(
                {'guild_id': ctx.guild.id},
                {'$set': {f'users.{member.id}': schema}}
            )
            data['users'][str(member.id)] = schema

        levels_user = data['users'][str(member.id)]
        user_hp = levels_user['hp']
        new_hp = amount + user_hp

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.hp': new_hp}})
        print(levels_user)
        levels_user['hp'] = new_hp
        print(levels_user)

        await embed_maker.message(
            ctx, f'**{member.name}** has been awarded **{amount} honours points**',
            colour='green'
        )
        if levels_user['hp'] == 0:
            print('here')
            leveling_routes = data['leveling_routes']

            # gets the name of the first honours role
            h_role_tuple = leveling_routes['honours'][0]
            h_role_name = h_role_tuple[0]
            h_role = discord.utils.find(lambda r: r.name == h_role_name, ctx.guild.roles)

            if h_role is None:
                h_role = await ctx.guild.create_role(name=h_role_name)

            await member.add_roles(h_role)
            db.levels.update_one(
                {'guild_id': ctx.guild.id},
                {'$set': {f'users.{member.id}.h_role': h_role.name}}
            )
            levels_user['h_role'] = h_role.name

        return await self.level_up(ctx, member, 'honours', data)

    # User Commands

    @commands.command(name='@_me', help='Makes the bot @ you when you level up', usage='@_me',
                      examples=['@_me', '@_me'], clearance='User', cls=command.Command)
    async def at_me(self, ctx):
        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        if 'settings' not in data['users'][str(ctx.author.id)]:
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.settings': {'@_me': False}}})
            data['users'][str(ctx.author.id)]['settings'] = {'@_me': False}

        settings = data['users'][str(ctx.author.id)]['settings']
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
        return await embed_maker.message(ctx, msg, colour=colour)

    @commands.command(help='See current leveling routes', usage='leveling_routes',
                      examples=['leveling_routes'], clearance='User', cls=command.Command, aliases=['ranks'])
    async def leveling_routes(self, ctx, branch='parliamentary'):
        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        branch_switch = {
            'h': 'honours',
            'p': 'parliamentary'
        }
        branch = branch_switch.get(branch[0], 'parliamentary')

        leveling_routes = data['leveling_routes']
        embed_colour = config.EMBED_COLOUR

        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_author(name='Leveling Routes', icon_url=ctx.guild.icon_url)
        embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

        # Look up how many people are in a role
        # i don't know how this works, but it does
        m_counts = dict.fromkeys([k[0] for k in leveling_routes[branch]], [])
        count = dict.fromkeys([k[0] for k in leveling_routes[branch]], 0)
        for r in reversed(leveling_routes[branch]):
            role = discord.utils.find(lambda _r: _r.name == r[0], ctx.guild.roles)
            for m in role.members:
                if m.id not in m_counts[r[0]]:
                    count[r[0]] += 1
                    m_counts[r[0]].append(m.id)

        value = ''
        for i, _role in enumerate(leveling_routes[branch]):
            role = discord.utils.find(lambda rl: rl.name == _role[0], ctx.guild.roles)
            if role is None:
                role = await ctx.guild.create_role(name=_role[0])
            value += f'\n**#{i + 1}:** <@&{role.id}> - {count[role.name]} People'
        embed.add_field(name=f'>{branch.title()} - Every 5 levels you advance a role', value=value, inline=False)

        return await ctx.send(embed=embed)

    @commands.command(help='Shows the leveling leaderboards (parliamentary(p)/honours(h)) on the server',
                      usage='leaderboard (branch)', aliases=['lb'],
                      examples=['leaderboard parliamentary', 'leaderboard honours'], clearance='User',
                      cls=command.Command)
    async def leaderboard(self, ctx, branch='parliamentary'):
        if branch is None:
            return await embed_maker.command_error(ctx)

        key_switch = {
            'h': 'hp',
            'p': 'pp',
            # 'r': 'reputation',
        }
        branch_switch = {
            'h': 'honours',
            'p': 'parliamentary',
            # 'r': 'reputation'
        }
        key = key_switch.get(branch[0], 'pp')
        branch = branch_switch.get(branch[0], 'parliamentary')

        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        # Sorts users and takes out people who's pp or hp is 0
        sorted_users = sorted(
            [(u, data['users'][u]) for u in data['users'] if key in data['users'][u] and data['users'][u][key] > 0],
            key=lambda x: x[1][key], reverse=True
        )
        user = [u for u in sorted_users if u[0] == str(ctx.author.id)]
        user_index = sorted_users.index(user[0]) if user else None

        embed_colour = config.EMBED_COLOUR
        leaderboard_str = ''

        u_rank = 1
        for i, u in enumerate(sorted_users):
            if i == 10:
                break

            user_id, user_values = u

            member = ctx.guild.get_member(int(user_id))
            if member is None:
                try:
                    member = await ctx.guild.fetch_member(int(user_id))
                except:
                    continue

            leaderboard_str += f'***`#{u_rank}`*** - *{member.name}' if user_id == str(ctx.author.id) else f'`#{u_rank}` - {member.name}'

            if key[0] in ['p', 'h']:
                user_role_name = user_values[f'{key[0]}_role']
                user_role = discord.utils.find(lambda r: r.name == user_role_name, ctx.guild.roles)

                if user_role_name is None:
                    continue

                if user_role is None:
                    user_role = await ctx.guild.create_role(name=user_role_name)

                role_level = self.user_role_level(branch, data, user_values)
                progress_percent = self.percent_till_next_level(branch, user_values)
                leaderboard_str += f' | **Level {role_level}** <@&{user_role.id}> | Progress: **{progress_percent}%**'
                leaderboard_str += '*\n' if user_id == str(ctx.author.id) else '\n'

            else:
                rep = user_values['reputation']
                leaderboard_str += f' | **{rep} Reputation**'
                leaderboard_str += '*\n' if user_id == str(ctx.author.id) else '\n'

            u_rank += 1

        description = 'Damn, this place is empty' if not leaderboard_str else leaderboard_str

        leaderboard_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=description)
        leaderboard_embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)
        leaderboard_embed.set_author(name=f'{branch.title()} Leaderboard', icon_url=ctx.guild.icon_url)

        # Displays user position under leaderboard and users above and below them if user is below position 10
        u_rank = -1
        if user_index is None or user_index <= 9:
            return await ctx.send(embed=leaderboard_embed)

        your_pos_str = ''
        for i in range(-1, 2):
            if user_index == 10 and i == -1:
                continue

            user_id, user_values = sorted_users[user_index + i]
            member = ctx.guild.get_member(int(user_id))

            if member is None:
                try:
                    member = await ctx.guild.fetch_member(int(user_id))
                except:
                    continue

            your_pos_str += f'***`#{user_index + u_rank}`*** - *{member.name}' if user_id == str(ctx.author.id) else f'`#{user_index + u_rank}` - {member.name}'

            if key[0] in ['p', 'h']:
                user_role_name = user_values[f'{key[0]}_role']
                user_role = discord.utils.find(lambda r: r.name == user_role_name, ctx.guild.roles)

                if user_role_name is None:
                    continue

                if user_role is None:
                    user_role = await ctx.guild.create_role(name=user_role_name)

                role_level = self.user_role_level(branch, data, user_values)
                progress_percent = self.percent_till_next_level(branch, user_values)
                your_pos_str += f' | **Level {role_level}** <@&{user_role.id}> | Progress: **{progress_percent}%**'
                your_pos_str += '*\n' if user_id == str(ctx.author.id) else '\n'

            else:
                rep = user_values['reputation']
                your_pos_str += f' | **{rep} Reputation**'
                your_pos_str += '*\n' if user_id == str(ctx.author.id) else '\n'

            u_rank += 1

        leaderboard_embed.add_field(name='Your Position', value=your_pos_str)

        await ctx.send(embed=leaderboard_embed)

    @commands.command(help='Show someone you respect them by giving them a reputation point', usage='rep [member]',
                      examples=['rep @Hattyot'], clearance='Mod', cls=command.Command, aliases=['reputation'])
    async def rep(self, ctx, mem=None):
        # check if user can give rep point
        data = db.levels.find_one({'guild_id': ctx.guild.id})
        levels_user = data['users'][str(ctx.author.id)]
        now = time()
        if 'rep_timer' in levels_user and now < levels_user['rep_timer']:
            rep_time = levels_user['rep_timer'] - round(time())
            return await embed_maker.message(ctx, f'You can give someone a reputation point again in **{format_time.seconds(rep_time)}**')

        if mem is None:
            return await embed_maker.command_error(ctx)

        if ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            return await embed_maker.command_error(ctx, '[member]')

        # check if user has been in server for more than 5 days
        now = datetime.now()
        joined_at = ctx.author.joined_at
        diff = now - joined_at
        if round(diff.total_seconds()) < 86400 * 5:  # 5 days
            return await embed_maker.message(ctx, f'You need to be on this server for at least 5 days to give rep points')

        if member.id == ctx.author.id:
            return await embed_maker.message(ctx, f'You can\'t give rep points to yourself')

        if member.bot:
            return await embed_maker.message(ctx, f'You can\'t give rep points to bots')

        # check if member is in database
        if str(member.id) not in data['users']:
            schema = database.schemas['levels_user']
            db.levels.update_one(
                {'guild_id': ctx.guild.id},
                {'$set': {f'users.{member.id}': schema}}
            )
            data['users'][str(member.id)] = schema

        # set rep_time to 24h so user cant spam rep points
        expire = round(time()) + 86400  # 24 hours
        db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{ctx.author.id}.rep_timer': expire}})  # 24 hours

        # give user rep point
        db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{member.id}.reputation': 1}})

        # give user 5% xp boost for 6 hours
        boost_dict = {
            'expires': round(time()) + (3600 * 6),  # 6 hours
            'multiplier': 0.05
        }
        db.levels.update_one({'guild_id': ctx.guild.id}, {'$push': {f'boost.users.{member.id}': boost_dict}})

        return await embed_maker.message(ctx, f'Gave +1 rep to <@{member.id}>')

    @commands.command(help='Shows your (or someone else\'s) rank and level',
                      usage='rank (member)', examples=['rank', 'rank @Hattyot', 'rank Hattyot'],
                      clearance='User', cls=command.Command)
    async def rank(self, ctx, member=None):
        if member is None:
            mem = ctx.author
        else:
            mem = self.get_member(ctx, member)
            if mem is None:
                return await embed_maker.command_error(ctx)

        if mem.bot:
            return await embed_maker.message(ctx, 'No bots allowed >:(', colour='red')

        embed_colour = config.EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_footer(text=f'{mem}', icon_url=mem.avatar_url)
        embed.set_author(name=f'{mem.name} - Rank', icon_url=ctx.guild.icon_url)

        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        # Check if user in database, if not, add them
        if str(mem.id) not in data['users']:
            schema = database.schemas['levels_user']
            db.levels.update_one(
                {'guild_id': ctx.guild.id},
                {'$set': {f'users.{mem.id}': schema}}
            )
            data['users'][str(mem.id)] = schema

        levels_user = data['users'][str(mem.id)]

        # inform user of boost, if they have it
        boost_multiplier = self.user_boost(data, mem)
        if boost_multiplier > 1:
            boost_percent = round((boost_multiplier - 1) * 100)
            embed.description = f'Active boost: **{boost_percent}%** parliamentary points gain!'

        # checks if honours section needs to be added
        member_hp = levels_user['hp']
        if member_hp > 0:
            member_h_level = self.user_role_level('honours', data, levels_user)
            h_role_name = levels_user['h_role']
            h_role_obj = discord.utils.find(lambda r: r.name == h_role_name, ctx.guild.roles)
            h_rank = await self.calculate_user_rank('hp', ctx.guild.id, mem.id)

            if h_role_name is not None:
                if h_role_obj is None:
                    member_h_role = await ctx.guild.create_role(name=h_role_name)
                    await mem.add_roles(member_h_role)

                hp_progress = self.percent_till_next_level('honours', levels_user)
                hp_value = f'**#{h_rank}** | **Level** {member_h_level} <@&{h_role_obj.id}>' \
                           f' | Progress: **{hp_progress}%**'
                embed.add_field(name='>Honours', value=hp_value, inline=False)

        # add parliamentary section
        member_p_level = self.user_role_level('parliamentary', data, levels_user)
        p_role_name = levels_user['p_role']
        p_role_obj = discord.utils.find(lambda r: r.name == p_role_name, ctx.guild.roles)
        p_rank = await self.calculate_user_rank('pp', ctx.guild.id, mem.id)

        if p_role_obj is None:
            member_p_role = await ctx.guild.create_role(name=p_role_name)
            await mem.add_roles(member_p_role)

        pp_progress = self.percent_till_next_level('parliamentary', levels_user)
        pp_value = f'**#{p_rank}** | **Level** {member_p_level} <@&{p_role_obj.id}> | Progress: **{pp_progress}%**'
        embed.add_field(name='>Parliamentary', value=pp_value, inline=False)

        # add reputation section if user has rep
        # if 'reputation' in levels_user and levels_user['reputation'] > 0:
        #     rep = levels_user['reputation']
        #     rep_rank = await self.calculate_user_rank('reputation', ctx.guild.id, mem.id)
        #     rep_value = f'**#{rep_rank}** | **{rep}** Rep Points'
        #     embed.add_field(name='>Reputation', value=rep_value, inline=False)

        return await ctx.send(embed=embed)

    @commands.command(help='See all the perks that a role has to offer',
                      usage='perks [role name]',
                      examples=['perks Party Member'],
                      clearance='User', cls=command.Command)
    async def perks(self, ctx, *, role_name=None):
        if role_name is None:
            return await embed_maker.command_error(ctx)

        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        leveling_routes = data['leveling_routes']
        honours_branch = leveling_routes['honours']
        parliamentary_branch = leveling_routes['parliamentary']

        filtered_parliamentary = list(filter(lambda x: x[0].lower() == role_name.lower(), parliamentary_branch))
        filtered_honours = list(filter(lambda x: x[0].lower() == role_name.lower(), honours_branch))
        if filtered_parliamentary:
            role = filtered_parliamentary[0]
        elif filtered_honours:
            role = filtered_honours[0]
        else:
            return await embed_maker.message(ctx, 'I couldn\'t find a role by that name', colour='red')

        # checks if perks list in role tuple
        if len(role) < 3 or not role[2]:
            msg = f'**{role[0]}** currently offers no perks'
        else:
            perks_str = "\n • ".join(role[2])
            msg = f'Perks for {role[0]}:\n • {perks_str}'

        return await embed_maker.message(ctx, msg)

    # Functions

    @staticmethod
    def parse_rewards_args(args):
        result = {'r': '', 'p': []}

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

    @staticmethod
    async def update_user_roles(ctx, branch, role):
        pre = 'p_' if branch == 'parliamentary' else 'h_'
        for m in role.members:
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{m.id}.{pre}role': role.name}})

    # For displaying new leveling routes when they are edited
    @staticmethod
    async def display_new_leveling_routes(ctx, data, branch):
        embed = discord.Embed(colour=embed_maker.get_colour('green'), timestamp=datetime.now())
        embed.set_author(name='New Leveling Routes', icon_url=ctx.guild.icon_url)
        embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

        lvl_routes = data['leveling_routes']

        value = ''
        for i, _role in enumerate(lvl_routes[branch]):
            role = discord.utils.find(lambda r: r.name == _role[0], ctx.guild.roles)
            if role is None:
                role = await ctx.guild.create_role(name=_role[0])
            value += f'\n**#{i + 1}:** <@&{role.id}> - Max Level: {_role[1]}'
        embed.add_field(name=f'>{branch.title()}', value=value, inline=False)

        return await ctx.send(embed=embed)

    @staticmethod
    def parse_role_args(args):
        result = dict.fromkeys(['b', 'r', 'l', 'nr', 'nl'], '')

        split_args = filter(None, args.split('-'))
        for a in split_args:
            match = tuple(map(str.strip, a.split(' ', 1)))
            if len(match) < 2:
                return result
            key, value = match
            result[key] = value

        return result

    @staticmethod
    def percent_till_next_level(branch, levels_user):
        pre = 'h' if branch == 'honours' else 'p'

        user_points = levels_user[f'{pre}p']
        user_level = levels_user[f'{pre}_level']

        if pre == 'p':
            # points needed to gain next level from beginning of current level
            pnu = (5 * (user_level ** 2) + 50 * user_level + 100)
            # total points needed to gain next level from 0 points
            tpu = 0
            for j in range(int(user_level) + 1):
                tpu += (5 * (j ** 2) + 50 * j + 100)

            # point needed to gain next level
            pun = tpu - user_points

            percent = 100 - int((pun * 100) / pnu)

        else:
            pnu = 1000
            tpu = 1000 * (user_level + 1)
            pun = tpu - user_points

            percent = 100 - int((pun * 100) / pnu)

        # return 99.9 when int rounds to 0, but user wont level up yet
        if percent == 100 and pun != 0:
            return 99.9

        return percent

    async def calculate_user_rank(self, key, guild_id, user_id):
        # creates pipeline that reduces data to only user id and key
        pipeline = [
            {'$match': {'guild_id': guild_id}},
            {"$project": {"users": {"$objectToArray": "$users"}}},
            {"$project": {'_id': 0, 'users.k': 1, f"users.v.{key}": 1}},
            {"$project": {"users": {"$arrayToObject": "$users"}}},
        ]
        data = list(db.levels.aggregate(pipeline))[0]
        data['users'] = {k: v for k, v in data['users'].items() if v}
        sorted_users = sorted(data['users'].items(), key=lambda x: x[1][key], reverse=True)

        guild = self.bot.get_guild(int(guild_id))
        u_rank = 1
        for u in sorted_users:
            u_id, _ = u
            member = guild.get_member(int(u_id))
            if member is None:
                try:
                    await guild.fetch_member(int(u_id))
                except:
                    continue

            if int(u_id) == int(user_id):
                return u_rank

            u_rank += 1

    @staticmethod
    def get_member(ctx, source):
        # check if source is member mention
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
        # Check if source is user id
        elif source.isdigit():
            member = discord.utils.find(lambda m: m.id == source, ctx.guild.members)
        # Check if source is member's name
        else:
            regex = re.compile(fr'({source.lower()})')
            member = discord.utils.find(
                lambda m: re.findall(regex, m.name.lower()) or re.findall(regex, m.display_name.lower()),
                ctx.guild.members
            )

        return member

    async def process_hp_message(self, message):
        if cooldown_expired(hp_cooldown, message.guild.id, message.author.id, 60):
            hp_add = 10
            data = db.levels.find_one({'guild_id': message.guild.id})
            if data is None:
                data = self.bot.add_collections(message.guild.id, 'levels')

            # Check if user in database, if not, add them
            if str(message.author.id) not in data['users']:
                schema = database.schemas['levels_user']
                db.levels.update_one(
                    {'guild_id': message.guild.id},
                    {'$set': {f'users.{message.author.id}': schema}}
                )
                data['users'][str(message.author.id)] = schema

            levels_user = data['users'][str(message.author.id)]

            # adds honours role to user if it's their first honours points gain
            if levels_user['hp'] == 0:
                leveling_routes = data['leveling_routes']

                # gets the name of the first honours role
                h_role_tuple = leveling_routes['honours'][0]
                h_role_name = h_role_tuple[0]
                h_role = discord.utils.find(lambda r: r.name == h_role_name, message.guild.roles)

                if h_role is None:
                    h_role = await message.guild.create_role(name=h_role_name)

                await message.author.add_roles(h_role)
                db.levels.update_one(
                    {'guild_id': message.guild.id},
                    {'$set': {f'users.{message.author.id}.h_role': h_role.name}}
                )
                levels_user['h_role'] = h_role.name

            levels_user['hp'] += hp_add
            db.levels.update_one(
                {'guild_id': message.guild.id},
                {'$set': {f'users.{message.author.id}.hp': levels_user['hp']}}
            )

            # Check if user leveled up
            return await self.level_up(message, message.author, 'honours', data)

    async def process_message(self, message):
        if cooldown_expired(pp_cooldown, message.guild.id, message.author.id, 60):
            pp_add = randint(15, 25)
            data = db.levels.find_one({'guild_id': message.guild.id})
            if data is None:
                data = self.bot.add_collections(message.guild.id, 'levels')

            # Check if user in database, if not, add them
            if str(message.author.id) not in data['users']:
                schema = database.schemas['levels_user']
                db.levels.update_one(
                    {'guild_id': message.guild.id},
                    {'$set': {f'users.{message.author.id}': schema}}
                )
                data['users'][str(message.author.id)] = schema

            # check for active boost and add to pp_add if active
            boost_multiplier = self.user_boost(data, message.author)
            if boost_multiplier > 1:
                pp_add = round(pp_add * boost_multiplier)

            levels_user = data['users'][str(message.author.id)]
            levels_user['pp'] += pp_add
            db.levels.update_one(
                {'guild_id': message.guild.id},
                {'$set': {f'users.{message.author.id}.pp': levels_user['pp']}}
            )

            # Check if user leveled up
            return await self.level_up(message, message.author, 'parliamentary', data)

    @staticmethod
    def user_boost(data, user):
        multiplier = 1
        if 'boost' in data:
            if 'users' in data['boost'] and str(user.id) in data['boost']['users']:
                for i, boost in enumerate(data['boost']['users'][str(user.id)]):
                    expires = boost['expires']
                    if round(time()) > expires:
                        del data['boost']['users'][str(user.id)][i]

                        # removes user from boost if user has no active boosts otherwise just removes expired boost
                        if not data['boost']['users'][str(user.id)]:
                            cmd = {'$unset': {f'boost.users.{str(user.id)}': ''}}
                        else:
                            cmd = {'$pull': {f'boost.users.{str(user.id)}': {'expires': expires}}}

                        db.levels.update_one({'guild_id': data['guild_id']}, cmd)
                    else:
                        multiplier += boost['multiplier']

            if 'roles' in data['boost']:
                for r in user.roles:
                    if str(r.id) in data['boost']['roles']:
                        expires = data['boost']['roles'][str(r.id)]['expires']
                        if round(time()) > expires:
                            db.levels.update_one(
                                {'guild_id': data['guild_id']},
                                {'$unset': {f'boost.roles.{str(r.id)}': ''}}
                            )
                        else:
                            multiplier += data['boost']['roles'][str(r.id)]['multiplier']

        return multiplier

    async def level_up(self, ctx, member, branch, data):
        levels_user = data['users'][str(member.id)]

        if branch == 'honours':
            pre = 'h_'
            levels_up = honours_levels_up(levels_user)
        else:
            pre = 'p_'
            levels_up = parliamentary_levels_up(levels_user)

        user_role = levels_user[f'{pre}role']

        if user_role is None:
            return

        # Checks if user has role
        role = discord.utils.find(lambda rl: rl.name == user_role, ctx.guild.roles)
        if role is None:
            role = await ctx.guild.create_role(name=user_role)
        if role is not None and role not in member.roles:
            await member.add_roles(role)

        user_role_level = self.user_role_level(branch, data, levels_user, levels_up)

        if not levels_up and user_role_level >= 0:
            return

        new_role = ()
        if user_role_level < 0:
            # Get next role and add it to user
            leveling_routes = data['leveling_routes']
            roles = leveling_routes[branch]

            role = [role for role in roles if role[0] == user_role]
            role_index = roles.index(role[0])

            # if goes up multiple roles, add previous roles to user
            if user_role_level < -1:
                roles_up = roles[role_index + 1:role_index + abs(user_role_level) + 1]
                new_role = roles_up[-1]
                new_role_obj = None
                for r in roles_up:
                    role_object = discord.utils.find(lambda rl: rl.name == r[0], ctx.guild.roles)
                    if role_object is None:
                        role_object = await ctx.guild.create_role(name=r[0])

                    if role_object not in member.roles:
                        await member.add_roles(role_object)

                    new_role_obj = role_object

            # get new role and add it to user
            else:
                if len(roles) - 1 < role_index + abs(user_role_level):
                    new_role = roles[-1]
                else:
                    new_role = roles[role_index + abs(user_role_level)]

                new_role_obj = discord.utils.find(lambda rl: rl.name == new_role[0], ctx.guild.roles)
                if new_role_obj is None:
                    new_role_obj = await ctx.guild.create_role(name=new_role[0])

                await member.add_roles(new_role_obj)

            db.levels.update_one(
                {'guild_id': ctx.guild.id},
                {'$set': {f'users.{member.id}.{pre}role': new_role_obj.name}}
            )
            levels_user[f'{pre}role'] = new_role_obj.name

            user_role_level = self.user_role_level(branch, data, levels_user, levels_up)
            reward_text = f'Congrats **{member.name}** you\'ve advanced to a ' \
                          f'level **{user_role_level}** <@&{new_role_obj.id}>'

        else:
            reward_text = f'Congrats **{member.name}** you\'ve become a level **{user_role_level}** <@&{role.id}>'

        reward_text += ' due to your contributions!' if branch == 'honours' else '!'

        db.levels.update_one({'guild_id': ctx.guild.id}, {'$inc': {f'users.{member.id}.{pre}level': levels_up}})
        levels_user[f'{pre}level'] += levels_up

        await self.level_up_message(ctx, member, data, reward_text, new_role)

    async def level_up_message(self, ctx, member, data, reward_text, role_tuple):
        embed_colour = config.EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, description=reward_text, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name='Level Up!', icon_url=ctx.guild.icon_url)

        channel_id = data['level_up_channel']
        channel = self.bot.get_channel(channel_id)

        if channel is None:
            channel = ctx.channel

        if 'settings' not in data['users'][str(member.id)]:
            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'users.{member.id}.settings': {'@_me': False}}})
            data['users'][str(member.id)]['settings'] = {'@_me': False}

        settings = data['users'][str(member.id)]['settings']
        enabled = settings['@_me']

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
    @staticmethod
    def user_role_level(branch, data, levels_user, add_levels=0):
        # Return negative number if user need to go up roles otherwise returns positive number of users role level

        pre = 'h_' if branch == 'honours' else 'p_'

        user_level = levels_user[f'{pre}level']
        user_role = levels_user[f'{pre}role']

        if user_role is None:
            return None

        user_level = int(user_level + add_levels)

        leveling_routes = data['leveling_routes']
        all_roles = leveling_routes[branch]
        role_amount = len(all_roles)

        # Get role index
        role_obj = [role for role in all_roles if role[0] == user_role][0]
        role_index = all_roles.index(role_obj)

        up_to_current_role = all_roles[:role_index + 1]
        # how many levels to reach current user role
        current_level_total = sum([role[1] for role in up_to_current_role])
        # how many levels to reach previous user role
        if len(up_to_current_role) > 1:
            del up_to_current_role[-1]
            previous_level_total = sum([role[1] for role in up_to_current_role])
        else:
            previous_level_total = 0

        if role_amount == role_index + 1:
            return user_level - previous_level_total
        if current_level_total > user_level:
            return user_level - previous_level_total
        if current_level_total == user_level:
            return role_obj[1]
        if current_level_total < user_level:
            # calculates how many roles user goes up
            roles_up = 0
            for i, r in enumerate(all_roles):
                if role_index >= i:
                    continue
                elif current_level_total < user_level:
                    roles_up -= 1
                    current_level_total += all_roles[i][1]
            return roles_up


def parliamentary_levels_up(levels_user):
    user_level = levels_user['p_level']
    user_pp = levels_user['pp']

    for i in range(10000):
        # total pp needed to gain the next level
        total_pp = 0
        for j in range(int(user_level) + i + 1):
            # the formula to calculate how much pp you need for the next level
            total_pp += (5 * (j ** 2) + 50 * j + 100)

        if total_pp - user_pp >= 0:
            return i


def honours_levels_up(levels_user):
    user_level = levels_user['h_level']
    user_hp = levels_user['hp']

    for i in range(1000):
        total_hp = 1000 * (user_level + i)
        if total_hp - user_hp >= 0:
            return i - 1


def setup(bot):
    bot.add_cog(Leveling(bot))
