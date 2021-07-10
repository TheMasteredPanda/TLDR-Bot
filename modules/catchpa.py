from enum import Enum
from discord.guild import Guild
from discord.channel import TextChannel
import modules.database as database

"""
A Catchpa Gateway System to prevent continuous bot attacks.

Requirements:
    - [ ] Bot to have ownership over gateway server.
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
    def __init__(self):
        self.connection = database.get_connection()
        self.catchpa_guilds = self.connection.catchpa_guilds

    def add_guild(self, guild_id: int):
        self.catchpa_guilds.insert_one({"guild_id": guild_id})

    def get_guilds(self) -> list[int]:
        return list(self.catchpa_guilds.find({}))


class GatewayGuild:
    def __init__(self, bot, data_manager: DataManager, **kwargs):
        self.bot = bot
        self.data_manager = data_manager
        if "guild" in kwargs:
            self.guild: Guild = kwargs["guild"]
            self.id: int = self.guild.id

        if "guild_id" in kwargs:
            self.guild: Guild = bot.get_guild(kwargs["guild_id"])
            if self.guild is not None:
                self.id: int = self.guild.id

        if "landing_channel_id" in kwargs:
            self.landing_channelP: TextChannel = self.guild.get_channel(
                kwargs["landing_channel"]
            )
        else:
            landing_channel = self.guild.create_text_channel("welcome")
            # Add welcome message here; make welcome message configurable.
            self.landing_channel: TextChannel = landing_channel

    async def create_single_use_invite(self, ttl: int = 60):
        invite = await self.landing_channel.create_invite(max_age=ttl, max_uses=1)
        return invite


class CatchpaModule:
    def __init__(self, bot):
        self.gateway_guilds = []
        self.data_manager = DataManager()
        self.bot = bot

    async def create_guild(self, name: str) -> GatewayGuild:
        guild = await self.bot.create_guild(name)
        self.data_manager.add_guild(guild.id)
        g_guild = GatewayGuild(self.bot, self.data_manager, guild=guild)
        self.gateway_guilds.append(g_guild)
        return g_guild

    def get_gateway_guilds(self) -> list[GatewayGuild]:
        return self.gateway_guilds
