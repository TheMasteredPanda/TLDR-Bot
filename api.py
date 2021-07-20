import config

from modules import database
from slack_bolt.app.async_app import AsyncWebClient
from sanic import Sanic, HTTPResponse
from sanic.views import HTTPMethodView

db = database.get_connection()
app = Sanic("TLDR-Bot-api")


class SlackOauth(HTTPMethodView):
    async def get(self, code):
        if not code:
            return HTTPResponse()

        client = AsyncWebClient()
        try:
            response = await client.oauth_v2_access(
                client_id=config.SLACK_CLIENT_ID,
                client_secret=config.SLACK_CLIENT_SECRET,
                code=code
            )
        except:
            return HTTPResponse()

        team_id = response['team']['id']
        access_token = response['access_token']
        db.slack_bridge.update_one(
            {'guild_id': config.MAIN_SERVER},
            {'$set': {'tokens': {team_id: access_token}}}
        )
        return HTTPResponse()


app.add_route(SlackOauth.as_view(), '/slack/oauth')
app.run(host='0.0.0.0', port=80)
