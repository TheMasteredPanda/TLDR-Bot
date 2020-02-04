import pymongo
from config import MONGODB_URL
from modules import cache


class Connection:
    def __init__(self):
        self.mongo_client = pymongo.MongoClient(MONGODB_URL)
        self.db = self.mongo_client['TLDR']
        self.levels = self.db['levels']
        self.timers = self.db['timers']

    def _get_levels(self, guild_id):
        doc = self.levels.find_one({'guild_id': guild_id})
        if doc is None:
            doc = {
                'guild_id': guild_id,
                'users': {},
                'level_up_channel': 0,
                'leveling_routes': {
                    'parliamentary': [
                        ('Member', 5),
                        ('Local Councillor', 5)
                    ],
                    'honours': [
                        ('Public Servant', 5)
                    ]
                },
                'honours_channels': []
            }
            self.levels.insert_one(doc)
        return doc

    @cache.cache()
    def get_levels(self, value, guild_id, user_id=None):
        doc = self._get_levels(guild_id)
        if user_id is None:
            return doc[value]
        user_id = str(user_id)
        if user_id not in doc['users']:
            user = {
                'pp': 0,
                'p_level': 0,
                'hp': 0,
                'h_level': 0,
                'p_role': 'Member',
                'h_role': ''
            }
            self.levels.update_one({'guild_id': guild_id}, {'$set': {f'users.{user_id}': user}})
            doc['users'][user_id] = user

        return doc['users'][user_id][value]

    def _get_timers(self, guild_id):
        doc = self.timers.find_one({'guild_id': guild_id})
        if doc is None:
            doc = {
                'guild_id': guild_id,
                'timers': {
                    # '_id': {
                    #     'expires': 0,
                    #     'event': 0,
                    # }
                }
            }
            self.timers.insert_one(doc)
        return doc

    @cache.cache()
    def get_timers(self, guild_id, id):
        doc = self._get_timers(guild_id)
        timers = doc['timers']
        return timers[id] if id in timers else None
