import flask
from cogs.utils import Oauth
from modules import database

db = database.Connection()
flask_app = flask.Flask(__name__)


@flask_app.route('/', methods=['get'])
def index():
    return flask.redirect(Oauth.discord_login_url)


@flask_app.route('/login', methods=['get'])
def login():
    # Get user data
    code = flask.request.args.get('code')
    access_token = Oauth.get_access_token(code)
    user_json = Oauth.get_user_json(access_token)

    # Store email



flask_app.run(debug=True, host='0.0.0.0')