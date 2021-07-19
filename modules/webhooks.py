import discord
import inspect

from modules import database
from discord import Webhook, RequestsWebhookAdapter
from typing import Optional
db = database.get_connection()


class Webhooks:
    def __init__(self, bot):
        self.bot = bot
        self.webhooks = {}

    def initialize(self):
        """Cache all the existing webhooks."""
        for guild in self.bot.guilds:
            self.webhooks[guild.id] = {}
            webhooks = db.webhooks.find({'guild_id': guild.id})
            for webhook in webhooks:
                partial_webhook = Webhook.from_url(webhook['url'], adapter=RequestsWebhookAdapter())
                self.webhooks[guild.id][partial_webhook.channel_id] = partial_webhook

    async def create_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        """Create a webhook for a channel."""
        webhook = await channel.create_webhook(name='TLDR-Bot-webhook')
        self.webhooks[channel.guild.id][channel.id] = webhook
        return webhook

    async def get_webhook(self, channel: discord.TextChannel) -> Optional[discord.Webhook]:
        """Get a webhook for a channel or create it, if it doesn't exist."""
        if channel.id in self.webhooks[channel.guild.id]:
            webhook = self.webhooks[channel.guild.id][channel.id]
        else:
            webhook = await self.create_webhook(channel)

        return webhook

    async def send(self, channel: discord.TextChannel, content: str, username: str = None, avatar_url: str = None, files: list[discord.File] = None, embeds: list[discord.Embed] = None) -> Optional[discord.WebhookMessage]:
        """Send webhook message."""
        channel_webhook = await self.get_webhook(channel)
        if channel_webhook is None:
            channel_webhook = self.create_webhook(channel)

        kwargs = {'username': username, 'avatar_url': avatar_url, 'files': files, 'embeds': embeds}
        return await channel_webhook.send(content, **kwargs)
