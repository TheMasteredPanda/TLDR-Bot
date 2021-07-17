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
from discord.channel import TextChannel
from discord import Member
import modules.database as database
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
        * [ ] A command to add gateway guilds to the list of gateway guilds handled by the bot. This is only for the edgest
        of cases, so I don't think I'll end up doing this.
        * A command to invalidate an invitiation link.
        * Captchas:
            - Used to determine whether a user is a bot or a human.
            - What will be the captchas?
                * At the moment nobody has a clue, so the basic captchas now will be:
                    * [ ] Choosing out six pictures the correct object.
                    * [ ] Typing out what word has squiggled about in a manner no readable by computers.
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

    def get_captcha_channels(self, guild_id: int):
        return self._captcha_channels.find({"guild_id": int})

    def add_captcha_channel(
        self, guild_id: int, channel_id: int, tries: int, member_id: int
    ):
        entry = {
            "guild_id": guild_id,
            "channel_id": channel_id,
            "tries": tries,
            "member_id": member_id,
        }
        self._captcha_channels.insert_one(entry)
        return entry

    def get_captcha_channel(self, guild_id: int, channel_id: int):
        return self._captcha_channels.find_one(
            {"guild_id": guild_id, "channel_id": channel_id}
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
        channel_name = random_chars(12)
        self._channel: TextChannel = bot.create_text_channel(
            name=channel_name,
            category=g_guild.get_main_category(),
            overwrites={
                self._guild.default_role: discord.PermissionOverwrite(
                    view_channel=False, read_message_history=False
                ),
                member: discord.PermissionOverwrite(
                    view_channel=True,
                    read_messages=True,
                    send_messages=True,
                    read_message_history=True,
                ),
            },
        )

        self._data_manager = bot.captcha.get_data_manager()
        self._guild = g_guild.get_guild()
        self._generate_image = bot.modules.captcha.create_captcha_image()
        self._answer_text = None
        self._started = False
        self._member = member
        self._bot = bot

    def _get_entry(self):
        return self._data_manager.get_captcha_channel(self._guild_id, self._channel_id)

    def construct_embed(self):
        entry = self._get_entry()
        tries = entry["tries"]
        image, text = self._generate_image()
        image_file = discord.File(fp=image, filename="captcha.png")
        self._answer_text = text
        embed: discord.Embed = discord.Embed(
            colour=config.EMBED_COLOUR,
            title=f"Try {tries}. {tries - 1} remaining.",
            description="Try the text presented in the image correctly.",
        )
        embed.set_image("attachment://captcha.png")
        return embed, image_file

    async def send_captcha_message(self):
        entry = self._get_entry()
        channel: Union[TextChannel, None] = discord.utils.get(
            self._guild.text_channels, id=self._channel.id
        )

        if entry["tries"] != 0:
            embed, image_file = self.construct_embed()
            await channel.send(file=image_file, embed=embed)
        else:
            embed: discord.Embed = discord.Embed(
                color=config.EMBED_COLOUR,
                title="Too many tries.",
                description="Unfortunately, you have not completed captchas despite three tries. Your account id has been temporarily blacklisted for a day. Please come back after5 minutes and try again :) .",
            )
            await channel.send(embed)
            asyncio.sleep(10)
            self._data_manager.add_member_to_blacklist(self._member.id)
            await self._member.ban()

    async def on_message(self, message: discord.Message):
        if self._started is False:
            return

        if message.author.bot:
            return

        if message.channel.id != self._channel_id:
            return

        if message.channel.guild.id != self._guild_id:
            return

        if self._answer_text is None:
            return

        if message.content.lower() != self._answer_text:
            await self._channel.send("Incorrect.")
            await self.send_captcha_message()
            entry = self._get_entry()
            entry["tries"] = entry["tries"] - 1 if entry["tries"] > 0 else 0
            if entry["tries"] == 0:
                self._data_manager.add_member_to_blacklist(self._member.id)
                await self._member.kick()
        else:
            embed: discord.Embed = discord.Embed(
                color=config.EMBED_COLOUR,
                title="Successfully Completed Captcha.",
                description=f"Successfully completed Captcha, heres the single use, valid for 2 minutes, invitation link to TLDR! Once you join, you will be kicked from this Gateway guild. {self.create_tldr_invite()}",
            )
            # Create invite to welcome channel.

    async def create_tldr_invite(self):
        main_guild: Guild = discord.utils.get(self.bot.guilds, id=config.MAIN_SERVER)
        settings = self.settings_handler.get_settings(config.MAIN_SERVER)["modules"][
            "captcha"
        ]
        main_channel: TextChannel = discord.utils.get(
            main_guild.text_channels, id=settings["main_guild_landing_channel"]
        )
        invite: Invite = main_channel.create_invite(max_age=120, max_uses=1)
        return invite


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
            landing_channel = await self._guild.create_text_channel("welcome")
            # Add welcome message here; make welcome message configurable.
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

    async def delete(self):
        self._data_manager.remove_guild(self._id)
        # Need to write in here a better way to delete a gateway guild. I need to check if this is the only guild within the list, then check if people are in the guild doing captchas before I delete the guild.
        try:
            await self._guild.delete()
            return True
        except (HTTPException, Forbidden) as ignore:
            return False

    def get_landing_channel(self):
        return self._landing_channel

    def set_landing_channel(self, channel: TextChannel):
        self._landing_channel = channel

    def get_main_category(self):
        if self._category is None:
            for category in self._bot.categories:
                if category.name.lower() == "TLDR Gateway":
                    self._category = category
                    break
        return self._category

    def get_name(self):
        return self._guild.name

    def get_id(self):
        return self._id

    def get_guild(self):
        return self._guild

    def create_captcha_channel(self, for_member: Member):
        captcha_channel = CaptchaChannel(self._bot, self, for_member)
        self._captcha_channels[for_member.id] = captcha_channel
        return captcha_channel

    def on_member_join(self, member: Member):
        pass

    def on_member_leave(self, member: Member):
        pass


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
                "landing_channel": {"name": "welcome", "message": ""},
                "main_guild_landing_channel": None,
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
                    self._gateway_guilds.append(g_guild)
                    self._logger.info(
                        f"Found gateway {g_guild.get_name()}/{g_guild.get_id()}. Adding to Gateway Guild List."
                    )

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

    def is_gatway_guild(self, guild_id: int) -> bool:
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
