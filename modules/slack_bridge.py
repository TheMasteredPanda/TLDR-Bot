import re

import discord.utils
import config

from html import unescape
from typing import Optional
from modules import database
from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from modules.utils import replace_mentions, embed_message_to_text

db = database.get_connection()


# TODO: if slack member doesnt have a discord account on the server, let admin define a name for them
# TODO: try to automatically assign aliases to slack members

class SlackMember:
    def __init__(self, data, bot, app: AsyncApp):
        self.bot = bot
        self.app = app

        self.id = data['id']
        # this value should only be used for the slack member info command
        self.slack_name = data['name']

        self.name = self.id
        self.colour = data['color']

        self.discord_member = None
        self.bot.loop.create_task(self.get_discord_member())
        self.initialize_data()

    def initialize_data(self):
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
        data = db.slack_bridge.find_one({'aliases': {'$elemMatch': {'slack_id': self.id}}}, {"aliases.$": 1})
        discord_id = data['aliases'][0]['discord_id'] if len(data['aliases']) > 0 else None

        await self.bot.wait_until_ready()
        main_guild = self.bot.get_guild(config.MAIN_SERVER)
        self.discord_member = discord.utils.get(main_guild.members, id=discord_id)
        if self.discord_member:
            self.name = self.discord_member.name

    def set_discord_member(self, discord_member: discord.Member):
        self.discord_member = discord_member
        self.name = discord_member.name

        db.slack_bridge.update_one(
            {'aliases': {'$elemMatch': {'slack_id': self.id}}},
            {'$set': {'aliases.$.discord_id': discord_member.id}}
        )

    async def get_user_info(self):
        return await self.app.client.users_info(user=self.id)


class SlackChannel:
    def __init__(self, data: dict, bot, app: AsyncApp):
        self.bot = bot
        self.app = app

        self.id = data['id']
        self.slack_name = self.id
        self.name = self.id

        self.discord_channel = None
        self.bot.loop.create_task(self.get_discord_channel())
        self.bot.loop.create_task(self.get_name())
        self.initialize_data()

    def initialize_data(self):
        data = db.slack_bridge.find_one({'guild_id': config.MAIN_SERVER, 'bridges': {'$elemMatch': {'slack_channel_id': self.id}}}, {"bridges.$": 1})
        if not data:
            channel_data = {
                'slack_channel_id': self.id,
                'discord_channel_id': None
            }
            db.slack_bridge.update_one(
                {'guild_id': config.MAIN_SERVER},
                {'$push': {'bridges': channel_data}}
            )

    async def get_name(self):
        data = await self.app.client.conversations_info(channel=self.id)
        self.slack_name = data['channel']['name']

    async def get_discord_channel(self):
        data = db.slack_bridge.find_one({'guild_id': config.MAIN_SERVER, 'bridges': {'$elemMatch': {'slack_channel_id': self.id}}}, {"bridges.$": 1})
        discord_channel_id = data['bridges'][0]['discord_channel_id'] if len(data['bridges']) > 0 else None

        await self.bot.wait_until_ready()
        main_guild = self.bot.get_guild(config.MAIN_SERVER)
        self.discord_channel = discord.utils.get(main_guild.channels, id=discord_channel_id)
        if self.discord_channel:
            self.name = self.discord_channel.name

    def set_discord_channel(self, discord_channel: discord.TextChannel):
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
        self.app.event("message")(self.handle_message_events)

        self.handler = AsyncSocketModeHandler(self.app, config.SLACK_APP_TOKEN)
        self.bot.loop.create_task(self.handler.start_async())
        self.bot.loop.create_task(self.cache_channels())
        self.bot.loop.create_task(self.cache_members())
        self.bot.add_listener(self.on_message, 'on_message')

        self.channels: list[SlackChannel] = []
        self.members: list[SlackMember] = []
        self.initialize_data()

    @staticmethod
    def initialize_data():
        data = db.slack_bridge.find_one({'guild_id': config.MAIN_SERVER})
        if not data:
            data = {
                'guild_id': config.MAIN_SERVER,
                'aliases': [],
                'bridges': []
            }
            db.slack_bridge.insert_one(data)

    def get_user(self, slack_id: str = None, *, discord_id: int = None) -> Optional[SlackMember]:
        return next(
            filter(
                lambda user:
                (slack_id is not None and user.id == slack_id) or
                (discord_id is not None and user.discord_member and user.discord_member.id == discord_id)
                ,self.members
            ),
            None
        )

    def get_channel(self, slack_id: str = None, *, discord_id: int = None) -> Optional[SlackChannel]:
        return next(
            filter(
                lambda channel:
                (slack_id is not None and channel.id == slack_id) or
                (discord_id is not None and channel.discord_channel and channel.discord_channel.id == discord_id)
                ,self.channels
            ),
            None
        )

    async def get_channels(self) -> list[dict]:
        return [channel for channel in (await self.app.client.conversations_list())['channels'] if channel['is_member']]

    async def get_members(self) -> list[dict]:
        return [member for member in (await self.app.client.users_list())['members'] if not member['is_bot'] and not member['id'] == 'USLACKBOT']

    async def cache_channels(self):
        channels = await self.get_channels()
        for channel_data in channels:
            channel = SlackChannel(
                data=channel_data,
                bot=self.bot,
                app=self.app
            )
            self.channels.append(channel)

    async def cache_members(self):
        # TODO: members have colour values
        members = await self.get_members()
        for member_data in members:
            member = SlackMember(
                data=member_data,
                bot=self.bot,
                app=self.app,
            )
            self.members.append(member)

    async def submission(self, ack):
        await ack()

    def discord_to_slack_formatting(self, text):
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

    @staticmethod
    def hyperlink_converter(text):
        special_chars_map = {i: '\\' + chr(i) for i in b'()[]{}?*+-|^$\\.&~#'}

        matches = re.findall(r'(\[(.*)\]\((.*)\))', text)
        for match in matches:
            url_text = match[1]
            url = match[2]
            text = re.sub(match[0].translate(special_chars_map), f'<{url}|{url_text}>', text)

        return text

    def discord_embed_to_blocks(self, message: discord.Message) -> list:
        text = embed_message_to_text(message)
        text = '>' + text.replace('\n', '\n>')
        text = replace_mentions(message.guild, text)
        text = self.hyperlink_converter(text)
        text = self.discord_to_slack_formatting(text)

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

    async def send_message(self, channel: SlackChannel, member: SlackMember, text: str):
        if not channel.discord_channel:
            return

        # TODO: bring back edit functionality
        text = unescape(text)

        await self.bot.webhooks.send(
            content=text,
            channel=channel.discord_channel,
            username=member.name,
            avatar_url=member.discord_member.avatar_url if member.discord_member else None,
            embeds=[],
        )

    async def handle_message_events(self, body):
        # TODO: change stuff like "&gt;" to actual values
        if 'subtype' in body['event'] and body['event']['subtype'] == 'message_changed':
            data = body['event']['message']
        else:
            data = body['event']

        if 'subtype' in data and data['subtype'] == 'bot_message':
            return

        user_id = data['user']
        channel_id = data['channel']
        blocks = data['blocks']
        text = data['text']
        files = []
        if 'files' in data:
            for file in data['files']:
                files.append(file['url_private_download'])  # TODO: this

        member = self.get_user(user_id)
        channel = self.get_channel(channel_id)

        if member is None:
            member = SlackMember(user_id, self.bot, self.app)
            self.members.append(member)
        if channel is None:
            channel = SlackChannel(channel_id, self.bot, self.app)
            self.channels.append(channel)

        return await self.send_message(channel, member, text)

    async def on_message(self, message: discord.Message):
        # ignore webhook messages
        if message.webhook_id:
            return

        slack_channel = self.get_channel(discord_id=message.channel.id)
        if not slack_channel:
            return

        kwargs = {}
        if message.author.bot and message.embeds:
            blocks = self.discord_embed_to_blocks(message)
            kwargs['blocks'] = blocks
        else:
            content = replace_mentions(message.guild, message.content)
            text = content
            text = replace_mentions(message.guild, text)
            text = self.hyperlink_converter(text)
            text = self.discord_to_slack_formatting(text)
            kwargs['text'] = text

        await self.app.client.chat_postMessage(
            channel=slack_channel.id,
            icon_url=str(message.author.avatar_url),
            username=message.author.name,
            **kwargs
        )




