import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

if os.path.isfile('.env'):
    load_dotenv('.env')
elif os.path.isfile('../.env'):
    load_dotenv('../.env')


BOT_TOKEN = os.getenv('BOT_TOKEN', '')
PREFIX = os.getenv('PREFIX', '>')
EMBED_COLOUR = int(os.getenv('EMBED_COLOUR', '0x00a6ad'), 16)  # TLDR blue

MONGODB_HOST = os.getenv('MONGODB_HOST', 'localhost')
MONGODB_PORT = os.getenv('MONGODB_PORT', '27017')
DATABASE_USERNAME = os.getenv('DATABASE_USERNAME', 'tldradmin')
DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD', 'rP8P5nw3nOjq7T7LBthBNlB8yKEnmT')
MONGODB_URL = f'mongodb://{quote_plus(DATABASE_USERNAME)}:{quote_plus(DATABASE_PASSWORD)}@{MONGODB_HOST}:{MONGODB_PORT}/'

MAIN_SERVER = int(os.getenv('MAIN_SERVER', 0))

# Error server and channel where to send error messages
ERROR_SERVER = int(os.getenv('ERROR_SERVER', 0))
ERROR_CHANNEL = int(os.getenv('ERROR_CHANNEL', 0))
WEB_API_URL = os.getenv('WEB_API_URL', '')

# for google drive integration
# path to given credentials for drive_service account
SERVICE_ACCOUNT_FILE = os.getenv('SERVICE_ACCOUNT_FILE', '')
DRIVE_PARENT_FOLDER_ID = os.getenv('DRIVE_PARENT_FOLDER_ID', '')

# for when the bot cant dm the user
BOT_CHANNEL_ID = int(os.getenv('BOT_CHANNEL_ID', 0))

# For the time command https://www.geonames.org/
GEONAMES_USERNAME = os.getenv('GEONAMES_USERNAME', '')

CLEARANCE_SPREADSHEET_ID = os.getenv('CLEARANCE_SPREADSHEET_ID', '')

SLACK_APP_TOKEN = os.getenv('SLACK_APP_TOKEN', '')
SLACK_CLIENT_ID = os.getenv('SLACK_CLIENT_ID', '')
SLACK_CLIENT_SECRET = os.getenv('SLACK_CLIENT_SECRET', '')
SLACK_REDIRECT_DOMAIN = os.getenv('SLACK_REDIRECT_DOMAIN', '')

MODULES = {
    'google_drive': True,
    'webhooks': True,
    'watchlist': True,
    'timers': True,
    'reaction_menus': True,
    'custom_commands': True,
    'leveling_system': True,
    'invite_logger': True,
    'moderation': True,
    'ukparl_module': True,
    'clearance': False,
    'channels': True,
    'slack_bridge': False,
    'tasks': True,
    "captcha": True,
}

COGS = {
    'admin': True,
    'dev': True,
    'events': True,
    'fun': True,
    'leveling': True,
    'mod': True,
    'privatemessages': True,
    'settings': True,
    'uk_parliament': True,
    'utility': True,
    'captcha': True,
}