import pymongo
import config


class Connection:
    __slots__ = ['mongo_client', 'db', 'leveling_data', 'leveling_users', 'boosts', 'timers', 'tickets',
                 'commands', 'daily_debates', 'watchlist', 'watchlist_data', 'tags', 'reaction_menus',
                 'outside_emotes', 'channels']

    def __init__(self):
        self.mongo_client = pymongo.MongoClient(config.MONGODB_URL)
        self.db = self.mongo_client['TLDR']
        self.leveling_data = self.db['leveling_data']
        self.leveling_users = self.db['leveling_users']
        self.boosts = self.db['boosts']
        self.timers = self.db['timers']
        self.tickets = self.db['tickets']
        self.tags = self.db['tags']
        self.commands = self.db['commands']
        self.watchlist = self.db['watchlist']
        self.watchlist_data = self.db['watchlist_data']
        self.daily_debates = self.db['daily_debates']
        self.reaction_menus = self.db['reaction_menus']
        self.outside_emotes = self.db['outside_emotes']
        self.channels = self.db['channels']


schemas = {
    'leveling_user': {
        'pp': 0,  # Participation points or parliamentary points
        'p_level': 0,  # parliamentary level
        'hp': 0,  # honours points
        'h_level': 0,  # honours level
        'p_role': 'Citizen',  # parliamentary role
        'h_role': None,  # honours role
        'settings': {
            '@_me': False  # setting to check if user wants to be @'d when they level up
        },
        'reputation': 0,
        'rep_timer': 0,
        'last_rep': 0
    },
    'leveling_data': {
        'guild_id': 0,
        'level_up_channel': 0,
        'leveling_routes': {
            'parliamentary': [
                ('Citizen', 5, []),  # 0: name of role 1: how many levels in role 2: rewards list sent to user
            ],
            'honours': [
                ('Public Servant', 5, [])
            ]
        },
        'honours_channels': [],
    },
    'watchlist_data': {
        'guild_id': 0,
        'channel_id': 0
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
