import pymongo
from config import MONGODB_URL
from modules import cache


class Connection:
    def __init__(self):
        self.mongo_client = pymongo.MongoClient(MONGODB_URL)
        self.db = self.mongo_client['TLDR']
        self.server_options = self.db['server_options']
        self.levels = self.db['levels']

    def _get_server_options(self, guild_id):
        doc = self.server_options.find_one({'guild_id' : guild_id})
        if doc is None:
            new_doc = {
                'guild_id': guild_id,
                'prefix': '>',
                'embed_colour': 0x551a8b
            }
            self.server_options.insert_one(new_doc)
            doc = new_doc

        return doc

    @cache.cache()
    def get_server_options(self, guild_id, option):
        doc = self._get_server_options(guild_id)
        return doc[option]

    def _get_levels(self, guild_id):
        doc = self.levels.find_one({'guild_id': guild_id})
        if doc is None:
            doc = {
                'guild_id': guild_id,
                'users': {
                    'user_id': {
                        'xp': 0,
                        'level': 0
                    }
                }
            }
            self.levels.insert_one(doc)
        return doc

    @cache.cache()
    def get_user_xp(self, guild_id, user_id, value):
        doc = self._get_levels(guild_id)
        return doc['users'][str(user_id)][value]
