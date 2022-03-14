import asyncio
import math
import time
from codecs import replace_errors
from typing import Union

import config
import discord
import pymongo
from cachetools import cached
from cachetools.ttl import TTLCache
from discord import ButtonStyle, Interaction, Member, Message, Thread, threads
from discord.channel import TextChannel
from discord.ext.commands import Context
from discord.ext.tasks import loop
from discord.ui import Button, View, button
from pymongo.collection import Collection

import modules.database as database
import modules.embed_maker as embed_maker
import modules.format_time as format_time
from modules.utils import SettingsHandler

# TODO: Setup cooldowns according to the perks a user had (cooldown between creating threadpolls.
# TODO: Create mod commands to unilaterally rewrite a thread topic.
# TODO: Create a command to allow the community to change the name of a thread (>namepoll?)

# TODO: See if you can't get that announcement channel working for Captcha.
# TODO: Perhaps rework the daily report for Captcha.
class DataManager:
    def __init__(self, logger):
        self._logger = logger
        self._db = database.get_connection()
        self._threading_profiles: Collection = self._db.threading_profiles
        self._threading_threads: Collection = self._db.threading_threads

    def save_profile(self, profile):
        self._threading_profiles.update_one(
            {"member_id": profile.get_id()},
            {
                "$set": {
                    "rep": profile.get_rep(),
                    "cooldown_timestamp": profile.get_cooldown_timestamp(),
                    "perm": profile.has_perm(),
                }
            },
            upsert=True,
        )

    def get_profiles(self, sort_by_rep: bool = False):
        if sort_by_rep:
            return self._threading_profiles.find({}).sort("rep", pymongo.DESCENDING)
        else:
            return self._threading_profiles.find({})

    def fetch_profile(self, member_id: int):
        return self._threading_profiles.find_one({"member_id": member_id})

    def save_thread(self, thread_dict: dict):

        return self._threading_threads.update_one(
            {"thread_id": thread_dict["thread_id"]},
            {
                "$set": {
                    "thread_id": thread_dict["thread_id"],
                    "renamepoll_cooldown": thread_dict["renamepoll_cooldown"],
                }
            },
            upsert=True,
        )

    def fetch_thread(self, thread_id: int):
        return self._threading_threads.find_one({"thread_id": thread_id})

    def is_thread(self, first_message_id: int):
        m_thread = self._threading_threads.find_one(
            {"first_message_id": first_message_id}
        )
        if m_thread is None:
            return False
        if m_thread["first_message_id"] != 0:
            return True
        return False


class ThreadProfile:
    def __init__(
        self,
        data_manager: DataManager,
        member_id: int,
        rep: int = 0,
        permission: bool = True,
        cooldown_timestamp: int = 0,
    ):
        self._member_id = member_id
        self._rep = rep
        self._perm = permission
        self._cooldown_end = cooldown_timestamp
        self._data_manager = data_manager

    def has_perm(self):
        return self._perm

    def set_perm(self, perm: bool):
        self._perm = perm
        self._data_manager.save_profile(self)

    def get_id(self):
        return self._member_id

    def get_rep(self):
        return self._rep

    def set_rep(self, rep):
        self._rep = rep
        self._data_manager.save_profile(self)

    def set_cooldown(self, cooldown_in_seconds: int):
        self._cooldown_end = time.time() + cooldown_in_seconds
        self._data_manager.save_profile(self)

    def get_cooldown_timestamp(self):
        return self._cooldown_end - time.time()

    def can_create_threadpoll(self):
        return self._cooldown_end <= time.time()


class RenamePoll(View):
    def __init__(
        self, module, initiator: Member, ctx: Context, thread: Thread, new_name
    ):
        super().__init__()
        self._module = module
        self._initiator = initiator
        self._ctx = ctx
        self._thread = thread
        self._new_title = new_name
        self._settings = module.get_settings()
        self._internal_clock = self._settings["renamepoll"]["poll_duration"]
        self._voting_threshold = self._settings["renamepoll"]["aye_vote_threshold"]
        self._ctx = ctx
        self._yes_votes = []
        self._no_votes = []

    @button(label="Yes", style=ButtonStyle.green)
    async def yes_button_callback(self, button: Button, interaction: Interaction):
        client_id = interaction.user.id

        if client_id not in self._yes_votes:
            if client_id in self._no_votes:
                self._no_votes.pop(self._no_votes.index(client_id))
            self._yes_votes.append(client_id)

    @button(label="No", style=ButtonStyle.danger)
    async def no_button_callback(self, button: Button, interaction: Interaction):
        client_id = interaction.user.id

        if client_id not in self._no_votes:
            if client_id in self._yes_votes:
                self._yes_votes.pop(self._yes_votes.index(client_id))
            self._no_votes.append(client_id)

    async def initiate(self):
        poll_embed_messages = self._settings["messages"]["renamepoll"]["poll_embed"]

        await embed_maker.message(
            self._ctx,
            description=poll_embed_messages["description"]
            .replace("{proposed_new_title}", self._new_title)
            .replace("{voting_threshold}", str(self._voting_threshold))
            .replace("{formatted_duration}", format_time.seconds(self._internal_clock)),
            title=poll_embed_messages["title"],
            view=self,
            send=True,
        )
        self.countdown.start()

    @loop(seconds=1)
    async def countdown(self):
        def delete_from_dict():
            del self._module._renamepolls[self._thread.id]

        async def succeeded():
            poll_embed_messages = self._settings["messages"]["renamepoll"]["poll_embed"]

            await embed_maker.message(
                self._ctx,
                description=poll_embed_messages["succeeded"]["description"]
                .replace("{old_thread_name}", self._thread.name)
                .replace("{new_thread_name}", self._new_title)
                .replace("{yes_vote_result}", str(len(self._yes_votes)))
                .replace("{no_vote_result}", str(len(self._no_votes))),
                title=poll_embed_messages["succeeded"]["title"],
                send=True,
            )
            thread = await self._thread.edit(name=self._new_title)
            renamepoll_cooldown = self._settings["renamepoll"]["cooldown"]
            self._module.get_data_manager().save_thread(
                {
                    "thread_id": thread.id,
                    "renamepoll_cooldown": time.time() + renamepoll_cooldown,
                }
            )
            print("Set rename cooldown.")
            profile = self._module.get_profile(self._initiator.id)
            profile.set_rep(
                profile.get_rep() + self._settings["renamepoll"]["rep_renamepoll_pass"]
            )
            delete_from_dict()

        async def failed():
            poll_embed_messages = self._settings["messages"]["renamepoll"]["poll_embed"]

            await embed_maker.message(
                self._ctx,
                description=poll_embed_messages["failed"]["description"]
                .replace("{proposed_new_title}", self._new_title)
                .replace("{yes_vote_result}", str(len(self._yes_votes)))
                .replace("{no_vote_result}", str(len(self._no_votes))),
                title=poll_embed_messages["failed"]["title"],
                send=True,
            )
            delete_from_dict()

        self._internal_clock -= 1
        if self._internal_clock <= 0:
            self.countdown.stop()
            if len(self._yes_votes) > len(self._no_votes):
                if len(self._yes_votes) >= self._voting_threshold:
                    await succeeded()
                else:
                    await failed()
            else:
                if len(self._yes_votes) > self._voting_threshold and len(
                    self._yes_votes
                ) > len(self._no_votes):
                    await succeeded()
                else:
                    await failed()


class ThreadPoll(View):
    def __init__(self, module, ctx: Context, replying_message: Message, title: str):
        super().__init__()
        self._module = module
        self._settings = module.get_settings()
        self._internal_clock = self._settings["threadpoll"]["poll_duration"]
        self._voting_threshold = self._settings["threadpoll"]["aye_vote_threshold"]
        self._ctx = ctx
        self._replying_message = replying_message
        self._title = title
        self._yes_votes = []
        self._no_votes = []

    def _get_internal_clock(self):
        return self._internal_clock

    @button(label="Yes", style=ButtonStyle.green)
    async def yes_button_callback(self, button: Button, interaction: Interaction):
        client_id = interaction.user.id

        if client_id not in self._yes_votes:
            if client_id in self._no_votes:
                self._no_votes.pop(self._no_votes.index(client_id))
            self._yes_votes.append(client_id)

    @button(label="No", style=ButtonStyle.danger)
    async def no_button_callback(self, button: Button, interaction: Interaction):
        client_id = interaction.user.id

        if client_id not in self._no_votes:
            if client_id in self._yes_votes:
                self._yes_votes.pop(self._yes_votes.index(client_id))
            self._no_votes.append(client_id)

    def get_replying_message_id(self):
        return self._replying_message.id

    async def initiate(self):
        poll_embed_messages = self._settings["messages"]["threadpoll"]["poll_embed"]

        await embed_maker.message(
            self._ctx,
            description=poll_embed_messages["description"]
            .replace("{replying_comment}", self._replying_message.content)
            .replace("{voting_threshold}", str(self._voting_threshold))
            .replace("{formatted_duration}", format_time.seconds(self._internal_clock)),
            title=poll_embed_messages["title"],
            view=self,
            send=True,
        )
        self.countdown.start()

    @loop(seconds=1)
    async def countdown(self):
        def delete_from_dict():
            del self._module._threadpolls[self._replying_message.id]

        async def succeeded():
            poll_embed_messages = self._settings["messages"]["threadpoll"]["poll_embed"]

            await embed_maker.message(
                self._ctx,
                description=poll_embed_messages["succeeded"]["description"]
                .replace("{replying_comment}", self._replying_message.content)
                .replace("{yes_vote_result}", str(len(self._yes_votes)))
                .replace("{no_vote_result}", str(len(self._no_votes))),
                title=poll_embed_messages["succeeded"]["title"],
                send=True,
            )
            thread = await self._replying_message.create_thread(
                name=self._title.capitalize()
            )
            self._module.get_data_manager().save_thread(
                {
                    "thread_id": thread.id,
                    "renamepoll_cooldown": 0,
                }
            )
            profile = self._module.get_profile(self._replying_message.author.id)
            profile.set_rep(
                profile.get_rep() + self._settings["threadpoll"]["rep_threadpoll_pass"]
            )
            delete_from_dict()

        async def failed():
            poll_embed_messages = self._settings["messages"]["threadpoll"]["poll_embed"]

            await embed_maker.message(
                self._ctx,
                description=poll_embed_messages["failed"]["description"]
                .replace("{replying_comment}", self._replying_message.content)
                .replace("{yes_vote_result}", str(len(self._yes_votes)))
                .replace("{no_vote_result}", str(len(self._no_votes))),
                title=poll_embed_messages["failed"]["title"],
                send=True,
            )
            delete_from_dict()

        self._internal_clock -= 1
        if self._internal_clock <= 0:
            self.countdown.stop()
            poll_embed_messages = self._settings["messages"]["threadpoll"]["poll_embed"]
            if len(self._yes_votes) > len(self._no_votes):
                if len(self._yes_votes) >= self._voting_threshold:
                    await succeeded()
                else:
                    await failed()
            else:
                if len(self._yes_votes) > self._voting_threshold and len(
                    self._yes_votes
                ) > len(self._no_votes):
                    await succeeded()
                else:
                    await failed()


class ThreadingModule:
    def __init__(self, bot):
        self._bot = bot
        self._threadpolls = {}
        self._renamepolls = {}

        self._default_settings = {
            "bot_channel_id": 0,
            "threadpoll": {
                "poll_duration": 60,
                "aye_vote_threshold": 1,
                "rep_threadpoll_pass": 10,
            },
            "renamepoll": {
                "poll_duration": 60,
                "aye_vote_threshold": 1,
                "rep_renamepoll_pass": 10,
                "cooldown": 30,
            },
            "word_blacklist": [],
            "messages": {
                "threadpoll": {
                    "poll_embed": {
                        "title": "ThreadPoll",
                        "description": "**Topic Question:** {replying_comment}\n**Voting:** Required a majority vote and a voting majority threshold of {voting_threshold}.\n**Poll Duration:** {formatted_duration}",
                        "succeeded": {
                            "title": "Poll Passed!",
                            "description": "**Topic Question:** {replying_comment}\n**Result:** {yes_vote_result} Ayes to {no_vote_result} Noes.",
                        },
                        "failed": {
                            "title": "Poll Failed!",
                            "description": "**Topic Question:** {replying_comment}\n**Result:** {no_vote_result} Noes to {yes_vote_result} Ayes.",
                        },
                    },
                },
                "renamepoll": {
                    "poll_embed": {
                        "title": "RenamePoll",
                        "description": "**Proposed Title:** {proposed_new_title}\n**Voting:** Required a majority vote and a voting majority threshold of {voting_threshold}.\n**Poll Duration:** {formatted_duration}",
                        "succeeded": {
                            "title": "Poll Passed!",
                            "description": "**Proposed Title:** {new_thread_name}\n**Result:** {yes_vote_result} Ayes to {no_vote_result} Noes.",
                        },
                        "failed": {
                            "title": "Poll Failed!",
                            "description": "**Proposed Title:** {proposed_new_title}\n**Result:** {no_vote_result} Noes to {yes_vote_result} Ayes.",
                        },
                    },
                },
                "user": {
                    "cooldown_cant_create_poll": "Can't create poll. {formatted_cooldown} cooldown left.",
                    "no_perms": {
                        "title": "No Permission.",
                        "description": "You do not have permission to create a threadpoll.",
                    },
                    "embed_rep": {
                        "title": "{display_name}'s Reputation",
                        "description": "**Rep:** {rep_value}",
                    },
                    "stats_embed": {
                        "title": "Leaderboard",
                        "stat_entry": "`#{position}` - {display_name} [{username}#{discriminator}] | {rep_value}",
                    },
                    "info_embed": {
                        "title": "Reputation Levels",
                        "info_entry": "`#{position}` - Rep: {rep_value} / {formatted_cooldown} ",
                    },
                    "mod": {
                        "failed_to_find_user": {
                            "title": "Failed.",
                            "description": "Failed to find user.",
                        },
                        "already_revoked_perms": {
                            "title": "Already Revoked Permissions",
                            "description": "User {display_name} already has threading perms removed.",
                        },
                        "already_has_perms": {
                            "title": "Already has Perms.",
                            "description": "User {display_name} already has voting and poll creation perms.",
                        },
                        "renamed_thread": {
                            "title": "Renamed Thread.",
                            "description": "Renamed thread `{thread_id}` from `{previous_title}` to `{current_title}`",
                        },
                        "revoked_perms": {
                            "title": "Revoked Permissions",
                            "description": "Revoking perms of {display_name} to create and vote on threads.",
                        },
                        "returned_perms": {
                            "title": "Returned Perms.",
                            "description": "Returning perms of {display_name} to create and vote on threads.",
                        },
                        "blacklist_embed": {
                            "title": "Blacklisted Words",
                            "word_entry": "**{position}.** {word}",
                        },
                        "add_words_to_blacklist_embed": {
                            "description": "Added the following words: {added_words}. {already_added_words}",
                            "already_added_words": "The following words were already added: {already_added_words}",
                            "title": "Added Words to Blacklist.",
                        },
                        "remove_words_from_blacklist_embed": {
                            "description": "The following words were removed: {words_removed}. {words_not_removed}",
                            "words_not_in_blacklist": "The follow words were not in the blacklist: {words_not_in_blacklist}",
                        },
                    },
                },
            },
        }

        self._logger = bot.logger
        self._settings_handler: SettingsHandler = bot.settings_handler
        settings = self._settings_handler.get_settings(config.MAIN_SERVER)

        if "threading" not in settings["modules"].keys():
            self._logger.info(
                "Threading Module settings not found in Guild settings. Adding default settings now."
            )
            settings["modules"]["threading"] = self._default_settings
            self._settings_handler.save(settings)
        self._settings_handler.update(
            "threading", self._default_settings, config.MAIN_SERVER
        )

        self._thread_profiles: TTLCache[int, ThreadProfile] = TTLCache(
            maxsize=500, ttl=500
        )
        self._data_manager = DataManager(bot.logger)
        self._rep_levels: dict[int, int] = {}

        if self._bot.google_drive:
            self.levels_spreadsheet = self._bot.google_drive.download_spreadsheet(
                config.REP_SPREADSHEET_ID
            )
            self._bot.logger.info("Downloading Threading Rep Level Spreadsheet.")
            for row in self.levels_spreadsheet["levels"][1:]:
                if not row:
                    break
                self._rep_levels[int(row[0])] = int(row[1])
            self._bot.logger.info(
                f"{len(self._rep_levels)} Threading Rep Levels Loaded."
            )
        else:
            raise Exception(
                "Threading module depends on google drive module being enabled."
            )

    def get_rep_levels(self):
        return self._rep_levels

    def get_word_blacklist(self):
        return self.get_settings()["word_blacklist"]

    def add_words_to_blacklist(self, words: list):
        blacklist = self.get_settings()["word_blacklist"]
        l_words = list(map(lambda word: word.lower(), words))
        self.get_settings()["word_blacklist"] = blacklist + l_words
        global_settings = self._bot.settings_handler.get_settings(config.MAIN_SERVER)
        global_settings["modules"]["threading"] = self.get_settings()
        self._bot.settings_handler.save(global_settings)

    def remove_words_from_blacklist(self, words: list):
        blacklist = self.get_settings()["word_blacklist"]

        new_blacklist = []

        for b_word in blacklist:
            for word in words:
                if b_word == word:
                    b_word = b_word.replace(word, "")
            new_blacklist.append(b_word)
        self.get_settings()["word_blacklist"] = new_blacklist
        self._bot.settings_handler.save(self.get_settings())

    def is_blacklisted_word(self, word: str):
        return word.lower() in self.get_settings()["word_blacklist"]

    def get_settings(self):
        return self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
            "threading"
        ]

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

        path = f"modules.threading.{path}"
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

    def get_profile(self, member_id: int):
        if member_id not in self._thread_profiles.keys():
            profile = self._data_manager.fetch_profile(member_id)
            thread_profile = None

            if profile is None:
                thread_profile = ThreadProfile(self._data_manager, member_id)
                self._data_manager.save_profile(thread_profile)
                self._thread_profiles[member_id] = thread_profile
            else:
                thread_profile = ThreadProfile(
                    self._data_manager,
                    member_id,
                    profile["rep"],
                    profile["perm"],
                    profile["cooldown_timestamp"],
                )
            self._thread_profiles[member_id] = thread_profile
        return self._thread_profiles[member_id]

    def get_cooldown(self, user_rep: int):
        reps = list(self._rep_levels.keys())

        for rep in reps:
            if user_rep >= rep:
                return rep

        return 60

    def get_data_manager(self):
        return self._data_manager

    def get_profiles(self, sort_by_rep: bool = False):
        if sort_by_rep:
            m_profiles = self._data_manager.get_profiles(sort_by_rep)
            print(m_profiles)
            if m_profiles is not None:
                for m_profile in m_profiles:
                    profile = ThreadProfile(
                        self._data_manager,
                        m_profile["member_id"],
                        m_profile["rep"],
                        m_profile["perm"],
                        m_profile["cooldown_timestamp"],
                    )

                    self._thread_profiles[m_profile["member_id"]] = profile

        return list(self._thread_profiles.values())

    def being_polled(self, replying_message_id: int):
        return replying_message_id in self._threadpolls.keys()

    async def threadpoll(self, ctx: Context, title: str):
        replying_message = await ctx.channel.fetch_message(
            ctx.message.reference.message_id
        )
        self._threadpolls[replying_message.id] = ThreadPoll(
            self, ctx, replying_message, title
        )
        profile = self.get_profile(ctx.author.id)
        cooldown = self._bot.threading.get_cooldown(profile.get_rep())
        profile.set_cooldown(
            cooldown + self.get_settings()["threadpoll"]["poll_duration"]
        )
        return self._threadpolls[replying_message.id]

    def can_create_renamepoll(self, ctx: Context):
        m_thread = self._data_manager.fetch_thread(ctx.channel.id)
        if m_thread is None:
            return False

        return m_thread["renamepoll_cooldown"] <= time.time()

    def is_already_thread(self, message_id: int):
        return self._data_manager.is_thread(message_id)

    def get_renamepoll(self, thread_id: int):
        m_thread = self._data_manager.fetch_thread(thread_id)
        if m_thread is None:
            return 0
        return m_thread["renamepoll_cooldown"]

    def renamepoll(self, ctx: Context, new_title: str):
        thread = ctx.channel
        self._renamepolls[thread.id] = RenamePoll(
            self, ctx.author, ctx, thread, new_title
        )
        return self._renamepolls[thread.id]
