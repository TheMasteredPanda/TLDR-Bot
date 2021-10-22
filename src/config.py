BOT_TOKEN = "NjcyMDUyNzQ4MzU4Nzc4ODkw.XjF35Q.g_lCmWIaMSH1Sy4ovBwOlmApgqk"
MONGODB_URL = "mongodb://tldradmin:W08L2wk0dldnw2L@tldrcommunity.duckdns.org:27017/TLDR?authSource=admin&w=1"
PREFIX = ">>"
MAIN_SERVER = 524213542635700224
ERROR_SERVER = 524213542635700224
ERROR_CHANNEL = 748622037383381036
WEB_API_URL = "https://tldr-process-images.herokuapp.com/"
SERVICE_ACCOUNT_FILE = "tldr-bot-71b67ba59890.json"
DRIVE_PARENT_FOLDER_ID = "1GGFtzEuSH3hX9aHT5rn-FzOV0rZnpPXP"
BOT_CHANNEL_ID = 697181595890614323
GEONAMES_USERNAME = "tldrbot"
CLEARANCE_SPREADSHEET_ID = "1RBc8wZS_mRKxP5jr8ZgOLadGCUuqKRUikkeLaN4zXyo"
SLACK_APP_TOKEN = "xapp-1-A028L5UBNP4-2289182305941-500e75f8ad7d6e0f2014a87f3a00e097c9d8a7fc5138b8bd327226cf5eb66112"
SLACK_CLIENT_ID = "2242616258578.2292198396786"
SLACK_CLIENT_SECRET = "9f51feb94914b141bfcc81102ab382d4"
SLACK_REDIRECT_DOMAIN = 'tldrcommunity.duckdns.org'
EMBED_COLOUR = 0x00a6ad

MODULES = {
    'google_drive': False,
    'webhooks': True,
    'watchlist': False,
    'timers': False,
    'reaction_menus': False,
    'custom_commands': False,
    'leveling_system': False,
    'invite_logger': False,
    'moderation': False,
    'ukparl_module': False,
    'clearance': False,
    'slack_bridge': False,
    'tasks': False,
    'captcha': False
}

COGS = {
    'admin': False,
    'dev': False,
    'events': True,
    'fun': False,
    'leveling': False,
    'mod': True,
    'privatemessages': False,
    'settings': False,
    'uk_parliament': False,
    'utility': True,
    'captcha': False
}