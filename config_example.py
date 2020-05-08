BOT_TOKEN = 'Token of the bot'
MONGODB_URL = 'MongoDB url'
DEV_IDS = [0]
DEFAULT_EMBED_COLOUR = 0x00a6ad
DEFAULT_PREFIX = '>'
MAIN_SERVER = 0
WEB_API_URL = ''
# my web api github: https://github.com/Hattyot/image_processor

class Patreon(object):
    client_id = ''
    client_secret = ''
    scopes = ['identity']
    redirect_uri = ''
    patreon_login_url = f'https://www.patreon.com/oauth2/authorize?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}&scope={"%20".join(scopes)}'
