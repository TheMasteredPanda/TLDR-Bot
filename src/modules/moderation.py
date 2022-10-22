import time
from typing import Union

import config
import discord
from bot import TLDR
from discord.ext.commands import Bot, bot_has_any_role
from discord.message import Message
from pyasn1.type.univ import Null

from modules import database
from modules.utils import SettingsHandler

db = database.get_connection()


class Case:
    def __init__(self, data: dict):
        self.guild_id: int = data.get("guild_id")
        self.type: str = data.get("type")
        self.reason: str = data.get("reason")
        self.member_id: int = data.get("member_id")
        self.moderator_id: int = data.get("moderator_id")
        self.created_at = data.get("created_at")
        self.extra = data.get("extra", {})


class Cases:
    def __init__(self, bot):
        self.bot = bot

    def get_cases(
        self, guild_id: int, *, before: int = 0, after: int = 0, **kwargs
    ) -> list[Case]:
        """
        Get cases based on given kwargs.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the guild.
        before: :class:`int`
            Retrieve cases before this unix time.
        after: :class:`int`
            Retrieve cases after this unix time.
        kwargs: :class:`dict`
            Different values to search for cases by.

        Returns
        -------
        :class:`list`
           All the found cases.
        """
        kwargs = {key: value for key, value in kwargs.items() if value}
        query = {"guild_id": guild_id, **kwargs}
        if before:
            query["created_at"] = {"$lt": before}
        if after:
            query["created_at"] = {"$gt": after}

        return [Case(c) for c in db.cases.find(query).sort("created_at", -1)]

    def add_case(
        self,
        guild_id: int,
        case_type: str,
        reason: str,
        member: discord.member,
        moderator: discord.Member,
        extra: dict = {},
    ) -> Case:
        """
        Adds a case to the database.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the guild.
        case_type: :class:`str`
            Type of the case => mute | ban | kick | warn
        reason: :class:`str`
            Reason behind the case.
        member: :class:`discord.Member`
            Member who had the action taken upon.
        moderator: :class:`discord.Member`
            Member who took action on member.
        extra: :class:`dict`
            Any extra info that needs to be added.

        Returns
        -------
        :class:`dict`
            The case's data.
        """
        case_data = {
            "guild_id": guild_id,
            "member_id": member.id,
            "type": case_type,
            "reason": reason,
            "created_at": time.time(),
            "moderator_id": moderator.id,
            "extra": extra,
        }
        result = db.cases.insert_one(case_data)
        case_data["_id"] = result.inserted_id

        return Case(case_data)


class CGPoll:
    def __init__(self, reprimand, cg_id: str):
        self._reprimand = reprimand
        self._reprimand_module = reprimand._get_module()
        self._cg_id = cg_id
        self._message: Union[Message, None] = None

    async def start(self):
        cg_description = self._reprimand_module.get_bot().moderation.get_cg(self._cg_id)
        cg_poll_embed = self._reprimand_module.get_settings()["messages"]["cg_poll_embed"]
        accused: discord.Member = self._reprimand_module.get_accused()
        embed = discord.Embed(
            colour=config.EMBED_COLOUR,
            description=cg_poll_embed["body"].replace(
                "{cg_description}", cg_description
            ),
            title=cg_poll_embed["header"].replace(
                "{user}", f"{accused.name}#{accused.discriminator}"
            ),
        )
        self._message: Message = await self._reprimand_module.get_voting_channel().send(embed=embed)
        await self._message.add_reaction("👍")
        await self._message.add_reaction("👎")

class PunishmentPoll:
    def __init__(self, bot, reprimand, cg_id: str = None):

class Reprimand:
    def __init__(
        self,
        module,
        accused: discord.Member,
        cgs_breached: list[str],
        evidence_links: list[str],
    ):
        self._module = module
        self._accused = accused
        self._cgs = cgs_breached
        self._evidence_links = evidence_links
        self._settings = module.get_config()
        self._polls = []

        if len(self._cgs) > 1:
            for cg_id in self._cgs:
                self._polls.append(CGPoll(self, cg_id))
        else:
            pass

    def _get_module(self):
        return self._module

    def get_accused(self) -> Member:
        return self._accused

    def start(self):
        pass

    def is_multi_cgs(self):
        return len(self._cgs) > 1

    def end(self):
        pass


class ReprimandModule:
    def __init__(self, bot):
        self._bot: Bot = bot
        self._bot.logger.info("Reprimand Module has been initiated.")
        self._reprimand_voting_channel = None
        self._reprimand_discussion_channel = None
        self._settings_handler: SettingsHandler = bot.settings_handler
        self._logger = bot._logger
        self._live_reprimands: list[Reprimand] = []


        self._default_settings = {
            "punishments": {
                "informal": {
                    "description": "An informal warning, often a word said to them thorough a ticket or direct messages. This form of punishment doesn't appear on their record.",
                    "punishment_command": "",
                },
                "1formal": {
                    "description": "A formal warning. Unlike informal warnings this does appear on their record, and is given thorough the bot to the user on a ticket or thorough DMs",
                    "punishment_command": "",
                },
                "2formal": {
                    "description": "Two formal warnings",
                    "punishment_command": "",
                },
                "mute": {
                    "description": "Mutes a user for an alloted amount of time, this will obviously appear on their record. The amount of time a person gets can be determined thorough a poll or preestablished times.",
                    "punishment_command": "",
                },
                "ban": {
                    "description": "Bans a user from the server, this will appear on their record too.",
                    "punishment_command": "",
                },
            },
            "channels": {
                "reprimand_voting_channel": "",
                "reprimand_discussion_channel": ""
                },
            "messages": {
                "case_log_messages": {},
                "message_to_accused": {},
                "cg_poll_embed": {
                    "header": "Has {user} breached {cg_id}?",
                    "footer": "",
                    "body": "{cg_description}",
                },
                "punishment_poll_embed": {"header": "", "footer": "", "body": ""},
                "evidence_messages": {},
                "cg_embed": {},
            },
        }

        if config.MAIN_SERVER == 0:
            bot.logger.info(
                "Reprimand Module required the MAIN_SERVER variable in config.py to be set to a non zero value (a valid guild id). Will not initiate until this is rectified."
            )
            return

        settings = self._settings_handler.get_settings(config.MAIN_SERVER)

        if "reprimand" not in settings["modules"].keys():
            self._logger.info(
                "Reprimand Module settings not found in Guild dsettings. Adding default settings now."
            )
            settings["modules"]["reprimand"] = self._default_settings
            self._logger.save(settings)
        self._settings_handler.update(
            "reprimand", self._default_settings, config.MAIN_SERVER
        )

    async def _get_bot(self):
        return self._bot

    async def on_ready(self):
        guild = self._bot.get_guild(config.MAIN_SERVER)
        channels = settings['channels']

        if channels['reprimand_voting_channel'] == "":
            self._bot.logger.info("Reprimand Voting Channel not set.")
        else:
            self._reprimand_voting_channel = guild.get_channel(channels['reprimand_voting_channel'])

        if channels['reprimand_discussion_channel'] == "":
            self._bot.logger.info("Reprimand Discussion Channel not set.")
        else:
            self._reprimand_discussion_channel = guild.get_channel(channels['reprimand_discussion_channel'])

    async def get_voting_channel(self):
        return self._reprimand_voting_channel

    async def get_discussion_channel(self):
        return self._reprimand_discussion_channel

    def get_config(self):
        return self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
            "reprimand"
        ]

    def create_reprimand(
        self, accused: discord.Member, cg_ids: list[str], evidence_links: list[str]
    ) -> Reprimand:
        reprimand = Reprimand(self._bot, self, accused, cg_ids, evidence_links)
        self._live_reprimands.append(reprimand)
        return reprimand

    def get_reprimand(self):
        pass


class ModerationSystem:
    def __init__(self, bot):
        self.bot = bot
        self.cases = Cases(bot)
        self.bot.logger.info("Moderation System module has been initiated")
        self.parsed_cgs
        self.reprimand = ReprimandModule(bot)

    async def parse_cgs(self):
        aiohttp_session = getattr(self.bot.http, "__HTTPClient__session")
        async with aiohttp_session as session:
            async with session.get(
                "https://tldrnews.co.uk/discord-community-guidelines/"
            ) as response:
                html = await response.text()
                soup = bs4.BeautifulSoup(html, "html.parser")
                entry = soup.find("div", {"class": "entry-content"})
                cg_list = [*entry.children][15]

                cg: bs4.element.Tag
                i: int

                def walk(step_str: str, cg_id: int, parent: Tag, branch: Tag) -> dict:
                    contents = branch.contents
                    result = {}

                    if len(contents) > 1:
                        step_str = f"{step_str}.{cg_id}"
                        for i, cg_c in enumerate(
                            filter(lambda cg_c: type(cg_c) == Tag, contents[1])
                        ):
                            result = result | walk(step_str, i + 1, branch, cg_c)

                    else:
                        step_str = f"{step_str}.{cg_id}"
                        result[step_str] = contents[0]
                    return result

                parsed_cg = {}
                for i, cg in enumerate(filter(lambda cg: type(cg) == Tag, cg_list)):
                    cg_id = i + 1
                    str_cg_id = f"{cg_id}"
                    contents = cg.contents
                    parsed_cg[str_cg_id] = contents[0]

                    if len(contents) > 1:
                        cg_c: Tag
                        j: int
                        for j, cg_c in enumerate(
                            filter(lambda cg_c: type(cg_c) == Tag, contents[1])
                        ):
                            parsed_cg = parsed_cg | walk(str_cg_id, j + 1, cg, cg_c)
                self.parsed_cgs = parsed_cg

    def is_valid_cg(self, cg_id: str) -> bool:
        return cg_id in self.parsed_cgs.keys()

    def get_cg(self, cg_id: str) -> str:
        return self.parsed_cgs[cg_id]
