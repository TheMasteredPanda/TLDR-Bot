from __future__ import annotations

import math
import discord
import time
import config

from pymongo.collection import Collection
from typing import Tuple, Union
from datetime import datetime
from modules import database
from modules.utils import get_guild_role

db = database.get_connection()

# TODO: bring back __setattr__ system

# TODO: do this sort of thing for commands too


class DatabaseList(list):
    """Special list which co-opts the append and remove method, so the same values can be updated in the database."""
    def __init__(self, collection: Collection, query_filter: dict, key: str, *args):
        self.collection = collection
        self.query_filter = query_filter
        self.key = key

        super().__init__()
        self.extend(list(args))

    def __delitem__(self, index: int):
        raise Exception('Del operation not allowed on DatabaseList')

    def __setitem__(self, index: int, value):
        self.collection.update_one(
            self.query_filter,
            {'$set': {f'{self.key}.{index}': value if type(value) != LevelingRole else value.values()}}
        )
        super()[index] = value

    def insert(self, index: int, value):
        raise Exception('Insert operation not allowed on DatabaseList')

    def append(self, item) -> None:
        """Method that pushes item to list and database list."""
        self.collection.update_one(
            self.query_filter,
            {'$push': {self.key: item if type(item) != LevelingRole else item.values()}}
        )
        super().append(item)

    def remove(self, item) -> None:
        """Method that removes item from list and database list."""
        self.collection.update_one(
            self.query_filter,
            {'$pull': {self.key: item if type(item) != LevelingRole else item.values()}}
        )
        super().remove(item)


class Boost:
    """Class for a boost"""
    def __init__(self, leveling_member: LevelingMember, boost_type: str, boost: dict):
        self.leveling_member = leveling_member
        self.boost_type = boost_type
        self.multiplier = boost.get('multiplier', 0)
        self.expires = boost.get('expires', 0)

    def has_expired(self):
        """
        Check if boost has expired
        :return: True if boost has expired
        """
        return round(time.time()) > self.expires

    def remove(self):
        """Delete boost from the database."""
        db.leveling_users.update_one(
            {'guild_id': self.leveling_member.guild.id, 'user_id': self.leveling_member.id},
            {'$unset': {f'boosts.{self.boost_type}': 1}}
        )

    def __setattr__(self, key, value):
        """For some variables, changing their value will allo edit the entry in the database."""
        if key in ['multiplier', 'expires'] and key in self.__dict__ and self.__dict__[key] != value:
            db.leveling_users.update_one(
                {'guild_id': self.leveling_member.guild.id, 'user_id': self.leveling_member.id},
                {'$set': {f'boosts.{self.boost_type}.{key}': value}}
            )
        self.__dict__[key] = value


class LevelingUserBoosts:
    """Class for storing leveling user boosts"""
    def __init__(self, leveling_member: LevelingMember, boosts: dict):
        self.leveling_member = leveling_member
        self.rep = Boost(leveling_member, 'rep', boosts.get('rep', {}))
        self.daily_debate = Boost(leveling_member, 'daily_debate', boosts.get('daily_debate', {}))

    def __iter__(self):
        """
        Iter over list of boosts, where boost is included if it has an actual expires time.
        If i a boost has an expires time of 0, it means it isn't set in the database
        """
        yield from [*filter(lambda boost: boost.expires > 0 and not boost.has_expired(), [self.rep, self.daily_debate])]

    def __bool__(self):
        """
        :return: True if there are any active boosts
        """
        return bool([*filter(lambda boost: boost.expires > 0, [self.rep, self.daily_debate])])

    def get_multiplier(self):
        return 1 + sum(boost.multiplier for boost in self)

    def __setattr__(self, key, value):
        """For some variables, changing their value will allo edit the entry in the database."""
        if key in ['rep', 'daily_debate'] and key in self.__dict__ and self.__dict__[key] != value:
            db.leveling_users.update_one(
                {'guild_id': self.leveling_member.guild.id, 'user_id': self.leveling_member.id},
                {'$set': {f'boosts.{key}': value}}
            )

        self.__dict__[key] = value


class LevelingUserSettings:
    """Class for storing leveling user settings"""
    def __init__(self, leveling_member: LevelingMember, settings: dict):
        self.member = leveling_member
        self.at_me = settings.get('@_me', False)

    def toggle_at_me(self):
        """Toggle @_me setting"""
        self.at_me = not bool(self.at_me)
        db.leveling_users.update_one(
            {'guild_id': self.member.guild.id, 'user_id': self.member.id},
            {'$set': {'settings': {'@_me': self.at_me}}}
        )


class LevelingUserBranch:
    """Class for storing leveling user branch data"""
    def __init__(self, leveling_member: LevelingMember, branch: str, points: int, level: int, role: str):
        self.leveling_member = leveling_member
        self.branch = branch
        self.points = points
        self.level = level
        self.role = role

    def __setattr__(self, key, value):
        """For some variables, changing their value will allo edit the entry in the database."""
        if key in ['points', 'level', 'role'] and key in self.__dict__ and self.__dict__[key] != value:
            key_switch = {
                'points': f'{self.branch[0]}p',
                'level': f'{self.branch[0]}_level',
                'role': f'{self.branch[0]}_role'
            }
            db.leveling_users.update_one(
                {'guild_id': self.leveling_member.guild.id, 'user_id': self.leveling_member.id},
                {'$set': {key_switch.get(key): value}}
            )

        self.__dict__[key] = value


class LevelingUser:
    """Class for storing leveling user data"""
    def __init__(self, leveling_member: LevelingMember, leveling_user_data: dict):
        self.leveling_member = leveling_member

        self.parliamentary = LevelingUserBranch(
            leveling_member,
            'parliamentary',
            leveling_user_data['pp'],
            leveling_user_data['p_level'],
            leveling_user_data['p_role']
        )

        self.honours = LevelingUserBranch(
            leveling_member,
            'honours',
            leveling_user_data['hp'],
            leveling_user_data['h_level'],
            leveling_user_data['h_role']
        )

        self.settings = LevelingUserSettings(leveling_member, leveling_user_data.get('settings', {}))

        # this is needed in some places like the leaderboard command
        self.reputation = LevelingUserBranch(
            leveling_member,
            'reputation',
            leveling_user_data.get('rp', 0),
            0,
            ''
        )

        self.rp = leveling_user_data.get('rp', 0)
        self.last_rep = leveling_user_data.get('last_rep', 0)
        self.rep_timer = leveling_user_data.get('rep_timer', 0)

        self.boosts = LevelingUserBoosts(leveling_member, leveling_user_data.get('boosts', {}))

    @property
    def rep_timer_expired(self) -> bool:
        """:return: True if rep timer has expired"""
        return round(time.time()) > self.rep_timer

    @property
    def rep_time_left(self):
        """:return: Seconds left until timer expires"""
        return self.rep_timer - round(time.time())

    def __setattr__(self, key, value):
        """For some variables, changing their value will allo edit the entry in the database."""
        if key in ['rp', 'rep_timer', 'last_rep'] and key in self.__dict__ and self.__dict__[key] != value:
            db.leveling_users.update_one(
                {'guild_id': self.leveling_member.guild.id, 'user_id': self.leveling_member.id},
                {'$set': {key: value}}
            )

        self.__dict__[key] = value


class LevelingRole:
    """Class for leveling roles"""
    def __init__(self, guild: discord.Guild, branch: str, leveling_role: dict):
        self.guild = guild
        self.branch = branch
        self.name = leveling_role.get('name', '')
        self.perks = DatabaseList(
            db.leveling_data,
            {'guild_id': self.guild.id, f'leveling_routes.{self.branch}': {'$elemMatch': {'name': self.name}}},
            f'leveling_routes.{self.name}.$.perks',
            *leveling_role.get('perks', [])
        )

    def values(self):
        return {
            'name': self.name,
            'perks': self.perks
        }

    async def get_guild_role(self) -> discord.Role:
        """
        Get guild's role
        :return: discord.Role
        """
        # TODO: maybe cache this value?
        role = await get_guild_role(self.guild, self.name)
        # if role doesnt exist, create it
        if role is None:
            role = await self.guild.create_role(name=self.name)


        return role

    def __setattr__(self, key, value):
        """For some variables, changing their value will allo edit the entry in the database."""
        if key in ['name', 'perks'] and key in self.__dict__ and self.__dict__[key] != value:
            db.leveling_data.update_one({
                'guild_id': self.guild.id,
                f'leveling_routes.{self.branch}': {'$elemMatch': {'name': self.name}}},
                {f'$set': {f'leveling_routes.{self.name}.$.{key}': value}}
            )

        # special case for perks
        if key == 'perks' and 'perks' in self.__dict__:
            self.__dict__[key].list = value
            return

        self.__dict__[key] = value


class LevelingRoute:
    """Class for leveling route data."""
    def __init__(self, guild: discord.Guild, name: str, roles: list):
        self.guild = guild
        self.name = name
        self.roles = DatabaseList(
            db.leveling_data,
            {'guild_id': self.guild.id},
            f'leveling_routes.{self.name}',
            *[LevelingRole(guild, name, role) for role in roles]
        )

    def find_role(self, role_name: str) -> Union[LevelingRole, None]:
        """
        Find a role in the leveling route.
        :param role_name: name of the needed role
        :return: leveling role from this leveling route, if role by name exists
        """
        return next(filter(lambda role: role.name.lower() == role_name.lower(), self.roles), None)

    def __iter__(self):
        """Iterator magic method to loop over route's roles."""
        yield from self.roles


class LevelingRoutes:
    """Class for the leveling routes in a guild."""
    def __init__(self, guild: discord.Guild, leveling_routes: dict):
        self.guild = guild
        self.parliamentary = LevelingRoute(guild, 'parliamentary', leveling_routes.get('parliamentary', []))
        self.honours = LevelingRoute(guild, 'honours', leveling_routes.get('honours', []))
        self.reputation = LevelingRoute(guild, 'reputation', [])  # need in some places

    def get_leveling_role(self, role_name: str) -> LevelingRole:
        """
        Get leveling role of a branch
        :param role_name: the role name of the needed role
        :return: leveling role
        """
        for branch in self:
            role = branch.find_role(role_name)
            if role:
                return role

    def __iter__(self):
        """Iter magic method so when an instance of this class is looped over, it'll loop over the list of available branches"""
        yield from [self.parliamentary, self.honours]


class LevelingData:
    """Class for storing leveling data for a guild."""
    def __init__(self, guild: discord.Guild, leveling_data: dict):
        self.guild = guild
        self.level_up_channel = leveling_data.get('level_up_channel', 0)
        self.leveling_routes = LevelingRoutes(guild, leveling_data.get('leveling_routes', {}))
        self.honours_channels = DatabaseList(
            db.leveling_data,
            {'guild_id': self.guild.id},
            f'honours_channels',
            *leveling_data.get('honours_channels', [])
        )
        self.automember = leveling_data.get('automember', False)

    def toggle_automember(self):
        """Toggle automember setting"""
        self.automember = not bool(self.automember)
        db.leveling_data.update_one(
            {'guild_id': self.guild.id},
            {'$set': {'automember': self.automember}}
        )

    def __setattr__(self, key, value):
        """For some variables, changing their value will allo edit the entry in the database."""
        if key in ['level_up_channel', 'honours_channels'] and key in self.__dict__ and self.__dict__[key] != value:
            db.leveling_data.update_one(
                {'guild_id': self.guild.id},
                {'$set': {key: value}}
            )

        # special case for honours_channels
        if key == 'honours_channels' and 'honours_channels' in self.__dict__:
            self.__dict__[key].list = value
            return

        self.__dict__[key] = value


class LevelingGuild(LevelingData):
    """The leveling class for guilds."""
    # TODO: remove user function
    def __init__(self, bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.id = guild.id

        self.members = []

        leveling_data = db.get_leveling_data(guild.id)
        super().__init__(guild, leveling_data)

    def get_leveling_role(self, role_name: str) -> LevelingRole:
        """
        :param role_name: the name that the role will be searched by
        :return: Leveling role with the name role_name
        """
        return self.leveling_routes.get_leveling_role(role_name)

    def get_leveling_route(self, name: str) -> LevelingRoute:
        """
        :param name: name of the branch
        :return: either parliamentary or honours leveling route
        """
        for branch in self.leveling_routes:
            if branch.name[0] == name[0]:
                return branch

    async def get_member(self, member_id: int) -> Union[LevelingMember, None]:
        """
        Looks for member in self.members, if member isn't found, will look for member in guild and add it to self.members
        if member isnt in guild, will return None

        :param member_id: id of the member that will be returned
        :return: Leveling member if member is found, otherwise None
        """
        # try to get member from list of members
        member = next(filter(lambda m: m.id == member_id, self.members), None)
        if member is None:
            # try to get member from cache
            member = self.guild.get_member(member_id)
            if member is None:
                # Try to fetch member with an api request
                try:
                    member = await self.guild.fetch_member(member_id)
                except Exception:
                    # TODO: remove user
                    return None

            member = self.add_member(member)

        return member

    def add_member(self, member: discord.Member) -> LevelingMember:
        """
        Converts member to leveling member a member to self.members
        :param member: discord.Member that will be added
        :return: converted leveling member
        """
        leveling_member = LevelingMember(self.bot, self, member)
        self.members.append(leveling_member)
        return leveling_member

    def get_level_up_channel(self, message: discord.Message):
        """
        :param message: discord.Message that will be defaulted to if needed
        :return: Level up channel if one is set, otherwise message.channel
        """
        # get channel where to send level up message
        channel = self.bot.get_channel(self.level_up_channel)
        # if channel is none default to message channel
        if channel is None:
            channel = message.channel

        return channel


class LevelingMember(LevelingUser):
    """The leveling class for members."""
    def __init__(self, bot, guild: LevelingGuild, member: discord.Member):
        self.bot = bot
        self.guild = guild

        self.id = member.id
        self.roles = member.roles
        self.member = member

        # add leveling user data to this class
        leveling_user_data = db.get_leveling_user(member.guild.id, member.id)
        super().__init__(self, leveling_user_data)

    async def add_points(self, branch_name: str, amount: int):
        """
        Add points to a branch for member
        :param branch_name: branch where to add points
        :param amount: how many points to add
        """
        branch = self.guild.get_leveling_route(branch_name)
        user_branch = self.parliamentary if branch.name == 'parliamentary' else self.honours
        # if user is receiving their first points give them the first role
        if user_branch.points == 0:
            user_branch.role = branch.roles[0].name

        # increase amount if user has boost
        boost_multiplier = self.boosts.get_multiplier()
        amount = round(amount * boost_multiplier)

        user_branch.points += amount

    async def add_role(self, role: LevelingRole) -> discord.Role:
        # get discord.Role role
        guild_role = await role.get_guild_role()
        # give role to user
        await self.member.add_roles(guild_role)
        return guild_role

    async def level_up(self, branch: LevelingRoute) -> Tuple[discord.Role, int, int]:
        """
        Level up and rank up member
        :param branch: branch which will be used
        :return: current_role, levels_up (how many levels user went up), roles_up (how many roles user went up)
        """
        user_branch = self.parliamentary if branch.name == 'parliamentary' else self.honours
        levels_up = self.calculate_levels_up(user_branch)
        user_branch.level += levels_up

        # Checks if user has current role
        current_role = branch.find_role(user_branch.role)
        current_guild_role = await current_role.get_guild_role()
        if current_guild_role not in self.member.roles:
            await self.member.add_roles(current_guild_role)

        # get user role level
        role_level = self.user_role_level(user_branch)

        # user needs to go up a role
        if role_level < 0:
            role_index = branch.roles.index(current_role)
            new_role = branch.roles[-1] if len(branch.roles) - 1 < role_index + abs(role_level) else branch.roles[role_index + abs(role_level)]

            user_branch.role = new_role.name
            await self.add_role(new_role)

            await self.notify_perks(new_role)

            current_role = new_role

        return current_role, levels_up, abs(role_level)

    async def level_up_message(self, message: discord.Message, user_branch: LevelingUserBranch, current_role: discord.Role, roles_up: int):
        """
        Send message about user leveling up
        :param message: message which caused the level up, needed for get_level_up_channel()
        :param user_branch: branch which will be used
        :param current_role: the role the member has / ranked up to
        :param roles_up: how many roles user went up
        """
        role_level = self.user_role_level(user_branch)
        if roles_up:
            reward_text = f'Congrats **{self.member.name}** you\'ve advanced to a level **{role_level}** <@&{current_role.id}>'
        else:
            reward_text = f'Congrats **{self.member.name}** you\'ve become a level **{role_level}** <@&{current_role.id}>'

        reward_text += ' due to your contributions!' if user_branch.branch == 'honours' else ''

        # send level up message
        embed = discord.Embed(colour=config.EMBED_COLOUR, timestamp=datetime.now())
        embed.description = reward_text
        embed.set_author(name='Level Up!', icon_url=self.guild.guild.icon_url)
        embed.set_footer(text=str(self.member), icon_url=self.member.avatar_url)

        # @ user if they have @_me enabled
        content = f'<@{self.id}>' if self.settings.at_me else ''

        # get channel where to send level up message
        channel = self.guild.get_level_up_channel(message)
        await channel.send(embed=embed, content=content)

    def user_role_level(self, user_branch: LevelingUserBranch) -> int:
        """
        Get users role level
        :param user_branch: branch which will be used
        :return: negative number if user needs to go up role(s) otherwise returns positive number of users role level
        """
        branch = self.guild.get_leveling_route(user_branch.branch)

        user_role = branch.find_role(user_branch.role)
        if not user_role:
            return 0  # return 0 if user's current role isn't listen in the branch

        all_roles = branch.roles
        role_index = all_roles.index(user_role)

        # + 1 includes current role
        up_to_current_role = all_roles[:role_index + 1]

        # how many levels to reach current user role
        current_level_total = 5 * len(up_to_current_role)

        # how many levels to reach previous user role
        previous_level_total = 5 * len(up_to_current_role[:-1])

        # if user is on last role user level - how many levels it took to reach previous role
        # or if current level total is bigger than user level
        if len(all_roles) == role_index + 1 or current_level_total > user_branch.level:
            return int(user_branch.level - previous_level_total)

        # if current level total equals user level return current roles max level
        if current_level_total == user_branch.level:
            return 5

        # if current level total is smaller than user level, user needs to rank up
        if current_level_total < user_branch.level:
            # calculates how many roles user goes up
            roles_up = 0
            # loop through roles above current user role
            for _ in all_roles[role_index + 1:]:
                if current_level_total < user_branch.level:
                    roles_up += 1
                    current_level_total += 5

            return -roles_up

    @staticmethod
    def calculate_levels_up(user_branch: LevelingUserBranch) -> int:
        """
        Calculate how many levels user needs to go up from current standing.
        :param user_branch: branch which will be used
        :return: how many levels user needs to go up by
        """
        user_levels = user_branch.level
        user_points = user_branch.points

        total_points = 0
        total_levels_up = 0
        while total_points <= user_points:
            next_level = user_levels + total_levels_up + 1
            # total points needed to gain the next level
            total_points = round(5 / 6 * next_level * (2 * next_level * next_level + 27 * next_level + 91))

            total_levels_up += 1

        return total_levels_up - 1

    async def notify_perks(self, role: LevelingRole):
        """
        Sends user info about perks if role has them
        :param role: leveling role
        """
        if role.perks:
            perks_str = "\n • ".join(role.perks)
            perks_message = f'**Congrats** again on advancing to **{role.name}**!' \
                            f'\nThis role also gives you new **perks:**' \
                            f'\n • {perks_str}' \
                            f'\n\nFor more info on these perks ask one of the TLDR server mods'

            embed = discord.Embed(colour=config.EMBED_COLOUR, timestamp=datetime.now())
            embed.description = perks_message
            embed.set_author(name='New Perks!', icon_url=self.guild.guild.icon_url)
            embed.set_footer(text=str(self.member), icon_url=self.member.avatar_url)

            try:
                await self.member.send(embed=embed)
            # in case user doesnt allow dms from bot
            except Exception:
                # TODO: maybe send message to bot channel
                pass

    def rank(self, user_branch: LevelingUserBranch) -> int:
        """
        Get members rank in branch
        :param user_branch: branch which will be used
        :return: members rank
        """
        key = f'{user_branch.branch[0]}p'
        sorted_users = [u for u in db.leveling_users.find({
            'guild_id': self.guild.id,
            key: {'$gt': user_branch.points - 0.1}  # 0.1 is subtracted so member will be included
        }).sort(key, -1)]

        return len(sorted_users)

    @staticmethod
    def percent_till_next_level(user_branch: LevelingUserBranch) -> float:
        """
        :param user_branch: branch that will be used
        :return: precent of how close user is to leveling up
        """
        # points needed to gain next level from beginning of user level
        points_to_level_up = (5 * (user_branch.level ** 2) + 50 * user_branch.level + 100)

        next_level = user_branch.level + 1
        # total points needed to gain next level
        total_points_to_next_level = round(5 / 6 * next_level * (2 * next_level * next_level + 27 * next_level + 91))
        points_needed = total_points_to_next_level - int(user_branch.points)

        percent = math.floor((100 - ((points_needed * 100) / points_to_level_up)) * 10) / 10

        return percent


class LevelingSystem:
    """Main handler of the leveling guilds."""
    def __init__(self, bot):
        self.bot = bot
        # list of leveling guilds
        self.guilds = []

    def initialise_guilds(self):
        """Function called in cogs.events.on_ready() to initialise all the guilds and cache them"""
        for guild in self.bot.guilds:
            self.add_guild(guild)

    async def get_member(self, guild_id: int, member_id: int) -> LevelingMember:
        """
        :param guild_id: the id for the guild where to pull the member from
        :param member_id: the id of the member that will be returned
        :return: leveling member with all the leveling data attached
        """
        guild = self.get_guild(guild_id)
        if guild:
            return await guild.get_member(member_id)

    def get_guild(self, guild_id: int) -> LevelingGuild:
        """
        :param guild_id: id of the guild that will be returned
        :return: a guild from self.guild if guild by the id exists, if it doesnt, will return None
        """
        return next(filter(lambda guild: guild.id == guild_id, self.guilds), None)

    def add_guild(self, guild: discord.Guild) -> LevelingGuild:
        """
        :param guild: type discord.Guild guild that will be added to the list of guilds
        :return: Same guild, but converted to leveling guild
        """
        leveling_guild = LevelingGuild(self.bot, guild)
        self.guilds.append(leveling_guild)
        return leveling_guild
