import flask
import patreon
import config
from modules import database, pubsub

db = database.Connection()
flask_app = flask.Flask(__name__)


@flask_app.route('/link_patreon_uk', methods=['get'])
def index_uk():
    return flask.redirect(config.Oauth_uk.patreon_login_url)

@flask_app.route('/link_patreon_us', methods=['get'])
def index_us():
    return flask.redirect(config.Oauth_us.patreon_login_url)

@flask_app.route('/link_patreon_eu', methods=['get'])
def index_eu():
    return flask.redirect(config.Oauth_eu.patreon_login_url)


def get_data(account):
    get_oauth = {
        'UK': config.Oauth_uk,
        'US': config.Oauth_us,
        'EU': config.Oauth_eu
    }
    Oauth = get_oauth[account]

    oauth_client = patreon.OAuth(Oauth.client_id, Oauth.client_secret)
    tokens = oauth_client.get_tokens(flask.request.args.get('code'), Oauth.redirect_uri)
    access_token = tokens['access_token']

    api_client = patreon.API(access_token)
    user_response = api_client.fetch_user()
    user = user_response.data()
    patreon_id = user.id()
    discord_id = user.attribute('discord_id')

    if discord_id is None:
        return 'It seems that you havent connected your patreon account with discord, please do so at https://www.patreon.com/settings/apps and try again in a few minutes.\n' \
               'If it doesn\'t work in 10 minutes, please contact Hattyot or one of the moderators', None, None

    pledges = user.relationship('pledges')
    pledge = pledges[0] if pledges and len(pledges) > 0 else None

    if pledge is None or pledge['attributes']['declined_since'] is not None:
        return f'It seems like you don\'t have any active patreon pledges to TLDR {account} on this account, if you believe this is a mistake, please contact Hattyot or one of the moderators', None, None

    return patreon_id, discord_id, pledge


@flask_app.route('/patreon_uk', methods=['get'])
def login_uk():
    patreon_id, discord_id, pledges = get_data('UK')

    # Returns the error message from get_data if there is one
    if pledges is None:
        return patreon_id

    publisher = pubsub.Publisher(db.pubsub, 'patreon_link')
    publisher.push({'patreon_id': patreon_id, 'user_id': discord_id, 'pledges': pledges, 'account': 'UK'})

    # Gets guild id
    doc = db.pubsub.find_one({'discord_id': int(discord_id)})
    guild_id = doc['guild_id']

    return flask.redirect(f'https://discord.com/channels/{guild_id}')


@flask_app.route('/patreon_us', methods=['get'])
def login_us():
    patreon_id, discord_id, pledges = get_data('US')

    # Returns the error message from get_data if there is one
    if pledges is None:
        return patreon_id

    publisher = pubsub.Publisher(db.pubsub, 'patreon_link')
    publisher.push({'patreon_id': patreon_id, 'user_id': discord_id, 'pledges': pledges, 'account': 'US'})

    # Gets guild id
    doc = db.pubsub.find_one({'discord_id': int(discord_id)})
    guild_id = doc['guild_id']

    return flask.redirect(f'https://discord.com/channels/{guild_id}')


@flask_app.route('/patreon_eu', methods=['get'])
def login_eu():
    patreon_id, discord_id, pledges = get_data('EU')

    # Returns the error message from get_data if there is one
    if pledges is None:
        return patreon_id

    publisher = pubsub.Publisher(db.pubsub, 'patreon_link')
    publisher.push({'patreon_id': patreon_id, 'discord_id': discord_id, 'pledges': pledges, 'account': 'EU'})

    # Gets guild id
    doc = db.pubsub.find_one({'discord_id': int(discord_id)})
    guild_id = doc['guild_id']

    return flask.redirect(f'https://discord.com/channels/{guild_id}')


flask_app.run(host='0.0.0.0')
