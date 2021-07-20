import math
import asyncio
import datetime
import io
import time
from captcha.image import ImageCaptcha
import string
import random
import discord
from discord.colour import Colour
from discord.invite import Invite
from pymongo.cursor import Cursor
import config
from enum import Enum
from typing import Tuple, Union
from discord.errors import Forbidden, HTTPException
from discord.guild import Guild
from discord.channel import CategoryChannel, TextChannel
from discord import Member
import modules.database as database
from modules.utils import SettingsHandler
import modules.timers as timers

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
    def __init__(self, logger):
        self._logger = logger
        self._db = database.get_connection()
        self._captcha_guilds = self._db.captcha_guilds
        self._captcha_channels = self._db.captcha_channels
        self._captcha_blacklist = self._db.captcha_blacklist
        self._captcha_counter = self._db.captcha_counter

    def add_captcha_channel(self, channel):
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
        entry = self._captcha_counter.find_one({"member_id": member_id})
        now = time.time()
        if entry:
            self._captcha_counter.update_one(
                {"member_id": member_id},
                {"counter": {"$add": counter}, "updated_at": now},
            )
        else:
            self._captcha_counter.insert_one(
                {"member_id": member_id, "counter": counter, "updated_at": now}
            )

    def get_captcha_counter(self, member_id: int):
        return self._captcha_counter.find_one({"member_id": member_id})

    def get_captcha_channels(self, guild_id: int, only_active: bool = True) -> list:
        return list(
            self._captcha_channels.find({"guild_id": guild_id, "active": only_active})
        )

    def get_captcha_counters(self):
        return list(self._captcha_counter.find({}))

    def update_captcha_channel(self, guild_id: int, channel_id: int, update: dict):
        self._captcha_channels.update(
            {"guild_id": guild_id, "channel_id": channel_id}, {"$set": update}
        )

    def add_guild(self, guild_id: int, landing_channel_id: int = 0):
        self._captcha_guilds.insert_one(
            {
                "guild_id": guild_id,
                "landing_channel_id": landing_channel_id,
                "stats": {},
            }
        )

    def remove_guild(self, guild_id: int):
        self._captcha_guilds.delete_one({"guild_id": guild_id})

    def get_guilds(self, include_stats: bool = False) -> Cursor:
        return (
            self._captcha_guilds.find({}, {"stats": 0})
            if include_stats is False
            else self._captcha_guilds.find({}, {"stats": 0})
        )

    def is_blacklisted(self, **kwargs) -> Tuple[Cursor, list, None]:
        member_id: Union[int, None] = (
            kwargs["member_id"] if "member_id" in kwargs else None
        )
        member_name: Union[str, None] = (
            kwargs["member_name"] if "member_name" in kwargs else None
        )
        member: Union[Member, None] = kwargs["member"] if "member" in kwargs else None

        if member_id is not None:
            return self._captcha_blacklist.find_one({"member": {"id": member_id}})

        if member_name is not None:
            return list(
                self._captcha_blacklist.find(
                    {"member": {{"name": {"$regex": f"^({member_name}.*)"}}}}
                )
            )

        if member is not None:
            return self._captcha_blacklist.find({"member": {"id": member.id}})

        return None

    def add_member_to_blacklist(self, member: Member, duration: int = 86400):
        now = time.time()
        self._captcha_blacklist.insert_one(
            {
                "member": {"id": member.id, "name": member.display_name},
                "started": datetime.datetime.now(),
                "ends": now + duration,
            }
        )

    def get_blacklisted_member(self, **kwargs) -> Union[Cursor, None]:
        args = {}

        if "name" in kwargs:
            args["name"] = {"$regex": f"^({kwargs['name']}.*)"}
        if "member_id" in kwargs:
            args["member_id"] = kwargs["member_id"]

        return self._captcha_blacklist.find_one({"member": args})

    def rm_member_from_blacklist(self, member_id: int):
        self._captcha_blacklist.delete_one({"member": {"id": member_id}})

    def get_blacklist(self):
        return self._captcha_blacklist.find({})


class CaptchaChannel:
    def __init__(
        self,
        bot,
        g_guild,
        member: Member,
    ):
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

    def get_ttl(self):
        return self._ttl

    def is_active(self):
        return self._active

    def has_completed(self):
        return self._completed

    def get_name(self):
        return self._channel.name

    def get_gateway_guild(self):
        return self._g_guild

    def has_completed_captcha(self):
        return self._completed

    def get_invite(self) -> Union[Invite, None]:
        return self._invite

    def get_id(self):
        return self._channel.id

    def get_tries(self):
        return self._tries

    def get_member(self):
        return self._member

    @timers.loop(seconds=1)
    async def countdown(self):
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
                description=self._bot.get_config()["messages"][
                    "countdown_alert_message"
                ]
                .replace("{time_unit}", time_unit)
                .replace("{time_value}", time_value),
                title=self._bot.get_config()["messages"][
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
            default_ttl = self._bot.get_config()["captcha_time_to_live"]
            minutes = math.floor(default_ttl / 60)
            time_value = minutes if minutes > 0 else default_ttl
            time_unit = (
                ("minutes" if minutes > 1 else "minute")
                if minutes > 0
                else ("seconds" if default_ttl > 1 else "second")
            )

            embed: discord.Embed = discord.Embed(
                colour=config.EMBED_COLOUR,
                title=self._bot.get_config()["messages"]["time_elapsed_message_title"],
                description=self._bot.get_config()["messages"]["time_elapsed_message"]
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
                self._member.ban()
                self._data_manager.add_member_to_blacklist(member=self._member)

            await self.destory()

    async def start(self, **kwargs):
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
                description=self._bot.get_config()["messages"][
                    "bot_startup_captcha_message"
                ]
                .replace("{time_unit}", time_unit)
                .replace("{time_value}", time_value),
                title="Bot started.",
            )
            await self._channel.send(embed=embed)
        await self.send_captcha_message()

    def construct_embed(self):
        image, text = self._bot.captcha.create_captcha_image()
        image_file = discord.File(fp=image, filename="captcha.png")
        self._answer_text = text
        embed: discord.Embed = discord.Embed(
            colour=config.EMBED_COLOUR,
            title=self._bot.get_config()["messages"]["captcha_message_embed_title"]
            .replace("{current_try}", self.get_tries())
            .replace("{tries_left}", self.get_tries() - 1),
            description=self._bot.get_config()["messages"][
                "captcha_message_embed_description"
            ],
        )
        embed.set_image(url="attachment://captcha.png")
        return embed, image_file

    async def send_captcha_message(self):
        if self._tries != 0:
            tuple_embed = self.construct_embed()
            embed = tuple_embed[0]
            image_file = tuple_embed[1]
            await self._channel.send(file=image_file, embed=embed)
        else:
            embed: discord.Embed = discord.Embed(
                color=config.EMBED_COLOUR,
                title=self._bot.get_config()["messages"][
                    "failed_captcha_message_title"
                ],
                description=self._bot.get_config()["messages"][
                    "failed_captcha_message"
                ],
            )
            await self._channel.send(embed=embed)

    async def on_message(self, message: discord.Message):
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
                    self._data_manager.add_member_to_blacklist(self._member.id)
                    await self._member.ban()
                await self._channel.delete()
        else:
            self._invite = await self.create_tldr_invite()
            url = self._invite.url
            embed: discord.Embed = discord.Embed(
                color=config.EMBED_COLOUR,
                title=self._bot.get_config()["messages"][
                    "completed_captcha_message_title"
                ],
                description=self._bot.get_config()["messages"][
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
        main_guild: Guild = discord.utils.get(self._bot.guilds, id=config.MAIN_SERVER)
        settings = self._bot.get_config()
        main_channel: TextChannel = discord.utils.get(
            main_guild.text_channels, id=settings["main_guild_landing_channel"]
        )
        invite: Invite = await main_channel.create_invite(max_age=120, max_uses=1)
        return invite

    async def destory(self):
        await self._channel.delete()


class GatewayGuild:
    def __init__(self, bot, data_manager: DataManager, **kwargs):
        self._bot = bot
        self._data_manager = data_manager
        self._kwargs = kwargs
        self._category = None
        self._captcha_channels = {}

    async def load(self):
        if "guild" in self._kwargs:
            self._guild: Guild = self._kwargs["guild"]
            self._id: int = self._guild.id

        if "guild_id" in self._kwargs:
            self._guild: Guild = self._bot.get_guild(self.kwargs["guild_id"])
            if self._guild is not None:
                self.id: int = self._guild.id

        if "landing_channel_id" in self._kwargs:
            self._landing_channel: TextChannel = self._guild.get_channel(
                self._kwargs["landing_channel_id"]
            )
        else:
            landing_channel_name = self._bot.get_config()["messages"][
                "landing_channel_name"
            ]
            landing_channel = await self._guild.create_text_channel(
                landing_channel_name
            )
            landing_channel_message = self._bot.get_config()["messages"][
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

        blacklist = self._bot.captcha.get_data_manager().get_blacklist()
        bans = await self._guild.bans()

        self._bot.logger.info("Syncing with Blacklist...")
        banned = 0
        unbanned = 0
        for entry in blacklist:
            if entry["ends"] <= time.time():
                await self._guild.unban(entry["member"]["id"])
                self._bot.captcha.get_data_manager().rm_member_from_blacklist(
                    entry["member"]["id"]
                )
                unbanned += 1
                continue

            ban_entry = discord.utils.find(
                lambda be: be.user.id == entry["member"]["id"], bans
            )

            if ban_entry is None:
                banned += 1
                await self._guild.ban(entry["member"]["id"])

        self._bot.logger.info(
            f"Banned {banned} users and unbanned {unbanned} users on guild {self._guild.name}."
        )

        main_guild = self._bot.get_guild(config.MAIN_SERVER)

        for member in self._guild.members:
            if member.bot:
                continue
            if self._bot.captcha.is_operator(member.id):
                continue
            if main_guild.get_member(member.id):
                await member.kick()

    def get_user_count(self):
        return len(self._guild.members)

    def has_captcha_channel(self, member_id: int) -> bool:
        return member_id in self._captcha_channels.keys()

    def get_captcha_channel(self, member_id: int) -> Union[CaptchaChannel, None]:
        return self._captcha_channels[member_id]

    def add_captcha_channel(self, member_id: int, channel: CaptchaChannel):
        self._captcha_channels[member_id] = channel

    async def delete(self):
        self._data_manager.remove_guild(self._id)
        # Need to write in here a better way to delete a gateway guild. I need to check if this is the only guild within the list, then check if people are in the guild doing captchas before I delete the guild.
        try:
            await self._guild.delete()
            await self._bot.captcha.rm_gateway_guild_from_cache(self)
            return True
        except (HTTPException, Forbidden) as ignore:
            return False

    def get_landing_channel(self) -> Union[TextChannel, None]:
        return self._landing_channel

    def get_main_category(self):
        if self._category is None:
            for category in self._guild.categories:
                if category.name.lower() == "tldr gateway":
                    self._category = category
                    break
        return self._category

    def get_name(self) -> str:
        return self._guild.name

    def get_id(self) -> int:
        return self._id

    def get_guild(self) -> Guild:
        return self._guild

    def create_captcha_channel(self, for_member: Member):
        captcha_channel = CaptchaChannel(self._bot, self, for_member)
        self._captcha_channels[for_member.id] = captcha_channel
        return captcha_channel

    async def delete_captcha_channel(self, member: Member):
        captcha_channel = self._captcha_channels[member.id]
        if captcha_channel is None:
            return
        await captcha_channel.destory()
        del self._captcha_channels[member.id]

    async def on_member_join(self, member: Member):
        captcha_module = self._bot.captcha
        user_id = member.id

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
        if self.has_captcha_channel(member.id):
            await self.delete_captcha_channel(member)
            is_operator = self._bot.captcha.is_operator(member.id)
            if is_operator is False:
                self._data_manager.update_captcha_counter(member.id, 1)
            settings = self._bot.settings_handler.get_settings(config.MAIN_SERVER)[
                "modules"
            ]["captcha"]
            if (
                self._data_manager.get_captcha_counter(member.id)
                >= settings["gateway_rejoin"]["limit"]
                and is_operator is False
            ):
                await member.ban()
                self._bot.logger.info(
                    f"Banned member {member.name} for joining and leaving {settings['gateway_rejoin']['limit']} times."
                )


class CaptchaModule:
    def __init__(self, bot):
        self._gateway_guilds = []
        self._data_manager = DataManager(bot.logger)
        self._settings_handler: SettingsHandler = bot.settings_handler
        self._bot = bot
        self._logger = bot.logger
        self._image_captcha = ImageCaptcha(width=360, height=120)

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
                "messages": {
                    "landing_channel": "Welcome to {guild_name}! Please follow the following steps by the Family Foundation for the Foundation of Families.",
                    "captcha_message_embed_title": "Try {curent_try}. {tries_left} Attempts Left.",
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
                        m_guild_id
                    )

                    if len(mongo_captcha_channels) > 0:
                        pass

                    for entry in mongo_captcha_channels:
                        if guild.get_member(entry["member_id"]) is None:
                            print(
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

    def get_config(self):
        return self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
            "captcha"
        ]

    def set_announcement_channel(self) -> bool:
        captcha_settings = self._settings_handler.get_settings(config.MAIN_SERVER)[
            "modules"
        ]["captcha"]
        if captcha_settings["main_announcement_channel"] != 0:
            self._announcement_channel = self._bot.get_guild(
                config.MAIN_SERVER
            ).get_channel(captcha_settings["main_announcement_channel"])
            return True
        return False

    def get_operators(self):
        return self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
            "captcha"
        ]["operators"]

    def set_operator(self, member_id: int):
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
        return (
            member_id
            in self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
                "captcha"
            ]["operators"]
        )

    def rm_gateway_guild_from_cache(self, guild_id: int):
        for g_guild in self._gateway_guilds:
            if g_guild.get_guild().id == guild_id:
                self._gateway_guilds.remove(g_guild)
                break

    def create_captcha_image(self):
        text = random_chars(6)
        captcha_image = self._image_captcha.generate_image(text)
        image_bytes = io.BytesIO()
        captcha_image.save(image_bytes, "PNG")
        image_bytes.seek(0)
        return image_bytes, text

    async def create_guild(self) -> GatewayGuild:
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
        return self._gateway_guilds

    def is_gateway_guild(self, guild_id: int) -> bool:
        for guild in self._gateway_guilds:
            if guild.get_id() == guild_id:
                return True
        return False

    def get_gateway_guild(self, guild_id: int) -> Union[GatewayGuild, None]:
        for g_guild in self._gateway_guilds:
            if g_guild.get_id() == guild_id:
                return g_guild
        return None

    def get_data_manager(self) -> DataManager:
        return self._data_manager

    def get_settings(self):
        return self._settings_handler.get_settings(config.MAIN_SERVER)

    async def unban(self, member_id: int):
        # Used primarily to unblacklist a member on all active guilds.
        for g_guild in self._gateway_guilds:
            guild: Guild = g_guild.get_guild()
            await guild.unban(member_id)

    @timers.loop(minutes=5)
    async def unban_task(self):
        blacklist = self._data_manager.get_blacklist()
        now = time.time()

        for entry in blacklist:
            if entry["ends"] <= now:
                await self.unban(entry["member"]["id"])
                self._logger.info(
                    f"Removing {entry['member']['name']}/{entry['member']['id']} from blacklist."
                )
                self._data_manager.rm_member_from_blacklist(entry["member"]["id"])

        captcha_counter_entries = self._data_manager.get_captcha_counters()
        captcha_counter_cooldown_seconds = self._settings_handler.get_settings(
            config.MAIN_SERVER
        )["modules"]["captcha"]["gateway_rejoin"]["cooldown"]

        for entry in captcha_counter_entries:
            if (entry["updated_at"] + captcha_counter_cooldown_seconds) <= time.time():
                await self.unban(entry["member_id"])

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

    async def on_member_leave(self, member: discord.Member):
        guild_id = member.guild.id

        for g_guild in self._gateway_guilds:
            if g_guild.id == guild_id:
                await g_guild.on_member_leave(member)

    async def on_member_join(self, member: discord.Member):
        user_id = member.id
        guild_id = member.guild.id
        if self.is_gateway_guild(guild_id):
            main_guild: Guild = self._bot.get_guild(config.MAIN_SERVER)
            main_guild_user = main_guild.get_member(user_id)
            if (
                main_guild_user is not None
                and self._bot.captcha.is_operator(user_id) is False
            ):
                print(
                    f"Member {main_guild_user.display_name} on Gateway Guild and Main Guild. Kicking member."
                )
                # await member.guild.kick(member)

            await self._bot.captcha.get_gateway_guild(guild_id).on_member_join(member)

        if guild_id == config.MAIN_SERVER:
            for g_guild in self._bot.captcha.get_gateway_guilds():
                if g_guild.has_captcha_channel(user_id):
                    channel = g_guild.get_captcha_channel(user_id)
                    if channel.has_completed_captcha():
                        await g_guild.get_guild().kick(member)
                        await channel.destory()
