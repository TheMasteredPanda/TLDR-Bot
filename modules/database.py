import pymongo
import config


class Connection:
    def __init__(self):
        self.mongo_client = pymongo.MongoClient(config.MONGODB_URL)
        self.db = self.mongo_client['TLDR']
        self.levels = self.db['levels']
        self.timers = self.db['timers']
        self.polls = self.db['polls']
        self.tickets = self.db['tickets']


# Default schemas for databases
schemas = {
    'tickets': {
        'guild_id': 0,
        'tickets': {
            # 'channel_id': 'user_id'
        }
    },
    'polls': {
        'guild_id': 0,
        'polls': {
            # 'message id': {
            #     'emote': 0,
            # }
        }
    },
    'timers': {
        'guild_id': 0,
        'timers': []
    },
    'levels': {
        'guild_id': 0,
        'users': {},
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
        'boost': {
            'users': {},
            'roles': {}
        }
    },
    'levels_user': {
        'pp': 0,  # Participation points or parliamentary points
        'p_level': 0,  # parliamentary level
        'hp': 0,  # honours points
        'h_level': 0,  # honours level
        'p_role': 'Citizen',  # parliamentary role
        'h_role': None,  # honours role
        'settings': {
            '@_me': False  # setting to check if user wants to be @'d when they level up
        }
    }
}
