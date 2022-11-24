import json
import os
import random
import time
from typing import Union

import bs4
import config
import discord
from bot import TLDR
from bs4.element import Tag
from bson import json_util
from discord.channel import TextChannel
from discord.enums import ChannelType
from discord.ext.commands import Bot, bot_has_any_role
from discord.message import Message
from discord.threads import Thread
from pyasn1.type.univ import Null
from pymongo.collection import Collection

import modules.database as database
from modules import database
from modules.timers import loop
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


class Poll:
    async def load(self):
        pass

    def get_ayes(self) -> int:
        pass

    def get_noes(self) -> int:
        pass


class CGPoll(Poll):
    def __init__(self, reprimand, **kwargs):
        self._reprimand = reprimand
        self._reprimand_module = reprimand._get_module()

        if "cg_id" in kwargs.keys():
            self._cg_id = kwargs["cg_id"]
        else:
            if kwargs["cg_data"]:
                raise Exception("cg_id nor cg_data was passed in CGPoll instantiation.")

            self._cg_id = kwargs["cg_data"]["cg_id"]

        self._thread: TextChannel = self._reprimand._get_thread()
        self._message_id = (
            kwargs["cg_data"]["message_id"]
            if "message_id" in kwargs["cg_data"].keys()
            else None
        )
        self._message: Message = None

    async def load(self):
        if self._message_id:
            self._message = await self._thread.fetch_message(self._message_id)

        if self._message is None:
            cg_description = self._reprimand_module.get_bot().moderation.get_cg(
                self._cg_id
            )
            cg_poll_embed = self._reprimand_module.get_settings()["messages"][
                "cg_poll_embed"
            ]
            accused: discord.Member = self._reprimand_module.get_accused()
            embed = discord.Embed(
                colour=config.EMBED_COLOUR,
                description=cg_poll_embed["body"].replace(
                    "{cg_description}", cg_description
                ),
                title=cg_poll_embed["title"].replace(
                    "{user}", f"{accused.name}#{accused.discriminator}"
                ),
            )
            self._message: Message = (
                await self._reprimand_module.get_voting_channel().send(embed=embed)
            )
            await self._message.add_reaction("👍")
            await self._message.add_reaction("👎")

    def get_message(self):
        return self._message

    def get_cg_id(self):
        return self._cg_id

    def get_ayes(self) -> int:
        reactions = self._message.reactions

        for reaction in reactions:
            if reaction.emoji == "👍":
                return reaction.count
        return 0

    def get_noes(self) -> int:
        reactions = self._message.reactions

        for reaction in reactions:

            if reaction.emoji == "👎":
                return reaction.count
        return 0


class PunishmentPoll(Poll):
    def __init__(self, reprimand, **kwargs):
        self._reprimand = reprimand
        self._settings = reprimand._get_module().get_settings()
        self._message: Union[discord.Message, None] = None

    async def load(self, **kwargs):
        thread: Thread = self._reprimand._get_thread()

        if self._message_id:
            self._message = await thread.fetch_message(self._message_id)
        else:
            punishment_embed_msgs = self._settings["messages"]["punishment_poll_embed"]
            punishment_entry = punishment_embed_msgs["punishment_entry"]
            punishments = self._settings["punishments"]
            desc = ""

            for name, entry in punishments:
                desc = desc + punishment_entry.replace(
                    "{emoji}", entry["emoji"]
                ).replace("{name}", name).replace(
                    "{short_description}", entry["short_description"]
                ).replace(
                    "{type}", entry["punishment_type"]
                )

            embed = discord.Embed(
                colour=config.EMBED_COLOUR,
                title=punishment_embed_msgs["title"].replace(
                    "{username}",
                    f"{self._reprimand.get_accused().name}#{self._reprimand.get_accused().discriminator}",
                ),
                description=desc,
            )
            self._message = self._reprimand._get_thread().send(embed=embed)

            for entry in punishments.values():
                self._message.add_reaction(entry["emoji"])

    def get_ayes(self) -> int:
        if not self._message:
            raise Exception("No message reference in PunishmentPoll.")

        reactions = self._message.reactions

        for reaction in reactions:
            if reaction.emoji == "👍":
                return reaction.count
        return 0

    def get_noes(self) -> int:
        if not self._message:
            raise Exception("No message reference in PunishmentPoll.")

        reactions = self._message.reactions

        for reaction in reactions:
            if reaction.emoji == "👎":
                return reaction.count
        return 0


class Reprimand:
    def __init__(self, module):
        self._module = module
        self._settings = module.get_settings()
        self._polls: list[Poll] = []

    async def load(self, **kwargs):
        bot = self._module._get_bot()
        self._accused: discord.Member = (
            kwargs["accused"]
            if "accused" in kwargs.keys()
            else bot.get_guild(config.MAIN_SERVER).get_member(kwargs["accused_id"])
        )
        self._channel: TextChannel = self._module.get_channel()

        if "thread_id" not in kwargs.keys():
            self._thread = await self._channel.create_thread(
                name=f"{self._accused.name}#{self._accused.discriminator}",
                type=ChannelType.public_thread,
            )
        else:
            self._thread = self._channel.get_thread(kwargs["thread_id"])

        return
        self._polls.append(
            PunishmentPoll(self, punishments=kwargs["punishment_poll"])
            if "punishment_poll" in kwargs.keys()
            else PunishmentPoll(self)
        )
        if "cg_polls" in kwargs.keys():
            for cg_poll_data in kwargs["cg_polls"]:
                self._polls.append(CGPoll(self, cg_data=cg_poll_data))

        if "cg_ids" in kwargs.keys():
            for cg_id in kwargs["cg_ids"]:
                self._polls.append(CGPoll(self, cg_id=cg_id))

        for poll in self._polls:
            await poll.load()

    def start(self):
        self.countdown_loop.start()

    @loop(seconds=1)
    async def countdown_loop(self):
        pass

    def _get_module(self):
        return self._module

    def _get_thread(self) -> Thread:
        return self._thread

    def get_accused(self) -> discord.Member:
        return self._accused

    def is_multi_cgs(self):
        return len(self._cgs) > 1

    def end(self):
        pass


class ReprimandModule:
    def __init__(self, bot):
        self._bot: Bot = bot
        self._bot.logger.info("Reprimand Module has been initiated.")
        self._reprimand_channel: Union[TextChannel, None] = None
        self._settings_handler: SettingsHandler = bot.settings_handler
        self._logger = bot.logger
        self._db = database.get_connection()
        self._live_reprimands: list[Reprimand] = []

        self._settings = {
            "punishments": {
                "informal": {
                    "description": "An informal warning, often a word said to them thorough a ticket or direct messages. This form of punishment doesn't appear on their record.",
                    "short_description": "",
                    "emoji": "",
                    "punishment_type": "",
                    "punishment_duration": "",
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
            "reprimand_channel": "",
            "messages": {
                "case_log_messages": {},
                "message_to_accused": {},
                "cg_poll_embed": {
                    "title": "Has {user} breached {cg_id}?",
                    "footer": "",
                    "body": "{cg_description}",
                },
                "punishment_poll_embed": {
                    "title": "",
                    "footer": "",
                    "punishment_entry": "**{punishment_name}:** {punishment_description}",
                },
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
            settings["modules"]["reprimand"] = self._settings
            self._settings_handler.save(settings)
        self._settings_handler.update("reprimand", self._settings, config.MAIN_SERVER)

    def _get_bot(self):
        return self._bot

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

        path = f"modules.reprimand.{path}"
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
                    welcome_message.replace(
                        "{guild_name}", g_guild.get_guild().name
                    ).replace("\\n", "\n")
                )

    async def load(self):
        reprimand_collection = self._db.reprimands

        for reprimand_data in reprimand_collection:
            reprimand = Reprimand(self, reprimand_data)
            await reprimand.start()
            self._live_reprimands.append(reprimand)

    async def on_ready(self):
        guild = self._bot.get_guild(config.MAIN_SERVER)
        reprimand_channel = self._settings["reprimand_channel"]

        if not reprimand_channel:
            self._logger.info("No reprimand channel set for Reprimand Module.")
            return

        self._reprimand_channel = self._bot.get_guild(config.MAIN_SERVER).get_channel(
            reprimand_channel
        )

        await self.load()

    def get_channel(self):
        if not self._reprimand_channel:
            self._reprimand_channel = self._bot.get_guild(
                config.MAIN_SERVER
            ).get_channel(self.get_settings()["reprimand_channel"])

        return self._reprimand_channel

    def get_settings(self):
        return self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
            "reprimand"
        ]

    async def create_reprimand(
        self, accused: discord.Member, cg_ids: list[str], evidence_links: list[str]
    ) -> Reprimand:
        reprimand = Reprimand(self)
        await reprimand.load(
            accused=accused, cg_ids=cg_ids, evidence_links=evidence_links
        )
        # self._live_reprimands.append(reprimand)
        return reprimand

    def get_reprimand(self):
        pass


class ModerationSystem:
    def __init__(self, bot):
        self.bot: Bot = bot
        self.cases = Cases(bot)
        self.bot.logger.info("Moderation System module has been initiated")
        self.bot.add_listener(self.on_ready, "on_ready")

    async def on_ready(self):
        await self.parse_cgs()

    async def parse_cgs(self):
        if os.path.exists("../cgs.json"):
            with open("../cgs.json", "r") as cg_json_file:
                self.parsed_cgs = json.load(cg_json_file)
        else:
            aiohttp_session = getattr(self.bot.http, "_HTTPClient__session")
            async with aiohttp_session.get(
                "https://tldrnews.co.uk/discord-community-guidelines/"
            ) as response:
                html = await response.text()
                soup = bs4.BeautifulSoup(html, "html.parser")
                entry = soup.find("div", {"class": "entry-content"})
                if entry is None:
                    raise Exception(
                        "Couldn't find entry with CGs. Is the website down?"
                    )
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
                            result[step_str] = contents[0]
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
                if os.path.exists("cgs.json") is False:
                    with open("cgs.json", "w") as cg_json_file:
                        cg_json_file.write(json.dumps(self.parsed_cgs, indent=4))

    def is_valid_cg(self, cg_id: str) -> bool:
        return cg_id in self.parsed_cgs.keys()

    def get_cg(self, cg_id: str) -> str:
        return self.parsed_cgs[cg_id]
