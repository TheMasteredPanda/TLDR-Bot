import datetime
import re
from typing import Optional

import config
import discord
from bson import json_util
from discord.enums import ChannelType

from modules import database
from modules.custom_commands import Role
from modules.utils import SettingsHandler

db = database.get_connection()


class Watchlist:
    def __init__(self, bot):
        self.bot = bot

        if not self.bot.webhooks:
            self.bot.watchlist = None
            raise Exception(
                "Watchlist module depends on google drive module being enabled"
            )

        self.members = {}
        self.watchlist_data = {}
        self.bot.add_listener(self.on_message, "on_message")
        self.bot.add_listener(self.on_ready, "on_ready")
        self._default_settings = {"roles": []}
        self._settings_handler: SettingsHandler = bot.settings_handler
        settings = self._settings_handler.get_settings(config.MAIN_SERVER)

        if "watchlist" not in settings["modules"].keys():
            bot.logger.info(
                "Watchlist Module settings not found in Guild settings. Adding default settings now."
            )
            settings["modules"]["watchlist"] = self._default_settings
            self._settings_handler.save(settings)
            self._settings_handler.update(
                "watchlist", self._default_settings, config.MAIN_SERVER
            )

        self._settings = settings["modules"]["watchlist"]

    def add_role(self, role: discord.Role = None):
        if role is None:
            return

        self._settings["roles"].append(role.id)
        settings = self._settings_handler.get_settings(config.MAIN_SERVER)
        settings["modules"]["watchlist"] = self._settings
        self._settings_handler.save(settings)

    def rm_role(self, role: discord.Role = None):
        if role is None:
            return

        if role.id in self._settings["roles"]:
            self._settings["roles"].pop(self._settings["roles"].index(role.id))
        settings = self._settings_handler.get_settings(config.MAIN_SERVER)
        settings["modules"]["watchlist"] = self._settings
        self._settings_handler.save(settings)

    def get_settings(self):
        return self._settings

    async def on_ready(self):
        await self.bot.watchlist.initialize()

    async def initialize(self):
        """Cache all the existing webhook users."""
        watchlist_members = db.watchlist.find({"guild_id": config.MAIN_SERVER})
        print(watchlist_members.count())
        watchlist_category = await self.get_watchlist_category(
            self.bot.get_guild(config.MAIN_SERVER)
        )
        watchlist_channel = await self.get_thread_channel(watchlist_category)

        for m_member in watchlist_members:
            if m_member["channel_id"] != watchlist_channel.id:
                m_member["channel_id"] = watchlist_channel.id

            if "thread_id" not in m_member:
                if "user_id" != 0:
                    main_guild = self.bot.get_guild(config.MAIN_SERVER)
                    member = main_guild.get_member(m_member["user_id"])

                    if member is None:
                        db.watchlist.delete_one({"user_id": m_member["user_id"]})
                        self.bot.logger.info(
                            f"Deleted user {m_member['user_id']} as they are no longer on the main guild."
                        )
                        continue

                    thread = await self.get_thread(watchlist_channel, member)

                    self.bot.logger.info(
                        f"Created watchlist thread channel {thread.name}/{watchlist_channel.name} for watched user {member.display_name}#{member.discriminator}. Updating collection."
                    )
                    m_member["thread_id"] = thread.id
            db.watchlist.update_one({"_id": m_member["_id"]}, {"$set": m_member})

        for guild in self.bot.guilds:
            if guild.id != config.MAIN_SERVER:
                continue

            self.watchlist_data[guild.id] = {}
            users = db.watchlist.find({"guild_id": guild.id})
            for user in users:
                self.watchlist_data[guild.id][user["user_id"]] = user

    @staticmethod
    async def get_generic_channel(
        category: discord.CategoryChannel,
    ) -> Optional[discord.TextChannel]:
        channel = discord.utils.get(category.channels, name="generic")
        if channel is None:
            channel = await category.create_text_channel("generic")
        return channel

    @staticmethod
    async def get_thread_channel(
        category: discord.CategoryChannel,
    ) -> Optional[discord.TextChannel]:
        channel = discord.utils.get(category.channels, name="watchlist")
        if channel is None:
            channel = await category.create_text_channel("watchlist")
        return channel

    async def get_thread(
        self, channel: discord.TextChannel, member: discord.Member
    ) -> discord.Thread:
        thread = discord.utils.get(channel.threads, name=member.name)

        if thread is None:
            thread = await channel.create_thread(
                name=member.name, type=ChannelType.public_thread
            )

            c_roles = self._settings["roles"]
            d_roles: list[Role] = []

            for c_r in c_roles:
                main_guild = self.bot.get_guild(config.MAIN_SERVER)
                role = main_guild.get_role(c_r)
                if role is None:
                    continue
                d_roles.append(role)

            members: list[discord.Member] = []

            for role in d_roles:
                for member in role.members:
                    if member not in members:
                        members.append(member)
            for member in members:
                await thread.add_user(member)

        return thread

    @staticmethod
    async def get_watchlist_category(
        guild: discord.Guild,
    ) -> Optional[discord.CategoryChannel]:
        """Get the watchlist category or create it if it doesn't exist."""
        if guild is None:
            return

        category = discord.utils.get(guild.categories, name="Watchlist")
        if category is None:
            # get all staff roles
            staff_roles = filter(lambda r: r.permissions.manage_messages, guild.roles)
            # staff roles can read channels in category, users cant
            overwrites = dict.fromkeys(
                staff_roles,
                discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, read_message_history=True
                ),
            )
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                view_channel=False, read_messages=False
            )
            category = await guild.create_category(
                name="Watchlist",  # overwrites=overwrites
            )

        return category

    async def get_member(
        self, member: Optional[discord.Member], guild: discord.Guild
    ) -> Optional[dict]:
        """Get a watchlist member."""
        guild_watchlist_data = self.watchlist_data[guild.id]
        if not member and guild_watchlist_data.get(0, None) is None:
            return await self.add_member(member, guild, [])
        return (
            guild_watchlist_data.get(0, None)
            if not member
            else guild_watchlist_data.get(member.id, None)
        )

    async def add_member(
        self, member: Optional[discord.Member], guild: discord.Guild, filters: list
    ) -> dict:
        """Add a watchlist member, creating a channel for them."""
        category = await self.get_watchlist_category(guild)
        watchlist_channel = (
            await self.get_thread_channel(category)
            if member
            else await self.get_generic_channel(category)
        )
        # watchlist_channel = await guild.create_text_channel(
        #    f'{member.name if member else "Generic"}',
        #    category=category,
        #    position=int(bool(member)),
        # )

        thread = None

        if member and watchlist_channel.name.lower() != "generic":
            thread = await self.get_thread(watchlist_channel, member)

        watchlist_doc = {
            "guild_id": guild.id,
            "user_id": member.id if member else 0,
            "filters": [{"regex": f} for f in filters] if filters else [],
            "channel_id": watchlist_channel.id,
            "thread_id": thread.id if thread else 0,
        }

        db.watchlist.insert_one(watchlist_doc)
        self.watchlist_data[guild.id][member.id if member else 0] = watchlist_doc
        return watchlist_doc

    async def remove_member(
        self, member: Optional[discord.Member], guild: discord.Guild
    ):
        """Remove watchlist member and delete their channel."""
        watchlist_member = await self.get_member(member, guild)
        category = await self.get_watchlist_category(guild)
        watchlist_channel = await self.get_thread_channel(category)
        thread = watchlist_channel.get_thread(watchlist_member["thread_id"])
        if thread:
            await thread.archive()

        db.watchlist.delete_one(
            {"guild_id": guild.id, "user_id": member.id if member else 0}
        )

    async def add_filters(
        self,
        member: Optional[discord.Member],
        guild: discord.Guild,
        filters: list,
        mention_roles: list = [],
        set: bool = False,
    ):
        """Add filters to a watchlist member."""
        watchlist_member = await self.get_member(member, guild)
        all_filters = watchlist_member["filters"]
        if all_filters and set:
            filters += all_filters

        filters_dict = [{"regex": f, "mention_roles": mention_roles} for f in filters]
        db.watchlist.update_one(
            {"guild_id": guild.id, "user_id": member.id if member else 0},
            {"$set": {f"filters": filters_dict}},
        )
        self.watchlist_data[guild.id][member.id if member else 0][
            "filters"
        ] = filters_dict

    async def remove_filters(
        self,
        member: Optional[discord.Member],
        guild: discord.Guild,
        filters_to_remove: list,
    ):
        watchlist_member = await self.get_member(member, guild)
        all_filters = watchlist_member["filters"]
        new_filters = []
        for filter in all_filters:
            if filter["regex"] in filters_to_remove:
                continue
            new_filters.append(filter)
        db.watchlist.update_one(
            {"guild_id": guild.id, "user_id": member.id if member else 0},
            {"$set": {f"filters": new_filters}},
        )
        self.watchlist_data[guild.id][member.id if member else 0][
            "filters"
        ] = new_filters

    async def send_message(
        self,
        message: discord.Message,
        matched_filter: Optional[dict],
        generic: bool = False,
        *,
        channel: discord.TextChannel = None,
        thread: discord.Thread = None,
    ):
        """Send watchlist message with a webhook."""
        # update stats first

        if channel is None and thread is None:
            raise Exception("Both thread and channel is none")

        if channel is None:
            channel = thread.parent

        if matched_filter:
            db.watchlist.update_one(
                {
                    "guild_id": message.guild.id,
                    "filters": {"$elemMatch": {"regex": matched_filter["regex"]}},
                },
                {"$inc": {"filters.$.matches": 1}},
            )

        embeds = [
            discord.Embed(
                description=f"{message.content}\n{message.channel.mention} [link]({message.jump_url})",
                timestamp=datetime.datetime.now(),
            )
        ]
        if generic:
            embeds[0].set_author(
                name=str(message.author), icon_url=message.author.avatar_url
            )

        files = [await attachment.to_file() for attachment in message.attachments]
        content = (
            f", ".join(
                f"<@&{int(role_id)}>"
                for role_id in (
                    matched_filter["mention_roles"]
                    if "mention_roles" in matched_filter
                    else []
                )
            )
            if matched_filter
            else ""
        )
        await self.bot.webhooks.send(
            channel=channel,
            thread=thread,
            content=content,
            username=message.author.name if not generic else self.bot.user.name,
            avatar_url=message.author.avatar
            if not generic
            else self.bot.user.avatar_url,
            files=files,
            embeds=embeds,
        )

    async def on_message(self, message: discord.Message):
        """Function run on every message to check if user is on watchlist and send their message."""
        if not self.bot._ready.is_set():
            return

        if message.guild is None:
            return

        if message.guild.id != config.MAIN_SERVER:
            print("Not in main server.")
            return

        ctx = await self.bot.get_context(message)
        if ctx.command and (
            ctx.command.name == "watchlist"
            or (ctx.command.parent and ctx.command.parent.name == "watchlist")
        ):
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

        user_filters = user_watchlist_data.get("filters", [])
        generic_filters = generic_watchlist_data.get("filters", [])

        if generic_filters:
            category = self.get_watchlist_category(
                self.bot.get_guild(config.MAIN_SERVER)
            )
            channel = await self.get_generic_channel(category)
            for filter in generic_filters:
                if re.findall(filter["regex"], message.content, re.IGNORECASE):
                    return await self.send_message(
                        message, filter, True, channel=channel
                    )

        thread_id = user_watchlist_data.get("thread_id", "0")
        category = await self.get_watchlist_category(message.guild)
        watchlist_channel = await self.get_thread_channel(category)
        thread = watchlist_channel.get_thread(thread_id)
        if thread:
            matched_filter = None
            if user_filters:
                for filter in user_filters:
                    if re.findall(filter["regex"], message.content, re.IGNORECASE):
                        matched_filter = filter
                        break
            await self.send_message(
                message, matched_filter, channel=watchlist_channel, thread=thread
            )
        else:
            # remove from watchlist, since watchlist channel doesnt exist
            db.watchlist.delete_one(
                {"guild_id": message.guild.id, "user_id": message.author.id}
            )
