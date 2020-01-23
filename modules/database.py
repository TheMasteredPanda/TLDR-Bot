import pymongo
from config import MONGODB_URL
from modules import cache


class Connection:
    def __init__(self):
        self.mongo_client = pymongo.MongoClient(MONGODB_URL)
        self.db = self.mongo_client['TLDR']
        self.server_options = self.db['server_options']

    def get_server_options(self, guild_id):
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
    def get_prefix(self, guild_id):
        doc = self.get_server_options(guild_id)
        return doc['prefix']

    @cache.cache()
    def get_embed_colour(self, guild_id):
        doc = self.get_server_options(guild_id)
        return doc['embed_colour']
