import pymongo
import config
import time
import discord

from bson import ObjectId


class Connection:
    def __init__(self):
        self.mongo_client = pymongo.MongoClient(config.MONGODB_URL)
        self.db = self.mongo_client['TLDR']
        self.leveling_users = self.db['leveling_users']
        self.leveling_data = self.db['leveling_data']
        self.left_leveling_users = self.db['left_leveling_users']
        self.timers = self.db['timers']
        self.commands = self.db['commands']
        self.daily_debates = self.db['daily_debates']
        self.tickets = self.db['tickets']
        self.custom_commands = self.db['custom_commands']
        self.watchlist = self.db['watchlist']

    def get_leveling_user(self, guild_id: int, member_id: int) -> dict:
        leveling_user = self.leveling_users.find_one({
            'guild_id': guild_id,
            'user_id': member_id
        })

        if leveling_user is None:
            # add user to leveling_user collection
            leveling_user = schemas['leveling_user']
            leveling_user['guild_id'] = guild_id
            leveling_user['user_id'] = member_id
            self.leveling_users.insert_one(leveling_user.copy())

        return leveling_user

    def add_points(self, branch: str, guild_id: int, member_id: int, points: int):
        self.leveling_users.update_one({
            'guild_id': guild_id,
            'user_id': member_id},
            {
                '$inc': {f'{branch[0]}p': points}
            }
        )

    def get_leveling_data(self, guild_id: int, fields: dict = None):
        if fields is None:
            fields = {}

        leveling_data = self.leveling_data.find_one({'guild_id': guild_id}, fields)
        if not leveling_data:
            leveling_data = schemas['leveling_data']
            leveling_data['guild_id'] = guild_id
            self.leveling_data.insert_one(leveling_data.copy())

        return leveling_data

    def get_command_data(self, guild_id: int, command_name: str, *, insert: bool = False):
        command_data = self.commands.find_one({'guild_id': guild_id, 'command_name': command_name})
        if command_data is None:
            command_data = {
                'guild_id': guild_id,
                'command_name': command_name,
                'disabled': 0,
                'user_access': {},
                'role_access': {}
            }
            if insert:
                self.commands.insert_one(command_data)

        return command_data

    def get_daily_debates(self, guild_id: int):
        daily_debates = self.daily_debates.find_one({'guild_id': guild_id})
        if not daily_debates:
            daily_debates = schemas['daily_debates']
            daily_debates['guild_id'] = guild_id
            self.daily_debates.insert_one(daily_debates)

        return daily_debates

    def get_automember(self, guild_id: int):
        leveling_data = self.get_leveling_data(guild_id, {'automember': 1})
        if not leveling_data or 'automember' not in leveling_data:
            self.leveling_data.update_one({'guild_id': guild_id}, {'$set': {'automember': False}})
            automember = False
        else:
            automember = leveling_data['automember']

        return automember


schemas = {
    'leveling_user': {
        'pp': 0,  # Participation points or parliamentary points
        'p_level': 0,  # parliamentary level
        'hp': 0,  # honours points
        'h_level': 0,  # honours level
        'p_role': '',  # parliamentary role
        'h_role': None,  # honours role
        'settings': {
            '@_me': False  # setting to check if user wants to be @'d when they level up
        },
        'rp': 0,
        'rep_timer': 0,
        'last_rep': 0,
        'boosts': {
            # 'rep': {
            #     'expires': 0,
            #     'multiplier': 0
            # }
        }
    },
    'leveling_data': {
        'guild_id': 0,
        'level_up_channel': 0,
        'leveling_routes': {
            'parliamentary': [],
            'honours': []
        },
        'honours_channels': [],
    },
    'daily_debates': {
        'guild_id': 0,
        'channel_id': 0,
        'poll_channel_id': 0,
        'role_id': 0,
        'time': 0,
        'topics': []
    }
}
