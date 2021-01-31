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
pip3 install -r requirements.txt
```
3. Rename **config_example.py** to **config.py** and add relevant info
4. Install community edition mongodb server. Installation guides: https://docs.mongodb.com/manual/administration/install-community/
5. Run the bot
```
python3 bot.py
```
## Running with docker
```
docker-compose build
docker-compose up -d
```