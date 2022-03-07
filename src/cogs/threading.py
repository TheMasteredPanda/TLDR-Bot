import copy
import functools
import math
from datetime import datetime
from typing import Union

import config
import modules.embed_maker as embed_maker
import modules.format_time as format_time
from bot import TLDR
from bson import json_util
from discord import Thread
from discord.ext.commands import Cog, Context, command, group
from modules.commands import Command, Group
from modules.reaction_menus import BookMenu
from modules.threading import ThreadProfile
from modules.utils import ParseArgs


class Threading(Cog):
    def __init__(self, bot: TLDR):
        self._bot = bot

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

        if title == "":
            return await embed_maker.command_error(ctx)

        replying_message = await ctx.channel.fetch_message(
            ctx.message.reference.message_id
        )

        if await self._bot.threading.being_polled(replying_message.id):
            await ctx.message.delete()
            return

        profile = self._bot.threading.get_profile(ctx.author.id)

        if profile.can_create_threadpoll() is False:
            await ctx.author.send(
                f"Can't create threadpoll yet. Cooldown Left: {format_time.seconds(profile.get_cooldown_timestamp())}"
            )
            return

        threadpoll = await self._bot.threading.threadpoll(ctx, title)
        await threadpoll.initiate()

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

    @config_mod_cmd.command(
        name="view",
        help="View the Threading config.",
        usage="threads mod config view",
        examples=["threads mod config view"],
        cls=Command,
    )
    async def config_mod_view(self, ctx: Context):
        config_copy = copy.deepcopy(self._bot.threading.get_settings())

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
        examples=["threads mod revoke TheMasteredPanda"],
        cls=Command,
    )
    async def revoke_mod_cmd(self, ctx: Context):
        pass

    @mod_cmd.command(
        name="permit",
        help="Permit threadpoll creation and voting rights of a user who had them revoked.",
        examples=["threads mod permit TheMasteredPanda"],
        cls=Command,
    )
    async def permit_mod_cmd(self, ctx: Context):
        pass

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
        return await embed_maker.message(
            ctx,
            description=f"**Rep:** {profile.get_rep()}",
            title=f"{member.display_name}'s Repuation.",
            send=True,
        )

    @threads.command(
        name="stats",
        help="A leaderboard showing which users have the most threadpoll reputation.",
        examples=["threads rep stats"],
        cls=Command,
    )
    async def rep_stats(self, ctx: Context):
        pass

    @threads.command(
        name="info",
        help="Info regarding what levels of reputation get you what benefits.",
        examples=["threads rep info"],
        cls=Command,
    )
    async def rep_info(self, ctx: Context):
        pass


def setup(bot: TLDR):
    bot.add_cog(Threading(bot))
