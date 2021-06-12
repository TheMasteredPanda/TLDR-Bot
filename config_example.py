import collections

BOT_TOKEN = ""
PREFIX = ">>"
EMBED_COLOUR = 0x00A6AD
MONGODB_URL = "mongodb://10.171.63.66:27017"
DEV_IDS = []

MAIN_SERVER = 0

# for daily debate reminder
MOD_ROLE_ID = 0

# Error server and channel where to send error messages
ERROR_SERVER = 0
ERROR_CHANNEL = 0
WEB_API_URL = ""

# for google drive integration
# path to given credentials for service account
SERVICE_ACCOUNT_FILE = ""
DRIVE_PARENT_FOLDER_ID = ""

# clearance levels
CLEARANCE = collections.OrderedDict(
    {
        "User": lambda *a: True,
        "Mod": lambda member: member.guild_permissions.manage_messages,
        "Admin": lambda member: member.guild_permissions.administrator,
        "Dev": lambda member: member.id in DEV_IDS,
    }
)

# for when the bot cant dm the user
BOT_CHANNEL_ID = 0

# For the time command https://www.geonames.org/
GEONAMES_USERNAME = ""
