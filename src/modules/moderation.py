import json
import os
import random
import time
from enum import Enum
from typing import Union

import bs4
import config
import discord
import pymongo
from bot import TLDR
from bs4.element import Tag
from bson import json_util
from discord.channel import TextChannel
from discord.emoji import Emoji
from discord.enums import ChannelType
from discord.ext.commands import Bot, bot_has_any_role
from discord.message import Message
from discord.threads import Thread
from pyasn1.type.univ import Null
from pymongo.collection import Collection

import modules.database as database
import modules.format_time as format_time
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


class PollType(Enum):
    GC_POLL = 1
    PUNISHMENT_POLL = 2


class ReprimandDataManager:
    """
    A class dedicated to addeding, removing, and updating temporal information associated with reprimand polls.
    """

    def __init__(self):
        self._db = database.get_connection()
        self._reprimand_polls: Collection = self._db.reprimand_polls
        self._reprimand_cases: Collection = self._db.reprimand_cases

    def add_poll(self, thread_id: int, message_id: int, remaining_seconds: int):
        self._reprimand_polls.insert_one(
            {
                "thread_id": thread_id,
                "message_id": message_id,
                "remaining_seconds": remaining_seconds,
            }
        )

    def rm_poll(self, thread_id: int, message_id: int):
        self._reprimand_polls.delete_one(
            {"thread_id": thread_id, "message_id": message_id}
        )

    def rm_polls(self, thread_id: int):
        self._reprimand_polls.delete_many({"thread_id": thread_id})

    def update_poll(self, thread_id: int, message_id: int, remaining_seconds: int):
        self._reprimand_polls.update_one(
            {"thread_id": thread_id, "message_id": message_id},
            {"$set": {"remaining_seconds": remaining_seconds}},
        )

    def get_polls(self):
        return self._reprimand_polls.find()

    def get_poll(self, thread_id: int, message_id: int):
        return self._reprimand_polls.find_one(
            {"thread_id": thread_id, "message_id": message_id}
        )


class Poll:
    async def load(self):
        pass

    def get_ayes(self) -> int:
        pass

    def get_noes(self) -> int:
        pass

    def get_type(self) -> PollType:
        pass

    def tick(self, reprimand):
        pass

    def get_seconds_remaining(self) -> int:
        pass

    def _has_countdown_elapsed(self) -> bool:
        pass


class CGPoll(Poll):
    def __init__(self, reprimand):
        self._reprimand = reprimand
        self._reprimand_module = reprimand._get_module()
        self._thread: TextChannel = self._reprimand._get_thread()
        self._message: Message = None
        self._countdown = 0

    async def load(self, **kwargs):
        if "cg_id" in kwargs.keys():
            self._cg_id = kwargs["cg_id"]

        if "duration" not in kwargs.keys():
            raise Exception(
                "Parameter 'duration' not included in CGPoll. Can't load CG Poll."
            )

        self._countdown = kwargs["duration"]

        cg_poll_embed = self._reprimand_module.get_settings()["messages"][
            "cg_poll_embed"
        ]
        accused: discord.Member = self._reprimand.get_accused()
        parsed_cgs = self._reprimand_module._get_bot().moderation.get_parsed_cgs()
        selected_cgs = {}
        for key in parsed_cgs.keys():
            if self._cg_id.startswith(key):
                selected_cgs[key] = parsed_cgs[key]

        desc = ""

        for key, value in selected_cgs.items():
            desc = desc + f"`{key}` {value}"

        embed = discord.Embed(
            colour=config.EMBED_COLOUR,
            description=cg_poll_embed["body"]
            .replace("{cg_description}", desc)
            .replace("{duration}", format_time.seconds(self._countdown)),
            title=cg_poll_embed["title"]
            .replace("{cg_id}", self._cg_id)
            .replace("{user}", f"{accused.name}#{accused.discriminator}"),
        )
        self._message: Message = await self._reprimand._get_thread().send(embed=embed)
        await self._message.add_reaction("👍")
        await self._message.add_reaction("👎")

    def save(self):
        """
        Saves current duration of poll to relevant collection.
        """
        self._reprimand_module.get_data_manager().update_poll(
            self._thread.id, self._message.id, self._countdown
        )

    def tick(self, reprimand):
        if self._countdown > 0:
            new_countdown = self._countdown - 1
            self._countdown = new_countdown

        if self._countdown % 60 == 0:
            self.save()

    # print(f"GCPoll (CG: {self._cg_id}): {self._countdown})")

    def _has_countdown_elapsed(self):
        return self._countdown <= 0

    def get_message(self):
        return self._message

    def get_cg_id(self):
        return self._cg_id

    def get_ayes(self) -> int:
        reactions = self._message.reactions

        for reaction in reactions:
            if reaction.emoji == "👍":
                return reaction.count  # Accounting for the bot emoji.
        return 0

    def get_noes(self) -> int:
        reactions = self._message.reactions

        for reaction in reactions:

            if reaction.emoji == "👎":
                return reaction.count - 1  # Accounting for the bot emoji.
        return 0

    def get_type(self):
        return PollType.GC_POLL

    def get_seconds_remaining(self):
        return self._countdown


class PunishmentPoll(Poll):
    def __init__(self, reprimand):
        self._reprimand = reprimand
        self._module = reprimand._get_module()
        self._settings = reprimand._get_module().get_settings()
        self._message: Union[discord.Message, None] = None
        self._thread = self._reprimand._get_thread()
        self._data_manager: ReprimandDataManager = self._module.get_data_manager()
        self._countdown = 0

    async def load(self, **kwargs):
        if "duration" not in kwargs.keys():
            raise Exception(
                "Expected parameter 'duration' not included in PunishmentPoll. Can't load poll."
            )

        self._countdown = kwargs["duration"]

        if "message_id" in kwargs.keys():
            self._message = await thread.fetch_message(kwargs["message_id"])
        else:
            punishment_embed_msgs = self._settings["messages"]["punishment_poll_embed"]
            punishment_entry = punishment_embed_msgs["punishment_entry"]
            punishments = self._settings["punishments"]
            punishment_poll_description_format = punishment_embed_msgs[
                "description_format"
            ]

            desc = ""
            punishment_entries = ""

            for p_id, entry in punishments.items():
                punishment_entries = (
                    punishment_entries
                    + punishment_entry.replace("{emoji}", entry["emoji"])
                    .replace("{name}", entry["name"].capitalize())
                    .replace("{short_description}", entry["short_description"])
                    .replace("{type}", entry["punishment_type"])
                    + "\n"
                )

            title = None

            async def send_cg_embed(cg_id: str, thread: Thread):
                parsed_cgs = self._module._get_bot().moderation.get_parsed_cgs()
                selected_cgs = {}
                for key in parsed_cgs.keys():
                    if cg_id.startswith(key):
                        selected_cgs[key] = parsed_cgs[key]

                desc = ""

                for key, value in selected_cgs.items():
                    desc = desc + f"`{key}` {value}"

                cg_embed: discord.Embed = discord.embeds.Embed(
                    colour=config.EMBED_COLOUR,
                    description=f"{desc}",
                    title=f"CG: {cg_id}",
                )

                await thread.send(embed=cg_embed)

            if "cg_id" in kwargs.keys():
                if "message_id" not in kwargs.keys():
                    await send_cg_embed(kwargs["cg_id"], self._reprimand._get_thread())

                title = (
                    punishment_embed_msgs["title"]["singular"]
                    .replace("{cg_id}", kwargs["cg_id"])
                    .replace(
                        "{accused_name}",
                        f"{self._reprimand.get_accused().name}#{self._reprimand.get_accused().discriminator}",
                    )
                )
            else:
                title = punishment_embed_msgs["title"]["multiple"].replace(
                    "{accused_name}",
                    f"{self._reprimand.get_accused().name}#{self._reprimand.get_accused().discriminator}",
                )

            embed = discord.Embed(
                colour=config.EMBED_COLOUR,
                title=title,
                description=punishment_poll_description_format.replace(
                    "{punishment_entries}", punishment_entries
                ).replace("{duration}", format_time.seconds(self._countdown)),
            )
            self._message = await self._reprimand._get_thread().send(embed=embed)

            for entry in punishments.values():
                await self._message.add_reaction(entry["emoji"])

            if kwargs["is_new"]:
                self._data_manager.add_poll(
                    self._thread.id, self._message.id, self._countdown
                )

    def save(self):
        """
        Saves current duration of poll to relevant collection.
        """
        self._module.get_data_manager().update_poll(
            self._thread.id, self._message.id, self._countdown
        )

    def tick(self, reprimand):
        if self._countdown > 0:
            self._countdown = self._countdown - 1

        if self._countdown % 0 == 0:
            self.save()

    # print(self._countdown)

    def get_seconds_remaining(self):
        return self._countdown

    def get_ayes(self) -> int:
        if not self._message:
            raise Exception("No message reference in PunishmentPoll.")

        reactions = self._message.reactions

        for reaction in reactions:
            if reaction.emoji == "👍":
                return reaction.count - 1  # Accounting for the the emoji.
        return 0

    def get_noes(self) -> int:
        if not self._message:
            raise Exception("No message reference in PunishmentPoll.")

        reactions = self._message.reactions

        for reaction in reactions:
            if reaction.emoji == "👎":
                return reaction.count - 1  # Accounting for the bot emoji.
        return 0

    def get_type(self):
        return PollType.PUNISHMENT_POLL


class Reprimand:
    def __init__(self, module):
        self._module = module
        self._data_manager: ReprimandDataManager = module.get_data_manager()
        self._settings = module.get_settings()
        self._polls: list[Poll] = []
        self._accused: discord.Member = None

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
                name=f"{self._accused.name} {self._accused.discriminator}",
                type=ChannelType.public_thread,
            )
        else:
            self._thread = self._channel.get_thread(kwargs["thread_id"])

        # This part is for new Reprimand threads, not existing ones being loaded.

        cg_ids = kwargs["cg_ids"]
        cg_poll_duration = self._settings["duration"]["multiple_poll"]["cg_poll"]
        m_pun_poll_duration = self._settings["duration"]["multiple_poll"][
            "punishment_poll"
        ]
        s_pun_poll_duration = self._settings["duration"]["single_poll"]

        if len(cg_ids) > 1:
            for cg_id in cg_ids:
                cg_poll = CGPoll(self)
                self._polls.append(cg_poll)
                await cg_poll.load(cg_id=cg_id, duration=cg_poll_duration)

            p_poll = PunishmentPoll(self)
            await p_poll.load(duration=m_pun_poll_duration)
            self._polls.append(p_poll)
        else:
            p_poll = PunishmentPoll(self)
            self._polls.append(p_poll)
            cg_id = kwargs["cg_ids"][0]
            await p_poll.load(
                cg_id=cg_id,
                duration=s_pun_poll_duration,
                is_new=kwargs["is_new"] if "is_new" in kwargs.keys() else False,
            )

        self.countdown_loop.start()

    def start(self):
        self.countdown_loop.start()

    @loop(seconds=1)
    async def countdown_loop(self):
        for poll in self._polls:
            poll.tick(self)

    def _get_module(self):
        return self._module

    def _get_thread(self) -> Thread:
        return self._thread

    def get_polls(self):
        return self._polls

    def get_accused(self) -> discord.Member:
        return self._accused

    def is_multi_cgs(self):
        return len(self._cgs) > 1

    def end(self):
        pass


class PunishmentType(Enum):
    INFORMAL = 0
    FORMAL = 1
    MUTE = 2
    BAN = 3


class ReprimandModule:
    def __init__(self, bot):
        self._bot: Bot = bot
        self._bot.logger.info("Reprimand Module has been initiated.")
        self._reprimand_channel: Union[TextChannel, None] = None
        self._settings_handler: SettingsHandler = bot.settings_handler
        self._logger = bot.logger
        self._db = database.get_connection()
        self._live_reprimands: list[Reprimand] = []
        self._data_manager = ReprimandDataManager()

        self._settings = {
            "punishments": {
                "informal": {
                    "description": "An informal warning, often a word said to them thorough a ticket or direct messages. This form of punishment doesn't appear on their record.",
                    "short_description": "Informal warning.",
                    "emoji": "1️⃣",
                    "name": "Informal Warning",
                    "punishment_type": "WARNING",
                    "punishment_duration": "",
                },
                "1formal": {
                    "description": "A formal warning. Unlike informal warnings this does appear on their record, and is given thorough the bot to the user on a ticket or thorough DMs",
                    "emoji": "2️⃣",
                    "name": "1 Formal Warning",
                    "punishment_type": "WARNING",
                    "short_description": "Formal warning.",
                    "punishment_duration": "",
                },
                "2formal": {
                    "description": "Two formal warnings",
                    "name": "2 Formal Warnings",
                    "short_description": "Two formal warnings.",
                    "punishment_type": "WARNING",
                    "emoji": "3️⃣",
                },
                "mute": {
                    "description": "Mutes a user for an alloted amount of time, this will obviously appear on their record. The amount of time a person gets can be determined thorough a poll or preestablished times.",
                    "emoji": "4️⃣",
                    "name": "Mute",
                    "short_description": "Mute",
                    "punishment_type": "MUTE",
                },
                "ban": {
                    "description": "Bans a user from the server, this will appear on their record too.",
                    "short_description": "Ban",
                    "name": "Ban",
                    "punishment_type": "BAN",
                    "emoji": "5️⃣",
                },
            },
            "reprimand_channel": "",
            "duration": {
                "single_poll": 500,
                "multiple_poll": {"cg_poll": 500, "punishment_poll": 600},
            },
            "notifications": {"500": "Notification Text"},
            "messages": {
                "case_log_messages": {},
                "message_to_accused": {},
                "rtime": {
                    "header": "Time Remaining",
                    "entry": {
                        "gc_poll": "{cg_id} GCPoll has {time_remaining}",
                        "p_poll": "Poll has {time_remaining}",
                    },
                },
                "cg_poll_embed": {
                    "title": "Has {user} breached {cg_id}?",
                    "footer": "",
                    "body": "{cg_description}\n\nPoll Duration: {duration} (execute >time to see current time)\n\n**Options**\n👍 to vote in the affirmative\n👎 to vote in the negative",
                },
                "punishment_poll_embed": {
                    "title": {
                        "singular": "{accused_name} accused of breaching {cg_id}. What action should be taken?",
                        "multiple": "{accused_name} accused of breaching multiple CGs. What action should be taken?.",
                    },
                    "footer": "",
                    "punishment_entry": "{emoji} | **{name}:**  {short_description}",
                    "description_format": "{punishment_entries} \n Poll Duration: {duration} (execute >time to see current time)",
                },
                "evidence_messages": {
                    "header": "-- Evidence --",
                },
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

    def get_data_manager(self) -> ReprimandDataManager:
        return self._data_manager

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

    def is_reprimand_thread(self, thread_id: int) -> bool:
        reprimands = self._live_reprimands

        for reprimand in reprimands:
            print(f"Reprimand Thread ID: {reprimand._get_thread().id}")
            if reprimand._get_thread().id == thread_id:
                return True
        return False

    def get_punishments(self):
        return self.get_settings()["punishments"]

    def is_punishment_id(self, possible_id: str):
        return possible_id in self.get_punishments().keys()

    def get_punishment(self, punishment_id: str):
        return self.get_punishments()[punishment_id]

    def add_punishment(
        self,
        punishment_id: str,
        punishment_type: PunishmentType,
        duration: str,
        name: str,
        short_description: str,
        emoji: Emoji,
    ):
        """
        Add a punishment to the reprimand config file.

        Parameters
        ----------
        punishment_id: :class:`str`
            The id of the punishment.
        punishment_type: :class:`PunishmentType`
            The type of punishment th is entry is.
        duration: :class:`str`
            The duration of the punishmen in string form (5m, 1h, 30s, 0s, &c)
        name: :class:`str`
            The formal name of the punishment.
        short_description: :class:`str`
            A very brief description of the punishment (One Formal Warning - for example)
        emoji: :class:`Emoji`
            The emoji used in a modpoll to sympolise a vote for this punishment/
        """

        punishment_settings = self.get_settings()["punishments"]

        punishment_settings[punishment_id] = {
            "short_description": short_description,
            "type": punishment_type,
            "duration": format_time.parse(duration),
            "emoji": str(emoji),
            "name": name,
        }

        self.set_setting("punishments", punishment_settings)

    def remove_punishment(self, punishment_id: str):
        """
        Removes a punishment from the reprimand config file.

        Parameters
        ----------
        punishment_id: :class:`str`
            The id of the punishment being removed.
        """
        punishment_settings = self.get_settings()["punishments"]
        p_ids = punishment_settings.keys()

        if punishment_id in p_ids:
            del punishment_settings[punishment_id]
            self.set_setting("punishments", punishment_settings)

    def get_settings(self):
        return self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
            "reprimand"
        ]

    async def create_reprimand(
        self, accused: discord.Member, cg_ids: list[str]  # evidence_links: list[str]
    ) -> Reprimand:
        reprimand = Reprimand(self)
        await reprimand.load(
            accused=accused, cg_ids=cg_ids, is_new=True  # evidence_links=evidence_links
        )
        self._live_reprimands.append(reprimand)
        return reprimand

    def get_reprimand(self, thread_id: int) -> Union[Reprimand, None]:
        reprimands = self._live_reprimands

        for reprimand in reprimands:
            if reprimand._get_thread().id == thread_id:
                return reprimand
        return None


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

    def get_parsed_cgs(self):
        return self.parsed_cgs

    def get_cg(self, cg_id: str) -> str:
        return self.parsed_cgs[cg_id]
