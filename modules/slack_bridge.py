import asyncio
import json
import re
import time

import discord
import discord.utils
import config

from cachetools import TTLCache
from html import unescape
from typing import Optional
from modules import database
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from modules.utils import replace_mentions, embed_message_to_text, async_file_downloader

db = database.get_connection()


# TODO: handle replies
# TODO: handles message deletes
class SlackMessage:
    def __init__(self, data: dict, slack: 'Slack'):
        self.data = data
        self.slack = slack

        event_data = data['event']
        # ignore bot messages
        # TODO: maybe dont ignore
        if 'subtype' in event_data and event_data['subtype'] == 'bot_message':
            return

        self.user_id = event_data['user']
        self.channel_id = event_data['channel']
        self.text = event_data['text']
        self.ts = event_data['ts']
        self.files = [
            {'url': file['url_private_download'], 'name': file['name']}
            for file in event_data['files']
        ] if 'files' in event_data else []

        self.member = self.slack.get_user(self.user_id)
        self.channel = self.slack.get_channel(self.channel_id)

        if self.channel is None:
            self.channel = SlackChannel(self.channel_id, self.slack.bot, self.slack.app)
            slack.channels.append(self.channel)

        self.discord_message_id = event_data['discord_message_id'] if 'discord_message_id' in event_data else None
        self.reactions = {}
        slack.slack_messages[self.ts] = self
        slack.bot.loop.create_task(self.initialise_data())

    async def initialise_data(self):
        if self.member is None:
            self.member = await self.slack.add_user(self.user_id)

        data = db.slack_messages.find_one({'slack_message_id': self.ts})
        if not data:
            db.slack_messages.insert_one({
                'slack_message_id': self.ts,
                'discord_message_id': self.discord_message_id,
                'slack_channel_id': self.channel.id,
                'origin': 'slack',
                'files': self.files,
                'text': self.text,
                'user_id': self.user_id,
                'timestamp': round(time.time())
            })

    def __setattr__(self, key, value):
        if (
            key in ["text", "discord_message_id"]
            and key in self.__dict__
            and self.__dict__[key] != value
        ):
            db.slack_messages.update_one(
                {"slack_message_id": self.ts},
                {"$set": {f"{key}": value}},
            )
        self.__dict__[key] = value

    async def send_to_discord(self, *, edit: bool = False):
        """Function for sending messages from slack to discord via a webhook."""
        if not self.channel.discord_channel:
            return

        if edit and not self.discord_message_id:
            return

        file_urls = [file['url'] for file in self.files]
        download_files = [
            discord.File(file, filename=self.files[i]['name']) for i, file in
            enumerate(
                await async_file_downloader(file_urls, headers={'Authorization': f'Bearer {config.SLACK_BOT_TOKEN}'})
            )
        ]

        text = unescape(self.text)

        discord_message = await self.slack.bot.webhooks.send(
            content=text,
            channel=self.channel.discord_channel,
            username=self.member.name,
            avatar_url=self.member.discord_member.avatar_url if self.member.discord_member else None,
            files=download_files,
            embeds=[],
            edit=self.discord_message_id
        )
        if not edit:
            self.discord_message_id = discord_message.id


class DiscordMessage:
    def __init__(self, message: discord.Message, slack: 'Slack'):
        self.slack = slack

        self.id = message.id
        self.text = message.content
        self.embeds = message.embeds
        self.guild_id = message.guild.id
        self.guild: discord.Guild = slack.bot.get_guild(self.guild_id)
        self.channel_id = message.channel.id
        self.author_is_bot: bool = message.author.bot
        self.author_name = message.author.name
        self.author_avatar = str(message.author.avatar_url)
        self.attachment_urls = [{'url': attachment.url, 'filename': attachment.filename} for attachment in message.attachments]

        self.slack_message_id = None
        self.initialise_data()
        slack.discord_messages[self.id] = self

    def initialise_data(self):
        data = db.slack_messages.find_one({'discord_message_id': self.id})
        if not data:
            db.slack_messages.insert_one({
                'slack_message_id': self.slack_message_id,
                'discord_message_id': self.id,
                'discord_channel_id': self.channel_id,
                'origin': 'discord',
                'timestamp': round(time.time())
            })

    def __setattr__(self, key, value):
        if (
            key in ["text", "slack_message_id"]
            and key in self.__dict__
            and self.__dict__[key] != value
        ):
            db.slack_messages.update_one(
                {"discord_message_id": self.id},
                {"$set": {f"{key}": value}},
            )
        self.__dict__[key] = value

    @staticmethod
    def hyperlink_converter(text):
        """Converts discord hyperlink format to slack format."""
        special_chars_map = {i: '\\' + chr(i) for i in b'()[]{}?*+-|^$\\.&~#'}
        matches = re.findall(r'(\[(.*)]\((.*)\))', text)
        for match in matches:
            url_text = match[1]
            url = match[2]
            text = re.sub(match[0].translate(special_chars_map), f'<{url}|{url_text}>', text)

        return text

    def normalize_text(self, text):
        """Function for normalising discord text to slack standards."""
        text = replace_mentions(self.guild, text)
        text = self.hyperlink_converter(text)
        text = self.text_to_slack_formatting(text)
        return text

    def embed_to_blocks(self) -> tuple[list, str]:
        """Converts discord embeds into slack blocks."""
        text = embed_message_to_text(self.embeds[0])
        text = '>' + text.replace('\n', '\n>')
        text = self.normalize_text(text)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text
                }
            }
        ]
        return blocks, text

    @staticmethod
    def text_to_slack_formatting(text):
        """Converts discord's bold and italic formatting to slack standards."""
        special_chars_map = {i: '\\' + chr(i) for i in b'()[]{}?*+-|^$\\.&~#'}
        italic = re.findall(r'((?=[^*]|^)\*([^*\s][^*]+[^*\s])\*(?=[^*]|$))', text)
        for match in italic:
            match_text = match[1]
            text = re.sub(match[0].translate(special_chars_map), f'_{match_text}_', text)

        bold = re.findall(r'(\*\*([^*\s][^*]+[^*\s])\*\*)', text)
        for match in bold:
            match_text = match[1]
            text = re.sub(match[0].translate(special_chars_map), f'*{match_text}*', text)

        return text

    def to_slack_blocks(self):
        """Main entrypoint for converting discord message to appropriate slack format."""
        kwargs = {'blocks': [], 'text': ''}
        if self.author_is_bot and self.embeds:
            kwargs['blocks'], kwargs['text'] = self.embed_to_blocks()
        else:
            text = replace_mentions(self.guild, self.text)
            text = self.normalize_text(text)
            kwargs['text'] = text
            kwargs['blocks'] = [{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text,
                }
            }]

        return kwargs

    async def send_to_slack(self, edit: bool = False):
        if edit and not self.slack_message_id:
            return

        slack_channel = self.slack.get_channel(discord_id=self.channel_id)
        if not slack_channel:
            return

        kwargs = self.to_slack_blocks()

        if kwargs['blocks'] and kwargs['text']:
            kwargs.update({'channel': slack_channel.id})
            if edit:
                kwargs['ts'] = self.slack_message_id
                func = self.slack.app.client.chat_update
            else:
                kwargs.update({'icon_url': str(self.author_avatar), 'username': self.author_name})
                func = self.slack.app.client.chat_postMessage

            slack_message = await func(**kwargs)
            if not edit:
                self.slack_message_id = slack_message['message']['ts']

        if self.attachment_urls:
            files = await async_file_downloader([a['url'] for a in self.attachment_urls])
            for i, file in enumerate(files):
                await self.slack.app.client.files_upload(
                    file=file,
                    filename=self.attachment_urls[i]['filename'],
                    channels=slack_channel.id,
                    title=f'Uploaded by: {self.author_name}'
                )


# TODO: find out how to keep > from formatting to | thing on the slack side for commands
# TODO: allow slack members to run commands on discord side
class SlackMember:
    def __init__(self, data, bot, app: AsyncApp):
        self.bot = bot
        self.app = app

        self.id = data['id']
        # this value should only be used for the slack member info command
        self.slack_name = data['name']
        # bool used to check if member has a name set
        self.discord_name = False
        self.name = self.id

        self.discord_member = None
        self.initialize_data()
        self.bot.loop.create_task(self.get_discord_member())

    def initialize_data(self):
        """Initialise slack user in the database if needed."""
        data = db.slack_bridge.find_one({'aliases': {'$elemMatch': {'slack_id': self.id}}}, {"aliases.$": 1})
        if not data:
            member_data = {
                'slack_id': self.id,
                'discord_id': None
            }
            db.slack_bridge.update_one(
                {'guild_id': config.MAIN_SERVER},
                {'$push': {'aliases': member_data}}
            )

    async def get_discord_member(self):
        """Gets slack user alias and sets the alias variables if alias has been set."""
        data = db.slack_bridge.find_one({'aliases': {'$elemMatch': {'slack_id': self.id}}}, {"aliases.$": 1})
        discord_id = data['aliases'][0]['discord_id'] if len(data['aliases']) > 0 else None
        discord_name = data['aliases'][0]['discord_name'] if len(data['aliases']) > 0 else None

        if discord_id:
            await self.bot.wait_until_ready()
            main_guild = self.bot.get_guild(config.MAIN_SERVER)
            self.discord_member = discord.utils.get(main_guild.members, id=discord_id)
            if self.discord_member:
                self.name = self.discord_member.name
        elif discord_name:
            self.name = discord_name
            self.discord_name = True

    def set_discord_name(self, name: str):
        """Set the discord name of slack user"""
        self.name = name
        self.discord_name = True

        db.slack_bridge.update_one(
            {'aliases': {'$elemMatch': {'slack_id': self.id}}},
            {'$set': {'aliases.$.discord_name': name}}
        )

    def unset_discord_member(self):
        """Unsets all the alias variables and  updates the database."""
        self.discord_member = None
        self.discord_name = False
        self.name = self.id

        db.slack_bridge.update_one(
            {'aliases': {'$elemMatch': {'slack_id': self.id}}},
            {'$set': {'aliases.$.discord_id': None, 'aliases.$.discord_name': None}}
        )

    def set_discord_member(self, discord_member: discord.Member):
        """Set the needed alias variables and update the database.."""
        self.discord_member = discord_member
        self.name = discord_member.name

        db.slack_bridge.update_one(
            {'aliases': {'$elemMatch': {'slack_id': self.id}}},
            {'$set': {'aliases.$.discord_id': discord_member.id}}
        )

    async def get_user_info(self):
        """Returns slack user info of user."""
        return await self.app.client.users_info(user=self.id)


class SlackChannel:
    def __init__(self, channel_id: str, bot, app: AsyncApp):
        self.bot = bot
        self.app = app

        self.id = channel_id
        self.slack_name = self.id
        self.name = self.id

        self.discord_channel = None
        self.initialize_data()
        self.bot.loop.create_task(self.get_discord_channel())
        self.bot.loop.create_task(self.set_slack_name())

    def initialize_data(self):
        """Initialise data of the channel in the database if needed."""
        data = db.slack_bridge.find_one(
            {'guild_id': config.MAIN_SERVER, 'bridges': {'$elemMatch': {'slack_channel_id': self.id}}},
            {"bridges.$": 1})
        if not data:
            channel_data = {
                'slack_channel_id': self.id,
                'discord_channel_id': None
            }
            db.slack_bridge.update_one(
                {'guild_id': config.MAIN_SERVER},
                {'$push': {'bridges': channel_data}}
            )

    async def set_slack_name(self):
        """Set the slack name of the channel."""
        data = await self.app.client.conversations_info(channel=self.id)
        self.slack_name = data['channel']['name']

    async def get_discord_channel(self):
        """Get discord channel if slack channel is bridged with a discord channel."""
        data = db.slack_bridge.find_one(
            {'guild_id': config.MAIN_SERVER, 'bridges': {'$elemMatch': {'slack_channel_id': self.id}}},
            {"bridges.$": 1})
        discord_channel_id = data['bridges'][0]['discord_channel_id'] if len(data['bridges']) > 0 else None

        await self.bot.wait_until_ready()
        main_guild = self.bot.get_guild(config.MAIN_SERVER)
        self.discord_channel = discord.utils.get(main_guild.channels, id=discord_channel_id)
        if self.discord_channel:
            self.name = self.discord_channel.name

    def unset_discord_channel(self):
        """Unsets all the alias variables and updates the database."""
        self.discord_channel = None
        self.name = self.id

        db.slack_bridge.update_one(
            {'bridges': {'$elemMatch': {'slack_channel_id': self.id}}},
            {'$set': {'bridges.$.discord_channel_id': None}}
        )

    def set_discord_channel(self, discord_channel: discord.TextChannel):
        """Set the discord_channel and name variable and update the database."""
        self.discord_channel = discord_channel
        self.name = discord_channel.name

        db.slack_bridge.update_one(
            {'bridges': {'$elemMatch': {'slack_channel_id': self.id}}},
            {'$set': {'bridges.$.discord_channel_id': discord_channel.id}}
        )


class Slack:
    def __init__(self, bot):
        self.bot = bot
        self.logger = self.bot.logger
        self.app = AsyncApp(token=config.SLACK_BOT_TOKEN)

        self.app.view("socket_modal_submission")(self.submission)
        self.app.event("message")(self.slack_message)

        self.handler = AsyncSocketModeHandler(self.app, config.SLACK_APP_TOKEN)
        self.bot.loop.create_task(self.handler.start_async())

        self.bot.add_listener(self.on_message, 'on_message')
        self.bot.add_listener(self.on_message_edit, 'on_message_edit')

        self.channels: list[SlackChannel] = []
        self.members: list[SlackMember] = []

        self.discord_messages = TTLCache(ttl=600.0, maxsize=100)
        self.slack_messages = TTLCache(ttl=600.0, maxsize=100)
        self.message_links = []

        self.initialize_data()
        self.messages_cached = asyncio.Event()
        self.members_cached = asyncio.Event()
        self.channels_cached = asyncio.Event()
        self.bot.loop.create_task(self.cache_members())
        self.bot.loop.create_task(self.cache_channels())
        self.bot.loop.create_task(self.cache_messages())

    @staticmethod
    def initialize_data():
        """Initilises the data in the database if needed."""
        data = db.slack_bridge.find_one({'guild_id': config.MAIN_SERVER})
        if not data:
            data = {
                'guild_id': config.MAIN_SERVER,
                'aliases': [],
                'bridges': []
            }
            db.slack_bridge.insert_one(data)

    async def add_user(self, user_id: str):
        user_data = await self.app.client.users_info(user=user_id)
        slack_member = SlackMember(user_data, self.bot, self.app)
        self.members.append(slack_member)
        return slack_member

    def get_user(self, slack_id: str = None, *, discord_id: int = None) -> Optional[SlackMember]:
        """Get SlackMember via slack id or discord id."""
        return next(
            filter(
                lambda user:
                (slack_id is not None and user.id == slack_id) or
                (discord_id is not None and user.discord_member and user.discord_member.id == discord_id)
                , self.members
            ),
            None
        )

    def get_channel(self, slack_id: str = None, *, discord_id: int = None) -> Optional[SlackChannel]:
        """Get SlackChannel via slack id or discord id."""
        return next(
            filter(
                lambda channel:
                (slack_id is not None and channel.id == slack_id) or
                (discord_id is not None and channel.discord_channel and channel.discord_channel.id == discord_id)
                , self.channels
            ),
            None
        )

    async def get_channels(self) -> list[dict]:
        """Function for getting channels, makes call to slack api and filters out channels bot isnt member of."""
        return [channel for channel in (await self.app.client.conversations_list())['channels'] if channel['is_member']]

    async def get_members(self) -> list[dict]:
        """Function for getting members, makes call to slack api and filters out bot accounts and slack bot account."""
        # TOOD: maybe make a special case for bots? allow their messages through like on the discord side
        return [
            member for member in (await self.app.client.users_list())['members']
            if not member['is_bot'] and not member['id'] == 'USLACKBOT'
        ]

    async def cache_messages(self):
        """Cache messages in the database."""
        await self.bot.wait_until_ready()
        await self.members_cached.wait()
        await self.channels_cached.wait()

        messages = db.slack_messages.find({})
        for message in messages:
            twenty_four_hours = 24 * 60 * 60
            if time.time() - message['timestamp'] > twenty_four_hours:
                db.slack_messages.delete_one(message)
                continue

            if message['origin'] == 'discord':
                channel_id = message['discord_channel_id']
                channel = self.bot.get_channel(channel_id)
                discord_message = await channel.fetch_message(message['discord_message_id'])
                if not discord_message:
                    db.slack_messages.delete_one(message)
                    continue
                message = DiscordMessage(discord_message, self)
                self.discord_messages[message.id] = message
            elif message['origin'] == 'slack':
                data = {
                    'event': {
                        'user': message['user_id'],
                        'discord_message_id': message['discord_message_id'],
                        'channel': message['slack_channel_id'],
                        'text': message['text'],
                        'ts': message['slack_message_id'],
                        'files': message['files'],
                        'subtype': ''
                    }
                }
                slack_message = SlackMessage(data, self)
                self.slack_messages[slack_message.ts] = slack_message
        self.messages_cached.set()

    async def cache_channels(self):
        """Caches channels."""
        channels = await self.get_channels()
        for channel_data in channels:
            channel = SlackChannel(
                channel_id=channel_data['id'],
                bot=self.bot,
                app=self.app
            )
            self.channels.append(channel)

        self.channels_cached.set()

    async def cache_members(self):
        """Caches members."""
        members = await self.get_members()
        for member_data in members:
            member = SlackMember(
                data=member_data,
                bot=self.bot,
                app=self.app,
            )
            self.members.append(member)

        self.members_cached.set()

    async def submission(self, ack):
        """Function that acknowledges events."""
        await ack()

    async def slack_message(self, body):
        """Function called on message even from slack."""
        await self.messages_cached.wait()
        # ignore message_changed events if the messages are already cached
        is_edit = 'subtype' in body['event'] and body['event']['subtype'] == 'message_changed'
        ts = body['event']['message']['ts'] if is_edit else body['event']['ts']
        if is_edit:
            # check if message was edit by the bot
            edit_message = next(filter(lambda dm: dm.slack_message_id == ts, self.discord_messages.values()), None)
            if edit_message:
                return

        if 'subtype' in body['event'] and body['event']['subtype'] == 'bot_message':
            return

        if is_edit:
            cached_message = self.slack_messages[ts]
            if not cached_message:
                return

            cached_message.text = body['event']['message']['text']
            asyncio.create_task(
                cached_message.send_to_discord(edit=True)
            )
        else:
            message = SlackMessage(body, self)
            asyncio.create_task(
                message.send_to_discord()
            )

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """
        Function called on on_edit_message event, used for dealing with message edit events on the discord side
        and doing the same on the slack end.
        """
        if before.content != after.content and after.id in self.discord_messages:
            cached_message = self.discord_messages[after.id]
            await cached_message.send_to_slack(edit=True)

    async def on_message(self, message: discord.Message):
        """Function call on on_message event, used for identifying discord bridge channel and forwarding the messages to slack."""
        # ignore webhook messages and pms
        if not message.guild or message.webhook_id:
            return

        message = DiscordMessage(message, self)
        await message.send_to_slack()
