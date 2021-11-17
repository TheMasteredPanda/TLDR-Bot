import datetime
import re

import discord

from typing import Optional
from modules import database

db = database.get_connection()


class Watchlist:
    def __init__(self, bot):
        self.bot = bot

        if not self.bot.webhooks:
            self.bot.watchlist = None
            raise Exception('Watchlist module depends on google drive module being enabled')

        self.members = {}
        self.watchlist_data = {}
        self.bot.add_listener(self.on_message, 'on_message')
        self.bot.add_listener(self.on_ready, 'on_ready')

    async def on_ready(self):
        self.bot.watchlist.initialize()

    def initialize(self):
        """Cache all the existing webhook users."""
        for guild in self.bot.guilds:
            self.watchlist_data[guild.id] = {}
            users = db.watchlist.find({"guild_id": guild.id})
            for user in users:
                self.watchlist_data[guild.id][user['user_id']] = user

    @staticmethod
    async def get_watchlist_category(guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        """Get the watchlist category or create it if it doesn't exist."""
        if guild is None:
            return

        category = discord.utils.get(guild.categories, name='Watchlist')
        if category is None:
            # get all staff roles
            staff_roles = filter(lambda r: r.permissions.manage_messages, guild.roles)
            # staff roles can read channels in category, users cant
            overwrites = dict.fromkeys(staff_roles, discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True))
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False, read_messages=False)
            category = await guild.create_category(name='Watchlist', overwrites=overwrites)

        return category

    async def get_member(self, member: Optional[discord.Member], guild: discord.Guild) -> Optional[dict]:
        """Get a watchlist member."""
        guild_watchlist_data = self.watchlist_data[guild.id]
        if not member and guild_watchlist_data.get(0, None) is None:
            return await self.add_member(member, guild, [])
        return guild_watchlist_data.get(0, None) if not member else guild_watchlist_data.get(member.id, None)

    async def add_member(self, member: Optional[discord.Member], guild: discord.Guild, filters: list) -> dict:
        """Add a watchlist member, creating a channel for them."""
        category = await self.get_watchlist_category(guild)
        watchlist_channel = await guild.create_text_channel(f'{member.name if member else "Generic"}', category=category, position=int(bool(member)))
        watchlist_doc = {
            'guild_id': guild.id,
            'user_id': member.id if member else 0,
            'filters': [{'regex': f} for f in filters],
            'channel_id': watchlist_channel.id
        }
        db.watchlist.insert_one(watchlist_doc)
        self.watchlist_data[guild.id][member.id if member else 0] = watchlist_doc
        return watchlist_doc

    async def remove_member(self, member: Optional[discord.Member], guild: discord.Guild):
        """Remove watchlist member and delete their channel."""
        watchlist_member = await self.get_member(member, guild)
        channel = self.bot.get_channel(int(watchlist_member['channel_id']))
        if channel:
            await channel.delete()

        db.watchlist.delete_one({'guild_id': guild.id, 'user_id': member.id if member else 0})

    async def add_filters(self, member: Optional[discord.Member], guild: discord.Guild, filters: list, mention_roles: list = [], set: bool = False):
        """Add filters to a watchlist member."""
        watchlist_member = await self.get_member(member, guild)
        all_filters = watchlist_member['filters']
        if all_filters and set:
            filters += all_filters

        filters_dict = [{'regex': f, 'mention_roles': mention_roles} for f in filters]
        db.watchlist.update_one({'guild_id': guild.id, 'user_id': member.id if member else 0}, {'$set': {f'filters': filters_dict}})
        self.watchlist_data[guild.id][member.id if member else 0]['filters'] = filters_dict

    async def remove_filters(self, member: Optional[discord.Member], guild: discord.Guild, filters_to_remove: list):
        watchlist_member = await self.get_member(member, guild)
        all_filters = watchlist_member['filters']
        new_filters = []
        for filter in all_filters:
            if filter['regex'] in filters_to_remove:
                continue
            new_filters.append(filter)
        db.watchlist.update_one({'guild_id': guild.id, 'user_id': member.id if member else 0}, {'$set': {f'filters': new_filters}})
        self.watchlist_data[guild.id][member.id if member else 0]['filters'] = new_filters

    async def send_message(self, channel: discord.TextChannel, message: discord.Message, matched_filter: Optional[dict], generic: bool = False):
        """Send watchlist message with a webhook."""
        # update stats first
        if matched_filter:
            db.watchlist.update_one(
                {'guild_id': message.guild.id, 'filters': {'$elemMatch': {'regex': matched_filter['regex']}}},
                {'$inc': {'filters.$.matches': 1}}
            )

        embeds = [
            discord.Embed(
                description=f'{message.content}\n{message.channel.mention} [link]({message.jump_url})',
                timestamp=datetime.datetime.now(),
            )
        ]
        if generic:
            embeds[0].set_author(name=str(message.author), icon_url=message.author.avatar_url)

        files = [await attachment.to_file() for attachment in message.attachments]
        content = f', '.join(f'<@&{int(role_id)}>' for role_id in matched_filter['mention_roles']) if matched_filter else ''
        await self.bot.webhooks.send(
            channel=channel,
            content=content,
            username=message.author.name if not generic else self.bot.user.name,
            avatar_url=message.author.avatar_url if not generic else self.bot.user.avatar_url,
            files=files,
            embeds=embeds
        )

    async def on_message(self, message: discord.Message):
        """Function run on every message to check if user is on watchlist and send their message."""
        if not self.bot._ready.is_set():
            return

        ctx = await self.bot.get_context(message)
        if ctx.command and (ctx.command.name == 'watchlist' or (ctx.command.parent and ctx.command.parent.name == 'watchlist')):
            return

        if message.author.bot:
            return

        if not message.guild:
            return

        guild_watchlist_data = self.watchlist_data[message.guild.id]
        user_watchlist_data = guild_watchlist_data.get(message.author.id, {})
        generic_watchlist_data = guild_watchlist_data.get(0, {})
        watchlist_category = await self.get_watchlist_category(message.guild)
        if not watchlist_category:
            return

        user_filters = user_watchlist_data.get('filters', [])
        generic_filters = generic_watchlist_data.get('filters', [])

        if generic_filters:
            channel_id = generic_watchlist_data["channel_id"]
            channel = self.bot.get_channel(int(channel_id))
            for filter in generic_filters:
                if re.findall(filter['regex'], message.content, re.IGNORECASE):
                    return await self.send_message(channel, message, filter, True)

        channel_id = user_watchlist_data.get("channel_id", '0')
        channel = self.bot.get_channel(int(channel_id))
        if channel:
            matched_filter = None
            for filter in user_filters:
                if re.findall(filter['regex'], message.content, re.IGNORECASE):
                    matched_filter = filter
                    break
            await self.send_message(channel, message, matched_filter)
        else:
            # remove from watchlist, since watchlist channel doesnt exist
            db.watchlist.delete_one({"guild_id": message.guild.id, "user_id": message.author.id})
