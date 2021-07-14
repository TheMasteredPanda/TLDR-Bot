import discord
import copy

from modules import database
from discord import Webhook, AsyncWebhookAdapter
from typing import Optional


class Webhooks:
    def __init__(self, bot):
        self.bot = bot
        self.webhooks = {}

    async def initialize(self):
        """Cache all the existing webhooks."""
        for guild in self.bot.guilds:
            self.webhooks[guild.id] = {}
            for channel in guild.channels:
                if type(channel) != discord.TextChannel:
                    continue

                channel_webhooks = await channel.webhooks()
                if not channel_webhooks:
                    continue

                webhook = channel_webhooks[0]
                try:
                    partial_webhook = Webhook.from_url(webhook.url, adapter=AsyncWebhookAdapter(channel._state.http._HTTPClient__session))
                    self.webhooks[guild.id][channel.id] = partial_webhook
                except:
                    continue

    async def create_webhook(self, channel: discord.TextChannel) -> discord.Webhook:
        """Create a webhook for a channel."""
        webhook = await channel.create_webhook(name='TLDR-Bot-webhook')
        self.webhooks[channel.guild.id][channel.id] = webhook
        return webhook

    async def get_webhook(self, channel: discord.TextChannel) -> Optional[discord.Webhook]:
        """Get a webhook for a channel or create it, if it doesn't exist."""
        print(self.webhooks)
        if channel.id in self.webhooks[channel.guild.id]:
            webhook = self.webhooks[channel.guild.id][channel.id]
        else:
            webhook = await self.create_webhook(channel)

        return copy.copy(webhook)

    async def send(self, channel: discord.TextChannel, content: str = '', username: str = None, avatar_url: str = None, files: list[discord.File] = None, embeds: list[discord.Embed] = None) -> Optional[discord.WebhookMessage]:
        """Send webhook message."""
        channel_webhook = await self.get_webhook(channel)
        if not channel_webhook:
            channel_webhook = await self.create_webhook(channel)

        kwargs = {'username': username, 'avatar_url': avatar_url, 'files': files, 'embeds': embeds, 'content': content}
        return await channel_webhook.send(**kwargs)
