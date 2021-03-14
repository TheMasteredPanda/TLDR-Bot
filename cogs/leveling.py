import discord
import time
import math
import datetime

from bot import TLDR
from modules.utils import (
    Branch,
    Role,
    ParseArgs,
    get_leveling_role,
    get_user_clearance,
    get_member,
    get_branch_role,
    get_user_boost_multiplier
)
from typing import Union, Optional
from modules import embed_maker, cls, database, format_time
from random import randint
from discord.ext import commands

db = database.Connection()


class Cooldown:
    def __init__(self, cooldown_in_seconds: int = 60):
        self.cooldown_in_seconds = cooldown_in_seconds
        self.cooldown_users = {}

    def add_user(self, guild_id: int, user_id: int):
        if guild_id not in self.cooldown_users:
            self.cooldown_users[guild_id] = {}

        now = time.time() + self.cooldown_in_seconds
        self.cooldown_users[guild_id][user_id] = now

    def user_cooldown(self, guild_id: int, user_id: int) -> int:
        if guild_id not in self.cooldown_users:
            self.cooldown_users[guild_id] = {}

        if user_id in self.cooldown_users[guild_id]:
            now = time.time()
            cooldown_time = self.cooldown_users[guild_id][user_id] - now
            if cooldown_time < 0:
                del self.cooldown_users[guild_id][user_id]
                cooldown_time = 0
        else:
            cooldown_time = 0

        return int(cooldown_time)


class Leveling(commands.Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

        # parliamentary points earn cooldown
        self.pp_cooldown = Cooldown()
        self.hp_cooldown = Cooldown()

    @commands.command(
        help='Show someone you respect them by giving them a reputation point',
        usage='rep [member] [reason for the rep]',
        examples=['rep @Hattyot for being an excellent example in this text'],
        clearance='User',
        cls=cls.Command,
        aliases=['reputation']
    )
    async def rep(self, ctx: commands.Context, member_identifier: str = None, *, reason: str = None):
        # check if user has been in server for more than 7 days
        now_datetime = datetime.datetime.now()
        joined_at = ctx.author.joined_at
        diff = now_datetime - joined_at
        if round(diff.total_seconds()) < 86400 * 7:  # 7 days
            return await embed_maker.error(ctx, f'You need to be on this server for at least 7 days to give rep points')

        # check if user can give rep point
        leveling_user = db.leveling_users.find_one({'guild_id': ctx.guild.id, 'user_id': ctx.author.id})
        now = time.time()
        if 'rep_timer' in leveling_user and now < leveling_user['rep_timer']:
            rep_time = leveling_user['rep_timer'] - round(time.time())
            return await embed_maker.message(
                ctx,
                description=f'You can give someone a reputation point again in:\n'
                            f'**{format_time.seconds(rep_time, accuracy=3)}**',
                send=True
            )

        if member_identifier is None:
            return await embed_maker.command_error(ctx)

        if reason is None:
            return await embed_maker.command_error(ctx, '[reason for the rep]')

        member = await get_member(ctx, member_identifier)

        if type(member) == discord.Message:
            return

        if member.id == ctx.author.id:
            return await embed_maker.error(ctx, f'You can\'t give rep points to yourself')

        if member.bot:
            return await embed_maker.error(ctx, f'You can\'t give rep points to bots')

        # check last rep
        if 'last_rep' in leveling_user and int(leveling_user['last_rep']) == member.id:
            return await embed_maker.error(ctx, f'You can\'t give rep to the same person twice in a row')

        # check if member is in database
        member_leveling_user = db.get_leveling_user(ctx.guild.id, member.id)

        # set rep_time to 24h so user cant spam rep points
        expire = round(time.time()) + 86400  # 24 hours
        db.leveling_users.update_one(
            {'guild_id': ctx.guild.id, 'user_id': ctx.author.id},
            {'$set': {'rep_timer': expire, 'last_rep': member.id}}
        )

        # give user rep point
        db.leveling_users.update_one(
            {'guild_id': ctx.guild.id, 'user_id': member.id},
            {'$inc': {f'reputation': 1}}
        )

        await embed_maker.message(ctx, description=f'Gave +1 rep to <@{member.id}>', send=True)

        # send receiving user rep reason
        msg = f'<@{ctx.author.id}> gave you a reputation point:\n**"{reason}"**'
        embed = await embed_maker.message(
            ctx,
            description=msg,
            author={'name': 'Rep'}
        )

        # add a try because bot might not be able to dm member
        try:
            await member.send(embed=embed)
        except:
            pass

        # check if user already has rep boost, if they do, extend it by 30 minutes
        if 'boosts' in member_leveling_user and 'rep' in member_leveling_user['boosts']:
            boost = member_leveling_user['boosts']['rep']
            boost_expires = boost['expires']
            # if boost is expired or boost + 30min is bigger than 6 hours set expire to 6 hours
            if boost_expires < round(time.time()) or (boost_expires + 1800) - round(time.time()) > (3600 * 6):
                expire = round(time.time()) + (3600 * 6)
            # otherwise just expand expire by 30 minutes
            else:
                expire = boost_expires + 1800  # 30 min

            return db.leveling_users.update_one(
                {'guild_id': ctx.guild.id, 'user_id': member.id},
                {'$set': {f'boosts.rep.expires': expire}})

        # give user 10% xp boost for 6 hours
        boost_dict = {
            'expires': round(time.time()) + (3600 * 6),
            'multiplier': 0.1,
        }
        db.leveling_users.update_one(
            {'guild_id': ctx.guild.id, 'user_id': member.id},
            {'$set': {'boosts.rep': boost_dict}}
        )

    @commands.command(
        name='@_me',
        help='Makes the bot @ you when you level up',
        usage='@_me',
        examples=['@_me', '@_me'],
        clearance='User',
        cls=cls.Command
    )
    async def at_me(self, ctx):
        leveling_user = db.get_leveling_user(ctx.guild.id, ctx.author.id)

        if leveling_user['settings']['@_me']:
            msg = 'Disabling @ when you level up'
            colour = 'orange'
        else:
            msg = 'Enabling @ when you level up'
            colour = 'green'

        db.leveling_users.update_one(
            {'guild_id': ctx.guild.id, 'user_id': ctx.author.id},
            {'$set': {'settings': {'@_me': not bool(leveling_user['settings']['@_me'])}}}
        )
        return await embed_maker.message(ctx, description=msg, colour=colour, send=True)

    @commands.group(
        invoke_without_command=True,
        help='See current leveling routes',
        usage='leveling_routes (branch <parliamentary/honours>)',
        examples=[
            'ranks',
            'ranks parliamentary',
            'ranks honours'
        ],
        clearance='User',

        Admin=cls.Help(
            help='See current leveling routes or add, remove or edit roles',
            usage='ranks (branch) (sub command) (args)',
            examples=['ranks', 'ranks honours'],
            sub_commands=['add', 'remove']
        ),

        cls=cls.Group
    )
    async def ranks(self, ctx: commands.Context, branch: Union[Branch, str] = 'parliamentary'):
        if ctx.subcommand_passed is None and branch:
            leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'leveling_routes': 1})
            leveling_routes = leveling_data['leveling_routes']
            embed = await embed_maker.message(ctx, author={'name': 'Ranks'})

            # Looks up how many people have a role
            count = {
                role['name']: db.leveling_users.count({'guild_id': ctx.guild.id, f'{branch[0]}_role': role['name']})
                for role in leveling_routes[branch]
            }

            value = ''
            for i, role in enumerate(leveling_routes[branch]):
                role_object = await get_leveling_role(ctx.guild, role['name'])
                value += f'\n**#{i + 1}:** <@&{role_object.id}> - {count[role_object.name]} People'

            if not value:
                value = 'This branch currently has no roles'

            value += f'\n\nTotal: **{sum(count.values())} People**'
            embed.add_field(name=f'>{branch.title()} - Every 5 levels you advance a role', value=value, inline=False)

            return await ctx.send(embed=embed)

    @ranks.command(
        name='add',
        help='Add a role to parliamentary or honours route',
        usage='ranks add [branch] [role name]',
        examples=['ranks add honours Pro', 'ranks add honours Knight 2'],
        clearance='admin',
        cls=cls.Command
    )
    async def ranks_add(self, ctx: commands.Context, branch: Union[Branch, str] = None, *, role_name: str = None):
        if not branch or type(branch) == int:
            return await embed_maker.command_error(ctx)

        if not role_name:
            return await embed_maker.command_error(ctx, '[role name]')

        new_role = {
            'name': role_name,
            'perks': []
        }

        db.leveling_data.update_one(
            {'guild_id': ctx.guild.id},
            {'$push': {f'leveling_routes.{branch}': new_role}}
        )

        await embed_maker.message(
            ctx,
            description=f'`{role_name}` has been added to the list of `{branch}` roles',
            colour='green',
            send=True
        )

        ctx.invoked_subcommand = ''
        return await self.ranks(ctx, branch)

    @ranks.command(
        name='remove',
        help='Remove a role from the list of parliamentary or honours roles',
        usage='ranks remove [branch] [role name]',
        examples=['ranks remove honours Knight'],
        clearance='admin',
        cls=cls.Command
    )
    async def ranks_remove(self, ctx: commands.Context, branch: Union[Branch, str] = None, *, role: Union[Role, dict, str]):
        if not branch or type(branch) == int:
            return await embed_maker.command_error(ctx)

        if type(role) != dict:
            return await embed_maker.error(ctx, f"Couldn't find a {branch} role by the name {role}")

        db.leveling_data.update_one(
            {'guild_id': ctx.guild.id},
            {'$pull': {f'leveling_routes.{branch}': role}}
        )

        await embed_maker.message(
            ctx,
            description=f'`{role["name"]}` has been remove from the list of `{branch}` roles',
            colour='green',
            send=True
        )

        ctx.invoked_subcommand = ''
        return await self.ranks(ctx, branch)

    @commands.group(
        invoke_without_command=True,
        help='See all the perks that a role has to offer',
        usage='perks (role name)',
        examples=['perks', 'perks Party Member'],
        clearance='User',

        Mod=cls.Help(
            help='See all the perks that a role has to offer or add or remove them',
            usage='perks (<sub command/role name>) (args)',
            examples=['perks', 'perks Party Member'],
            sub_commands=['set', 'add', 'remove'],
        ),

        cls=cls.Group
    )
    async def perks(self, ctx: commands.Context, *, role: Union[Role, dict] = None):
        if ctx.subcommand_passed is None:
            leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'leveling_routes': 1})

            leveling_routes = leveling_data['leveling_routes']
            honours_branch = leveling_routes['honours']
            parliamentary_branch = leveling_routes['parliamentary']

            if role is None:
                # find roles that have perks
                filtered_parliamentary = list(filter(lambda r: r['perks'], parliamentary_branch))
                filtered_honours = list(filter(lambda r: r['perks'], honours_branch))

                embed = await embed_maker.message(
                    ctx,
                    description=f'To view perks of a role type `{ctx.prefix}perks [role name]`',
                    author={'name': f'List of roles with perks'},
                )

                if filtered_parliamentary:
                    parliamentary_str = '\n'.join(r['name'] for r in filtered_parliamentary)
                else:
                    parliamentary_str = 'Currently no Parliamentary roles offer any perks'

                if filtered_honours:
                    honours_str = '\n'.join(r['name'] for r in filtered_honours)
                else:
                    honours_str = 'Currently no Honours roles offer any perks'

                embed.add_field(name='>Parliamentary Roles With Perks', value=parliamentary_str, inline=False)
                embed.add_field(name='>Honours Roles With Perks', value=honours_str, inline=False)

                return await ctx.send(embed=embed)

            if type(role) == dict:
                if not role['perks']:
                    perks_str = f'**{role["name"]}** currently offers no perks'
                else:
                    perks_str = "\n".join([f'`#{i + 1}` - {perk}' for i, perk in enumerate(role['perks'])])

                return await embed_maker.message(
                    ctx,
                    description=perks_str,
                    author={'name': f'{role["name"]} - Perks'},
                    send=True
                )

            if 'Mod' in get_user_clearance(ctx.author):
                return await embed_maker.error(ctx, 'Invalid sub command')

    @staticmethod
    async def modify_perks(ctx: commands.Context, command: str, args: dict, message: str) -> Optional[dict]:
        if args is None:
            return await embed_maker.command_error(ctx)

        if 'r' not in args or not args['r']:
            return await embed_maker.error(ctx, "Missing role arg")

        if ('p' not in args or not args['p']) and command != 'pull':
            return await embed_maker.error(ctx, "Missing perks arg")

        role_name = args['r'][0]
        new_perks = args['p']

        branch, role = get_branch_role(ctx.guild.id, role_name)

        if command == 'add':
            role['perks'] += new_perks
        elif command == 'set':
            role['perks'] = new_perks
        elif command == 'remove' and not new_perks:
            role['perks'] = []
        elif command == 'remove' and new_perks:
            to_remove = [int(num) - 1 for num in new_perks if num.isdigit() and 0 < int(num) <= len(role['perks'])]
            role['perks'] = [perk for i, perk in enumerate(role['perks']) if i not in to_remove]

        db.leveling_data.update_one({
            'guild_id': ctx.guild.id,
            f'leveling_routes.{branch}': {'$elemMatch': {'name': role['name']}}},
            {f'$set': {f'leveling_routes.{branch}.$.perks': role['perks']}}
        )

        await embed_maker.message(
            ctx,
            description=message.format(**role),
            colour='green',
            send=True
        )

        # send embed of role perks
        perks_str = "\n".join([f'`#{i + 1}` - {perk}' for i, perk in enumerate(role['perks'])])

        return await embed_maker.message(
            ctx,
            description=perks_str,
            author={'name': f'{role["name"]} - New Perks'},
            send=True
        )

    @perks.command(
        name='set',
        help='set the perks of a role',
        usage='perks set -r [role name] -p [perk 1] -p (perk 2)',
        examples=['perks set -r Party Member -p Monthly giveaways -p some cool perk'],
        clearance='Mod',
        cls=cls.Command
    )
    async def perks_set(self, ctx: commands.Context, *, args: Union[ParseArgs, dict] = None):
        return await self.modify_perks(ctx, 'set', args, 'New perks have been set for role `{name}`')

    @perks.command(
        name='add',
        help='Add perks to a role',
        usage='perks add -r [role name] -p [perk 1] -p (perk 2)',
        examples=['perks add -r Party Member -p Monthly giveaways -p some cool perk'],
        clearance='Mod',
        cls=cls.Command
    )
    async def perks_add(self, ctx: commands.Context, *, args: Union[ParseArgs, dict] = None):
        return await self.modify_perks(ctx, 'add', args, 'New perks have been added for role `{name}`')

    @perks.command(
        name='remove',
        help='remove perks of a role, or remove only some perks',
        usage='perks remove -r [role name] -p (perk number)',
        examples=[
            'perks remove -r Party Member -p 1 -p 2',
            'perks remove -r Party Member'
        ],
        clearance='Mod',
        cls=cls.Command
    )
    async def perks_remove(self, ctx: commands.Context, *, args: Union[ParseArgs, dict] = None):
        return await self.modify_perks(ctx, 'remove', args, 'Perks have been removed from role `{name}`')

    @commands.command(
        help='See all the honours channels or add or remove a channel from the list of honours channels',
        usage='honours_channel (action - <add/remove>) [#channel]',
        examples=['honours_channels', 'honours_channels add #court', 'honours_channels remove #Mods'],
        clearance='Mod',
        cls=cls.Command
    )
    async def honours_channels(self, ctx, action: str = None, channel: discord.TextChannel = None):
        leveling_data = db.leveling_data.find_one({'guild_id': ctx.guild.id}, {'honours_channels': 1})
        honours_channels = leveling_data['honours_channels']

        if action is None:
            # display list of honours channels
            channel_list_str = ', '.join(f'<#{channel}>' for channel in honours_channels) if honours_channels else 'None'
            return await embed_maker.message(ctx, description=channel_list_str, send=True)

        if action not in ['add', 'remove']:
            return await embed_maker.command_error(ctx, '[action - <add/remove>]')

        if not channel:
            return await embed_maker.command_error(ctx, '[#channel]')

        msg = ''

        if action == 'add':
            if channel.id in honours_channels:
                return await embed_maker.message(ctx, description='That channel is already on the list', colour='red', send=True)

            db.leveling_data.update_one({'guild_id': ctx.guild.id}, {'$push': {f'honours_channels': channel.id}})
            msg = f'<#{channel.id}> has been added to the list of honours channels'

        if action == 'remove':
            if channel.id not in honours_channels:
                return await embed_maker.message(ctx, description='That channel is not on the list', colour='red', send=True)

            db.leveling_data.update_one({'guild_id': ctx.guild.id}, {'$pull': {f'honours_channels': channel.id}})
            msg = f'<#{channel.id}> has been removed from the list of honours channels'

        return await embed_maker.message(ctx, description=msg, colour='green', send=True)

    @commands.command(
        help='See how many messages you need to send to level up (dont forget about the 60s cooldown)',
        usage='mlu',
        examples=['mlu'],
        clearance='User',
        cls=cls.Command
    )
    async def mlu(self, ctx: commands.Context):
        leveling_user = db.get_leveling_user(ctx.guild.id, ctx.author.id)

        p_level = leveling_user['p_level']
        pp = leveling_user['pp']

        # points needed until level_up
        pp_till_next_level = round((5 / 6) * (p_level + 1) * (2 * (p_level + 1) * (p_level + 1) + 27 * (p_level + 1) + 91)) - pp
        avg_msg_needed = math.ceil(pp_till_next_level / 20)

        # points needed to rank up
        user_rank = await user_role_level('parliamentary', leveling_user)
        missing_levels = 6 - user_rank

        rank_up_level = p_level + missing_levels
        pp_needed_rank_up = round((5 / 6) * rank_up_level * (2 * rank_up_level * rank_up_level + 27 * rank_up_level + 91)) - pp
        avg_msg_rank_up = math.ceil(pp_needed_rank_up / 20)

        return await embed_maker.message(
            ctx,
            description=f'Messages needed to:\n'
                        f'Level up: **{avg_msg_needed}**\n'
                        f'Rank up: **{avg_msg_rank_up}**',
            author={'name': 'MLU'},
            send=True
        )

    @staticmethod
    async def construct_lb_str(ctx: commands.Context, branch: str, sorted_users: list, index: int, your_pos: bool = False):
        lb_str = ''
        for i, leveling_user in enumerate(sorted_users):
            user_id = leveling_user['user_id']

            member = ctx.guild.get_member(int(user_id))
            if member is None:
                member = await ctx.guild.fetch_member(int(user_id))

            addition = 0 if your_pos else 1

            if user_id == ctx.author.id:
                lb_str += rf'**`#{index + i + addition}`**\* - {member.display_name}'
            else:
                lb_str += f'`#{index + i + addition}` - {member.display_name}'

            if not your_pos:
                lb_str += f'  [{member}]'

            pre = '\n' if not your_pos else ' | '

            if branch[0] in ['p', 'h']:
                user_role_name = leveling_user[f'{branch[0]}_role']
                user_role = await get_leveling_role(ctx.guild, user_role_name)
                role_level = await user_role_level(branch, leveling_user)
                progress_percent = percent_till_next_level(branch, leveling_user)
                lb_str += f'{pre}**Level {role_level}** <@&{user_role.id}> | Progress: **{progress_percent}%**\n'
                if not your_pos:
                    lb_str += '\n'
            else:
                rep = leveling_user['reputation']
                lb_str += f' | **{rep} Reputation**\n'

        return lb_str

    async def construct_lb_embed(self, ctx: commands.Context, branch: str, sorted_users: list, page_size_limit: int, page: int, user_index: int, max_page_num: int):
        sorted_users_page = sorted_users[page_size_limit * (page - 1):page_size_limit * page]
        leaderboard_str = await self.construct_lb_str(ctx, branch, sorted_users_page, index=page_size_limit * (page - 1))
        description = 'Damn, this place is empty' if not leaderboard_str else leaderboard_str

        leaderboard_embed = await embed_maker.message(
            ctx,
            description=description,
            footer={'text': f'{ctx.author} | Page {page}/{max_page_num}'},
            author={'name': f'{branch.title()} Leaderboard'}
        )

        # Displays user position under leaderboard and users above and below them if user is below position 10
        if user_index < len(sorted_users) and not (user_index + 1 <= page * page_size_limit):
            sorted_users_segment = sorted_users[user_index - 1:user_index + 2]
            your_pos_str = await self.construct_lb_str(ctx, branch, sorted_users_segment, user_index, your_pos=True)
            leaderboard_embed.add_field(name='Your Position', value=your_pos_str)

        return leaderboard_embed

    @commands.command(
        help='Shows the leveling leaderboards (parliamentary(p)/honours(h)) on the server',
        usage='leaderboard (branch)',
        aliases=['lb'],
        clearance='User',
        examples=['leaderboard parliamentary', 'lb honours'],
        cls=cls.Command
    )
    async def leaderboard(self, ctx: commands.Context, branch: str = 'parliamentary', page: int = 1):
        if branch.isdigit():
            page = int(branch)
            branch = 'parliamentary'
        else:
            branch_switch = {'p': 'parliamentary', 'h': 'honours', 'r': 'reputation'}
            branch = branch_switch.get(branch[0], 'parliamentary')

        key_switch = {'r': 'reputation', 'p': 'pp', 'h': 'hp'}
        key = key_switch.get(branch[0], 'pp')

        # get list of users sorted by points who have more than 0 points
        sorted_users = [u for u in db.leveling_users.find({'guild_id': ctx.guild.id, key: {'$gt': 0}}).sort(key, -1)]

        page_size_limit = 10

        # calculate max page number
        max_page_num = math.ceil(len(list(sorted_users)) / page_size_limit)
        if max_page_num == 0:
            max_page_num = 1

        if page > max_page_num:
            return await embed_maker.error(ctx, 'Exceeded maximum page number')

        leveling_user = db.get_leveling_user(ctx.guild.id, ctx.author.id)

        try:
            user_index = sorted_users.index(leveling_user)
        except ValueError:
            user_index = len(sorted_users)

        leaderboard_embed = await self.construct_lb_embed(ctx, branch, sorted_users, page_size_limit, page, user_index, max_page_num)
        leaderboard_message = await ctx.send(embed=leaderboard_embed)

        async def previous_page(reaction: discord.Reaction, user: discord.User, *, pages_remove: int = 1):
            nonlocal page

            page -= pages_remove
            page %= max_page_num

            if page == 0:
                page = max_page_num

            new_leaderboard_embed = await self.construct_lb_embed(ctx, branch, sorted_users, page_size_limit, page, user_index, max_page_num)
            return await leaderboard_message.edit(embed=new_leaderboard_embed)

        async def next_page(reaction: discord.Reaction, user: discord.User, *, pages_add: int = 1):
            nonlocal page

            page += pages_add
            page %= max_page_num

            if page == 0:
                page = 1

            new_leaderboard_embed = await self.construct_lb_embed(ctx, branch, sorted_users, page_size_limit, page, user_index, max_page_num)
            return await leaderboard_message.edit(embed=new_leaderboard_embed)

        async def five_pages_forward(reaction: discord.Reaction, user: discord.User):
            nonlocal page
            return await next_page(reaction, user, pages_add=5)

        async def five_pages_backward(reaction: discord.Reaction, user: discord.User):
            nonlocal page
            return await previous_page(reaction, user, pages_remove=5)

        buttons = {
            '⏪': five_pages_backward,
            '⬅️': previous_page,
            '➡️': next_page,
            '⏩': five_pages_forward
        }

        await self.bot.reaction_menus.add(leaderboard_message, buttons)

    async def branch_rank_str(self, branch: str, guild: discord.Guild, member: discord.Member, leveling_user: dict, verbose: bool):
        prefix = branch[0]
        # add parliamentary section
        role_level = await user_role_level(branch, leveling_user)
        role_name = leveling_user[f'{prefix}_role']

        # calculate user rank by counting users who have more points than user
        rank = get_user_rank(guild.id, branch, leveling_user)

        role_object = await get_leveling_role(guild, role_name, member)
        progress = percent_till_next_level(branch, leveling_user)

        if verbose:
            points = int(leveling_user[f'{prefix}p'])
            level = int(leveling_user[f'{prefix}_level'])

            points_till_next_level = round(5 / 6 * (level + 1) * (2 * (level + 1) * (level + 1) + 27 * (level + 1) + 91))
            cooldown_object = self.pp_cooldown

            cooldown = f'{cooldown_object.user_cooldown(guild.id, member.id)} seconds'

            rank_str = f'**Rank:** `#{rank}`\n' \
                       f'**Role:** <@&{role_object.id}>\n' \
                       f'**Role Level:** {role_level}\n' \
                       f'**Total Level:** {level}\n' \
                       f'**Points:** {points}/{points_till_next_level}\n' \
                       f'**Progress:** {progress}%\n' \
                       f'**Cooldown**: {cooldown}'
        else:
            rank_str = f'**#{rank}** | **Level** {role_level} <@&{role_object.id}> | Progress: **{progress}%**'

        return rank_str

    @commands.command(
        help='Shows your (or someone else\'s) rank and level, add -v too see all the data',
        usage='rank (member) (-v)',
        examples=['rank', 'rank @Hattyot', 'rank Hattyot -v'],
        clearance='User',
        cls=cls.Command
    )
    async def rank(self, ctx: commands.Context, *, user_input: str = ''):
        verbose = '-v' in user_input

        user_input = user_input.replace('-v', '').strip()

        # set member to author if user_input is just -v or user input isn't provided
        if not user_input or user_input.rstrip() == '-v':
            member = ctx.author
        else:
            member = await get_member(ctx, user_input)
            if type(member) == discord.Message:
                return

        if member.bot:
            return await embed_maker.error(ctx, 'No bots allowed >:(')

        rank_embed = await embed_maker.message(
            ctx,
            footer={'text': str(member), 'icon_url': member.avatar_url},
            author={'name': f'{member.name} - Rank'}
        )

        # inform user of boost, if they have it
        boost_multiplier = get_user_boost_multiplier(member)
        if boost_multiplier > 0:
            boost_percent = round(boost_multiplier * 100, 1)

            if boost_percent.is_integer():
                boost_percent = int(boost_percent)

            rank_embed.description = f'Active boost: **{boost_percent}%** parliamentary points gain!'

        leveling_user = db.get_leveling_user(ctx.guild.id, member.id)

        if leveling_user['hp'] > 0:
            hp_str = await self.branch_rank_str('honours', ctx.guild, member, leveling_user, verbose)
            rank_embed.add_field(name='>Honours', value=hp_str, inline=False)

        pp_str = await self.branch_rank_str('parliamentary', ctx.guild, member, leveling_user, verbose)
        rank_embed.add_field(name='>Parliamentary', value=pp_str, inline=False)

        if leveling_user['reputation']:
            rank = get_user_rank(ctx.guild.id, 'rep', leveling_user)
            if verbose:
                rep_time = int(leveling_user['rep_timer']) - round(time.time())
                if rep_time < 0:
                    rep_time = 0

                rep_time_str = format_time.seconds(rep_time, accuracy=10)

                last_rep = f'<@{leveling_user["last_rep"]}>' if leveling_user["last_rep"] else 'None'
                rep_str = f"**Reputation:** {leveling_user['reputation']}\n" \
                          f"**Rep timer:** {rep_time_str}\n" \
                          f"**Last Rep: {last_rep}**\n"
            else:
                rep_str = f'**#{rank}** | **{leveling_user["reputation"]}** reputation'

            rank_embed.add_field(name='>Reputation', value=rep_str, inline=False)

        # add boosts field
        if verbose and 'boosts' in leveling_user:
            boost_str = ''
            i = 1
            user_boosts = leveling_user['boosts']
            for boost_type, boost_data in user_boosts.items():
                expires = boost_data["expires"]
                if expires < round(time.time()):
                    db.leveling_users(
                        {'guild_id': ctx.guild.id, 'user_id': member.id},
                        {'$unset': f'boosts.{boost_type}'}
                    )
                    continue

                multiplier = boost_data["multiplier"]
                percent = round(multiplier * 100, 1)

                if percent.is_integer():
                    percent = int(percent)

                boost_str += f'`#{i}` - {percent}% boost | Expires: {format_time.seconds(expires - round(time.time()), accuracy=5)}'
                boost_str += f' | Type: {boost_type}\n'

                i += 1

            boost_str = 'None' if not boost_str else boost_str
            rank_embed.add_field(name='>Boosts', value=boost_str)

        if verbose:
            if "settings" not in leveling_user or "@_me" not in leveling_user['settings']:
                leveling_user["settings"] = {}
                leveling_user["settings"]["@_me"] = False

            rank_embed.add_field(name='>Settings', value=f'**@_me:** {leveling_user["settings"]["@_me"]}', inline=False)

        return await ctx.send(embed=rank_embed)

    @staticmethod
    async def advance_user_role(message: discord.Message, branch: str, leveling_user: dict, leveling_data: dict, role_level: int) -> discord.Role:
        prefix = branch[0]

        leveling_routes = leveling_data['leveling_routes']
        roles = leveling_routes[branch]

        branch_role = next(filter(lambda rl: rl['name'] == leveling_user[f'{prefix}_role'], roles))
        role_index = roles.index(branch_role)

        # check if user is on last role else set according to role index and new role level
        new_role = roles[-1] if len(roles) - 1 < role_index + abs(role_level) else roles[role_index + abs(role_level)]
        new_role_obj = await get_leveling_role(message.guild, new_role['name'], message.author)

        db.leveling_users.update_one({
            'guild_id': message.guild.id,
            'user_id': message.author.id},
            {
                '$set': {f'{prefix}_role': new_role_obj.name}
            }
        )

        # Sends user info about perks if role has them
        if new_role['perks']:
            perks_str = "\n • ".join(new_role['perks'])
            perks_message = f'**Congrats** again on advancing to **{new_role["name"]}**!' \
                            f'\nThis role also gives you new **perks:**' \
                            f'\n • {perks_str}' \
                            f'\n\nFor more info on these perks ask one of the TLDR server mods'

            perks_embed = await embed_maker.message(
                message,
                description=perks_message,
                author={'name': 'New Perks!'}
            )

            try:
                await message.author.send(embed=perks_embed)
            # in case user doesnt allow dms from bot
            except:
                pass

        return new_role_obj

    async def level_up_message(self, message: discord.Message, leveling_user: dict, reward_text: str):
        embed = await embed_maker.message(
            message,
            description=reward_text,
            author={'name': 'Level Up!'}
        )

        leveling_data = db.get_leveling_data(message.guild.id, {'level_up_channel': 1})
        channel_id = leveling_data['level_up_channel']

        # get channel where to send level up message
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = message.channel

        # check if settings needs to be added to user document
        if 'settings' not in leveling_user:
            db.leveling_users.update_one({
                'guild_id': message.guild.id,
                'user_id': message.author.id},
                {
                    '$set': {'settings': {'@_me': False}}
                }
            )
            leveling_user['settings'] = {'@_me': False}

        # true if user wants to be @'d when they level up
        enabled = leveling_user['settings']['@_me']

        content = f'<@{message.author.id}>' if enabled else ''

        await channel.send(embed=embed, content=content)

    async def level_up(self, branch: str, leveling_user: dict, message: discord.Message):
        prefix = branch[0]
        levels_up = calc_levels_up(branch, leveling_user)
        leveling_user[f'{prefix}_level'] += levels_up
        user_role_name = leveling_user[f'{prefix}_role']

        if not user_role_name:
            return

        # Checks if user has role
        new_role = await get_leveling_role(message.guild, user_role_name, message.author)
        # get user role level
        role_level = await user_role_level(branch, leveling_user)

        # return if user hasn't leveled up and they dont need to go up roles
        if not levels_up and role_level >= 0:
            return

        leveling_data = db.get_leveling_data(message.guild.id, {'level_up_channel': 1, 'leveling_routes': 1})

        # user needs to go up a role
        if role_level < 0:
            new_role = await self.advance_user_role(message, branch, leveling_user, leveling_data, role_level)
            leveling_user[f'{prefix}_role'] = new_role.name

            role_level = await user_role_level(branch, leveling_user)
            reward_text = f'Congrats **{message.author.name}** you\'ve advanced to a level **{role_level}** <@&{new_role.id}>'

        else:
            reward_text = f'Congrats **{message.author.name}** you\'ve become a level **{role_level}** <@&{new_role.id}>'

        reward_text += ' due to your contributions!' if branch == 'honours' else '!'

        db.leveling_users.update_one({
            'guild_id': message.guild.id,
            'user_id': message.author.id},
            {
                '$inc': {f'{prefix}_level': levels_up}
            }
        )

        await self.level_up_message(message, leveling_user, reward_text)

    async def process_message(self, message: discord.Message):
        author = message.author
        guild = message.guild

        leveling_user = db.get_leveling_user(guild.id, author.id)
        leveling_data = db.get_leveling_data(guild.id, {'leveling_routes': 1, 'honours_channels': 1})
        leveling_routes = leveling_data['leveling_routes']

        # level parliamentary route
        if not self.pp_cooldown.user_cooldown(guild.id, author.id):
            self.pp_cooldown.add_user(guild.id, author.id)

            # adds parliamentary role to user if it's their first parliamentary points gain
            if leveling_user['pp'] == 0:
                p_role = leveling_routes['parliamentary'][0]
                await get_leveling_role(guild, p_role['name'], author)
                db.leveling_users.update_one({
                    'guild_id': guild.id,
                    'user_id': author.id},
                    {
                        '$set': {'p_role': p_role['name']}
                    }
                )

                leveling_user['p_role'] = p_role['name']

            pp_add = randint(15, 25)

            # check for active boost and add to pp_add if active
            boost_multiplier = get_user_boost_multiplier(message.author)
            if boost_multiplier > 0:
                pp_add = round(pp_add * (1 + boost_multiplier))

            leveling_user['pp'] += pp_add
            db.add_points('parliamentary', guild.id, author.id, pp_add)

            await self.level_up('parliamentary', leveling_user, message)

        # level honours route
        if message.channel.id in leveling_data['honours_channels'] and not self.hp_cooldown.user_cooldown(guild.id, author.id):
            self.hp_cooldown.add_user(guild.id, author.id)

            # adds honours role to user if it's their first honours points gain
            if leveling_user['hp'] == 0:
                h_role = leveling_routes['honours'][0]
                await get_leveling_role(guild, h_role['name'], author)
                db.leveling_users.update_one({
                    'guild_id': guild.id,
                    'user_id': author.id},
                    {
                        '$set': {'h_role': h_role['name']}
                    }
                )

                leveling_user['h_role'] = h_role['name']

            hp_add = randint(7, 12)
            leveling_user['hp'] += hp_add
            db.add_points('honours', guild.id, author.id, hp_add)

            await self.level_up('honours', leveling_user, message)


def get_user_rank(guild_id, branch: str, leveling_user: dict) -> int:
    points_switch = {'p': 'pp', 'h': 'hp', 'r': 'reputation'}
    points = points_switch.get(branch[0])
    if points not in leveling_user:
        leveling_user[points] = 0

    sorted_users = [u for u in db.leveling_users.find({
        'guild_id': guild_id,
        points: {'$gt': leveling_user[points] - 0.1}
    }).sort(points, -1)]

    return sorted_users.index(leveling_user) + 1


def calc_levels_up(branch: Union[Branch, str], leveling_user: dict) -> int:
    user_levels = leveling_user[f'{branch[0]}_level']
    user_points = leveling_user[f'{branch[0]}p']

    total_points = 0
    total_levels_up = 0
    while total_points <= user_points:
        next_level = user_levels + total_levels_up + 1
        # total pp needed to gain the next level
        total_points = round(5 / 6 * next_level * (2 * next_level * next_level + 27 * next_level + 91))

        total_levels_up += 1

    return total_levels_up - 1


async def user_role_level(branch: str, leveling_user: dict) -> int:
    """Return negative number if user needs to go up role(s) otherwise returns positive number of users role level."""

    prefix = branch[0]

    user_level = leveling_user[f'{prefix}_level']
    user_role_name = leveling_user[f'{prefix}_role']

    leveling_data = db.get_leveling_data(leveling_user['guild_id'], {'leveling_routes': 1})
    leveling_routes = leveling_data['leveling_routes']
    all_roles = leveling_routes[branch]

    user_role = next(filter(lambda role: role['name'] == user_role_name, all_roles), None)
    if not user_role:
        # return 0 if user's current role isn't listen in the branch
        return 0

    role_index = all_roles.index(user_role)

    # + 1 includes current role
    up_to_current_role = all_roles[:role_index + 1]

    # how many levels to reach current user role
    current_level_total = 5 * len(up_to_current_role)

    # how many levels to reach previous user role
    previous_level_total = 5 * len(up_to_current_role[:-1])

    # if user is on last role user level - how many levels it took to reach previous role
    # or if current level total is bigger than user level
    if len(all_roles) == role_index + 1 or current_level_total > user_level:
        return int(user_level - previous_level_total)

    # if current level total equals user level return current roles max level
    if current_level_total == user_level:
        return 5

    # if current level total is smaller than user level, user needs to level up
    if current_level_total < user_level:
        # calculates how many roles user goes up
        roles_up = 0
        # loop through roles above current user role
        for _ in all_roles[role_index + 1:]:
            if current_level_total < user_level:
                roles_up += 1
                current_level_total += 5

        return -roles_up


def percent_till_next_level(branch: str, leveling_user: dict) -> float:
    prefix = branch[0]

    user_points = leveling_user[f'{prefix}p']
    user_level = leveling_user[f'{prefix}_level']

    # points needed to gain next level from beginning of user level
    points_to_level_up = (5 * (user_level ** 2) + 50 * user_level + 100)

    next_level = user_level + 1
    # total points needed to gain next level
    total_points_to_next_level = round(5 / 6 * next_level * (2 * next_level * next_level + 27 * next_level + 91))
    points_needed = total_points_to_next_level - int(user_points)

    percent = 100 - int((points_needed * 100) / points_to_level_up)

    # return 99.9 when int rounds to 100, but user hasn't leveled up yet
    if percent == 100 and points_needed != 0:
        return 99.9

    return percent


def setup(bot):
    bot.add_cog(Leveling(bot))
