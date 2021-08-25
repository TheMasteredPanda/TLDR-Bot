import asyncio
import io
import math
import random
import re
import string
import time
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

"""
A Captcha Gateway System to prevent continuous bot attacks.

Requirements:
    - [DONE] Bot to have ownership over gateway server.
    - [ ] Bot to create more gateway servers if the need arises.
    - [ ] Each new member to a captcha server will need a dedicated channel to prove they are not a bot.
        * [DONE] In this channel, only they will be able to see themselves and the bot.
        * [DONE] In this channel, the captcha will happen.
        * [ ] This channel will be removed after a time-to-live if the captcha has not be completed, configuable ofc.
        * [ ] This channel will be removed after the captcha is successfully on unsuccessfully completed.
    - [ ] The Bot should allow for invitation links to be generated for each gateway server through a command, accessed on
    the main TLDR guild.
    - [ ] The Bot should allow for warning announcements if any one gateway is becoming too full.
    - [ ] After the captcha is complete, the user should be given a one-time invitation link. Once they have joined the
    main TLDR server,
    they should be kicked off of the gateway server.
    - The following data points need to be stored:
        * [ ] Amount of successful captchas.
        * [ ] Amount of unsuccessful captchas.
        * [ ] Amount of joins per month.
    - The following commands need to be written:
        * [ ] A command to get an invitiation link. This command will also need to accomodate for the different types of
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
        return self._captcha_counter.find_one({"member_id": member_id})

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
            else self._member_cache.find({"mid": f"/^{member_id}.*/is"})
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
        self._captcha_channels.update(
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

    def is_blacklisted(self, member_id: int) -> Union[Cursor, list, None]:
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
        self._internal_clock = 0
        self._active = False
        self._logger = bot.logger

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

            embed: discord.Embed = discord.Embed(
                colour=config.EMBED_COLOUR,
                title=self._bot.captcha.get_config()["messages"][
                    "time_elapsed_message_title"
                ],
                description=self._bot.captcha.get_config()["messages"][
                    "time_elapsed_message"
                ]
                .replace("{time_value}", time_value)
                .replace("{time_unit}", time_unit),
            )
            await self._channel.send(embed=embed)
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
                await self._member.ban(reason="Failed to complete Captcha assessment.")
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
                .replace("{time_value}", time_value),
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
        if self._started is False:
            return

        if self._answer_text is None:
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
                    self._data_manager.add_blacklisted_member(self._member)
                    reason = (
                        "Failed to complete Captcha assessment; failed to complete the assessment in time..",
                    )

                    self._data_manager.add_member_to_blacklist(
                        self._member, 900, reason
                    )
                    self._logger.info(
                        f"Banning member {self._member.display_name}/{self._member.id} for failing to complete Captcha."
                    )
                    await self._member.ban(reason=reason)
                # await self._channel.delete() - Not quite sure why this is here.
        else:
            self._invite = await self.create_tldr_invite()
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
                {"active": False, "stats": {"completed": True}, "ttl": 0},
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
        invite: Invite = await main_channel.create_invite(max_age=120, max_uses=1)
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
                )
            )
            landing_channel_message = self._bot.captcha.get_config()["messages"][
                "landing_channel"
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

        blacklisted_member = (
            self._bot.captcha.get_data_manager().get_blacklisted_member(member.id)
        )
        if blacklisted_member:
            await member.ban(reason="Is a blacklisted member. Banned on join attempt.")

        if len(self._guild.members) in [100, 200, 300, 400, 500]:
            await captcha_module.announce(
                f"{self._guild.name} reached {self._guild.members}", self._guild
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
            if (
                self._data_manager.get_captcha_counter(member.id)["counter"]
                >= settings["gateway_rejoin"]["limit"]
                and is_operator is False
            ):
                bans = await self._guild.bans()

                for ban in bans:
                    if ban.user.id == member.id:
                        return

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
            settings["modules"]["captcha"] = {
                "operators": [],
                "guild_name": "Gateway Guild {number}",
                "landing_channel_name": "welcome",
                "main_guild_landing_channel": None,
                "main_announcement_channel": 0,
                "captcha_time_to_live": 900,
                "blacklist_length": 86400,
                "gateway_rejoin": {
                    "limit": 3,
                    "blacklist_duration": 86400,
                    "reset_after_duration": 900,
                },
                "messages": {
                    "landing_channel": "Welcome to {guild_name}! Please follow the following steps by the Family Foundation for the Foundation of Families.",
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
                },
            }
            self._settings_handler.save(settings)
        self._logger.info("Captcha Gateway settings found.")
        self._logger.info("Captcha Gateway Module initiated.")

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
        if len(valid_guild_ids) == 0:
            if len(self._bot.guilds) >= 10:
                return await self._bot.critical_error(
                    "Can't load Captcha Gateway Module, Bot cannot create new Guilds if it is in 10 or more Guilds."
                )
            self._logger.info("No previous Gateway Guilds active. Creating one...")
            g_guild = await self.create_guild()
            self._logger.info(f"Created {g_guild.get_name()}")
            self._logger.info("Added Guild to MongoDB.")
        else:
            self._logger.info("Previous Gateway Guilds found. Indexing...")

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

                    if len(mongo_captcha_channels) > 0:
                        pass

                    for entry in mongo_captcha_channels:
                        if guild.get_member(entry["member_id"]) is None:
                            self._logger.info(
                                f"Member under id {entry['member_id']} no longer on Gateway Guild."
                            )
                            self._data_manager.update_captcha_channel(
                                guild.id,
                                entry["channel_id"],
                                {
                                    "active": False,
                                    "stats": {"completed": True},
                                    "ttl": 0,
                                },
                            )
                            t_channel = guild.get_channel(entry["channel_id"])
                            if t_channel:
                                await t_channel.delete()
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
        if self.set_announcement_channel():
            self._bot.logger.info("Announcement channel set.")
        else:
            self._bot.logger.info("Announcement channel not set.")
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
        if captcha_settings["main_announcement_channel"] != 0:
            self._announcement_channel = self._bot.get_guild(
                config.MAIN_SERVER
            ).get_channel(captcha_settings["main_announcement_channel"])
            return True
        return False

    async def announce(self, message: str, guild: discord.Guild):
        """Sends an announcement embed on the announcement channel."""
        if self._announcement_channel:
            embed: discord.Embed = discord.Embed(
                colour=config.EMBED_COLOUR,
                description=message,
                title=f"Captcha Gateway Announcement on Gateway {guild.name}",
            )
            await self._announcement_channel.send(embed=embed)

    def get_operators(self) -> list[int]:
        """
        Returns a list of operators. Operators are essentially Admins on Gateway Guilds.
        """
        return self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
            "captcha"
        ]["operators"]

    def set_operator(self, member_id: int):
        """
        Adds or removes an operator. Depends what they were previously.

        Parameters
        ----------
        member_id: :class:`int`
            The id of the member to set.
        """
        operators: list[int] = self._settings_handler.get_settings(config.MAIN_SERVER)[
            "modules"
        ]["captcha"]["operators"]

        if member_id in operators:
            operators.remove(member_id)
        else:
            operators.append(member_id)
        self._settings_handler.save(
            self._settings_handler.get_settings(config.MAIN_SERVER)
        )

    def is_operator(self, member_id: int) -> bool:
        """
        Check if a member is already an Operator.

        Returns
        :class:`bool`
            True if they were already an operator. Else False.
        """
        return (
            member_id
            in self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
                "captcha"
            ]["operators"]
        )

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

    @timers.loop(minutes=5)
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

    def set_setting(self, path: str, value: object):
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
                # await member.guild.kick(member)
                # return

            await self._bot.captcha.get_gateway_guild(guild_id).on_member_join(member)

        if guild_id == config.MAIN_SERVER:
            for g_guild in self._bot.captcha.get_gateway_guilds():
                if g_guild.has_captcha_channel(user_id):
                    channel: CaptchaChannel = g_guild.get_captcha_channel(user_id)
                    if channel.has_completed_captcha():
                        self._bot.logger.info(
                            f"Member {main_guild_user.display_name} completed Captcha but was still on {channel.get_gateway_guild().get_guild().get_name()}. Kicking member."
                        )
                        await g_guild.get_guild().kick(member)
                        await channel.destory()

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
