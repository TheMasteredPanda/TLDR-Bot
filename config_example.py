import os

in_container = os.environ.get('IN_DOCKER', False)
if in_container:
    MONGODB_URL = 'mongodb://db:27017'
else:
    MONGODB_URL = 'mongodb://127.0.0.1:27017'

BOT_TOKEN = ''
PREFIX = ''
EMBED_COLOUR = 0x00a6ad  # TLDR blue
DEV_IDS = []

MAIN_SERVER = 0

# for daily debate reminder
MOD_ROLE_ID = 0

# Error server and channel where to send error messages
ERROR_SERVER = 0
ERROR_CHANNEL = 0
