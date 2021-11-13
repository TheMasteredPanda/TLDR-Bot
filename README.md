# TLDR-Bot
A discord bot for the tldr news network's discord server
## Install Guide
1. Download or clone the bot
```
git clone https://github.com/Hattyot/TLDR-Bot.git
cd TLDR-Bot
```
2. install required modules
```
pip3 install -r src/requirements/requirements-bot.txt
```
3. create a `.env` file in the base folder with these variables filled out with the needed info
```
MONGODB_URL =  # url to the database, if run with docker defaults to the database container url
DATABASE_USERNAME =  # username of the mongodb database
DATABASE_PASSWORD =  # password of the mongodb database

BOT_TOKEN =  # discord bot token
PREFIX =   # prefix used for commands
EMBED_COLOUR =  # hex value used for embeds  e.g. 0xffffff
MAIN_SERVER =  # discord id to the server this bot runs for
ERROR_SERVER =  # discord server id where errors should be posted
ERROR_CHANNEL =  # discord channel id in the error server where errors should be posted
WEB_API_URL =  # url to the image api - https://github.com/Hattyot/image_processor 
BOT_CHANNEL_ID =  # id of the main servers bot channel, where some messages will be posted
GEONAMES_USERNAME =  # username of the geonames account https://www.geonames.org/
MOD_ROLE_ID = # Id of the mod role on the main server

SERVICE_ACCOUNT_FILE =  # path to the google service account file
DRIVE_PARENT_FOLDER_ID =  # google drive folder id where other folders will be created

CLEARANCE_SPREADSHEET_ID =  # id of the clearance spreadsheet file

SLACK_APP_TOKEN =  # app token of the slack app
SLACK_CLIENT_ID =  # slack app client id
SLACK_CLIENT_SECRET =  # slack app client secret
SLACK_REDIRECT_DOMAIN =  # slack redirect domain, eg. discordserver.duckdns.org
```
4. Install community edition mongodb server. Installation guides: https://docs.mongodb.com/manual/administration/install-community/
5. Run the bot
```
python3 bot.py
```

Unneeded modules can be disabled in `src/config.py`

### Google Drive module
1. Enable Google spreadsheet and drive api
2. Create a google service account and download the credentials file
3. Put it in the `src` folder
4. Update the .env file with the relevant info\
`SERVICE_ACCOUNT_FILE, DRIVE_PARENT_FOLDER_ID`

### Clearance Module
1. Enable google drive module
2. Create a spreadsheet like [this example](https://docs.google.com/spreadsheets/d/1_beZntR6_BVNGw8wzHC_FdoNAh64f2JGpoCCZDA0K-8/edit?usp=sharing),
filled out with the info relevant to your server
3. Update the .env file with the relevant info\
`CLEARANCE_SPREADSHEET_ID`

### Slack Module
1. Get a domain
2. Create ssl certificates for the domain via certbot
3. Install requirements for the api
```
pip3 install -r src/requirements/requirements-api.txt
```
3. Update the .env file with the relevant info \
`SLACK_APP_TOKEN, SLACK_CLIENT_ID, SLACK_CLIENT_SECRET, SLACK_REDIRECT_DOMAIN`
4. Run the api
```
python3 api.py
```

## Running with docker
There are 2 docker images to consider, the api one and the bot one. A docker-compose file has also been created for the database.
docker-compose-deploy-bot.yml starts both the api and the bot.
because the docker images are kept updated on docker-hub, you can simply run this command:
```
docker-compose -f docker-compose-deploy-bot.yml up -d
```