import discord
import time

from modules import database

db = database.get_connection()


class Case:
    def __init__(self, data: dict):
        self.guild_id: int = data.get('guild_id')
        self.type: str = data.get('type')
        self.reason: str = data.get('reason')
        self.member_id: int = data.get('member_id')
        self.moderator_id: int = data.get('moderator_id')
        self.created_at = data.get('created_at')
        self.extra = data.get('extra', {})


class Cases:
    def __init__(self, bot):
        self.bot = bot

    def get_cases(self, guild_id: int, *, before: int = 0, after: int = 0, **kwargs) -> list[Case]:
        """
        Get cases based on given kwargs.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the guild.
        before: :class:`int`
            Retrieve cases before this unix time.
        after: :class:`int`
            Retrieve cases after this unix time.
        kwargs: :class:`dict`
            Different values to search for cases by.

        Returns
        -------
        :class:`list`
           All the found cases.
        """
        kwargs = {key: value for key, value in kwargs.items() if value}
        query = {'guild_id': guild_id, **kwargs}
        if before:
            query['created_at'] = {'$lt': before}
        if after:
            query['created_at'] = {'$gt': after}

        return [Case(c) for c in db.cases.find(query).sort('created_at', -1)]

    def add_case(self, guild_id: int, case_type: str, reason: str, member: discord.member, moderator: discord.Member, extra: dict = {}) -> Case:
        """
        Adds a case to the database.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the guild.
        case_type: :class:`str`
            Type of the case => mute | ban | kick | warn
        reason: :class:`str`
            Reason behind the case.
        member: :class:`discord.Member`
            Member who had the action taken upon.
        moderator: :class:`discord.Member`
            Member who took action on member.
        extra: :class:`dict`
            Any extra info that needs to be added.

        Returns
        -------
        :class:`dict`
            The case's data.
        """
        case_data = {
            'guild_id': guild_id,
            'member_id': member.id,
            'type': case_type,
            'reason': reason,
            'created_at': time.time(),
            'moderator_id': moderator.id,
            'extra': extra,
        }
        result = db.cases.insert_one(case_data)
        case_data['_id'] = result.inserted_id

        return Case(case_data)


class ModerationSystem:
    def __init__(self, bot):
        self.bot = bot
        self.cases = Cases(bot)
        self.bot.logger.info('Moderation System module has been initiated')
