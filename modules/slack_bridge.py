import asyncio
import json
import re

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
    def __init__(self, data: dict, bot, app: AsyncApp):
        self.bot = bot
        self.app = app

        self.id = data['id']
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


def hyperlink_converter(text):
    """Converts discord hyperlink format to slack format."""
    special_chars_map = {i: '\\' + chr(i) for i in b'()[]{}?*+-|^$\\.&~#'}
    matches = re.findall(r'(\[(.*)\]\((.*)\))', text)
    for match in matches:
        url_text = match[1]
        url = match[2]
        text = re.sub(match[0].translate(special_chars_map), f'<{url}|{url_text}>', text)

    return text


def normalize_text(text, guild: discord.Guild):
    """Function for normalising discord text to slack standards."""
    text = replace_mentions(guild, text)
    text = hyperlink_converter(text)
    text = discord_to_slack_formatting(text)
    return text


def discord_embed_to_blocks(message: discord.Message) -> list:
    """Converts discord embeds into slack blocks."""
    text = embed_message_to_text(message)
    text = '>' + text.replace('\n', '\n>')
    text = normalize_text(text, message.guild)

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": text
            }
        }
    ]
    return blocks


def discord_to_slack_formatting(text):
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


def discord_message_to_slack(message: discord.Message):
    """Main entrypoint for converting discord message to appropriate slack format."""
    if message.author.bot and message.embeds:
        blocks = discord_embed_to_blocks(message)
    else:
        content = replace_mentions(message.guild, message.content)
        text = normalize_text(content, message.guild)
        blocks = [{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": text,
            }
        }]

    return blocks


class Slack:
    def __init__(self, bot):
        self.bot = bot
        self.logger = self.bot.logger
        self.app = AsyncApp(token=config.SLACK_BOT_TOKEN)

        self.app.view("socket_modal_submission")(self.submission)
        self.app.event("message")(self.handle_message_events)

        self.handler = AsyncSocketModeHandler(self.app, config.SLACK_APP_TOKEN)
        self.bot.loop.create_task(self.handler.start_async())
        self.bot.loop.create_task(self.cache_channels())
        self.bot.loop.create_task(self.cache_members())
        self.bot.add_listener(self.on_message, 'on_message')
        self.bot.add_listener(self.on_message_edit, 'on_message_edit')

        self.channels: list[SlackChannel] = []
        self.members: list[SlackMember] = []
        self.cached_messages: TTLCache = TTLCache(ttl=600.0, maxsize=500)
        self.initialize_data()

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
        return [member for member in (await self.app.client.users_list())['members'] if
                not member['is_bot'] and not member['id'] == 'USLACKBOT']

    async def cache_channels(self):
        """Caches channels."""
        channels = await self.get_channels()
        for channel_data in channels:
            channel = SlackChannel(
                data=channel_data,
                bot=self.bot,
                app=self.app
            )
            self.channels.append(channel)

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

    async def submission(self, ack):
        """Function that acknowledges events."""
        await ack()

    async def send_message(
            self,
            channel: SlackChannel,
            member: SlackMember,
            text: str,
            token: str, *,
            edit: bool = False,
            files: list[dict] = False
    ):
        """Function for sending messages from slack to discord via a webhook."""
        if not channel.discord_channel:
            return

        file_urls = [file['url'] for file in files]
        download_images = [
            discord.File(image, filename=files[i]['name']) for i, image in
            enumerate(
                await async_file_downloader(file_urls, headers={'Authorization': f'Bearer {config.SLACK_BOT_TOKEN}'}))
        ]
        cached_message = self.cached_messages.get(token, None)

        # return if edit message event but no cached message
        if not cached_message and edit:
            return

        text = unescape(text)
        webhook_message = await self.bot.webhooks.send(
            content=text,
            channel=channel.discord_channel,
            username=member.name,
            avatar_url=member.discord_member.avatar_url if member.discord_member else None,
            files=download_images,
            embeds=[],
            edit=cached_message
        )

        if not cached_message and webhook_message.id:
            self.cached_messages[token] = webhook_message.id

    async def handle_message_events(self, body):
        """Function called on message even from slack."""
        # ignore message_changed events if the messages are already cached
        if 'subtype' in body['event'] and body['event']['subtype'] == 'message_changed':
            ts = body['event']['message']['ts']
            if ts in self.cached_messages.values():
                return

        # check if the message event is an edit or not
        edit_message = 'subtype' in body['event'] and body['event']['subtype'] == 'message_changed'
        data = body['event']

        if 'subtype' in data and data['subtype'] == 'bot_message':
            return

        print(json.dumps(body, indent=2))
        user_id = data['user'] if not edit_message else data['message']['user']
        channel_id = data['channel']
        text = data['text'] if not edit_message else data['message']['text']
        token = data['ts'] if not edit_message else data['message']['ts']
        files = [{'url': file['url_private_download'], 'name': file['name']} for file in
                 data['files']] if 'files' in data else []

        member = self.get_user(user_id)
        channel = self.get_channel(channel_id)

        if member is None:
            member = SlackMember(data, self.bot, self.app)
            self.members.append(member)
        if channel is None:
            channel = SlackChannel(data, self.bot, self.app)
            self.channels.append(channel)

        asyncio.create_task(
            self.send_message(channel, member, text, token, edit=edit_message, files=files)
        )

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """
        Function called on on_edit_message event, used for dealing with message edit events on the discord side
        and doing the same on the slack end.
        """
        if before.content != after.content and after.id in self.cached_messages:
            cached_message = self.cached_messages[after.id]
            slack_channel = self.get_channel(discord_id=after.channel.id)
            kwargs = discord_message_to_slack(after)
            if kwargs['text'] or kwargs['blocks']:
                await self.app.client.chat_update(
                    channel=slack_channel.id,
                    ts=cached_message,
                    **kwargs,
                )

    async def on_message(self, message: discord.Message):
        """Function call on on_message event, used for identifying discord bridge channel and forwarding the messages to slack."""
        # ignore webhook messages and pms
        if not message.guild or message.webhook_id:
            return

        slack_channel = self.get_channel(discord_id=message.channel.id)
        if not slack_channel:
            return

        blocks = discord_message_to_slack(message)

        if blocks:
            slack_message = await self.app.client.chat_postMessage(
                channel=slack_channel.id,
                icon_url=str(message.author.avatar_url),
                username=message.author.name,
                blocks=blocks,
                text=''
            )
            self.cached_messages[message.id] = slack_message['message']['ts']

        if message.attachments:
            for attachment in message.attachments:
                file = await attachment.to_file()
                await self.app.client.files_upload(
                    file=file.fp,
                    filename=attachment.filename,
                    channels=slack_channel.id,
                    title=f'Uploaded by: {message.author.name}'
                )
