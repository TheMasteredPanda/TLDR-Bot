import asyncio
import copy
import functools
import math
import time
from datetime import datetime
from typing import Union

import config
import modules.embed_maker as embed_maker
import modules.format_time as format_time
from bot import TLDR
from bson import json_util
from discord import Thread
from discord.errors import HTTPException
from discord.ext.commands import Cog, Context, command, group
from modules.commands import Command, Group
from modules.reaction_menus import BookMenu
from modules.threading import ThreadProfile
from modules.utils import ParseArgs, get_member_from_string


class Threading(Cog):
    def __init__(self, bot: TLDR):
        self._bot = bot

    async def send_dm(self, ctx: Context, description: str):
        channel_id = self._bot.threading.get_settings()["bot_channel_id"]

        try:
            return await ctx.author.send(description)
        except HTTPException as ex:
            channel = await self._bot.get_guild(config.MAIN_SERVER).get_channel(
                channel_id
            )
            channel.send(description)

    @group(
        name="threads",
        help="Root command for the Threading Manager. A manager used to regulate community self-management of threads.",
        examples=["threads config", "threads revoke", "threads permit"],
        invoke_without_command=True,
        module_dependency=["threading"],
        cls=Group,
    )
    async def threads(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @command(
        name="threadpoll",
        help="Creates a poll to ask the channel this command is executed in whether or not the replied comment should become a channel.",
        examples=["threadpoll [Channel Title - mandatory]"],
        cls=Command,
    )
    async def thread_poll_cmd(self, ctx: Context, *, title: str = ""):
        if ctx.message.reference is None:
            return await embed_maker.message(
                ctx,
                description="A poll can only be made by replying to the comment you want a thread made of.",
                title="No.",
                send=True,
            )

        if isinstance(ctx.channel, Thread):
            return await self.send_dm(ctx, "Can't create thread from a thread.")

        if title == "":
            return await embed_maker.command_error(ctx)

        blacklist = self._bot.threading.get_word_blacklist()

        for word in blacklist:
            if word in title.lower():
                return await self.send_dm(
                    ctx, f"Word {word.capitalize()} is blacklisted."
                )

        replying_message = await ctx.channel.fetch_message(
            ctx.message.reference.message_id
        )

        if replying_message.flags.has_thread:
            return await self.send_dm(ctx, "Can't create thread from a thread.")

        messages = self._bot.threading.get_settings()["messages"]["user"]
        if self._bot.threading.being_polled(replying_message.id):
            return await ctx.message.delete()

        profile = self._bot.threading.get_profile(ctx.author.id)

        if profile.has_perm() is False:
            return await embed_maker.message(
                ctx,
                description=messages["no_perms"]["description"],
                title=messages["no_perms"]["title"],
                send=True,
            )

        if profile.can_create_threadpoll() is False:
            return await self.send_dm(
                ctx,
                f"Can't create threadpoll yet. Cooldown Left: {format_time.seconds(profile.get_cooldown_timestamp())}",
            )

        threadpoll = await self._bot.threading.threadpoll(ctx, title)
        asyncio.create_task(threadpoll.initiate())

    @command(
        name="renamepoll",
        help="A rename poll allows a community to rename an already created thread through a poll.",
        examples=["renamepoll [proposed title]"],
        cls=Command,
    )
    async def rename_poll_cmd(self, ctx: Context, *, title: str = ""):
        if isinstance(ctx.channel, Thread) is False:
            return

        if title == "":
            return await embed_maker.command_error(ctx)

        blacklist = self._bot.threading.get_word_blacklist()

        for word in blacklist:
            if word in title.lower():
                return await self.send_dm(
                    ctx, f"Word {word.capitalize()} is blacklisted."
                )

        messages = self._bot.threading.get_settings()["messages"]["user"]

        profile = self._bot.threading.get_profile(ctx.author.id)

        if profile.has_perm() is False:
            return await embed_maker.message(
                ctx,
                description=messages["no_perms"]["description"],
                title=messages["no_perms"]["title"],
                send=True,
            )

        if self._bot.threading.can_create_renamepoll(ctx) is False:
            return await self.send_dm(
                ctx,
                f"Can't create renamepoll yet. Cooldown Left: {format_time.seconds(self._bot.threading.get_renamepoll(ctx.channel.id) - time.time())}",
            )

        renamepoll = self._bot.threading.renamepoll(ctx, title)
        asyncio.create_task(renamepoll.initiate())

    @threads.group(
        name="mod",
        help="Moderation commands for the threading feature.",
        examples=["threads mod revoke", "threads mod permit"],
        invoke_without_command=True,
        cls=Group,
    )
    async def mod_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @mod_cmd.group(
        name="config",
        help="Configuration commands for Threading.",
        usage="threads mod config <subcommand>",
        invoke_without_command=True,
        cls=Group,
    )
    async def config_mod_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @config_mod_cmd.group(
        name="blacklist",
        help="Blacklist certain words from being included in a namepoll or threadpoll.",
        usage="threads mod config blacklist",
        invoke_without_command=True,
        cls=Group,
    )
    async def wordlist_blacklist_config_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @wordlist_blacklist_config_cmd.command(
        name="view",
        help="View all blacklisted words.",
        usage="threads mod config blacklist view",
        cls=Command,
    )
    async def view_wordlist_cmd(self, ctx: Context):
        async def construct_blacklist_embed(
            ctx, words: list, max_page_num: int, page_limit: int, *, page: int
        ):
            if len(words) == 0:
                return await embed_maker.message(
                    ctx, description="No words found in blacklist."
                )

            bits = []
            blacklist_embed = self._bot.threading.get_settings()["messages"]["user"][
                "mod"
            ]["blacklist_embed"]

            for i, entry in enumerate(
                words[page_limit * (page - 1) : page_limit * page]
            ):
                bits.append(
                    blacklist_embed["word_entry"]
                    .replace("{position}", str(i + 1))
                    .replace("{word}", entry.capitalize())
                )

            return await embed_maker.message(
                ctx,
                description="\n".join(bits),
                author={"name": "Threading Word Blacklist."},
                footer={"text": f"Page {page}/{max_page_num}"},
            )

        blacklist = self._bot.threading.get_word_blacklist()
        max_page_size = 10
        max_page_num = math.ceil(len(blacklist) / max_page_size)
        page_constructor = functools.partial(
            construct_blacklist_embed,
            ctx=ctx,
            words=blacklist,
            max_page_num=max_page_num,
            page_limit=max_page_size,
        )
        embed = await page_constructor(page=1)
        message = await ctx.send(embed=embed)
        menu = BookMenu(
            message,
            page=1,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
            author=ctx.author,
        )
        self._bot.reaction_menus.add(menu)

    @wordlist_blacklist_config_cmd.command(
        name="add",
        help="Add words to the blacklist.",
        uasge="threads mod config blacklist add [word] <word> <word> <word>...",
        cls=Command,
    )
    async def add_wordlist_cmd(self, ctx: Context, *, words: str = ""):
        if words == "":
            return await embed_maker.command_error(ctx)

        words = list(map(lambda word: word.lower(), words.strip().split(",")))

        already_added = []
        for word in words:
            if self._bot.threading.is_blacklisted_word(word):
                already_added.append(word)

        for a_word in already_added:
            words = [word.replace(a_word, "") for word in words]

        messages = self._bot.threading.get_settings()["messages"]["user"]["mod"][
            "add_words_to_blacklist_embed"
        ]

        if len(words) == 0:
            return await embed_maker.message(
                ctx,
                description="No unique words to add.",
                title="No new words.",
                send=True,
            )

        words = list(filter(None, words))

        description = (
            messages["description"].replace("{added_words}", ", ".join(words))
            if len(words) != 0
            else messages["already_added_words"].replace(
                "{already_added_words}", ", ".join(already_added)
            )
        ).replace(
            "{already_added_words}",
            messages["already_added_words"].replace(
                "{already_added_words}", ", ".join(already_added)
            )
            if len(already_added) > 0
            else "",
        )
        self._bot.threading.add_words_to_blacklist(words)
        return await embed_maker.message(
            ctx, description=description, title=messages["title"], send=True
        )

    @wordlist_blacklist_config_cmd.command(
        name="remove",
        help="Remove words from the blacklist.",
        usage="threads mod config blacklist remove [word] <word> <word> <word>...",
        cls=Command,
    )
    async def remove_wordlist_cmd(self, ctx: Context, *, words: str = ""):
        if words == "":
            return await embed_maker.command_error(ctx)

        words = list(map(lambda word: word.lower(), words.split(",")))
        blacklist_words = self._bot.threading.get_word_blacklist()

        not_in_list = []

        for word in words:
            if word not in blacklist_words:
                not_in_list.append(word)

        if len(not_in_list) == len(words):
            return await embed_maker.message(
                ctx,
                description="No words provided exists in blacklist.",
                title="No words found.",
                send=True,
            )
        messages = self._bot.threading.get_settings()["messages"]["user"]["mod"][
            "remove_words_from_blacklist_embed"
        ]
        return await embed_maker.message(
            ctx,
            description=messages["description"]
            .replace("{words_removed}", ", ".join(words))
            .replace(
                "{words_not_removed}",
                messages["words_not_in_blacklist"].replace(
                    "{words_not_in_blacklist}", ", ".join(not_in_list)
                )
                if len(not_in_list) > 0
                else "",
            ),
            title=messages["title"],
            send=True,
        )

    @config_mod_cmd.command(
        name="view",
        help="View the Threading config.",
        usage="threads mod config view",
        examples=["threads mod config view"],
        cls=Command,
    )
    async def config_mod_view(self, ctx: Context, key: str = ""):
        config_copy = copy.deepcopy(self._bot.threading.get_settings())
        config_copy.pop("word_blacklist")

        bits = []

        if len(key.split(".")) > 0 and key != "":
            keys = key.split(".")

            for part in keys:
                if part in config_copy.keys():
                    config_copy = config_copy[part]
                else:
                    return await embed_maker.message(
                        ctx,
                        description=f"Key {part} in {keys} wasn't found.",
                        send=True,
                    )

        if "messages" in config_copy.keys():
            config_copy[
                "messages"
            ] = f"{len(self._bot.settings_handler.get_key_map(config_copy))} Elements"

        if "user" in config_copy.keys():
            config_copy[
                "user"
            ] = f"{len(self._bot.settings_handler.get_key_map(config_copy))} Elements"

        return await embed_maker.message(
            ctx,
            description=f"```{json_util.dumps(config_copy, indent=4)}```",
            title="Threading Settings.",
            send=True,
        )

    @config_mod_cmd.command(
        name="set",
        help="Set a value of a configuration variable.",
        usage="threads mod config set",
        examples=["captcha mod config set"],
        cls=Command,
        command_args=[
            (
                ("--path", "-p", str),
                "The path of the setting, with fullstops substituting spcaes.",
            ),
            (("--value", "-v", str), "Value to set the setting to."),
        ],
    )
    async def set_config_cmd(self, ctx: Context, *, args: Union[ParseArgs, str] = ""):
        if args == "":
            return await embed_maker.command_error(ctx)

        if args["pre"] != "":
            split_pre = args["pre"].split(" ")
            args["path"] = split_pre[0]
            args["value"] = " ".join(split_pre[1:])
        else:
            if args["path"] is None:
                return await embed_maker.command_error(ctx, "path")

            if args["value"] is None:
                return await embed_maker.command_error(ctx, "value")

        self._bot.threading.set_setting(
            args["path"],
            args["value"] if args["value"].isnumeric() is False else int(args["value"]),
        )

        await embed_maker.message(
            ctx,
            description=f"Set value {args['value']} on setting {args['path']}",
            title="Changed Setting",
            send=True,
        )

    @mod_cmd.command(
        name="revoke",
        help="Revokes threadpoll creation and voting rights of a user.",
        usage="threads mod revoke [username]",
        examples=["threads mod revoke TheMasteredPanda"],
        cls=Command,
    )
    async def revoke_mod_cmd(self, ctx: Context, username: str = ""):
        if username == "":
            return embed_maker.command_error(ctx)

        member, left = await get_member_from_string(
            ctx, username, guild=self._bot.get_guild(config.MAIN_SERVER)
        )

        mod_messages = self._bot.threading.get_settings()["messages"]["user"]["mod"]

        if member is None:
            return await embed_maker.message(
                ctx,
                description=mod_messages["failed_to_find_user"]["description"].replace(
                    "{username}", username
                ),
                title=mod_messages["failed_to_find_user"]["title"],
                send=True,
            )

        profile = self._bot.threading.get_profile(member.id)

        if profile.has_perm() is False:
            return await embed_maker.message(
                ctx,
                title=mod_messages["already_revoked_perms"]["title"],
                description=mod_messages["already_revoked_perms"][
                    "description"
                ].replace(
                    "{display_name}", f"{member.display_name}${member.discriminator}"
                ),
                send=True,
            )
        profile.set_perm(False)
        await embed_maker.message(
            ctx,
            description=mod_messages["revoked_perms"]["description"].replace(
                "{display_name}", f"{member.display_name}#{member.discriminator}"
            ),
            title=mod_messages["revoked_perms"]["title"],
            send=True,
        )

    @mod_cmd.command(
        name="permit",
        help="Permit threadpoll creation and voting rights of a user who had them revoked.",
        examples=["threads mod permit TheMasteredPanda"],
        cls=Command,
    )
    async def permit_mod_cmd(self, ctx: Context, username: str = ""):
        if username == "":
            return embed_maker.command_error(ctx)

        member, left = await get_member_from_string(
            ctx, username, guild=self._bot.get_guild(config.MAIN_SERVER)
        )
        mod_messages = self._bot.threading.get_settings()["messages"]["user"]["mod"]

        if member is None:
            return await embed_maker.message(
                ctx,
                description=mod_messages["failed_to_find_user"]["description"].replace(
                    "{username}", username
                ),
                title=mod_messages["failed_to_find_user"]["title"],
                send=True,
            )

        profile = self._bot.threading.get_profile(member.id)

        if profile.has_perm():
            return await embed_maker.message(
                ctx,
                description=mod_messages["already_has_perms"]["description"].replace(
                    "{display_name}", f"{member.display_name}#{member.discriminator}"
                ),
                title=mod_messages["already_has_perms"]["title"],
                send=True,
            )
        profile.set_perm(True)
        await embed_maker.message(
            ctx,
            description=mod_messages["returned_perms"]["description"].replace(
                "{display_name}", f"{member.display_name}#{member.discriminator}"
            ),
            title=mod_messages["returned_perms"]["title"],
            send=True,
        )

    @mod_cmd.command(
        name="rename",
        help="Unilaterally rename a thread, like a Dicatator.",
        examples=["threads mod rename 3243124328934832 new name"],
        usage="theads mod rename [thread_id] [new name]",
        cls=Command,
    )
    async def rename_mod_cmd(
        self, ctx: Context, thread_id: int = 0, *, new_name: str = ""
    ):
        if new_name == "":
            return await embed_maker.command_error(ctx)

        if thread_id == 0:
            return await embed_maker.command_error(ctx)

        guild = self._bot.get_guild(config.MAIN_SERVER)
        thread = guild.get_thread(thread_id)
        if thread is None:
            return await embed_maker.message(
                ctx, description=f"Thread not found.", title=f"Not found.", send=True
            )

        former_title = thread.name
        await thread.edit(name=new_name)
        renamed_thread_messages = self._bot.threading.get_settings()["messages"][
            "user"
        ]["mod"]["renamed_thread"]
        await embed_maker.message(
            ctx,
            description=renamed_thread_messages["description"]
            .replace("{thread_id}", str(thread.id))
            .replace("{previous_title}", former_title)
            .replace("{current_title}", thread.name),
            title=renamed_thread_messages["title"],
            send=True,
        )

    @mod_cmd.group(
        name="dev",
        help="Dev commands for Threading.",
        examples=["threads mod dev profiles"],
        invoke_without_command=True,
        cls=Group,
    )
    async def dev_mod_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @dev_mod_cmd.command(
        name="profiles",
        help="Lists all cached threading profiles.",
        examples=["threads mod dev profiles"],
        cls=Command,
    )
    async def profiles_mod_cmd(self, ctx: Context):
        async def construct_profiles(
            ctx: Context,
            profiles: list[ThreadProfile],
            max_page_num: int,
            page_limit: int,
            *,
            page: int,
        ):
            if len(profiles) == 0:
                return await embed_maker.message(
                    ctx, description="No Profiles present."
                )

            bits = []
            next_line = "\n"
            for i, profile in enumerate(
                profiles[page_limit * (page - 1) : page_limit * page]
            ):
                member_id = profile.get_id()
                c_time = (
                    datetime.fromtimestamp(profile.get_cooldown_timestamp()).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    if profile.get_cooldown_timestamp() != 0
                    else "No Cooldown Applied."
                )
                rep = profile.get_rep()
                perm = profile.has_perm()
                main_guild = self._bot.get_guild(config.MAIN_SERVER)
                member = main_guild.get_member(member_id)
                member_entry = member_id
                if member is not None:
                    member_entry = (
                        f"{member.display_name}#{member.discriminator}/{member_id}"
                    )

                bits.append(
                    f"**{(i + 1) + (page_limit * (page - 1))}. {member_entry}**{next_line}-  **Rep:** {str(rep)}{next_line}-  **Perm:** {'Yes' if perm else 'No'}{next_line}-  **Cooldown Ends:** {c_time}"
                )

            return await embed_maker.message(
                ctx,
                description=next_line.join(bits),
                author={"name": "Threading Profiles"},
                footer={"text": f"Page {page}/{max_page_num}"},
            )

        profiles = self._bot.threading.get_profiles()
        max_page_size = 5
        max_page_num = math.ceil(len(profiles) / max_page_size)
        page_constructor = functools.partial(
            construct_profiles,
            ctx=ctx,
            profiles=profiles,
            max_page_num=max_page_num,
            page_limit=max_page_size,
        )

        embed = await page_constructor(page=1)
        message = await ctx.send(embed=embed)
        menu = BookMenu(
            message,
            page=1,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
            author=ctx.author,
        )
        self._bot.reaction_menus.add(menu)

    @threads.command(
        name="rep",
        help="Returns your reputation score for threadpolls. Your rep is increased on successful thread creation. The higher rep the lower the voting threshold and threadpoll creations you can do.",
        examples=["threads rep"],
        invoke_without_command=True,
        cls=Group,
    )
    async def rep_cmd(self, ctx: Context):
        member = ctx.author
        profile = self._bot.threading.get_profile(member.id)
        rep_embed_msgs = self._bot.threading.get_settings()["messages"]["user"][
            "embed_rep"
        ]
        return await embed_maker.message(
            ctx,
            description=rep_embed_msgs["description"].replace(
                "{rep_value}", str(profile.get_rep())
            ),
            title=rep_embed_msgs["title"].replace(
                "{display_name}", f"{member.display_name}#{member.discriminator}"
            ),
            send=True,
        )

    @threads.command(
        name="repstats",
        help="A leaderboard showing which users have the most threadpoll reputation.",
        examples=["threads rep stats"],
        cls=Command,
    )
    async def rep_stats(self, ctx: Context):
        async def construct_leaderboard_embed(
            ctx: Context,
            profiles: list,
            max_page_num: int,
            page_limit: int,
            *,
            page: int,
        ):
            if len(profiles) == 0:
                return await embed_maker.message(
                    ctx, description="No profile entries found."
                )

            bits = []
            guild = self._bot.get_guild(config.MAIN_SERVER)
            stats_embed = self._bot.threading.get_settings()["messages"]["user"][
                "stats_embed"
            ]
            for i, entry in enumerate(
                profiles[page_limit * (page - 1) : page_limit * page]
            ):
                member = guild.get_member(entry.get_id())
                rep = entry.get_rep()
                bits.append(
                    stats_embed["stat_entry"]
                    .replace("{position}", str(i))
                    .replace("{display_name}", member.display_name)
                    .replace("{username}", member.name)
                    .replace("{discriminator}", member.discriminator)
                    .replace("{rep_value}", str(rep))
                )

            return await embed_maker.message(
                ctx,
                description="\n".join(bits),
                author={"name": "Threading Rep Leaderboard"},
                footer={"text": f"Page {page}/{max_page_num}"},
            )

        max_page_size = 10
        profiles = self._bot.threading.get_profiles(True)
        profiles.sort(key=lambda x: x.get_rep(), reverse=True)
        max_page_num = math.ceil(len(profiles) / max_page_size)
        page_constructor = functools.partial(
            construct_leaderboard_embed,
            ctx=ctx,
            profiles=profiles,
            max_page_num=max_page_num,
            page_limit=max_page_size,
        )

        embed = await page_constructor(page=1)
        message = await ctx.send(embed=embed)
        menu = BookMenu(
            message,
            page=1,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
            author=ctx.author,
        )
        self._bot.reaction_menus.add(menu)

    @threads.command(
        name="replevels",
        help="Info regarding what levels of reputation get you what benefits.",
        examples=["threads rep info"],
        cls=Command,
    )
    async def rep_levels(self, ctx: Context):
        async def construct_levels_embed(
            ctx: Context, levels: dict, max_page_num: int, page_limit: int, *, page: int
        ):

            rep_info_messages = self._bot.threading.get_settings()["messages"]["user"][
                "info_embed"
            ]

            if len(levels.values()) == 0:
                return await embed_maker.message(ctx, description="No levels found.")

            bits = [
                rep_info_messages["info_entry"]
                .replace("{position}", "Default")
                .replace("{rep_value}", "0")
                .replace(
                    "{formatted_cooldown}",
                    format_time.seconds(
                        self._bot.threading.get_settings()["threadpoll"]["cooldown"]
                    ),
                )
            ]

            for i, entry in enumerate(
                list(levels.items())[page_limit * (page - 1) : page_limit * page]
            ):
                bits.append(
                    rep_info_messages["info_entry"]
                    .replace("{position}", str(i))
                    .replace("{rep_value}", str(entry[0]))
                    .replace("{formatted_cooldown}", format_time.seconds(entry[1]))
                )

            return await embed_maker.message(
                ctx,
                description="\n".join(bits),
                author={"name": "Threading Reputation Level Info"},
                footer={"text": f"Page {page}/{max_page_num}"},
            )

        levels = self._bot.threading.get_rep_levels()
        max_page_size = 5
        max_page_num = math.ceil(len(levels) / max_page_size)
        page_constructor = functools.partial(
            construct_levels_embed,
            ctx=ctx,
            levels=levels,
            max_page_num=max_page_num,
            page_limit=max_page_size,
        )
        embed = await page_constructor(page=1)
        message = await ctx.send(embed=embed)
        menu = BookMenu(
            message,
            page=1,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
            author=ctx.author,
        )
        self._bot.reaction_menus.add(menu)


def setup(bot: TLDR):
    bot.add_cog(Threading(bot))
