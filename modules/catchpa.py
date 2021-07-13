import config
from enum import Enum
from typing import Union
from discord.errors import Forbidden, HTTPException
from discord.guild import Guild
from discord.channel import TextChannel
import modules.database as database
from modules.utils import SettingsHandler

"""
A Catchpa Gateway System to prevent continuous bot attacks.

Requirements:
    - [DONE] Bot to have ownership over gateway server.
    - [ ] Bot to create more gateway servers if the need arises.
    - [ ] Each new member to a catchpa server will need a dedicated channel to prove they are not a bot.
        * [ ] In this channel, only they will be able to see themselves and the bot.
        * [ ] In this channel, the catchpa will happen.
        * [ ] This channel will be removed after a time-to-live if the catchpa has not be completed, configuable ofc.
        * [ ] This channel will be removed after the catchpa is successfully on unsuccessfully completed.
    - [ ] The Bot should allow for invitation links to be generated for each gateway server through a command, accessed on
    the main TLDR guild.
    - [ ] The Bot should allow for warning announcements if any one gateway is becoming too full.
    - [ ] After the catchpa is complete, the user should be given a one-time invitation link. Once they have joined the
    main TLDR server,
    they should be kicked off of the gateway server.
    - The following data points need to be stored:
        * [ ] Amount of successful catchpas.
        * [ ] Amount of unsuccessful catchpas.
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
        * Catchpas:
            - Used to determine whether a user is a bot or a human.
            - What will be the catchpes?
                * At the moment nobody has a clue, so the basic catchpas now will be:
                    * [ ] Choosing out six pictures the correct object.
                    * [ ] Typing out what word has squiggled about in a manner no readable by computers.
"""


class CatchpaChannel:
    def __init__(self, guild: Guild, channel: TextChannel):
        self.guild = guild
        self.channel = channel
        self.catchpa = None


class DataManager:
    def __init__(self, logger):
        self._logger = logger
        self._db = database.get_connection()
        self._catchpa_guilds = self._db.catchpa_guilds

    def add_guild(self, guild_id: int):
        self._catchpa_guilds.insert_one(
            {"guild_id": guild_id, "landing_channel_id": 0, "stats": {}}
        )

    def remove_guild(self, guild_id: int):
        self._catchpa_guilds.delete_one({"guild_id": guild_id})

    def get_guilds(self, include_stats: bool = False) -> list[object]:
        return self._catchpa_guilds.find(
            {}, {} if include_stats is False else {"stats": 0}
        )


class GatewayGuild:
    def __init__(self, bot, data_manager: DataManager, **kwargs):
        self._bot = bot
        self._data_manager = data_manager
        self._kwargs = kwargs

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
                    self._kwargs["landing_channel"]
                )
            else:
                landing_channel = await self._guild.create_text_channel("welcome")
                # Add welcome message here; make welcome message configurable.
                self.landing_channel: TextChannel = landing_channel

    async def delete(self):
        self._data_manager.remove_guild(self._id)
        # Need to write in here a better way to delete a gateway guild. I need to check if this is the only guild within the list, then check if people are in the guild doing catchpas before I delete the guild.
        try:
            await self._guild.delete()
            return True
        except (HTTPException, Forbidden) as ignore:
            return False

    def get_landing_channel(self):
        return self.landing_channel

    def set_landing_channel(self, channel: TextChannel):
        self.landing_channel = channel

    def get_name(self):
        return self._guild.name

    def get_id(self):
        return self._id

    def get_guild(self):
        return self._guild


class CatchpaModule:
    def __init__(self, bot):
        self._gateway_guilds = []
        self._data_manager = DataManager(bot.logger)
        self._settings_handler: SettingsHandler = bot.settings_handler
        self._bot = bot
        self._logger = bot.logger
        if config.MAIN_SERVER == 0:
            bot.logger.info(
                "Catchpa Gateway Module required the MAIN_SERVER variable in config.py to be set to a non-zero value (a valid guild id). Will not initate module."
            )
            return

        settings = self._settings_handler.get_settings(config.MAIN_SERVER)

        if "catchpa" not in settings["modules"].keys():
            self._logger.info(
                "Catchpa Gateway settings not found in Guild settings. Adding default settings now."
            )
            settings["modules"]["catchpa"] = {
                "guild_name": "Gateway Guild {number}",
                "landing_channel": {"name": "welcome", "message": ""},
            }
            self._settings_handler.save(settings)
        self._logger.info("Catchpa Gateway settings found.")
        self._logger.info("Catchpa Gateway Module initiated.")

    async def load(self):
        mongo_guild_ids = self._data_manager.get_guilds(False)

        if len(mongo_guild_ids) == 0:
            self._logger.info("No previous Gateway Guilds active. Creating one...")
            g_guild = await self.create_guild()
            self._logger.info(f"Created {g_guild.get_name()}")
            self._logger.info("Added Guild to MongoDB.")
        elif len(mongo_guild_ids) > 0:
            self._logger.info("Previous Gateway Guilds found. Indexing...")
            guilds: list[Guild] = self._bot.guilds

            for guild in guilds:
                for m_guild in mongo_guild_ids:
                    m_guild_id = m_guild["guild_id"]
                    m_guild_landing_channel_id = m_guild["landing_channel_id"]
                    if guild.id == m_guild_id:
                        g_guild = GatewayGuild(
                            self._bot,
                            self._data_manager,
                            guild=guild,
                            landing_channel_id=m_guild_landing_channel_id,
                        )
                        self._logger.info(
                            f"Found gateway {g_guild.name}/{g_guild.id}. Adding to Gateway Guild List."
                        )
                        await g_guild.load()

    async def create_guild(self) -> GatewayGuild:
        guild = await self._bot.create_guild(
            self._data_manager.get_config["name"].replace(
                "{number}", len(self._gateway_guilds) + 1
            )
        )
        self._data_manager.add_guild(guild.id)
        g_guild = GatewayGuild(self._bot, self._data_manager, guild=guild)
        self._gateway_guilds.append(g_guild)
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
