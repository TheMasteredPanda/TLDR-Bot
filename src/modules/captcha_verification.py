import asyncio
import io
import math
import random
import re
import string
import time
from datetime import datetime
from typing import Optional, Union

import config
import discord
from captcha.image import ImageCaptcha
from discord import Member
from discord.channel import TextChannel
from discord.colour import Colour
from discord.errors import Forbidden, HTTPException
from discord.guild import Guild
from discord.invite import Invite
from pymongo.cursor import Cursor

import modules.database as database
import modules.timers as timers
from modules.utils import SettingsHandler
from ukparliament.utils import BetterEnum

"""
Author: TheMasteredPanda (Duke J. Morgan)
Description: A Captcha Gateway System to prevent continuous bot attacks.


Requirements:
    - [DONE] Bot to have ownership over gateway server.
    - [ ] Bot to create more gateway servers if the need arises.
    - [DONE] Each new member to a captcha server will need a dedicated channel to prove they are not a bot.
        * [DONE] In this channel, only they will be able to see themselves and the bot.
        * [DONE] In this channel, the captcha will happen.
        * [DONE] This channel will be removed after a time-to-live if the captcha has not be completed, configuable ofc.
        * [DONE] This channel will be removed after the captcha is successfully on unsuccessfully completed.
    - [DONE] The Bot should allow for invitation links to be generated for each gateway server through a command, accessed on
    the main TLDR guild.
    - [DONE] The Bot should allow for warning announcements if any one gateway is becoming too full.
    - [DONE] After the captcha is complete, the user should be given a one-time invitation link. Once they have joined the
    main TLDR server,
    they should be kicked off of the gateway server.
    - The following data points need to be stored:
        * [ ] Amount of successful captchas.
        * [ ] Amount of unsuccessful captchas.
        * [ ] Amount of joins per month.
    - The following commands need to be written:
        * [DONE] A command to get an invitiation link. This command will also need to accomodate for the different types of
        invitiation link a guild can offer. Whether it be one of or non-expiring.
        * [ ] A command to see the status of each gateway server. How many people join each gateway server,
        it's current lifetime, it's id, &c.
        * [ ] A command to set a channel for useful announcements from this feature. Announcements include:
            - [ ] When a new gateway guild is created.
            - [ ] When a gateway guild is closed.
            - [ ] When a gateway guild will no longer accept new invitations.
            - [ ] When a when a gateway is nearly full.
            - [ ] When a gateway is full.
        * [DONE] A command to add gateway guilds to the list of gateway guilds handled by the bot. This is only for the edgest
        of cases, so I don't think I'll end up doing this.
        * Captchas:
            - Used to determine whether a user is a bot or a human.
            - What will be the captchas?
                * At the moment nobody has a clue, so the basic captchas now will be:
                    * [DONE] Typing out what word has squiggled about in a manner no readable by computers.
"""


def random_chars(length: int):
    return "".join(random.choice(string.ascii_lowercase) for i in range(length))


class DataManager:
    """
    The primary MongoDB interface for this feature. This contains within it all functions interacting with the
    various collections associated with this feature.
    """

    def __init__(self, logger):
        self._logger = logger
        self._db = database.get_connection()
        self._captcha_guilds = self._db.captcha_guilds
        self._captcha_channels = self._db.captcha_channels
        self._captcha_blacklist = self._db.captcha_blacklist
        self._captcha_counter = self._db.captcha_counter
        self._member_cache = self._db.captcha_member_cache
        self._registered_invitations = self._db.captcha_registered_invitations

    def add_captcha_channel(self, channel):
        """
        Adds a captcha channel to the relevant collection.

        Parameters
        ----------
        channel: :class:`CaptchaChannel`
            CaptchaChannel instance to store.
        """
        self._captcha_channels.insert_one(
            {
                "guild_id": channel.get_gateway_guild().get_guild().id,
                "channel_id": channel.get_id(),
                "member_id": channel.get_member().id,
                "tries": channel.get_tries(),
                "active": channel.is_active(),
                "ttl": channel.get_ttl(),
                "stats": {"completed": False, "failed": False},
                "created_at": time.time(),
            }
        )

    def update_captcha_counter(self, member_id: int, counter: int):
        """
        Updates a captcha counter. A captcha counter being the integer that counts the amount of times
        a user has left. If this reaches a certain limit they become blacklisted, preventing them from helping
        someone circumvent the captcha system too much.

        Parameters
        ----------
        member_id: :class:`int`
            The id of the member associated with the coutner.
        counter: :class:`int`
            Depending on the pre-existentence of a counter, this value is used to either set or update
            the counter.
        """
        entry = self._captcha_counter.find_one({"mid": member_id})
        now = time.time()
        if entry:
            self._captcha_counter.update_one(
                {"mid": member_id},
                {"$set": {"counter": entry["counter"] + counter, "updated_at": now}},
            )
        else:
            self._captcha_counter.insert_one(
                {"mid": member_id, "counter": counter, "updated_at": now}
            )

    def get_captcha_counter(self, member_id: int):
        """
        Fetches a captcha counter entry, provided it is there already.

        Parameters
        ----------
        member_id: :class:`int`
            The id of the member associated to a counter.
        """
        return self._captcha_counter.find_one({"mid": member_id})

    def reset_captcha_counter(self, member_id: int):
        """
        Resets the captcha counter to 0.

        Parameters
        ----------
        member_id: :class:`int`
            The id of the member associated to a counter.
        """
        return self._captcha_counter.update_one(
            {"mid": member_id}, {"$set": {"counter": 0}}
        )

    def get_all_captcha_channels(
        self, *, from_date: float = -1, before_date: float = -1
    ):
        """
        Gets all captchas channels across all guilds. If no parameters are supplied then this function will
        returns as many captcha channels as the Mongo Server will allow.

        Parameters
        ----------
        from_date: :class:`float`
            Used to fetch all captcha channels that were created from a date onwards.
        from_date: :class:`float`
            Used to fetch all captcha channels that were created before a date backwards.

        Returns
        -------
        :class:`Cursor`
            Returns a cursor or None in the event that nothing is in the collection.
        """
        if from_date == -1 and before_date == -1:
            return self._captcha_channels.find({})
        else:
            params = {}

            if from_date != -1 and before_date == -1:
                params["created_at"] = {"$gte": from_date}
            elif before_date != -1 and from_date == -1:
                params["created_at"] = {"$lte": before_date}
            else:
                params["created_at"] = {"$gte": from_date, "$lte": before_date}
            return self._captcha_channels.find(params)

    def get_captcha_channels(self, guild_id: int, only_active: bool = True) -> list:
        """
        Returns all the captcha channels in a guild.

        Parameters
        ----------
        guild_id: :class:`int`
            The id of the Gateway Guild.
        only_active: :class:`int`
            If true will return only active captcha channels. If false will return inactive channels.

        Returns
        -------
        :class:`list`
            A list of documents containing key information about captcha channels.
        """
        return (
            list(
                self._captcha_channels.find(
                    {"guild_id": guild_id, "active": only_active}
                )
            )
            if only_active is True
            else list(self._captcha_channels.find({"guild_id": guild_id}))
        )

    def add_blacklisted_member(self, member: Member):
        """
        Add a blacklisted member to the user cache.

        Parameters
        ----------
        :class:`Member`
            The member that was just blacklied.
        """

        self._member_cache.insert_one({"mid": member.id, "name": member.display_name})

    def get_blacklisted_member(self, member_id: int) -> Union[Cursor, None]:
        """
        Fetch information on one cached member.

        Parameters
        ----------
        member_id: :class:`int`
            The id of the member.

        Returns
        -------
        :class:`object`
            A document associated with the member id provided or `None`.
        """
        return self._member_cache.find_one({"mid": member_id})

    def delete_blacklisted_members(self, mids: list[int]) -> None:
        """Deletes more than one member from the cache. Used primarily in the unban_task.

        Parameters
        ----------
        :class:`mids`
            A list of member ids.
        """
        self._member_cache.delete_many({"mid": mids})

    def get_blacklisted_members(self, username: str = "", member_id: int = 0):
        """
        Fetches a list of blacklisted members. If a username or member id is supplied then it will preform a
        'starts with' filter, and return the list of members whose username starts with the string supplied
        or whose id starts with the id supplied.

        Parameters
        ----------
        username: :class:`str`
            The starting characters of a username.
        member_id: :class:`int`
            The starting characters of a member id.

        Returns
        -------
        :class:`list`
            A list of documents that starts with the username provided or the id provided.
        """
        if username == "" and member_id == 0:
            return self._member_cache.find({})

        return (
            self._member_cache.find(
                {"name": re.compile(f"^{username}.*", re.IGNORECASE)}
            )
            if username != ""
            else self._member_cache.find({"mid": "/^{member_id}.*/is"})
        )

    def remove_blacklisted_member(self, member_id: int):
        """
        Removes a blacklisted member from the cache. Used usually after a member has been removed from the blacklist.
        """
        self._member_cache.remove({"mid": member_id})

    def get_captcha_counters(self) -> list:
        """
        Returns all the captcha counters.

        Returns
        -------
        :class:`list`
            A list of captcha counter documents.
        """
        return list(self._captcha_counter.find({}))

    def update_captcha_channel(self, guild_id: int, channel_id: int, update: dict):
        """
        Updates a captcha channel document with new information from the 'update' parameter.

        Parameters
        ----------
        guild_id: :class:`int`
            The id of the guild the captcha channel is in.
        channel_id: :class:`int`

        """

        if "last_updated" not in update.keys():
            update["last_updated"] = time.time()

        print(
            f"Captcha channel is {'None' if self._captcha_channels is None else 'Not None'}"
        )
        self._captcha_channels.update_one(
            {"guild_id": guild_id, "channel_id": channel_id}, {"$set": update}
        )

    def add_guild(self, guild_id: int, landing_channel_id: int = 0):
        """
        Add a Gateway Guild to the relevant collection.

        Parameters
        ----------
        guild_id: :class:`int`
            The id of the guild.
        landing_channel_id: :class:`int`
            The id of the landing channel, the channel the invites are created from.
        """
        self._captcha_guilds.insert_one(
            {
                "guild_id": guild_id,
                "landing_channel_id": landing_channel_id,
                "stats": {},
            }
        )

    def remove_guild(self, guild_id: int):
        """
        Remove a guild from the Gateway Guild collection.

        Parameters
        ----------
        guild_id: :class:`int`
            The id of the guild.
        """
        self._captcha_guilds.delete_one({"guild_id": guild_id})

    def get_guilds(self, include_stats: bool = False) -> Cursor:
        """
        Returns the Cursor the search for all Gateway Guilds.

        Parameters
        ----------
        include_stats: :class:`bool`
            If true, will include the stats for every document.
            If false will exclude the stats from the document.

        Returns
        -------
        :class:`Cursor`
            Returns the cursor of the search for Gateway Guilds.
        """
        return (
            self._captcha_guilds.find({}, {"stats": 0})
            if include_stats is False
            else self._captcha_guilds.find({}, {"stats": 0})
        )

    def is_blacklisted(self, member_id: int) -> bool:
        """
        Checks if a user is blacklisted.

        Parameters
        ----------
        member_id: :class:`int`
            The id of the member to search for.

        Returns
        -------
        :class:`bool`
            Returns true if blacklisted, else false.
        """

        return self._captcha_blacklist.find_one({"mid": member_id}) is not None

    def add_member_to_blacklist(
        self, member: Member, duration: int = 86400, reason: str = "No reason provided."
    ):
        """
        Add a member to the blacklist. This will store the date in which the member was blacklisted, the time which
        the blacklist will end, and the id of the member who is being blacklisted.

        Parameters
        ----------
        member: :class:`discord.Member`
            The member to blacklist.
        duration: :class:`int`
            The duration the blacklist should be.
        """
        now = time.time()
        self._captcha_blacklist.insert_one(
            {"mid": member.id, "started": now, "ends": now + duration, "reason": reason}
        )

    def get_blacklisted_member_info(self, member_id: int) -> Union[Cursor, None]:
        """
        Returns the temporal data associated with a member who has been blacklisted. This data is the full date the
        user was blacklisted (banned) as well as the date in which the blacklist will be over.

        Parameters
        ----------
        member_id: :class:`int`
            The id of the member to fetch.

        Returns
        -------
        :class:`Document`
            The document containing the information of the blacklisted member.
        """
        return self._captcha_blacklist.find_one({"mid": member_id})

    def remove_member_from_blacklist(self, member_id: int):
        """
        Remove a member from the blacklist.

        Parameters
        ----------
        member_id: :class:`int`
            The id of a member to remove from the blacklist
        """
        self._captcha_blacklist.delete_one({"mid": member_id})

    def get_blacklist(self):
        """
        Returns all blacklisted member documents.

        Returns
        -------
        :class:`list`
            A list of documents.
        """
        return list(self._captcha_blacklist.find({}))

    def is_registered_invitation(self, invite_code: str):
        return self._registered_invitations.find({"code": invite_code}) is not None

    def add_registered_invitation(self, invite_code: str, i_type: int):
        self._registered_invitations.insert_one({"code": invite_code, "type": i_type})

    def remove_registered_invitation(self, invite_code: str):
        self._registered_invitations.delete_one({"code": invite_code})

    def get_registered_invite(self, invite_code: str):
        return self._registered_invitations.find_one({"code": invite_code})

    def get_all_registered_invites(self, r_type: int):
        return self._registered_invitations.find({"type": r_type})


class TrackerManager:
    """
    Tracks all invitations on the main guild. This is used to determine if a user joined through a registered or
    unregistered invitations.
    """

    def __init__(self, bot):
        self._bot = bot
        self._logger = bot.logger
        self._cache = {}  # To keep all information on invites only.
        self._invite_cache = {}
        self._temporal_cache = {}  # To keep all temporal information on invites.

        self._bot = bot

    def has_temporal_entry(self, invite_code: str):
        """
        Checks if an invitation url already has an assocated temporal entry.

        Parameters
        ----------
        `invite_code`: :class:`str`
            The invite code part of an invitation url.

        Returns
        -------
        :class:`bool`
            True if there is an associated temporal entry, else False.
        """
        return invite_code in self._temporal_cache.keys()

    def is_user_registered(self, invite_code: str) -> bool:
        """
        Checks if an inviation link is registered.

        Parameters
        ----------
        `invite_code`: :class:`str`
            The invite code part of an invitation url.

        Returns
        -------
        :class:`bool`
            True if the invite link is registered, else false.
        """
        registered = self._data_manager.is_registered_invitation(invite_code)
        if registered is False:
            return False
        invite_entry = self._data_manager.get_registered_invite(invite_code)
        if invite_entry is None:
            return False
        return invite_entry["type"] == 2

    def is_captcha_registered(self, invite_code: str) -> bool:
        """
        Checks if an invitation link has been registered by the Captcha module. Invitations registered
        by the captcha module programmatically are links created after a successful captcha.
        """
        registered = self._data_manager.is_registered_invitation(invite_code)
        if registered is False:
            return False
        invite_entry = self._data_manager.get_registered_invite(invite_code)
        if invite_entry is None:
            return False
        return invite_entry["type"] == 1

    async def is_vanity_link(self, invite_code: str):
        main_guild: Union[None, Guild] = self._bot.get_guild(config.MAIN_SERVER)
        if main_guild is None:
            raise Exception("Main guild not set.")
        v_invite = await main_guild.vanity_invite()
        if v_invite is None:
            return False
        return v_invite.id is invite_code

    async def create_temporal_entry(self, invite_code: str):
        """
        Creates a temporal entry.

        A temporal entry is a dictionary entry comprosing of time sensitive data, used in the determination
        process of potential bot attacks on invitation urls that are not registered with the feature, thus
        allowing users to join the main guild without going through captcha.

        The follwing data is stored in a temporal entry:
        1. 'started'
            This is a variable that stored the time the temporal entry was first created. The value is the time of
            creation in seconds.
        2. 'finished'
            This is a variable that stores the time the temporal entry was first created in seconds and adds the timeout
            value to the time value, creating the time that the temporal entry will expire.
        3. 'uses'
            This varliable is a list of members who have used the invitation url associated with this temporal entry.
            What is stored is their member id, so that it can be references when the member limit has been met or
            exceeded on this invitation url.
        """
        is_vanity = await self.is_vanity_link(invite_code)
        self._temporal_cache[invite_code] = {
            "started": time.time(),
            "finished": (time.time() + self._member_join_timeout)
            if is_vanity is False
            else (time.time() + self._member_vanity_join_timeout),
            "uses": [],
        }

    def add_member_to_temporal_entry(self, invite_code: str, member_id: int):
        """
        Adds a member to the temporal entry of a cached invitation.

        Parameters
        ----------
        `invite_code` :class:`str`
            The code part of an invitation url.
        `member_id` :class:`int`
            The id of the member that used the invitation.
        """
        self._temporal_cache[invite_code]["uses"].append(member_id)

    def get_temporal_entry(self, invite_code: str) -> dict:
        """
        Fetches a temporal entry if the entry associated with the supplied invite code
        is present in the cache.

        Parameters
        ----------
        `invite_code`: :class:`str`
            The invite code part of the invitation url.

        Returns
        -------
        :class:`dict`
            A dictionary object or None if the invite_code doesn't associate with any temporal entry.
        """
        return self._temporal_cache[invite_code]

    def remove_temporal_entry(self, invite_code: str):
        """
        Removes a temporal entry from the temporal entry cache.

        Parameters
        ----------
        `invite_cache`: :class:`str`
            The invite code part of the invitation url.

        """
        del self._temporal_cache[invite_code]

    async def is_cached(self, invite_code: str) -> bool:
        """
        Checks if an invitation is in the cache.

        Parameters
        ----------
        `invite_code`: :class:`str`
            The invite code part of the invitation url.

        Returns
        -------
        :class:`bool`
            True if the invite code is in the cache, else False.
        """
        return invite_code in self._cache.keys()

    async def load(self):
        """
        Loads all invites and the current number of uses into a cache.
        This cache will be used in the process of determining which invite was
        used when a user joins the guild.
        """
        self._logger.info("Loading the TrackerManager.")
        self._main_guild = self._bot.get_guild(config.MAIN_SERVER)
        self._module = self._bot.captcha
        self._data_manager = self._module.get_data_manager()
        self._minimum_member_count = self._module.get_module_settings()[
            "unregistered_invitations"
        ][
            "minimum_member_count"
        ]  # This is the number of members that can join with n number of seconds before it is considered to be a bot attack.
        self._member_join_timeout = self._module.get_module_settings()[
            "unregistered_invitations"
        ][
            "join_timeout"
        ]  # This is the number of seconds, the 'timeout' that is used to determine whether a bot attack is happening on a unprotected invitiation.
        self._member_vanity_join_timeout = self._module.get_module_settings()[
            "vanity_link"
        ]["unregistered_invitations"]["join_timeout"]
        self._minimum_vanity_member_count = self._module.get_module_settings()[
            "vanity_link"
        ]["unregistered_invitations"]["minimum_member_count"]
        invites: list[Invite] = await self._main_guild.invites()
        for invite in invites:
            self._invite_cache[invite.id] = invite.uses
        self._logger.info(
            f"TrackerManager loaded; Loaded {len(invites)} invites into memory."
        )

    async def on_member_join(self, member: Member):
        """
        Handles the on_member_join event on the TrackerManager level. This will manage adding member ids to 'uses'
        as well as checking if a member has joined on a invitation link before the timeout on that link has elapsed.
        If they join before the elapsed time then the TrackerManager will consider all previous joins that joined
        within the timeout time to be bots and kick them. It will also send a direct message to those kicked asking
        for them to join through a Gateway Guild. The invite they used will also be removed too.
        """
        self._logger.info(f"Member joined guild {member.guild.name}")
        guild_id = member.guild.id

        if guild_id != config.MAIN_SERVER:
            return

        invites = await self._main_guild.invites()  # The Discord invites.
        invite_used = None

        for invite in invites:
            uses = self._invite_cache[invite.id]
            if invite.uses > uses:
                invite_used = invite

        if invite_used is None:
            self._logger.info(
                f"Couldn't determine which invite member {member.display_name} joined with."
            )
            return
        else:
            self._logger.info(
                f"Member {member.display_name} joined from invite {invite_used.id}"
            )
            if self.is_captcha_registered(invite_used.id):
                self._logger.info(
                    f"Member {member.display_name} joined from captcha registered invite. Deleting invite."
                )
                self._data_manager.remove_registered_invitation(invite_used.id)
                await invite_used.delete(
                    reason="Captcha invite. Deleting after single use."
                )
                return

        if self.is_user_registered(invite_used.id):
            return

        if self.has_temporal_entry(invite_used.id) is False:
            await self.create_temporal_entry(invite_used.id)

        self.add_member_to_temporal_entry(invite_used.id, member.id)
        entry = self.get_temporal_entry(invite_used.id)
        is_vanity = await self.is_vanity_link(invite_used.id)

        if entry["finished"] >= time.time():
            if len(entry["uses"]) >= (
                self._minimum_member_count
                if is_vanity is False
                else self._minimum_vanity_member_count
            ):
                self._logger.info(f"Potential bot attack detected on {invite_used.id}.")
                used_unregistered_message = self._module.get_module_settings()[
                    "messages"
                ]["used_unregistered_message"]

                for member_id in entry["uses"]:
                    e_member: discord.Member = member.guild.get_member(member_id)
                    dm_channel: Union[TextChannel, None] = e_member.dm_channel
                    if dm_channel is None:
                        dm_channel = await e_member.create_dm()

                    invite: Invite = await self._module.get_invitation_to_gateway()
                    await dm_channel.send(
                        used_unregistered_message.replace("{invite}", invite.url)
                    )
                    await e_member.kick(
                        reason=f"Considered a bot by Captcha Gateway, using invite {invite.url}."
                    )

                if is_vanity is False:
                    self._logger.info(
                        f"Deleting invitation link {invite_used.url} as it was determined by Tracker Manager in Captcha Gateway to be used for a potential bot attack."
                    )
                    await invite_used.delete(reason="Used in a potential bot attack.")
                self.remove_temporal_entry(invite_used.id)
        else:
            self._logger.info(
                f"Removing temporal entry associated with {invite_used.url} because a potential bot attack was not detected."
            )
            self.remove_temporal_entry(invite_used.id)

    async def on_invite_create(self, invite: Invite):
        if invite.guild.id != config.MAIN_SERVER:
            return

        self._invite_cache[invite.id] = invite.uses
        self._logger.info(
            f"Invite created. Added invitation link {invite.id} to the invite link cache."
        )

    async def on_invite_delete(self, invite: Invite):
        if invite.guild.id != config.MAIN_SERVER:
            return

        if invite.id in self._temporal_cache.keys():
            del self._temporal_cache[invite.id]
        if invite.id in self._temporal_cache.keys():
            del self._invite_cache[invite.id]

        self._logger.info(
            f"Invite link deleted. Removing invitation link {invite.id} from the invite link cache."
        )


class CaptchaChannel:
    def __init__(
        self,
        bot,
        g_guild,
        member: Optional[Member],
    ):
        """
        A Captcha Channel is a Class that handles a Text Channel that'll contain the captcha image for a user to decipher
        and answer. This entire class managed all interactions the user will have with that captcha image.
        """
        self._member = member
        self._g_guild = g_guild
        self._data_manager: DataManager = bot.captcha.get_data_manager()
        self._guild: Guild = g_guild.get_guild()
        self._answer_text = None
        self._started = False
        self._member = member
        self._bot = bot
        self._tries = 5
        self._invite = None
        self._completed = False
        self._ttl = bot.captcha.get_config()["captcha_time_to_live"]
        self._ttl_message_sent = False
        self._internal_clock = 0
        self._active = False
        self._logger = bot.logger
        bot.add_listener(self.on_message, "on_message")

    def get_ttl(self):
        """
        Returns the time to live. The amount of time this captcha channel has to live until it gets deleted.
        """
        return self._ttl

    def is_active(self):
        """
        Returns whether or not this channel is active. If it is active then the channel is waiting for a user to enter a captcha.
        If inactive the captcha is done and this channel should have it's channel deleted.
        """
        return self._active

    def has_completed(self):
        """
        Returns whether the captcha was completed successfully or not.
        """
        return self._completed

    def get_name(self):
        """
        Returns the name of the channel.
        """
        return self._channel.name

    def get_gateway_guild(self):
        """
        Returns the gateway guild this channel belongs to.
        """
        return self._g_guild

    def has_completed_captcha(self):
        """
        Returns whether the captcha was completed successfully or not.
        """
        return self._completed

    def get_invite(self) -> Union[Invite, None]:
        """
        Get the invite created when the Captcha was completed successfully.
        """
        return self._invite

    def get_id(self):
        """
        Returns the id of the channel.
        """
        return self._channel.id

    def get_tries(self):
        """
        Returns the amount of tries the member associated with this channel has left.
        """
        return self._tries

    def get_member(self):
        """
        Returns the member associated with this channel.
        """
        return self._member

    @timers.loop(seconds=1)
    async def countdown(self):
        """
        The countdown manages the countdown timer. When this time reaches 0, and the user has no completed the captcha, the channel will be deleted and the user will be blacklisted for a time.
        """

        async def alert():
            minutes = math.floor(self._ttl / 60)
            time_value = minutes if minutes > 0 else self._ttl
            time_unit = (
                ("minutes" if minutes > 1 else "minute")
                if minutes > 0
                else ("seconds" if self._ttl > 1 else "second")
            )
            embed: discord.Embed = discord.Embed(
                colour=config.EMBED_COLOUR,
                description=self._bot.captcha.get_config()["messages"][
                    "countdown_alert_message"
                ]
                .replace("{time_unit}", time_unit)
                .replace("{time_value}", time_value),
                title=self._bot.captcha.get_config()["messages"][
                    "countdown_alert_message_title"
                ],
            )
            await self._channel.send(embed=embed)

        self._ttl -= 1
        self._internal_clock += 1
        if self._internal_clock >= 60:
            self._data_manager.update_captcha_channel(
                self._guild.id, self._channel.id, {"ttl": self._ttl}
            )
            self._internal_clock = 0

        if self._ttl >= 600:
            minutes = self._ttl / 60
            if minutes in [10, 5, 4, 3, 2, 1]:
                await alert()
            if self._ttl in [30, 15, 10, 5]:
                await alert()

        if self._ttl <= 0:
            default_ttl = self._bot.captcha.get_config()["captcha_time_to_live"]
            minutes = math.floor(default_ttl / 60)
            time_value = minutes if minutes > 0 else default_ttl
            time_unit = (
                ("minutes" if minutes > 1 else "minute")
                if minutes > 0
                else ("seconds" if default_ttl > 1 else "second")
            )

            if self._ttl_message_sent is False:
                time_elapsed_message_title = self._bot.captcha.get_module_settings()[
                    "messages"
                ]["time_elapsed_message_title"]
                time_elapsed_message = self._bot.captcha.get_module_settings()[
                    "messages"
                ]["time_elapsed_message"]
                time_elapsed_message = time_elapsed_message.replace(
                    "{time_unit}", str(time_unit)
                ).replace("{time_value}", str(time_value))
                embed: discord.Embed = discord.Embed(
                    colour=config.EMBED_COLOUR,
                    title=time_elapsed_message_title,
                    description=time_elapsed_message,
                )

                await self._channel.send(embed=embed)
                self._ttl_message_sent = True

            if self._ttl <= -10:
                self.countdown.stop()
                self._data_manager.update_captcha_channel(
                    self._guild.id,
                    self._channel.id,
                    {
                        "active": False,
                        "stats": {"completed": False, "failed": True},
                        "ttl": 0,
                    },
                )
                if self._bot.captcha.is_operator(self._member.id) is False:
                    if self._data_manager.is_blacklisted(self._member.id):
                        return

                    await self._member.ban(
                        reason="Failed to complete Captcha assessment."
                    )
                    self._data_manager.add_member_to_blacklist(
                        self._member, 900, "Failed to complete Captcha assessment."
                    )

                await self.destory()

    async def start(self, **kwargs):
        """
        Starts the Captcha process.
        """
        if kwargs.get("channel_id") is None:
            channel_name = random_chars(12)
            self._channel: TextChannel = await self._g_guild.get_guild().create_text_channel(
                name=channel_name,
                category=self._g_guild.get_main_category(),
                overwrites={
                    self._g_guild.get_guild().default_role: discord.PermissionOverwrite(
                        view_channel=False, read_message_history=False
                    ),
                    self._member: discord.PermissionOverwrite(
                        view_channel=True,
                        read_messages=True,
                        send_messages=True,
                        read_message_history=True,
                    ),
                },
            )
        else:
            self._channel = self._guild.get_channel(kwargs["channel_id"])

        if kwargs.get("tries"):
            self._tries = kwargs["tries"]

        if kwargs.get("member_id"):
            member = self._guild.get_member(kwargs.get("member_id"))
            if member is None:
                self._bot.logger.info(
                    f"Couldn't find member under id {kwargs.get('member_id')}."
                )
                return
            self._member = member

        main_guild = self._bot.get_guild(config.MAIN_SERVER)
        main_member = main_guild.get_member(self._member.id)

        if kwargs.get("completed"):
            if main_member is not None:
                await self._member.kick()
                return

        if kwargs.get("ttl"):
            self._ttl = kwargs["ttl"]

        self._started = True
        self.countdown.start()
        self._active = True

        if len(kwargs.keys()) == 0:
            self._data_manager.add_captcha_channel(self)
        else:
            minutes = math.floor(self._ttl / 60)
            time_value = minutes if minutes > 0 else self._ttl
            time_unit = (
                ("minutes" if minutes > 1 else "minute")
                if minutes > 0
                else ("seconds" if self._ttl > 1 else "second")
            )

            embed: discord.Embed = discord.Embed(
                colour=config.EMBED_COLOUR,
                description=self._bot.captcha.get_config()["messages"][
                    "bot_startup_captcha_message"
                ]
                .replace("{time_unit}", time_unit)
                .replace("{time_value}", str(time_value))
                .replace("{try_count}", str(self._tries)),
                title="Bot started.",
            )
            await self._channel.send(embed=embed)
        await self.send_captcha_message()

    def construct_embed(self):
        """
        Constructs the embed that'll contain the captcha image.

        Returns
        -------
        :class:`discord.Embed`
            A Discord Embed that contains a captcha image.
        """
        image, text = self._bot.captcha.create_captcha_image()
        image_file = discord.File(fp=image, filename="captcha.png")
        self._answer_text = text
        embed: discord.Embed = discord.Embed(
            colour=config.EMBED_COLOUR,
            title=self._bot.captcha.get_config()["messages"][
                "captcha_message_embed_title"
            ]
            .replace("{current_try}", str(self.get_tries()))
            .replace("{tries_left}", str(self.get_tries() - 1)),
            description=self._bot.captcha.get_config()["messages"][
                "captcha_message_embed_description"
            ],
        )
        embed.set_image(url="attachment://captcha.png")
        return embed, image_file

    async def send_captcha_message(self):
        """
        Sends the captcha message into the channel.
        """
        if self._tries != 0:
            embed, image_file = self.construct_embed()
            await self._channel.send(file=image_file, embed=embed)
        else:
            embed: discord.Embed = discord.Embed(
                color=config.EMBED_COLOUR,
                title=self._bot.captcha.get_config()["messages"][
                    "failed_captcha_message_title"
                ],
                description=self._bot.captcha.get_config()["messages"][
                    "failed_captcha_message"
                ],
            )
            await self._channel.send(embed=embed)

    async def on_message(self, message: discord.Message):
        """
        The on_message function called in the cogs/events.py script. Handles the text coming from the user.
        """
        if message.author.id == self._bot.user.id:
            return

        if message.channel.id != self._channel.id:
            return

        if message.guild.id != self._guild.id:
            return

        if self._started is False:
            return

        if self._answer_text is None:
            return

        if self._completed:
            return

        if message.content.lower() != self._answer_text:
            await self._channel.send("Incorrect.")
            self._tries = self._tries - 1 if self._tries > 0 else 0
            self._data_manager.update_captcha_channel(
                self._guild.id, self._channel.id, {"tries": self._tries}
            )
            await self.send_captcha_message()
            if self._tries == 0:
                await asyncio.sleep(10)
                self._data_manager.update_captcha_channel(
                    self._guild.id,
                    self._channel.id,
                    {"active": False, "stats": {"completed": False, "failed": True}},
                )
                if self._bot.captcha.is_operator(self._member.id) is False:
                    if self._bot.captcha.is_blacklisted(self._member.id):
                        return

                    self._data_manager.add_blacklisted_member(self._member)
                    reason = "Failed to complete Captcha assessment in time.."

                    self._data_manager.add_member_to_blacklist(
                        self._member,
                        self._bot.captcha.get_config()["blacklist_length"],
                        reason,
                    )
                    self._logger.info(
                        f"Banning member {self._member.display_name}/{self._member.id} for failing to complete Captcha."
                    )
                    await self._member.ban(reason=reason)
        else:
            self._invite = await self.create_tldr_invite()
            if self._invite is None:
                await self._channel.send(
                    "Failed to create invitation link. This is likely due to incorrect configuration. Please try to contact someone using the ticketing system provided."
                )
                return
            url = self._invite.url
            embed: discord.Embed = discord.Embed(
                color=config.EMBED_COLOUR,
                title=self._bot.captcha.get_config()["messages"][
                    "completed_captcha_message_title"
                ],
                description=self._bot.captcha.get_config()["messages"][
                    "completed_captcha_message"
                ].replace("{invite_url}", url),
            )
            self._completed = True
            await self._channel.send(embed=embed)
            self._data_manager.update_captcha_channel(
                self._guild.id,
                self._channel.id,
                {
                    "active": False,
                    "stats": {"completed": True, "failed": False},
                    "ttl": 0,
                },
            )

    async def create_tldr_invite(self):
        """
        Creates a single use, 2 minute ttl value, invite. Used when they complete the Captcha.

        Returns
        -------
        :class:`discord.Invite`
            A discord invite instance.
        """
        main_guild: Guild = discord.utils.get(self._bot.guilds, id=config.MAIN_SERVER)
        settings = self._bot.captcha.get_config()
        main_channel: TextChannel = discord.utils.get(
            main_guild.text_channels, id=settings["main_guild_landing_channel"]
        )
        if main_channel is None:
            self._logger.info(
                "WARNING: main_guild_landing_channel config variable in Captcha Gateway Config not set. This variable should point to the landing channel on the main server."
            )
            return

        invite: Invite = await main_channel.create_invite(max_age=120, max_uses=2)
        self._data_manager.add_registered_invitation(
            invite.id, 1
        )  # Registering captcha invite.
        return invite

    async def destory(self):
        """
        Deletes the channel.
        """
        await self._channel.delete()


class GatewayGuild:
    def __init__(self, bot, data_manager: DataManager, **kwargs):
        """
        A Gateway Guild is a guild that a user first enters to complete a Captcha via a Captcha Channel.
        This class managed all interactions on a Guild level.
        """
        self._bot = bot
        self._logger = bot.logger
        self._data_manager = data_manager
        self._kwargs = kwargs
        self._category = None
        self._captcha_channels = {}

    async def load(self):
        """
        The functions that loads all information from Mongo collections into instances, or is used in the instantiation of instances, such as captcha channels.
        """
        if "guild" in self._kwargs:
            self._guild: Guild = self._kwargs["guild"]
            self._id: int = self._guild.id

        if "guild_id" in self._kwargs:
            self._guild: Guild = self._bot.get_guild(self._kwargs["guild_id"])
            if self._guild is not None:
                self.id: int = self._guild.id

        if "landing_channel_id" in self._kwargs:
            self._landing_channel: TextChannel = self._guild.get_channel(
                self._kwargs["landing_channel_id"]
            )
        else:
            landing_channel_name = self._bot.captcha.get_config()[
                "landing_channel_name"
            ]
            landing_channel = await self._guild.create_text_channel(
                landing_channel_name.replace(
                    "{number}", str(len(self._bot.captcha.get_gateway_guilds()) + 1)
                ),
                overwrites={
                    self.get_guild().default_role: discord.PermissionOverwrite(
                        read_messages=True, send_messages=False, view_channel=True
                    )
                },
            )
            landing_channel_message = self._bot.captcha.get_config()["messages"][
                "welcome_message"
            ].replace("{guild_name}", self._guild.name)
            # Add welcome message here; make welcome message configurable.
            await landing_channel.send(landing_channel_message)
            self._landing_channel: TextChannel = landing_channel

        roles = self._guild.roles

        if len(list(filter(lambda r: r.name.lower() == "operator", roles))) == 0:
            self._bot.logger.info(
                f"No Operator role found on {self._guild.name}, creating one..."
            )
            await self._guild.create_role(
                name="Operator",
                color=Colour.dark_gold(),
                permissions=discord.Permissions(8),
            )
        else:
            self._bot.logger.info(f"Found Operator role on {self._guild.name}.")

        main_guild = self._bot.get_guild(config.MAIN_SERVER)

        for member in self._guild.members:
            if member.bot:
                continue
            if self._bot.captcha.is_operator(member.id):
                continue
            if main_guild.get_member(member.id):
                self._logger.info(
                    f"Kicked user {member.display_name}/{member.id} from {self._guild.name} beacuse they were"
                    "already on the main guild."
                )
                await member.kick()

    async def get_permantent_invite(self) -> Invite:
        invites: list[Invite] = await self._guild.invites()

        for invite in invites:
            if invite.max_uses == 0 and invite.max_age == 0:
                return invite
        return await self._landing_channel.create_invite()

    async def transfer(self, new_owner: Member):
        """
        Transfers the ownership of a Gateway Guild to a new member.

        Parameters
        ----------
        new_owner: :class:`Member`
            The guild member who will become the new owner of this guild.
        """
        try:
            await self._guild.edit(owner=new_owner)
            self._bot.captcha.get_gateway_guilds().remove(self)
            return True
        except:
            return False

    def get_user_count(self):
        """
        Returns the user count.

        Returns
        -------
        :class:`int`
            Returns the number of members on this guild.
        """
        return len(self._guild.members)

    def has_captcha_channel(self, member_id: int) -> bool:
        """
        Returns whether or not a member has a captcha channel or not.

        Returns
        -------
        :class:`bool`
            If true the member has a captcha channel, if False the member doesn't have a captcha channel.
        """
        return member_id in self._captcha_channels.keys()

    def get_captcha_channel(self, member_id: int) -> Union[CaptchaChannel, None]:
        """
        Fetches a captcha channel assocated with a member.

        Parameters
        ----------
        member_id: :class:`int`
            The id of a member on the Gateway Guild.
        Returns
        -------
        :class:`CaptchaChannel`
            Returns a captcha channel instance if the member has one.
        """
        return self._captcha_channels[member_id]

    def add_captcha_channel(self, member_id: int, channel: CaptchaChannel):
        """
        Add a captcha channel to the dictionary of captcha channels.

        Parameters
        ----------
        member_id: :class:`int`
            The id of a member on the Gateway Guild.
        channel: :class`CaptchaChannel`
            A Captcha Channel instance.
        """
        self._captcha_channels[member_id] = channel

    async def delete(self):
        """
        Deletes a Gateway Guild.
        """
        self._data_manager.remove_guild(self._id)
        # Need to write in here a better way to delete a gateway guild. I need to check if this is the only guild within the list, then check if people are in the guild doing captchas before I delete the guild.
        try:
            await self._guild.delete()
            await self._bot.captcha.rm_gateway_guild_from_cache(self)
            return True
        except (HTTPException, Forbidden) as ignore:
            return False

    def get_landing_channel(self) -> Union[TextChannel, None]:
        """
        Returns the landing channel of this guild. This is the channel that invites are created from, usually called
        'welcome'.
        """
        return self._landing_channel

    def get_main_category(self):
        """
        Gets the main category for channels to enter into.
        """
        if self._category is None:
            for category in self._guild.categories:
                if category.name.lower() == "tldr gateway":
                    self._category = category
                    break
        return self._category

    def get_name(self) -> str:
        """
        Returns the name of the guild.
        """
        return self._guild.name

    def get_id(self) -> int:
        """
        Returns the id of the guild.
        """
        return self._id

    def get_guild(self) -> Guild:
        """
        Returns the raw guild instance.
        """
        return self._guild

    def create_captcha_channel(self, for_member: Member):
        """
        Creates a Captcha Channel for a member.

        Parameters
        ----------
        for_member: :class:`discord.Member`

        Returns
        -------
        :class:`CaptchaChannel`
            Returns a CaptchaChannel instance.
        """
        captcha_channel = CaptchaChannel(self._bot, self, for_member)
        self._captcha_channels[for_member.id] = captcha_channel
        return captcha_channel

    async def delete_captcha_channel(self, member: Member):
        """
        Delete a CaptchaChannel.

        Parameters
        ----------
        member: :class:`discord.Member`
            The member the CaptchaChannel was made for.
        """
        captcha_channel = self._captcha_channels[member.id]
        if captcha_channel is None:
            return
        await captcha_channel.destory()
        del self._captcha_channels[member.id]

    async def on_member_join(self, member: Member):
        """
        An event. Handles all guild level interactions for this specific event.
        """
        captcha_module = self._bot.captcha
        user_id = member.id

        blacklist_entry = (
            self._bot.captcha.get_data_manager().get_blacklisted_member_info(member.id)
        )
        if blacklist_entry:
            await member.ban(reason="Is a blacklisted member. Banned on join attempt.")

        if len(self._guild.members) in [100, 200, 300, 400, 500]:
            await captcha_module.announce(
                f"{self._guild.name} reached {self._guild.members} members", self._guild
            )

        if captcha_module.is_operator(user_id):
            roles = member.guild.roles
            op_roles = list(filter(lambda r: r.name.lower() == "operator", roles))
            if len(op_roles) != 0:
                await member.add_roles(op_roles[0])
                self._bot.logger.info(
                    f"Added Operator role to {member.name} on {member.guild.name} guild."
                )
        else:
            channel: CaptchaChannel = self.create_captcha_channel(member)
            await channel.start()

    async def on_member_leave(self, member: Member):
        """
        Handles all interactions with this event on a guild level.
        """
        if self.has_captcha_channel(member.id):
            await self.delete_captcha_channel(member)
            is_operator = self._bot.captcha.is_operator(member.id)
            if is_operator is False:
                self._data_manager.update_captcha_counter(member.id, 1)
            settings = self._bot.settings_handler.get_settings(config.MAIN_SERVER)[
                "modules"
            ]["captcha"]
            counter_entry = self._data_manager.get_captcha_counter(member.id)
            if (
                counter_entry is not None
                and counter_entry["counter"] >= settings["gateway_rejoin"]["limit"]
                and is_operator is False
            ):
                bans = await self._guild.bans()

                for ban in bans:
                    if ban.user.id == member.id:
                        return

                self._data_manager.add_blacklisted_member(member)
                self._data_manager.add_member_to_blacklist(
                    member,
                    self._bot.captcha.get_config()["gateway_rejoin"][
                        "blacklist_duration"
                    ],
                    "Rejoined a Gateway Guild too often.",
                )

                reason = f"Banned member {member.name} for joining and leaving {settings['gateway_rejoin']['limit']} times."
                await member.ban(reason=reason)
                self._bot.logger.info(reason)


class CaptchaModule:
    def __init__(self, bot):
        """
        This feature is meant to prevent bots from easily invading the server and spammning everyone with friend requests.
        This feature requests every user to prove they are human by entering into a channel the answer to a classic Captcha image.
        """
        self._gateway_guilds = []
        self._data_manager = DataManager(bot.logger)
        self._settings_handler: SettingsHandler = bot.settings_handler
        self._bot = bot
        self._logger = bot.logger
        self._image_captcha = ImageCaptcha(width=360, height=120)
        self._announcement_channel = None
        self.unban_task.start()
        self._tracker_manager = TrackerManager(bot)
        self._default_settings = {
            "operators": [],
            "guild_name": "Gateway Guild {number}",
            "landing_channel_name": "welcome",
            "main_guild_landing_channel": None,
            "captcha_time_to_live": 900,
            "blacklist_length": 86400,
            "unregistered_invitations": {
                "minimum_member_count": 1,
                "join_timeout": 10,
            },
            "vanity_link": {
                "unregistered_invitations": {
                    "minimum_member_count": 10,
                    "join_timeout": 10,
                }
            },
            "announcements": {
                "announcement_channel_id": 0,
                "scheduled_report": {"last_report": None, "interval": 86400},
            },
            "gateway_rejoin": {
                "limit": 3,
                "blacklist_duration": 86400,
                "reset_after_duration": 900,
            },
            "messages": {
                "welcome_message": "Welcome to {guild_name}! Please follow the following steps by the Family Foundation for the Foundation of Families.",
                "captcha_message_embed_title": "Try {current_try}. {tries_left} Attempts Left.",
                "captcha_message_embed_description": "Try and type the text presented in the image correctly.",
                "completed_captcha_message": "Well done! You have completed the captcha. Please click the following invite like. You will be kicked from this Gateway Guild once you have joined TLDR!\n\nInvite link: {invite_url}\n\nPS: If you share this invite link, you will be kicked off this guild having not joined the guild. This invite link only works once, and is only valid for the next two minutes.",
                "completed_captcha_message_title": "Successfully Completed Captcha.",
                "bot_startup_captcha_message": "Sorry for the inconvenence, the bot has now started up again. You have {time_value} {time_unit} remaining, and {try_count} attempts left.",
                "incorrect_captcha_message": "Incorrect. Try again :).",
                "failed_captcha_message": "You have failed all Captcha attempts this time. You will be blacklisted for 24 hours. After this blacklist time has elapsed, you may come back and try again :).",
                "failed_captcha_message_title": "Too many tries.",
                "countdown_alert_message": "You have {time_value} {time_unit} remaining.",
                "countdown_alert_message_title": "Alert!",
                "time_elapsed_message": "Your time has elapsed. You have had {time_value} {time_unit} to complete the captcha, you did not. Unfortunately this means you will be blacklisted for 24 hours after which you can rejoin a Gateway Guild and try again.",
                "time_elapsed_message_title": "Timer Elapsed",
                "used_unregistered_message": "You have used an unregistered invitation to join the main server, what is more the bot has identified you as a potential bot in a bot attack. Apologises if this is incorect. In order to rejoin, please go through our Captcha Process. {invite}",
            },
        }
        if config.MAIN_SERVER == 0:
            bot.logger.info(
                "Captcha Gateway Module required the MAIN_SERVER variable in config.py to be set to a non-zero value (a valid guild id). Will not initate module."
            )
            return

        settings = self._settings_handler.get_settings(config.MAIN_SERVER)

        if "captcha" not in settings["modules"].keys():
            self._logger.info(
                "Captcha Gateway settings not found in Guild settings. Adding default settings now."
            )
            settings["modules"]["captcha"] = self._default_settings
            self._settings_handler.save(settings)
        self._settings_handler.update(
            "captcha", self._default_settings, config.MAIN_SERVER
        )
        self._logger.info("Captcha Gateway settings found.")
        self._logger.info("Captcha Gateway Module initiated.")
        self._bot.add_listener(self.on_ready, "on_ready")
        self._bot.add_listener(
            self._tracker_manager.on_invite_create, "on_invite_create"
        )
        self._bot.add_listener(
            self._tracker_manager.on_invite_delete, "on_invite_delete"
        )

    async def on_ready(self):
        self._logger.info("Loading Captcha Gateway Module.")
        await self.load()
        self._logger.info("Loaded Captcha Gateway Module.")

    async def load(self):
        """
        Loads primarily Gateway Guilds and aids in the creation of pre-existing CaptchaChannels stored in MongoDB.
        """
        mongo_guild_ids: list = list(self._data_manager.get_guilds(False))
        valid_guild_ids = list(
            filter(
                lambda m_guild: self._bot.get_guild(m_guild["guild_id"]) is not None,
                mongo_guild_ids,
            )
        )

        if self.set_announcement_channel():
            self._bot.logger.info("Announcement channel set.")
            await self.announce(
                "Announcement Channel for the Captcha Module loaded.",
                self._bot.get_guild(config.MAIN_SERVER),
            )
        else:
            self._bot.logger.info("Announcement channel not set.")

        if len(valid_guild_ids) == 0:
            if len(self._bot.guilds) >= 10:
                return await self._bot.critical_error(
                    "Can't load Captcha Gateway Module, Bot cannot create new Guilds if it is in 10 or more Guilds."
                )
            self._logger.info("No previous Gateway Guilds active. Creating one...")
            await self.announce(
                "No previous Gateway Guilds active. Creatine one...",
                self._bot.get_guild(config.MAIN_SERVER),
            )
            g_guild = await self.create_guild()
            self._logger.info(f"Created {g_guild.get_name()}")
            self._logger.info("Added Guild to MongoDB.")
        else:
            self._logger.info("Previous Gateway Guilds found. Indexing...")
            await self.announce(
                "Previous Gateway Guilds found. Indexing...",
                self._bot.get_guild(config.MAIN_SERVER),
            )

            for m_guild in list(valid_guild_ids):
                m_guild_id = m_guild["guild_id"]
                m_guild_landing_channel_id = m_guild["landing_channel_id"]
                guild = self._bot.get_guild(m_guild_id)
                if guild is None:
                    continue
                if guild.id == m_guild_id:
                    g_guild = GatewayGuild(
                        self._bot,
                        self._data_manager,
                        guild=guild,
                        landing_channel_id=m_guild_landing_channel_id,
                    )
                    await g_guild.load()

                    mongo_captcha_channels = self._data_manager.get_captcha_channels(
                        m_guild_id, False
                    )

                    for entry in mongo_captcha_channels:
                        if guild.get_member(entry["member_id"]) is None:

                            self._data_manager.update_captcha_channel(
                                guild.id,
                                entry["channel_id"],
                                {
                                    "active": False,
                                    "stats": {"completed": True, "failed": False},
                                    "ttl": 0,
                                },
                            )
                            t_channel = guild.get_channel(entry["channel_id"])
                            if t_channel:
                                self._logger.info(
                                    f"Member under id {entry['member_id']} no longer on Gateway Guild."
                                )
                                await t_channel.delete()
                            continue

                        if entry["active"] is False:
                            continue
                        channel = CaptchaChannel(self._bot, g_guild, None)
                        await channel.start(
                            member_id=entry["member_id"],
                            tries=entry["tries"],
                            completed=entry["stats"]["completed"],
                            channel_id=entry["channel_id"],
                            ttl=entry["ttl"],
                        )
                        g_guild.add_captcha_channel(entry["member_id"], channel)

                    self._gateway_guilds.append(g_guild)
                    self._logger.info(
                        f"Found gateway {g_guild.get_name()}/{g_guild.get_id()}. Adding to Gateway Guild List."
                    )
        await self._tracker_manager.load()
        self.gateway_reset_task.start()

    def get_config(self):
        """
        Fetches the module settings for this feature.
        """
        return self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
            "captcha"
        ]

    def set_announcement_channel(self) -> bool:
        """
        Sets the announcement channel.

        Returns
        -------
        Returns true if set correctly, else False.
        """
        captcha_settings = self._settings_handler.get_settings(config.MAIN_SERVER)[
            "modules"
        ]["captcha"]
        if captcha_settings["announcements"]["announcement_channel_id"] != 0:
            self._announcement_channel = self._bot.get_guild(
                config.MAIN_SERVER
            ).get_channel(captcha_settings["announcements"]["announcement_channel_id"])
            return True
        return False

    async def announce(self, message: str, guild: discord.Guild):
        """Sends an announcement embed on the announcement channel."""
        if self._announcement_channel:
            embed: discord.Embed = discord.Embed(
                colour=config.EMBED_COLOUR,
                description=message,
                title=f"Captcha Announcement",
            )
            await self._announcement_channel.send(embed=embed)

    def get_operators(self) -> list[int]:
        """
        Returns a list of operators. Operators are essentially Admins on Gateway Guilds.
        """
        return self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
            "captcha"
        ]["operators"]

    def add_operator(self, member_id: int):
        """
        Add a member to the operator list.

        Parameters
        ----------
        member_id: :class:`int`
            The id of the member to add.
        """
        operators: list[int] = self._settings_handler.get_settings(config.MAIN_SERVER)[
            "modules"
        ]["captcha"]["operators"]

        operators.append(member_id)
        self._settings_handler.save(
            self._settings_handler.get_settings(config.MAIN_SERVER)
        )

    def remove_operator(self, member_id: int):
        """
        Add a member to the operator list.

        Parameters
        ----------
        member_id: :class:`int`
            The id of the member to add.
        """
        operators: list[int] = self._settings_handler.get_settings(config.MAIN_SERVER)[
            "modules"
        ]["captcha"]["operators"]

        operators.remove(member_id)
        self._settings_handler.save(
            self._settings_handler.get_settings(config.MAIN_SERVER)
        )

    def is_operator(self, member_id: int):
        """
        Checks if a member is an operator or not.

        Parameters
        ----------
        member_id: :class:`int`
            The id of a member.

        Returns
        -------
        :class:`bool`
            Returns True if member is an operator, else False.
        """
        operators: list[int] = self._settings_handler.get_settings(config.MAIN_SERVER)[
            "modules"
        ]["captcha"]["operators"]
        return member_id in operators

    def rm_gateway_guild_from_cache(self, guild_id: int):
        """
        Removes a Gateway Guild from the cache.

        Parameters
        ----------
        guild_id: :class:`int`
            The id of the Guild that is a Gateway Guild.
        """
        for g_guild in self._gateway_guilds:
            if g_guild.get_guild().id == guild_id:
                self._gateway_guilds.remove(g_guild)
                break

    def create_captcha_image(self):
        """
        Creates a captcha image.

        Returns
        -------
        :class:`tuple`
            A tuple with first the image in converted into bytes, and second the answer in text (string).
        """
        text = random_chars(6)
        captcha_image = self._image_captcha.generate_image(text)
        image_bytes = io.BytesIO()
        captcha_image.save(image_bytes, "PNG")
        image_bytes.seek(0)
        return image_bytes, text

    async def create_guild(self) -> GatewayGuild:
        """
        Creates a Gateway Guild.
        """
        guild_name_format = self._settings_handler.get_settings(config.MAIN_SERVER)[
            "modules"
        ]["captcha"]["guild_name"]
        guild = await self._bot.create_guild(
            guild_name_format.replace("{number}", str(len(self._gateway_guilds) + 1)),
            code="77ZnuJafvEQK",
        )
        g_guild = GatewayGuild(
            self._bot, self._data_manager, guild=guild, first_load=True
        )
        await g_guild.load()
        self._data_manager.add_guild(guild.id, g_guild.get_landing_channel().id)
        self._gateway_guilds.append(g_guild)
        self._logger.info(f"Created gateway guild {g_guild.get_name()}")
        return g_guild

    def get_gateway_guilds(self) -> list[GatewayGuild]:
        """
        Returns the Gateway Guilds cache. A list of Gateway Guilds.
        """
        return self._gateway_guilds

    def is_gateway_guild(self, guild_id: int) -> bool:
        """
        Checks if a Guild is a Gateway Guild or not.

        Returns
        -------
        :class:`bool`
            Returns True if the Guild is a Gateway Guild, else False.
        """
        for guild in self._gateway_guilds:
            if guild.get_id() == guild_id:
                return True
        return False

    def get_gateway_guild(self, guild_id: int) -> Union[GatewayGuild, None]:
        """
        Returns a Gateway Guild.

        Parameters
        ----------
        guild_id: :class:`int`
            Id of a Guild that is also a Gateway Guild.

        Returns
        -------
        :class:`GatewayGuild`
            Returns a Gateway Guild or None.
        """
        for g_guild in self._gateway_guilds:
            if g_guild.get_id() == guild_id:
                return g_guild
        return None

    def get_data_manager(self) -> DataManager:
        """
        Returns the DataManager instance.
        """
        return self._data_manager

    def get_settings(self):
        # This will need to be removed at a later date.
        return self._settings_handler.get_settings(config.MAIN_SERVER)

    def get_module_settings(self):
        return self.get_settings()["modules"]["captcha"]

    async def unban(self, member_id: int):
        """
        Used to unban members on all active Gateway Guilds.

        Parameters
        ----------
        member_id: :class:`int`
            The id of the member to unban.
        """
        # Used primarily to unblacklist a member on all active guilds.
        for g_guild in self._gateway_guilds:
            guild: Guild = g_guild.get_guild()
            guild_bans = await guild.bans()

            for ban in guild_bans:
                if ban.user.id == member_id:
                    await guild.unban(user=ban.user)

    @timers.loop(minutes=1)
    async def unban_task(self):
        """
        Unbans members from Gateway Guilds that were on the blacklist if the time has elapsed.
        """
        blacklist = self._data_manager.get_blacklist()

        now = time.time()
        cache_members_to_remove = []

        for entry in blacklist:
            if entry["ends"] <= now:
                await self.unban(entry["mid"])
                blacklist_member = self._data_manager.get_blacklisted_member(
                    entry["mid"]
                )

                if blacklist_member:
                    self._logger.info(
                        f"Removing {blacklist_member['name']}/{blacklist_member['mid']} from blacklist."
                    )
                else:
                    self._logger.info(
                        f"Removed a member from blacklist. Failed to find username associated with the member in the cache."
                    )
                self._data_manager.remove_member_from_blacklist(entry["mid"])
                cache_members_to_remove.append(entry["mid"])

        captcha_counter_entries = self._data_manager.get_captcha_counters()
        captcha_counter_cooldown_seconds = self._settings_handler.get_settings(
            config.MAIN_SERVER
        )["modules"]["captcha"]["gateway_rejoin"]["cooldown"]

        for entry in captcha_counter_entries:
            if (entry["updated_at"] + captcha_counter_cooldown_seconds) <= time.time():
                await self.unban(entry["mid"])
                self._data_manager.remove_member_from_blacklist(entry["mid"])
                blacklist_member = self._data_manager.get_blacklisted_member(
                    entry["mid"]
                )
                cache_members_to_remove.append(entry["mid"])
                await self.unban(entry["mid"])
                if blacklist_member:
                    self._logger.info(
                        f"Removing {blacklist_member['name']}/{blacklist_member['mid']} from blacklist and resetting relog counter."
                    )
                else:
                    self._logger.info(
                        f"Removing member from blacklist and resetting relog counter."
                    )
        self._data_manager.delete_blacklisted_members(cache_members_to_remove)

    async def set_setting(self, path: str, value: object):
        settings = self._settings_handler.get_settings(config.MAIN_SERVER)

        def keys():
            def walk(key_list: list, branch: dict, full_branch_key: str):
                walk_list = []
                for key in branch.keys():
                    if type(branch[key]) is dict:
                        walk(key_list, branch[key], f"{full_branch_key}.{key}")
                    else:
                        walk_list.append(f"{full_branch_key}.{key}".lower())

                key_list.extend(walk_list)
                return key_list

            key_list = []

            for key in settings.keys():
                if type(settings[key]) is dict:
                    key_list = walk(key_list, settings[key], key)
                else:
                    key_list.append(key.lower())
            return key_list

        path = f"modules.captcha.{path}"
        if path.lower() in keys():
            split_path = path.split(".")
            parts_count = len(split_path)

            def walk(parts: list[str], part: str, branch: dict):
                if parts.index(part) == (parts_count - 1):
                    branch[part] = value
                    self._settings_handler.save(settings)
                else:
                    walk(parts, parts[parts.index(part) + 1], branch[part])

            if parts_count == 1:
                settings[path] = value
            else:
                walk(split_path, split_path[0], settings)

        if "welcome_message" in path:
            for g_guild in self._gateway_guilds:
                landing_channel: TextChannel = g_guild.get_landing_channel()
                await landing_channel.purge()
                welcome_message = self.get_module_settings()["messages"][
                    "welcome_message"
                ]
                await landing_channel.send(
                    welcome_message.replace("{guild_name}", g_guild.get_guild().name)
                )

    def construct_scheduled_report_embed(self, automatic: bool = False):
        last_update = self.get_settings()["modules"]["captcha"]["announcements"][
            "scheduled_report"
        ]["last_report"]
        formatted_last_update = (
            datetime.fromtimestamp(last_update).strftime("%Y-%m-%d %H:%M:%S")
            if last_update is not None
            else None
        )
        channels = list(
            (
                self._data_manager.get_all_captcha_channels(from_date=last_update)
                if last_update is not None
                else self._data_manager.get_all_captcha_channels()
            )
            if automatic
            else self._data_manager.get_all_captcha_channels(
                from_date=(
                    time.time()
                    - self.get_settings()["modules"]["captcha"]["announcements"][
                        "scheduled_report"
                    ]["interval"]
                )
            )
        )
        embed: discord.Embed = discord.Embed(
            color=config.EMBED_COLOUR, timestamp=datetime.now()
        )

        if len(channels) == 0:
            embed.description = (
                f"No Captcha Channels have been created since {formatted_last_update}"
            )

            embed.title = "No Captcha Channels Found."
        else:
            successful = list(
                filter(lambda entry: entry["stats"]["completed"] is True, channels)
            )
            unsuccessful = list(
                filter(lambda entry: entry["stats"]["failed"] is True, channels)
            )

            embed.description = (
                f"{len(successful)} Captches"
                + "\n"
                + f"{len(unsuccessful)} Unsuccesful Captchas"
            )
            embed.title = "Captcha Gateway Daily Report"

        if automatic:
            self.set_setting("announcements.scheduled_report.last_report", time.time())
        embed.set_author(name="Captcha Gateway")
        return embed

    async def ban(self, member: discord.Member, reason: str = "No reason"):
        """
        Bans a member on all active Guilds.

        Parameters
        ----------
        :class:`discord.Member`
            The member to ban.
        """
        for g_guild in self._gateway_guilds:
            await g_guild.get_guild().ban(member.id, reason=reason)

    async def on_member_leave(self, member: discord.Member):
        """
        Handles the invocation of GatewayGuild on_member_leave events.
        """
        guild_id = member.guild.id

        for g_guild in self._gateway_guilds:
            if g_guild.get_guild().id == guild_id:
                await g_guild.on_member_leave(member)

    async def on_member_join(self, member: discord.Member):
        """
        Handles the invocation of GatewayGuild on_member_join events.
        """
        user_id = member.id
        guild_id = member.guild.id

        if self.is_gateway_guild(guild_id):
            main_guild: Guild = self._bot.get_guild(config.MAIN_SERVER)
            main_guild_user: Union[Member, None] = main_guild.get_member(user_id)

            if (
                main_guild_user is not None
                and self._bot.captcha.is_operator(user_id) is False
            ):
                self._bot.logger.info(
                    f"Member {main_guild_user.display_name} on Gateway Guild and Main Guild. Kicking member."
                )
                await member.guild.kick(member)
                await member.kick()
                return

            await self._bot.captcha.get_gateway_guild(guild_id).on_member_join(member)

        if guild_id == config.MAIN_SERVER:
            await self._tracker_manager.on_member_join(member)
            for g_guild in self._bot.captcha.get_gateway_guilds():
                if g_guild.has_captcha_channel(user_id):
                    channel: CaptchaChannel = g_guild.get_captcha_channel(user_id)
                    if channel.has_completed_captcha():

                        self._bot.logger.info(
                            f"Member {member.display_name} completed Captcha but was still on {channel.get_gateway_guild().get_name()}. Kicking member."
                        )
                        await g_guild.get_guild().kick(member)

    async def get_invitation_to_gateway(self):
        for g_guild in self._gateway_guilds:
            if g_guild.get_user_count() < 500:
                return await g_guild.get_permantent_invite()

    @timers.loop(minutes=5)
    async def gateway_reset_task(self):
        """
        Resets Captcha Counters after a period of time has elapsed.
        """
        for counter_entry in self._data_manager.get_captcha_counters():
            now = time.time()
            if (
                counter_entry["updated_at"]
                + self._bot.get_config()["gateway_rejoin"]["reset_after_duration"]
                <= now
            ):
                self._data_manager.reset_captcha_counter(counter_entry["mid"])

    async def scheduled_report_task(self):
        """
        A task used to announce a daily report of successful and unsuccessful captchas.
        """
        announcement_config = self.get_settings()["modules"]["captcha"]["announcements"]
        last_report = announcement_config["scheduled_report"]["last_report"]
        interval = announcement_config["scheduled_report"]["interval"]
        announcement_channel_id = announcement_config["announcement_channel_id"]

        if (last_report + interval) <= last_report:
            embed: discord.Embed = self.construct_scheduled_report_embed(True)
            await self._bot.get_guild(config.MAIN_SERVER).get_channel(
                announcement_channel_id
            ).send(embed=embed)
