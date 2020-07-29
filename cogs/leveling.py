import discord
import config
import math
import re
from bson import ObjectId
from datetime import datetime
from discord.ext import commands
from modules import database, embed_maker, command, format_time
from time import time
from random import randint
from cogs.utils import get_user_boost_multiplier, get_member

db = database.Connection()
pp_cooldown = {}
hp_cooldown = {}


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
            boost_remove = await get_member(ctx, self.bot, source)
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

        boost_data = [d for d in db.boosts.find({'guild_id': ctx.guild.id, f'{source_type}_id': boost_remove.id})]
        err = ''
        suc = ''
        if source_type == 'role' and boost_data:
            db.boosts.delete_one({'guild_id': ctx.guild.id, f'{source_type}_id': boost_remove.id})
            if source != '@everyone':
                suc = f'Removed <@&{boost_remove.id}>\'s boost'
            else:
                suc = 'Removed boost given to everyone'
        else:
            if source != '@everyone':
                err = f'<@&{boost_remove.id}> has no active boosts'
            else:
                err = 'No boost is active for everyone'

        if source_type == 'user' and boost_data:
            latest_boost = boost_data[-1]
            db.boosts.delete_one({'_id': ObjectId(latest_boost['_id'])})
            suc = f'Removed latest boost given to <@{boost_remove.id}>'
        else:
            err = f'User <@{boost_remove.id}> has no active boosts'

        if err:
            return await embed_maker.message(ctx, err, colour='red')
        elif suc:
            return await embed_maker.message(ctx, suc, colour='green')

    @commands.command(help='See active boosts of a role or a user', usage='boosts [user]', examples=['boosts hattyot'],
                      clearance='Mod', cls=command.Command)
    async def boosts(self, ctx, *, source=None):
        if source is None:
            return await embed_maker.command_error(ctx)

        # check if source is member
        boost_user = await get_member(ctx, self.bot, source)
        source_type = 'user'

        # check if source is role or everyone
        if boost_user is None:
            # role name of everyone is @everyone
            if source == 'everyone':
                source = f'@{source}'

            boost_remove = discord.utils.find(lambda rl: rl.name.lower() == source.lower(), ctx.guild.roles)
            source_type = 'role'

        boost_data = [d for d in db.boosts.find({'guild_id': ctx.guild.id, f'{source_type}_id': boost_user.id})]

        boost_str = ''
        for i, boost in enumerate(boost_data):
            expires = boost["expires"]
            if expires < round(time()):
                db.boosts.delete_one({'_id': ObjectId(boost['_id'])})
                continue
            multiplier = boost["multiplier"]
            percent = 100 - abs(round((multiplier - 1) * 100, 1))
            if percent.is_integer():
                percent = int(percent)
            boost_str += f'`#{i + 1}` - {percent}% boost | Expires: {format_time.seconds(expires - round(time()), accuracy=5)}'
            if 'type' in boost:
                boost_str += f'\nType: {boost["type"]}'

        return await embed_maker.message(ctx, boost_str, title=f'Active Boosts - {boost_user}')

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
            to_boost = await get_member(ctx, self.bot, source)
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

        boost_data = db.boosts.find_one({'guild_id': ctx.guild.id, f'{source_type}_id': to_boost.id})
        # check if role already has boost
        if source_type == 'role' and boost_data:
            expires = boost_data["expires"]
            if boost_data["expires"] <= time():
                db.boosts.delete_one({'_id': ObjectId(boost_data['_id'])})

            multiplier = boost_data["multiplier"]
            percent = 100 - abs(round((multiplier - 1) * 100, 1))
            if percent.is_integer():
                percent = int(percent)
            err = f'Role {source} already has an active boost\nExpires: {format_time.seconds(expires - round(time()))}\nBoost: {percent}%'
        if err:
            return await embed_maker.message(ctx, err, colour='red')

        multiplier = int(percent)/100
        expires = round(time()) + int(length_in_seconds)
        boost_object = {
            'guild_id': ctx.guild.id,
            f'{source_type}_id': to_boost.id,
            'expires': expires,
            'multiplier': multiplier
        }
        db.boosts.insert_one(boost_object)

        formatted_length = format_time.seconds(length_in_seconds)
        if source_type == 'user':
            msg = f'User {to_boost} will now receive a {percent}% boost to levels gain for {formatted_length}'
        elif source_type == 'role' and source != '@everyone':
            msg = f'Users with the role <@&{to_boost.id}> will now receive a {percent}% boost to their levels gain for {formatted_length}'
        else:
            msg = f'Everyone will now receive a {percent}% boost to their levels gain for {formatted_length}'

        return await embed_maker.message(ctx, msg, colour='green')

    @commands.command(
        help='Set or remove perks from parliamentary or honours roles which will be sent to user once they recieve that role',
        usage='perk [action] -r [role name] -p (perk 1) | (perk 2) | (perk 3)', clearance='Mod', cls=command.Command,
        examples=['perk set -r Party Member -p Access to party emotes | Access to the Ask TLDR channel', 'perk remove -r Party Member'])
    async def perk(self, ctx, action=None, *, args=None):
        if action is None:
            return await embed_maker.command_error(ctx)

        valid_actions = ['set', 'remove']
        if action not in valid_actions:
            return await embed_maker.command_error(ctx, '[action]')

        if args is None:
            embed = embed_maker.message(ctx, 'Missing args', colour='red')
            return await ctx.send(embed=embed)

        leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'leveling_routes': 1})
        leveling_routes = leveling_data['leveling_routes']
        honours_branch = leveling_routes['honours']
        parliamentary_branch = leveling_routes['parliamentary']

        parsed_args = self.parse_perk_args(args)
        role_name = parsed_args['r']

        err = ''
        if not role_name:
            err = 'Invalid role name'
        else:
            perks = parsed_args['p']
            if not perks:
                err = 'Invalid perks'

            filtered_parliamentary = list(filter(lambda x: x[0] == role_name, parliamentary_branch))
            filtered_honours = list(filter(lambda x: x[0] == role_name, honours_branch))
            if len(filtered_parliamentary) == 1:
                new_role_tuple = (filtered_parliamentary[0][0], filtered_parliamentary[0][1], perks)
                role_index = parliamentary_branch.index(filtered_parliamentary[0])
                branch = 'parliamentary'
            elif len(filtered_honours) == 1:
                new_role_tuple = (filtered_honours[0][0], filtered_honours[0][1], perks)
                role_index = honours_branch.index(filtered_honours[0])
                branch = 'honours'
            else:
                err = 'Invalid role name'

        if err:
            return await embed_maker.message(ctx, err, colour='red')

        # edit role instance in leveling routes list by replacing it
        leveling_routes[branch][role_index] = new_role_tuple
        db.leveling_data.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': leveling_routes[branch]}})

        perks_str = "\n • ".join(perks)
        msg = f'Added perks to {role_name}:\n • {perks_str}'
        return await embed_maker.message(ctx, msg, colour='green')

    @staticmethod
    def parse_perk_args(args):
        result = {'r': '', 'p': []}

        # Filters out empty strings
        _args = list(filter(lambda a: bool(a), re.split(r' ?-([rp]) ', args)))
        for i in range(int(len(_args) / 2)):
            if args[i + (i * 1)] == 'p':
                perks = list(map(str.strip, _args[i + (i + 1)].split('|')))
                result['p'] = perks
                continue

            result[_args[i + (i * 1)]] = _args[i + (i + 1)]

        return result

    @commands.command(help='Remove a role from a leveling route', usage='remove_role -b [branch] -r [role name]',
                      examples=['remove_role -b parliamentary -r Knight'], clearance='Admin', cls=command.Command)
    async def remove_role(self, ctx, *, args=None):
        if args is None:
            return await embed_maker.command_error(ctx)

        parsed_args = self.parse_role_args(args)
        branch = parsed_args['b'].lower()
        role_name = parsed_args['r']

        leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'leveling_routes': 1})
        leveling_routes = leveling_data['leveling_routes']

        if branch not in leveling_routes:
            return await embed_maker.message(ctx, 'That is not a valid branch. (honours/parliamentary)', colour='red')

        if not role_name:
            return await embed_maker.message(ctx, 'Missing role name', colour='red')

        role = discord.utils.find(lambda r: r.name == role_name, ctx.guild.roles)
        if role is None:
            return await embed_maker.message(ctx, 'Invalid role name', colour='red')

        role_tuple = [r for r in leveling_routes[branch] if r[0] == role_name]
        del leveling_routes[branch][leveling_routes[branch].index(role_tuple[0])]
        db.leveling_data.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': leveling_routes[branch]}})

        await ctx.send(f'Removed {branch} role {role_name}')
        await self.display_new_leveling_routes(ctx, leveling_routes, branch)

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

        leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'leveling_routes': 1})
        leveling_routes = leveling_data['leveling_routes']

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

        db.leveling_data.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': new_role_route_list}})
        leveling_routes[branch] = new_role_route_list

        await ctx.send(f'added {new_role.name} to {branch} route')
        await self.display_new_leveling_routes(ctx, leveling_routes, branch)

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

        leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'honours_channels': 1})
        channel_list = leveling_data['honours_channels']

        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]

            if action == 'add':
                if channel.id in channel_list:
                    return await embed_maker.message(ctx, f'That channel is already on the list', colour='red')

                db.leveling_data.update_one({'guild_id': ctx.guild.id}, {'$push': {f'honours_channels': channel.id}})
                msg = f'<#{channel.id}> has been added to the list'

            if action == 'remove':
                if channel.id not in channel_list:
                    return await embed_maker.message(ctx, f'That channel is not on the list', colour='red')

                db.leveling_data.update_one({'guild_id': ctx.guild.id}, {'$pull': {f'honours_channels': channel.id}})
                msg = f'<#{channel.id}> has been removed from the list'

            return await embed_maker.message(ctx, msg, colour='green')
        else:
            return await embed_maker.command_error(ctx, '[#channel]')

    @commands.command(help='See the current list of channels where honours points can be earned',
                      usage='honours_channels', examples=['honours_channels'],
                      clearance='Mod', cls=command.Command)
    async def honours_channels(self, ctx):
        leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'honours_channels': 1})
        honours_channels = leveling_data['honours_channels']
        channel_list_str = '\n'.join(f'<#{i}>\n' for i in honours_channels) if honours_channels else 'None'

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

        leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'leveling_routes': 1})
        leveling_routes = leveling_data['leveling_routes']

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

                db.leveling_data.update_one({'guild_id': ctx.guild.id}, {'$set': {f'leveling_routes.{branch}': new_role_list}})
                leveling_routes[branch] = new_role_list

                await ctx.send(f'Edited {role_name}')
                return await self.display_new_leveling_routes(ctx, leveling_routes, branch.lower())

    @staticmethod
    async def update_user_roles(ctx, branch, role):
        pre = 'p_' if branch == 'parliamentary' else 'h_'
        for m in role.members:
            db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': m.id}, {'$set': {f'{pre}role': role.name}})

    # For displaying new leveling routes when they are edited
    @staticmethod
    async def display_new_leveling_routes(ctx, leveling_routes, branch):
        embed = discord.Embed(colour=embed_maker.get_colour('green'), timestamp=datetime.now())
        embed.set_author(name='New Leveling Routes', icon_url=ctx.guild.icon_url)
        embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

        value = ''
        for i, _role in enumerate(leveling_routes[branch]):
            role = discord.utils.find(lambda r: r.name == _role[0], ctx.guild.roles)
            if role is None:
                role = await ctx.guild.create_role(name=_role[0])
            value += f'\n**#{i + 1}:** <@&{role.id}> - Max Level: {_role[1]}'
        embed.add_field(name=f'>{branch.title()}', value=value, inline=False)

        return await ctx.send(embed=embed)

    @staticmethod
    def parse_role_args(args):
        result = dict.fromkeys(['b', 'r', 'l', 'nr', 'nl'], '')

        _args = list(filter(lambda a: bool(a), re.split(r' ?-(b|r|l|nr|nl) ', args)))
        for i in range(int(len(_args) / 2)):
            result[_args[i + (i * 1)]] = _args[i + (i + 1)]

        return result

    @commands.command(help='award someone honours points', usage='award [member] [amount]', examples=['award Hattyot 500'], clearance='Mod', cls=command.Command)
    async def award(self, ctx, member=None, amount=None):
        if member is None:
            return await embed_maker.command_error(ctx)

        member = await get_member(ctx, self.bot, member)

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
        leveling_user = db.leveling_users.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})

        # Check if user in database, if not, add them
        if not leveling_user:
            leveling_user = database.schemas['leveling_user']
            leveling_user['guild_id'] = ctx.guild.id
            leveling_user['user_id'] = member.id
            db.leveling_users.insert_one(leveling_user)

        leveling_user['hp'] += amount

        db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': member.id}, {'$set': {'hp': leveling_user['hp']}})

        await embed_maker.message(ctx, f'**{member.name}** has been awarded **{amount} honours points**', colour='green')
        if leveling_user['hp'] - amount == 0:
            leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'leveling_routes': 1})
            leveling_routes = leveling_data['leveling_routes']

            # gets the name of the first honours role
            h_role_tuple = leveling_routes['honours'][0]
            h_role_name = h_role_tuple[0]
            h_role = discord.utils.find(lambda r: r.name == h_role_name, ctx.guild.roles)

            if h_role is None:
                h_role = await ctx.guild.create_role(name=h_role_name)

            await member.add_roles(h_role)
            db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': member.id}, {'$set': {f'h_role': h_role.name}})
            leveling_user['h_role'] = h_role.name

        return await self.level_up(ctx, member, 'honours', leveling_user)

    @commands.command(name='@_me', help='Makes the bot @ you when you level up', usage='@_me', examples=['@_me', '@_me'], clearance='User', cls=command.Command)
    async def at_me(self, ctx):
        leveling_user = db.leveling_users.find_one({'guild_id': ctx.guild.id, 'user_id': ctx.author.id})

        if 'settings' not in leveling_user:
            db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': ctx.author.id}, {'$set': {'settings': {'@_me': False}}})
            leveling_user['settings'] = {'@_me': False}

        settings = leveling_user['settings']
        enabled = settings['@_me']

        if enabled:
            msg = 'Disabling @ when you level up'
            colour = 'orange'
            boolean = False
        else:
            msg = 'Enabling @ when you level up'
            colour = 'green'
            boolean = True

        db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': ctx.author.id}, {'$set': {'settings': {'@_me': boolean}}})
        return await embed_maker.message(ctx, msg, colour=colour)

    @commands.command(help='See current leveling routes', usage='leveling_routes',
                      examples=['leveling_routes'], clearance='User', cls=command.Command, aliases=['ranks'])
    async def leveling_routes(self, ctx, branch='parliamentary'):
        leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'leveling_routes': 1})

        branch_switch = {
            'h': 'honours',
            'p': 'parliamentary'
        }
        branch = branch_switch.get(branch[0], 'parliamentary')

        leveling_routes = leveling_data['leveling_routes']
        embed_colour = config.EMBED_COLOUR

        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_author(name='Leveling Routes', icon_url=ctx.guild.icon_url)
        embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

        # Looks up how many people are in a role
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
            print(leveling_routes[branch])
            role = discord.utils.find(lambda rl: rl.name == _role[0], ctx.guild.roles)
            if role is None:
                role = await ctx.guild.create_role(name=_role[0])
            value += f'\n**#{i + 1}:** <@&{role.id}> - {count[role.name]} People'

        if not value:
            value = 'This branch currently has no roles'

        embed.add_field(name=f'>{branch.title()} - Every 5 levels you advance a role', value=value, inline=False)

        return await ctx.send(embed=embed)

    @commands.command(help='Shows the leveling leaderboards (parliamentary(p)/honours(h)) on the server',
                      usage='leaderboard (branch)', aliases=['lb'], cls=command.Command, clearance='User',
                      examples=['leaderboard parliamentary', 'leaderboard honours'])
    async def leaderboard(self, ctx, branch='parliamentary', page=1):
        if branch is None:
            return await embed_maker.command_error(ctx)

        key_switch = {'h': 'hp', 'p': 'pp', 'r': 'reputation'}
        branch_switch = {'h': 'honours', 'p': 'parliamentary', 'r': 'reputation'}
        key = key_switch.get(branch[0], 'pp')
        if branch.isdigit():
            page = int(branch)
        branch = branch_switch.get(branch[0], 'parliamentary')

        sorted_users = [d for d in db.leveling_users.find({'guild_id': ctx.guild.id, 'left': {'$exists': False}, key: {'$gt': 0}}).sort(key, -1)]

        # find out max page number
        max_page_num = math.ceil(len(list(sorted_users)) / 10)
        if page > max_page_num:
            return await embed_maker.message(ctx, 'Exceeded maximum page number', colour='red')

        leveling_user = db.leveling_users.find_one({'guild_id': ctx.guild.id, 'user_id': ctx.author.id})
        user_index = sorted_users.index(leveling_user)
        user_rank = await self.calculate_user_rank(key, ctx.guild, sorted_users[user_index])

        utils_cog = self.bot.get_cog('Utils')

        async def construct_lb_page(pg):
            lb_str = ''
            u_rank = 1
            limit = 10
            p = 1
            page_start = 1 + (10 * (pg - 1))
            for i, user in enumerate(sorted_users):
                if i == limit:
                    return lb_str

                user_id = user['user_id']

                member = ctx.guild.get_member(int(user_id))
                if member is None:
                    if 'left' in user:
                        limit += 1
                        continue
                    try:
                        member = await ctx.guild.fetch_member(int(user_id))
                    except:
                        db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': int(user_id)}, {'$set': {'left': True}})
                        expires = int(time()) + (86400 * 5)  # 5 days
                        await utils_cog.create_timer(expires=expires, guild_id=ctx.guild.id, event='delete_user_data', extras={'user_id': int(user_id)})
                        limit += 1
                        continue
                elif 'left' in user:
                    db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': int(user_id)}, {'$unset': {'left': True}})

                if p < page_start:
                    u_rank += 1
                    p += 1
                    limit += 1
                    continue

                lb_str += f'**`#{u_rank}`**\* - {member.display_name}  [{member}]' if user_id == ctx.author.id else f'`#{u_rank}` - {member.display_name}  [{member}]'

                if key[0] in ['p', 'h']:
                    user_role_name = user[f'{key[0]}_role']
                    if not user_role_name:
                        limit += 1
                        continue
                    
                    user_role = discord.utils.find(lambda r: r.name == user_role_name, ctx.guild.roles)
                    if user_role is None:
                        user_role = await ctx.guild.create_role(name=user_role_name)

                    role_level = self.user_role_level(branch, user)
                    progress_percent = self.percent_till_next_level(branch, user)
                    lb_str += f'\n**Level {role_level}** <@&{user_role.id}> | Progress: **{progress_percent}%**\n\n'

                else:
                    rep = user['reputation']
                    lb_str += f' | **{rep} Reputation**\n'

                u_rank += 1
                
            return lb_str

        async def construct_lb_your_pos(pg):
            yp_str = ''
            for i in range(-1, 2):
                if user_rank == pg * 10 and i == -1:
                    continue

                if i == -1:
                    for j in range(user_index - 1, 0, -1):
                        user = sorted_users[j]
                        user_id = user['user_id']

                        member = ctx.guild.get_member(int(user_id))
                        if member is None:
                            if 'left' in user:
                                continue
                            try:
                                await ctx.guild.fetch_member(int(user_id))
                            except:
                                continue
                        else:
                            if 'left' in user:
                                db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': int(user_id)}, {'$unset': {'left': True}})

                        break
                elif i == 0:
                    member = ctx.author
                    user = sorted_users[user_index]
                    user_id = user['user_id']
                elif i == 1:
                    for k in range(user_index + 1, len(sorted_users)):
                        user = sorted_users[k]
                        user_id = user['user_id']

                        member = ctx.guild.get_member(int(user_id))
                        if member is None:
                            if 'left' in user:
                                continue
                            try:
                                await ctx.guild.fetch_member(int(user_id))
                            except:
                                db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': int(user_id)}, {'$set': {'left': True}})
                                expires = int(time()) + (86400 * 5)  # 5 days
                                await utils_cog.create_timer(expires=expires, guild_id=ctx.guild.id, event='delete_user_data', extras={'user_id': int(user_id)})
                                continue
                        else:
                            if 'left' in user:
                                db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': int(user_id)}, {'$unset': {'left': True}})
                        break

                if i != 0 and member == ctx.author:
                    continue

                yp_str += f'**`#{user_rank + i}`**\* - {member.display_name}' if user_id == ctx.author.id else f'`#{user_rank + i}` - {member.display_name}'
                if key[0] in ['p', 'h']:
                    user_role_name = user[f'{key[0]}_role']
                    user_role = discord.utils.find(lambda r: r.name == user_role_name, ctx.guild.roles)

                    if not user_role_name:
                        continue

                    if user_role is None:
                        user_role = await ctx.guild.create_role(name=user_role_name)

                    role_level = self.user_role_level(branch, user)
                    progress_percent = self.percent_till_next_level(branch, user)
                    yp_str += f' | **Level {role_level}** <@&{user_role.id}> | Progress: **{progress_percent}%**\n'

                else:
                    rep = user['reputation']
                    yp_str += f' | **{rep} Reputation**\n'

            return yp_str

        embed_colour = config.EMBED_COLOUR
        leaderboard_str = await construct_lb_page(page)
        description = 'Damn, this place is empty' if not leaderboard_str else leaderboard_str
        leaderboard_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(), description=description)
        leaderboard_embed.set_footer(text=f'{ctx.author} | Page {page}/{max_page_num}', icon_url=ctx.author.avatar_url)
        leaderboard_embed.set_author(name=f'{branch.title()} Leaderboard', icon_url=ctx.guild.icon_url)

        # Displays user position under leaderboard and users above and below them if user is below position 10
        if user_rank is None or user_rank <= page * 10:
            return await ctx.send(embed=leaderboard_embed)
        else:
            your_pos_str = await construct_lb_your_pos(page)

        leaderboard_embed.add_field(name='Your Position', value=your_pos_str)

        await ctx.send(embed=leaderboard_embed)

    @commands.command(help='Show someone you respect them by giving them a reputation point',
                      usage='rep [member] [reason for the rep]',
                      examples=['rep @Hattyot for being an excellent example in this text'], clearance='User',
                      cls=command.Command, aliases=['reputation'])
    async def rep(self, ctx, mem=None, *, reason=None):
        # check if user has been in server for more than 2 days
        now_datetime = datetime.now()
        joined_at = ctx.author.joined_at
        diff = now_datetime - joined_at
        if round(diff.total_seconds()) < 86400 * 2:  # 2 days
            return await embed_maker.message(ctx, f'You need to be on this server for at least 5 days to give rep points', colour='red')

        # check if user can give rep point
        leveling_user = db.leveling_users.find_one({'guild_id': ctx.guild.id, 'user_id': ctx.author.id})
        now = time()
        if 'rep_timer' in leveling_user and now < leveling_user['rep_timer']:
            rep_time = leveling_user['rep_timer'] - round(time())
            return await embed_maker.message(ctx, f'You can give someone a reputation point again in **{format_time.seconds(rep_time, accuracy=3)}**')

        if mem is None:
            return await embed_maker.command_error(ctx)

        if reason is None:
            return await embed_maker.command_error(ctx, '[reason for the rep]')

        member = await get_member(ctx, self.bot, mem)

        if member is None:
            return await embed_maker.command_error(ctx, '[member]')
        elif isinstance(member, str):
            return await embed_maker.message(ctx, member, colour='red')

        if member.id == ctx.author.id:
            return await embed_maker.message(ctx, f'You can\'t give rep points to yourself', colour='red')

        if member.bot:
            return await embed_maker.message(ctx, f'You can\'t give rep points to bots', colour='red')

        # check last rep
        if 'last_rep' in leveling_user and int(leveling_user['last_rep']) == member.id:
            return await embed_maker.message(ctx, f'You can\'t give rep to the same person twice in a row', colour='red')

        # check if member is in database
        member_leveling_user = db.leveling_users.find_one({'guild_id': ctx.guild.id, 'user_id': member.id})
        if not member_leveling_user:
            leveling_user = database.schemas['leveling_user']
            leveling_user['guild_id'] = ctx.guild.id
            leveling_user['user_id'] = mem.id
            db.leveling_users.insert_one(leveling_user)

        # set rep_time to 24h so user cant spam rep points
        expire = round(time()) + 86400  # 24 hours
        db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': ctx.author.id}, {'$set': {'rep_timer': expire}})

        # give user rep point
        db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': member.id}, {'$inc': {f'reputation': 1}})

        # log who author repped
        db.leveling_users.update_one({'guild_id': ctx.guild.id, 'user_id': ctx.author.id}, {'$set': {'last_rep': member.id}})

        await embed_maker.message(ctx, f'Gave +1 rep to <@{member.id}>')

        # send receiving user rep reason
        msg = f'<@{ctx.author.id}> gave you a reputation point because: **"{reason}"**'
        embed = discord.Embed(colour=config.EMBED_COLOUR, description=msg, timestamp=datetime.now())
        embed.set_footer(text=f'{ctx.guild.name}', icon_url=ctx.guild.icon_url)
        embed.set_author(name='Rep')
        # add a try because bot might not be able to dm member
        try:
            await member.send(embed=embed)
        except:
            pass

        # check if user already has rep boost, if they do, extend it by 30 minutes
        boost = db.boosts.find_one({'guild_id': ctx.guild.id, 'user_id': member.id, 'type': 'rep'})
        if boost:
            boost_expire = boost['expires']
            # if boost is expired or boost + 30min is bigger than 6 hours set expire to 6 hours
            if boost_expire < round(time()) or (boost_expire + 1800) - round(time()) > (3600 * 6):
                expire = round(time()) + (3600 * 6)  # 6 hours
            # otherwise just expand expire by 30 mins
            else:
                expire = boost_expire + 1800  # 30 min
            return db.boosts.update_one({'_id': ObjectId(boost['_id'])}, {'$set': {f'expires': expire}})

        # give user 10% xp boost for 6 hours
        boost_dict = {
            'guild_id': ctx.guild.id,
            'user_id': member.id,
            'expires': round(time()) + (3600 * 6),
            'multiplier': 0.1,
            'type': 'rep'
        }
        db.boosts.insert_one(boost_dict)

    @commands.command(help='See all the perks that a role has to offer',
                      usage='perks [role name]',
                      examples=['perks Party Member'],
                      clearance='User', cls=command.Command)
    async def perks(self, ctx, *, role_name=None):
        if role_name is None:
            return await embed_maker.command_error(ctx)

        leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'leveling_routes': 1})

        leveling_routes = leveling_data['leveling_routes']
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

    @commands.command(help='Shows your (or someone else\'s) rank and level',
                      usage='rank (member)', examples=['rank', 'rank @Hattyot', 'rank Hattyot'],
                      clearance='User', cls=command.Command)
    async def rank(self, ctx, *, member=None):
        if member is None or member == '-v':
            mem = ctx.author
        else:
            mem = await get_member(ctx, self.bot, member)
            if mem is None:
                return await embed_maker.command_error(ctx)
            elif isinstance(mem, str):
                return await embed_maker.message(ctx, mem, colour='red')

        if mem.bot:
            return await embed_maker.message(ctx, 'No bots allowed >:(', colour='red')

        embed_colour = config.EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        embed.set_footer(text=f'{mem}', icon_url=mem.avatar_url)
        embed.set_author(name=f'{mem.name} - Rank', icon_url=ctx.guild.icon_url)

        leveling_user = db.leveling_users.find_one({'guild_id': ctx.guild.id, 'user_id': mem.id})
        if leveling_user is None:
            leveling_user = database.schemas['leveling_user']
            leveling_user['guild_id'] = ctx.guild.id
            leveling_user['user_id'] = mem.id
            db.leveling_users.insert_one(leveling_user)

        # inform user of boost, if they have it
        boost_multiplier = get_user_boost_multiplier(mem)
        if boost_multiplier > 1:
            boost_percent = round((boost_multiplier - 1) * 100, 1)
            if boost_percent.is_integer():
                boost_percent = round(boost_percent)
            embed.description = f'Active boost: **{boost_percent}%** parliamentary points gain!'

        # checks if honours section needs to be added
        member_hp = leveling_user['hp']
        if member_hp > 0:
            member_h_level = self.user_role_level('honours', leveling_user)
            h_role_name = leveling_user['h_role']
            h_role = discord.utils.find(lambda r: r.name == h_role_name, ctx.guild.roles)
            h_rank = await self.calculate_user_rank('hp', ctx.guild, leveling_user)

            if h_role_name is not None:
                if h_role is None:
                    member_h_role = await ctx.guild.create_role(name=h_role_name)
                    await mem.add_roles(member_h_role)

                hp_progress = self.percent_till_next_level('honours', leveling_user)
                # verbose option
                if member == '-v':
                    hp = leveling_user['hp']
                    totoal_h_level = leveling_user['h_level']
                    hp_till_next_level = (totoal_h_level + 1) * 1000
                    hp_needed = hp_till_next_level - hp
                    avg_msg_needed = math.ceil(hp_needed / 20)
                    hp_value = f'**Rank:** `#{h_rank}`\n**Role:** <@&{h_role.id}>\n**Role Level:** {member_h_level}\n**Total Level:** {totoal_h_level}\n**Points:** {hp}/{hp_till_next_level}\n**Progress:** {hp_progress}%\n**Mlu:**: {avg_msg_needed}'
                else:
                    hp_value = f'**#{h_rank}** | **Level** {member_h_level} <@&{h_role.id}> | Progress: **{hp_progress}%**'

                embed.add_field(name='>Honours', value=hp_value, inline=False)

        # add parliamentary section
        member_p_level = self.user_role_level('parliamentary', leveling_user)
        p_role_name = leveling_user['p_role']
        p_role = discord.utils.find(lambda r: r.name == p_role_name, ctx.guild.roles)
        p_rank = await self.calculate_user_rank('pp', ctx.guild, leveling_user)
        if p_role is None:
            member_p_role = await ctx.guild.create_role(name=p_role_name)
            await mem.add_roles(member_p_role)

        pp_progress = self.percent_till_next_level('parliamentary', leveling_user)
        # verbose option
        if member == '-v':
            pp = int(leveling_user['pp'])
            total_p_level = int(leveling_user['p_level'])
            pp_till_next_level = round(5 / 6 * (total_p_level + 1) * (2 * (total_p_level + 1) * (total_p_level + 1) + 27 * (total_p_level + 1) + 91))
            pp_needed = pp_till_next_level - pp
            avg_msg_needed = math.ceil(pp_needed / 20)
            pp_value = f'**Rank:** `#{p_rank}`\n**Role:** <@&{p_role.id}>\n**Role Level:** {member_p_level}\n**Total Level:** {total_p_level}\n**Points:** {pp}/{pp_till_next_level}\n**Progress:** {pp_progress}%\n**Mlu:**: {avg_msg_needed}'
        else:
            pp_value = f'**#{p_rank}** | **Level** {member_p_level} <@&{p_role.id}> | Progress: **{pp_progress}%**'

        embed.add_field(name='>Parliamentary', value=pp_value, inline=False)

        # add reputation section if user has rep
        if 'reputation' in leveling_user and leveling_user['reputation'] > 0:
            rep = leveling_user['reputation']
            rep_rank = await self.calculate_user_rank('reputation', ctx.guild, leveling_user)
            last_rep = f'<@{leveling_user["last_rep"]}>' if leveling_user['last_rep'] else 'None'
            rep_time = leveling_user['rep_timer'] - round(time())
            rep_again = format_time.seconds(rep_time, accuracy=3) if rep_time > 0 else '0 seconds'
            # verbose option
            if member == '-v':
                rep_value = f'**Rank:** `#{rep_rank}`\n**Points:** {rep}\n**Last Rep:** {last_rep}\n**Rep Timer:** {rep_again}'
            else:
                rep_value = f'**#{rep_rank}** | **{rep}** Rep Points'

            embed.add_field(name='>Reputation', value=rep_value, inline=False)

        return await ctx.send(embed=embed)

    async def calculate_user_rank(self, key, guild, leveling_user, return_mem=False):
        sorted_users = [d for d in db.leveling_users.find({'guild_id': guild.id, key: {'$gt': leveling_user[key] - 1}}).sort(key, -1)]

        u_rank = 1
        for user in sorted_users:
            user_id = user['user_id']
            member = guild.get_member(int(user_id))
            if member is None:
                if 'left' in user:
                    continue

                try:
                    await guild.fetch_member(int(user_id))
                except:
                    db.leveling_users.update_one({'guild_id': guild.id, 'user_id': user_id}, {'$set': {'left': True}})
                    continue
            else:
                if 'left' in user:
                    db.leveling_users.update_one({'guild_id': guild.id}, {'$unset': {'left': ''}})

            if int(user_id) == int(leveling_user['user_id']):
                if return_mem:
                    return u_rank, member

                return u_rank

            u_rank += 1

    @staticmethod
    def percent_till_next_level(branch, leveling_user):
        pre = 'h' if branch == 'honours' else 'p'

        user_points = leveling_user[f'{pre}p']
        user_level = leveling_user[f'{pre}_level']

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

        # return 99.9 when int rounds to 100, but user wont level up yet
        if percent == 100 and pun != 0:
            return 99.9

        return percent

    async def process_hp_message(self, message):
        if cooldown_expired(hp_cooldown, message.guild.id, message.author.id, 60):
            hp_add = 10
            leveling_user = db.leveling_users.find_one({'guild_id': message.guild.id, 'user_id': message.author.id})
            if leveling_user is None:
                leveling_user = database.schemas['leveling_user']
                leveling_user['guild_id'] = message.guild.id
                leveling_user['user_id'] = message.author.id

                db.leveling_users.insert_one(leveling_user)

            # adds honours role to user if it's their first honours points gain
            if leveling_user['hp'] == 0:
                leveling_data = db.leveling_data.find_one({'guild_id': message.guild.id}, {'leveling_routes': 1})
                leveling_routes = leveling_data['leveling_routes']

                # gets the name of the first honours role
                h_role_tuple = leveling_routes['honours'][0]
                h_role_name = h_role_tuple[0]
                h_role = discord.utils.find(lambda r: r.name == h_role_name, message.guild.roles)

                if h_role is None:
                    h_role = await message.guild.create_role(name=h_role_name)

                await message.author.add_roles(h_role)
                db.leveling_users.update_one({'guild_id': message.guild.id, 'user_id': message.author.id}, {'$set': {'h_role': h_role.name}})
                leveling_user['h_role'] = h_role.name

            leveling_user['hp'] += hp_add
            db.leveling_users.update_one({'guild_id': message.guild.id, 'user_id': message.author.id}, {'$set': {'hp': leveling_user['hp']}})

            # Check if user leveled up
            return await self.level_up(message, message.author, 'honours', leveling_user)

    async def process_message(self, message):
        if cooldown_expired(pp_cooldown, message.guild.id, message.author.id, 60):
            pp_add = randint(15, 25)
            leveling_user = db.leveling_users.find_one({'guild_id': message.guild.id, 'user_id': message.author.id})

            # Check if user in database, if not, add them
            if leveling_user is None:
                leveling_user = database.schemas['leveling_user']
                leveling_user['guild_id'] = message.guild.id
                leveling_user['user_id'] = message.author.id

                db.leveling_users.insert_one(leveling_user)

            # check for active boost and add to pp_add if active
            boost_multiplier = get_user_boost_multiplier(message.author)
            if boost_multiplier > 1:
                pp_add = round(pp_add * boost_multiplier)

            # check if 'left' tag is left in user data, remove if it is
            if 'left' in leveling_user:
                db.leveling_users.update_one({'guild_id': message.guild.id, 'user_id': message.author.id}, {'$unset': {'left': ''}})

            leveling_user['pp'] += pp_add
            db.leveling_users.update_one({'guild_id': message.guild.id, 'user_id': message.author.id}, {'$set': {f'pp': leveling_user['pp']}})

            # Check if user leveled up
            return await self.level_up(message, message.author, 'parliamentary', leveling_user)

    async def level_up(self, message, member, branch, leveling_user):
        if branch == 'honours':
            pre = 'h_'
            levels_up = honours_levels_up(leveling_user)
        else:
            pre = 'p_'
            levels_up = parliamentary_levels_up(leveling_user)

        leveling_user[f'{pre}level'] += levels_up
        user_role = leveling_user[f'{pre}role']

        if user_role is None:
            return

        # Checks if user has role
        role = discord.utils.find(lambda rl: rl.name == user_role, message.guild.roles)
        if role is None:
            role = await message.guild.create_role(name=user_role)

        if role not in member.roles:
            await member.add_roles(role)

        user_role_level = self.user_role_level(branch, leveling_user)

        if not levels_up and user_role_level >= 0:
            return

        new_role = ()
        if user_role_level < 0:
            leveling_data = db.leveling_data.find_one({'guild_id': leveling_user['guild_id']}, {'leveling_routes': 1})
            leveling_routes = leveling_data['leveling_routes']
            roles = leveling_routes[branch]

            role = [role for role in roles if role[0] == user_role]
            role_index = roles.index(role[0])

            # if goes up multiple roles, add previous roles to user
            if user_role_level < -1:
                roles_up = roles[role_index + 1:role_index + abs(user_role_level) + 1]
                new_role = roles_up[-1]
                new_role_obj = None
                for r in roles_up:
                    role_object = discord.utils.find(lambda rl: rl.name == r[0], message.guild.roles)
                    if role_object is None:
                        role_object = await message.guild.create_role(name=r[0])

                    if role_object not in member.roles:
                        await member.add_roles(role_object)

                    new_role_obj = role_object

            # get new role and add it to user
            else:
                if len(roles) - 1 < role_index + abs(user_role_level):
                    new_role = roles[-1]
                else:
                    new_role = roles[role_index + abs(user_role_level)]

                new_role_obj = discord.utils.find(lambda rl: rl.name == new_role[0], message.guild.roles)
                if new_role_obj is None:
                    new_role_obj = await message.guild.create_role(name=new_role[0])

                await member.add_roles(new_role_obj)

            db.leveling_users.update_one({'guild_id': message.guild.id, 'user_id': member.id}, {'$set': {f'{pre}role': new_role_obj.name}})
            leveling_user[f'{pre}role'] = new_role_obj.name

            user_role_level = self.user_role_level(branch, leveling_user)
            reward_text = f'Congrats **{member.name}** you\'ve advanced to a level **{user_role_level}** <@&{new_role_obj.id}>'

        else:
            reward_text = f'Congrats **{member.name}** you\'ve become a level **{user_role_level}** <@&{role.id}>'

        reward_text += ' due to your contributions!' if branch == 'honours' else '!'

        db.leveling_users.update_one({'guild_id': message.guild.id, 'user_id': member.id}, {'$set': {f'{pre}level': leveling_user[f'{pre}level']}})

        await self.level_up_message(message, member, leveling_user, reward_text, new_role)

    async def level_up_message(self, message, member, leveling_user, reward_text, role_tuple):
        embed_colour = config.EMBED_COLOUR
        embed = discord.Embed(colour=embed_colour, description=reward_text, timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        embed.set_author(name='Level Up!', icon_url=message.guild.icon_url)

        leveling_data = db.leveling_data.find_one({'guild_id': message.guild.id}, {'level_up_channel': 1})
        channel_id = leveling_data['level_up_channel']
        channel = self.bot.get_channel(channel_id)

        if channel is None:
            channel = message.channel

        if 'settings' not in leveling_user:
            db.leveling_users.update_one({'guild_id': message.guild.id, 'user_id': member.id}, {'$set': {'settings': {'@_me': False}}})
            leveling_user['settings'] = {'@_me': False}

        settings = leveling_user['settings']
        enabled = settings['@_me']

        content = ''
        if enabled:
            content = f'<@{member.id}>'
        await channel.send(embed=embed, content=content)

        # Sends user info about perks if role has them
        if len(role_tuple) < 3 or not bool(role_tuple[2]):
            return
        else:
            role = discord.utils.find(lambda r: r.name == role_tuple[0], message.guild.roles)
            if role is None:
                role = await message.guild.create_role(name=role_tuple[0])

            perks_str = "\n • ".join(role_tuple[2])
            msg = f'**Congrats** again on advancing to **{role.name}**!' \
                  f'\nThis role also gives you new **perks:**' \
                  f'\n • {perks_str}' \
                  f'\n\nFor more info on these perks ask one of the TLDR server mods'
            embed = discord.Embed(colour=embed_colour, description=msg, timestamp=datetime.now())
            embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
            embed.set_author(name='New Perks!', icon_url=message.guild.icon_url)

            return await member.send(embed=embed)

    @staticmethod
    def user_role_level(branch, leveling_user):
        # Return negative number if user needs to go up roles otherwise returns positive number of users role level

        pre = 'h_' if branch == 'honours' else 'p_'

        user_level = leveling_user[f'{pre}level']
        user_role = leveling_user[f'{pre}role']

        leveling_data = db.leveling_data.find_one({'guild_id': leveling_user['guild_id']}, {'leveling_routes': 1})
        leveling_routes = leveling_data['leveling_routes']
        all_roles = leveling_routes[branch]
        role_amount = len(all_roles)

        # Get role index
        role_obj = [role for role in all_roles if role[0] == user_role]
        if not role_obj:
            return 0
        else:
            role_obj = role_obj[0]
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
            return int(user_level - previous_level_total)
        if current_level_total > user_level:
            return int(user_level - previous_level_total)
        if current_level_total == user_level:
            return int(role_obj[1])
        if current_level_total < user_level:
            # calculates how many roles user goes up
            roles_up = 0
            for i, r in enumerate(all_roles):
                if role_index >= i:
                    continue
                elif current_level_total < user_level:
                    roles_up -= 1
                    current_level_total += all_roles[i][1]
            return int(roles_up)


def parliamentary_levels_up(levels_user):
    user_level = levels_user['p_level']
    user_pp = levels_user['pp']

    i = 0
    while True:
        # total pp needed to gain the next level
        total_pp = 0
        for j in range(int(user_level) + i + 1):
            # the formula to calculate how much pp you need for the next level
            total_pp += (5 * (j ** 2) + 50 * j + 100)

        if total_pp - user_pp >= 0:
            return i

        i += 1


def honours_levels_up(levels_user):
    user_level = levels_user['h_level']
    user_hp = levels_user['hp']

    i = 0
    while True:
        total_hp = 1000 * (user_level + i)
        if total_hp - user_hp >= 0:
            return i - 1

        i += 1


def setup(bot):
    bot.add_cog(Leveling(bot))
