import copy
import datetime
import functools
import math
import time
from typing import Union

import bs4
import dateparser
import discord
import emoji
from bot import TLDR
from bson import ObjectId, json_util
from discord.ext.commands import Cog, Context, command, group
from modules import (commands, database, embed_maker, format_time,
                     reaction_menus)
from modules.moderation import Case, PollType, PunishmentType
from modules.reaction_menus import BookMenu
from modules.utils import (ParseArgs, get_guild_role, get_member,
                           get_member_by_id, get_member_from_string)

db = database.get_connection()


class Mod(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @Cog.listener()
    async def on_ready(self):
        self._reprimand_module = self.bot.reprimand

    @staticmethod
    async def construct_cases_embed(
        ctx: Context,
        member: discord.Member,
        cases: dict,
        case_type: str,
        max_page_num: int,
        page_size_limit: int,
        *,
        page: int,
    ):
        thirty_days_ago = time.time() - (30 * 24 * 60)
        # cases in the past 30 days
        cases_30_days = [*filter(lambda case: case.created_at > thirty_days_ago, cases)]

        description = (
            f"**Total:** `{len(cases)}`\n"
            f"**In the pas 30 days:** `{len(cases_30_days)}`\n\n"
        )

        if len(cases) > 0:
            for i, case in enumerate(
                cases[page_size_limit * (page - 1) : page_size_limit * page]
            ):
                # limit it to 5 per page
                if i == page_size_limit:
                    break

                reason = case.reason
                # if reason is too long, cut it off
                if len(reason) > 300:
                    reason = reason[:300] + "..."

                type_str = f"**Type:** {case.type}\n" if not case_type else ""
                duration_str = (
                    f'**Duration:** {format_time.seconds(case.extra["duration"])}\n'
                    if case.type == "mute"
                    else ""
                )
                description += (
                    f"**#{page_size_limit * (page - 1) + i + 1}**\n"
                    f'`{datetime.datetime.fromtimestamp(case.created_at).strftime("%Y/%m/%d - %H:%M:%S")}`\n'
                    f"`{format_time.seconds(round(time.time()) - case.created_at, accuracy=3)} Ago`\n"
                    f"{type_str}"
                    f"{duration_str}"
                    f"**By:** <@{case.moderator_id}>\n"
                    f"**Reason:** {reason}\n\n"
                )
        else:
            description = f'This user has no {case_type if case_type else "case"}s'

        name_switch = {"warn": "Warnings", "mute": "Mutes", "ban": "Bans"}

        return await embed_maker.message(
            ctx,
            description=description,
            author={"name": f'{name_switch.get(case_type, "Cases")} - {member}'},
            footer={"text": f"Page {page}/{max_page_num}"},
        )

    async def cases_menu(
        self, ctx: Context, member: discord.Member, case_type: str, page: int = 1
    ):
        member_cases = self.bot.moderation.cases.get_cases(
            ctx.guild.id, member_id=member.id, type=case_type
        )

        page_size_limit = 5
        max_page_num = math.ceil(len(member_cases) / page_size_limit)
        if max_page_num == 0:
            max_page_num = 1

        if page > max_page_num:
            return await embed_maker.error(ctx, "Exceeded maximum page number")

        page_constructor = functools.partial(
            self.construct_cases_embed,
            ctx,
            member,
            member_cases,
            case_type,
            max_page_num,
            page_size_limit,
        )

        embed = await page_constructor(page=page)
        cc_message = await ctx.send(embed=embed)

        menu = reaction_menus.BookMenu(
            cc_message,
            author=ctx.author,
            page=page,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
        )

        self.bot.reaction_menus.add(menu)

    @command(
        help="Purge messages that match a filter or just all messages up to n. when given multiple filters all of them will be checked separately",
        usage="purge [number of messages] (args)",
        examples=["purge 500 -f buy bitcoin"],
        command_args=[
            (
                ("--filter", "-f", list),
                "A regex filter that will be matched against the users message, if a match is found the message will be deleted",
            ),
        ],
        cls=commands.Command,
        module_dependency=["moderation"],
    )
    async def purge(self, ctx: Context, *, args: Union[ParseArgs, dict] = None):
        if not args:
            return await embed_maker.command_error(ctx)

        number = args["pre"]
        if not number.isdigit():
            return await embed_maker.command_error(ctx)

        filters = args["filter"]

        t = 0
        messages = await ctx.channel.history(limit=int(number)).flatten()
        for message in messages:
            if not filters or any(x.strip() in message.content for x in filters):
                try:
                    await message.delete()
                    t += 1
                except:
                    pass

        return await embed_maker.message(
            ctx, description=f"Removed {t} messages.", send=True
        )

    @command(
        help="See the cases (warn/mute/ban) issued to a user",
        usage="cases [member] [case type] (page)",
        examples=["cases hattyot warn", "warns hattyot ban 2"],
        aliases=["case"],
        cls=commands.Command,
        module_dependency=["reaction_menus", "moderation"],
    )
    async def cases(self, ctx: Context, member_and_case_type: str = None):
        if member_and_case_type is None:
            return await embed_maker.command_error(ctx)

        member, case_type = await get_member_from_string(ctx, member_and_case_type)

        # get page number, if any has been provided
        split_member = case_type.split()
        if len(split_member) > 1:
            case_type = " ".join(split_member[:-1])

            page = split_member[-1]
            if not page.isdigit():
                page = 1
            else:
                page = int(page)
        else:
            page = 1

        if type(member) == discord.Message:
            return

        return await self.cases_menu(ctx, member, case_type, page)

    @command(
        help="Give a member a warning",
        usage="warn [member] [reason]",
        examples=["warn hattyot broke cg 10 several times"],
        aliases=["warning"],
        cls=commands.Command,
        module_dependency=["moderation"],
    )
    async def warn(self, ctx: Context, *, member_and_reason: str = None):
        if member_and_reason is None:
            return await embed_maker.command_error(ctx)

        member, reason = await get_member_from_string(ctx, member_and_reason)

        if member is None:
            return await embed_maker.error(ctx, "Unable to find member.")

        if reason is None:
            return await embed_maker.error(
                ctx, "You need to give a reason for the warning."
            )

        if member.bot:
            return await embed_maker.error(
                ctx, "You can't give a warning to a bot. Bots are good lads"
            )

        if member.id == ctx.author.id:
            return await embed_maker.error(ctx, "You can't warn yourself.")

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(
                ctx,
                "You can't warn a member who has a role that is equal or higher than yours.",
            )

        # send user message that they have been warned
        text = f"**{ctx.guild.name}** - You have been warned.:warning:\n**Reason**: {reason}"
        await member.send(text)

        # confirm that user has been warned
        thirty_days_ago = time.time() - (30 * 24 * 60)
        user_warns = self.bot.moderation.cases.get_cases(
            ctx.guild.id, member_id=member.id, type="warn", after=thirty_days_ago
        )
        await embed_maker.message(
            ctx,
            description=f"{member.mention} has been warned\n"
            f'They now have {len(user_warns) + 1} warning{"s" if len(user_warns) != 0 else ""} in the last 30 days.',
            colour="green",
            send=True,
        )

        # add case to the database
        self.bot.moderation.cases.add_case(
            ctx.guild.id, "warn", reason, member, ctx.author
        )

    @command(
        help="Unmute a member",
        usage="unmute [member] [reason]",
        examples=["unmute hattyot accidental mute"],
        cls=commands.Command,
    )
    async def unmute(self, ctx: Context, *, member_and_reason: str = None):
        if member_and_reason is None:
            return await embed_maker.command_error(ctx)

        guild_settings = db.get_guild_settings(ctx.guild.id)
        if guild_settings["mute_role_id"] is None:
            return await embed_maker.message(
                ctx,
                description=f"The mute role has not been set yet.\nYou can set it with `{ctx.prefix}setmuterole [role]`",
                colour="orange",
                send=True,
            )

        member, reason = await get_member_from_string(ctx, member_and_reason)

        if member is None:
            return await embed_maker.error(ctx, "Unable to find member.")

        if reason is None:
            return await embed_maker.error(
                ctx, "You need to give a reason for the unmute."
            )

        if member.bot:
            return await embed_maker.error(
                ctx, "You can't unmute a bot, they can't even be muted smh."
            )

        if member.id == ctx.author.id:
            return await embed_maker.error(
                ctx, "You can't unmute yourself, how did you even send this message."
            )

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(
                ctx,
                "You can't unmute a member who has a role that is equal or higher than yours.",
            )

        mute_timer = db.timers.find_one(
            {
                "guild_id": ctx.guild.id,
                "event": "automatic_unmute",
                "extras": {"member_id": member.id},
            }
        )
        if not mute_timer:
            return await embed_maker.message(
                ctx,
                description=f"<@{member.id}> is not muted.",
                colour="orange",
                send=True,
            )

        await self.unmute_user(ctx.guild.id, member.id, reason)

        time_left = mute_timer["expires"] - round(time.time())
        return await embed_maker.message(
            ctx,
            description=f"<@{member.id}> has been unmuted.\n**Reason**: {reason}Their mute had **{format_time.seconds(time_left)}** left.\n",
            send=True,
        )

    @command(
        help="Mute a member",
        usage="mute [member] [duration] [reason]",
        examples=["mute hattyot 7d 5h 10m 50s abused the bot"],
        cls=commands.Command,
        module_dependency=["timers", "moderation"],
    )
    async def mute(self, ctx: Context, *, member_and_duration_and_reason: str = None):
        if member_and_duration_and_reason is None:
            return await embed_maker.command_error(ctx)

        guild_settings = db.get_guild_settings(ctx.guild.id)
        if guild_settings["mute_role_id"] is None:
            return await embed_maker.message(
                ctx,
                description=f"The mute role has not been set yet.\nYou can set it with `{ctx.prefix}setmuterole [role]`",
                colour="orange",
                send=True,
            )

        member, duration_and_reason = await get_member_from_string(
            ctx, member_and_duration_and_reason
        )
        duration, reason = format_time.parse(duration_and_reason, return_string=True)

        if member is None:
            return await embed_maker.error(ctx, "Unable to find member.")

        if duration is None:
            return await embed_maker.error(
                ctx, "You need to give a duration for the mute"
            )

        if reason is None:
            return await embed_maker.error(
                ctx, "You need to give a reason for the mute."
            )

        if member.bot:
            return await embed_maker.error(
                ctx, "You can't mute a bot. Bots are good lads"
            )

        if member.id == ctx.author.id:
            return await embed_maker.error(ctx, "You can't mute yourself.")

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(
                ctx,
                "You can't mute a member who has a role that is equal or higher than yours.",
            )

        mute_timer = db.timers.find_one(
            {
                "guild_id": ctx.guild.id,
                "event": "automatic_unmute",
                "extras": {"member_id": member.id},
            }
        )
        if mute_timer:
            time_left = mute_timer["expires"] - round(time.time())
            return await embed_maker.message(
                ctx,
                description=f"<@{member.id}> is already muted.\nTheir mute will expire in: **{format_time.seconds(time_left)}**",
                colour="orange",
                send=True,
            )

        # send user message that they have been muted
        text = f"**{ctx.guild.name}** - You have been muted.:mute:\n**Duration**: {format_time.seconds(duration)}\n**Reason**: {reason}"
        try:
            await member.send(text)
        except:
            return await embed_maker.error(ctx, "Failed to send mute message to user.")

        # confirm that user has been warned
        thirty_days_ago = time.time() - (30 * 24 * 60)
        user_warns = self.bot.moderation.cases.get_cases(
            ctx.guild.id, member_id=member.id, type="warn", after=thirty_days_ago
        )
        await embed_maker.message(
            ctx,
            description=f"{member.mention} has been muted for **{format_time.seconds(duration)}**\n"
            f"**Reason:** {reason}\n"
            f'They now have **{len(user_warns) + 1}** mute{"s" * (len(user_warns) != 0)} in the last 30 days.',
            colour="green",
            send=True,
        )

        # add case to the database
        self.bot.moderation.cases.add_case(
            ctx.guild.id,
            "mute",
            reason,
            member,
            ctx.author,
            extra={"duration": duration},
        )

        # add mute role to user
        mute_role = await get_guild_role(ctx.guild, str(guild_settings["mute_role_id"]))
        if mute_role is None:
            return await embed_maker.error(ctx, "Current mute role is not valid.")
        else:
            await member.add_roles(mute_role)

        # start automatic unmute timer
        self.bot.timers.create(
            guild_id=ctx.guild.id,
            expires=round(time.time()) + duration,
            event="automatic_unmute",
            extras={"member_id": member.id},
        )

    async def unmute_user(self, guild_id: int, member_id: int, reason: str):
        guild = self.bot.get_guild(guild_id)
        member = await get_member_by_id(guild, member_id)

        # send user message that they have been unmuted
        text = f"**{guild.name}** - You have been unmuted.:loud_sound:\n**Reason**: {reason}"
        await member.send(text)

        # remove mute role from member
        mute_role_id = db.get_guild_settings(guild_id=guild_id)["mute_role_id"]
        if mute_role_id is None:
            return

        mute_role = await get_guild_role(guild, str(mute_role_id))
        if mute_role is None:
            return

        await member.remove_roles(mute_role)

        # remove mute timer
        db.timers.delete_one(
            {
                "guild_id": guild.id,
                "event": "automatic_unmute",
                "extras": {"member_id": member.id},
            }
        )

    @Cog.listener()
    async def on_automatic_unmute_timer_over(self, timer: dict):
        guild_id = timer["guild_id"]
        member_id = timer["extras"]["member_id"]
        return await self.unmute_user(guild_id, member_id, "Mute expired.")

    @command(
        help="Ban a member, their leveling data will be erased",
        usage="ban [member] [reason]",
        examples=["ban hattyot completely ignore cg"],
        cls=commands.Command,
        module_dependency=["moderation"],
    )
    async def ban(self, ctx: Context, *, member_and_reason: str = None):
        if member_and_reason is None:
            return await embed_maker.command_error(ctx)

        member, reason = await get_member_from_string(ctx, member_and_reason)

        if member is None:
            return await embed_maker.error(ctx, "Unable to find member.")

        if reason is None:
            return await embed_maker.error(
                ctx, "You need to give a reason for the ban."
            )

        if member.bot:
            return await embed_maker.error(
                ctx, "You can't ban a bot, they do too much work."
            )

        if member.id == ctx.author.id:
            return await embed_maker.error(
                ctx, "You can't ban yourself, why would you even try this"
            )

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(
                ctx,
                "You can't ban a member who has a role that is equal or higher than yours.",
            )

        # send user message that they have been warned
        text = f"**{ctx.guild.name}** - You have been banned.\n**Reason**: {reason}"
        try:
            await member.send(text)
        except:
            return await embed_maker.error(ctx, "Failed to send ban message to user.")

        await ctx.guild.ban(member, reason=reason)
        self.bot.dispatch("ban", member)

        await embed_maker.message(
            ctx,
            description=f"{member.mention} has been banned.\n" f"**Reason:** {reason}",
            colour="green",
            send=True,
        )

        # add case to the database
        self.bot.moderation.cases.add_case(
            ctx.guild.id, "ban", reason, member, ctx.author
        )

    @group(
        invoke_without_command=True,
        name="watchlist",
        help="Manage the watchlist, which logs all the users message to a channel.\nView all the details of a user with `watchlist [index number]`.",
        usage="watchlist [index number]",
        examples=["watchlist", "watchlist 1"],
        cls=commands.Group,
        module_dependency=["watchlist"],
    )
    async def watchlist(self, ctx: Context, index_number: int = None):
        if ctx.subcommand_passed is None:
            users_on_list = [
                d for d in db.watchlist.distinct("user_id", {"guild_id": ctx.guild.id})
            ]

            if index_number is not None:
                user_id = 0 if index_number == 0 else users_on_list[index_number - 1]
                user_filters = db.watchlist.find_one(
                    {"guild_id": ctx.guild.id, "user_id": user_id}
                )
                total = sum(
                    filter.get("matches", 0) for filter in user_filters["filters"]
                )
                filters_string = "\n".join(
                    f"`{filter['regex']}`: {filter.get('matches', 0)}"
                    for filter in user_filters["filters"]
                )
                user = self.bot.get_user(user_id)
                return await embed_maker.message(
                    ctx,
                    description=f"Filters and amount of matches total:\n{filters_string}\n\n"
                    f"Total filter message matches: {total}",
                    author={"name": str(user) if user else "All Users"},
                    send=True,
                )

            list_embed = await embed_maker.message(
                ctx, author={"name": "Users on the watchlist"}
            )

            on_list_str = ""
            if 0 in users_on_list:
                on_list_str += "`#0` - All Users\n"

            index = 1
            for user_id in users_on_list:
                if user_id == 0:
                    continue

                user = ctx.guild.get_member(int(user_id))
                if user is None:
                    try:
                        user = await ctx.guild.fetch_member(int(user_id))
                    except:
                        # remove user from the watchlist if user isnt on the server anymore
                        db.watchlist.delete_one(
                            {"guild_id": ctx.guild.id, "user_id": user_id}
                        )
                        continue
                on_list_str += f"`#{index}` - {str(user)}\n"
                index += 1

            list_embed.description = (
                "Currently no users are on the watchlist"
                if not on_list_str
                else on_list_str
            )

            return await ctx.send(embed=list_embed)

    @watchlist.group(
        name="config",
        help="Configuration commands for watchlist.",
        usage="watchlist config [subcommand]",
        examples=["watchlist config view", "watchlist config set"],
        cls=commands.Group,
        invoke_without_command=True,
    )
    async def watchlist_config(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @watchlist_config.command(
        name="view",
        help="View watchlist config.",
        usage="watchlist config view",
        cls=commands.Command,
    )
    async def config_view_watchlist_cmd(self, ctx: Context):
        settings = self.bot.watchlist.get_settings()
        return await embed_maker.message(
            ctx,
            description=f"```{json_util.dumps(settings, indent=4)}```",
            title="Watchlist Config.",
            send=True,
        )

    @watchlist_config.command(
        name="add",
        help="Add role to config. This will allow people with those roles to be added to newly created watchlist threads.",
        usage="watchlist config add",
        examples=["watchlist config add @Admin @Mod"],
        cls=commands.Command,
    )
    async def add_role_watchlist_cmd(self, ctx: Context, *, role: discord.Role = None):
        if role is None:
            return await embed_maker.command_error(ctx)
        if role.id in self.bot.watchlist.get_settings()["roles"]:
            return await embed_maker.message(
                ctx,
                description=f"Role {role.name}/{role.id} already added.",
                title="Role already added.",
                send=True,
            )
        self.bot.watchlist.add_role(role)
        return await embed_maker.message(
            ctx,
            description=f"Added role {role.name}/{role.id}",
            title="Role added.",
            send=True,
        )

    @watchlist_config.command(
        name="remove",
        help="Remove role from config.",
        usage="watchlist config remove",
        examples=["watchlist config remove @Admin"],
        cls=commands.Command,
    )
    async def rm_role_watchlist_cmd(self, ctx: Context, *, role: discord.Role = None):
        if role is None:
            return await embed_maker.command_error(ctx)

        if role.id not in self.bot.watchlist.get_settings()["roles"]:
            return await embed_maker.message(
                ctx,
                description=f"Role {role.name}/{role.id} wasn't added.",
                title="Role wasn't added.",
                send=True,
            )
        self.bot.watchlist.rm_role(role)
        return await embed_maker.message(
            ctx,
            description=f"Role {role.name}/{role.id} removed.",
            title="Role removed.",
            send=True,
        )

    @watchlist.command(
        name="add",
        help="add a user to the watchlist, with optionl filters (mathces are found with regex)",
        usage="watchlist add [user] (args)",
        examples=[r"watchlist add hattyot -f hattyot -f \sot\s -f \ssus\s"],
        command_args=[
            (
                ("--filter", "-f", list),
                "A regex filter that will be matched against the users message, if a match is found, mods will be @'d",
            ),
            (
                ("--mention-role", "-mr", list),
                "Role that should me mentioned when filter is matched.",
            ),
        ],
        cls=commands.Command,
        module_dependency=["watchlist"],
    )
    async def watchlist_add(self, ctx: Context, *, args: Union[ParseArgs, dict] = None):
        if not args:
            return await embed_maker.command_error(ctx)

        user_identifier = args["pre"]
        filters = args["filter"]
        mention_roles = args["mention-role"] if args["mention-role"] else []

        if not user_identifier:
            return await embed_maker.error(ctx, "Missing user")

        for role_id in mention_roles:
            guild: discord.Guild = ctx.guild
            try:
                role = await guild.get_role(int(role_id))
                if not role:
                    return await embed_maker.error(ctx, f"Invalid role id: `{role_id}`")
            except:
                return await embed_maker.error(ctx, f"Invalid role id: `{role_id}`")

        member = await get_member(ctx, user_identifier)
        if type(member) == discord.Message:
            return

        watchlist_user = await self.bot.watchlist.get_member(member, ctx.guild)
        if watchlist_user:
            return await embed_maker.error(ctx, "User is already on the watchlist")

        await self.bot.watchlist.add_member(member, ctx.guild, filters)

        msg = f"<@{member.id}> has been added to the watchlist"
        if filters:
            msg += f'\nWith these filters: {" or ".join(f"`{f}`" for f in filters)}'

        return await embed_maker.message(
            ctx, description=msg, colour="green", send=True
        )

    @watchlist.command(
        name="remove",
        help="remove a user from the watchlist",
        usage="watchlist remove [user]",
        examples=["watchlist remove hattyot"],
        cls=commands.Command,
        module_dependency=["watchlist"],
    )
    async def watchlist_remove(self, ctx: Context, *, user: str = None):
        if user is None:
            return await embed_maker.command_error(ctx)

        member = await get_member(ctx, user)
        if type(member) == discord.Message:
            return

        watchlist_user = await self.bot.watchlist.get_member(member, ctx.guild)
        if not watchlist_user:
            return await embed_maker.error(ctx, "User is not on the watchlist")

        await self.bot.watchlist.remove_member(member, ctx.guild)

        return await embed_maker.message(
            ctx,
            description=f"<@{member.id}> has been removed from the watchlist",
            colour="green",
            send=True,
        )

    @watchlist.command(
        name="add_filters",
        help="Add filters to a user on the watchlist, when a user message matches the filter, mods are pinged.",
        usage="watchlist add_filters [user] (args)",
        examples=[
            r"watchlist add_filters hattyot -f filter 1 -f \sfilter 2\s -m 658274389971697675 -m 810787506022121533"
        ],
        command_args=[
            (
                ("--filter", "-f", list),
                "A regex filter that will be matched against the users message.",
            ),
            (
                ("--mention-role", "-mr", list),
                "Role that should me mentioned when filter is matched.",
            ),
            (
                ("--set", "-s", bool),
                "Set the filters to given list instead of adding new ones.",
            ),
        ],
        cls=commands.Command,
        module_dependency=["watchlist"],
    )
    async def watchlist_add_filters(
        self, ctx: Context, *, args: Union[ParseArgs, dict] = None
    ):
        if not args:
            return await embed_maker.command_error(ctx)

        user_identifier = args["pre"]
        filters = args["filter"]
        mention_roles = args["mention-role"] if args["mention-role"] else []
        set = args["set"]

        if not filters:
            return await embed_maker.error(ctx, "Missing filters")

        for role_id in mention_roles:
            try:
                role = ctx.guild.get_role(int(role_id))
                if not role:
                    return await embed_maker.error(ctx, f"Invalid role id: `{role_id}`")
            except:
                return await embed_maker.error(ctx, f"Invalid role id: `{role_id}`")

        if not user_identifier:
            # if no user specified set up generic filter matching for all users. Matching messages will be sent to central watchlist channel
            await self.bot.watchlist.add_filters(
                None, ctx.guild, filters, mention_roles, set
            )
            member = None
        else:
            member = await get_member(ctx, user_identifier)
            if type(member) == discord.Message:
                return

            watchlist_user = await self.bot.watchlist.get_member(member, ctx.guild)
            if not watchlist_user:
                return await embed_maker.error(ctx, "User is not on the watchlist")

            await self.bot.watchlist.add_filters(
                member, ctx.guild, filters, mention_roles, set
            )

        return await embed_maker.message(
            ctx,
            description=f'If {member if member else "anybodys"} message matches {" or ".join(f"`{f}`" for f in filters)} '
            f'these roles will be @\'d: {", ".join(f"<@&{r}>" for r in mention_roles)}',
            colour="green",
            send=True,
        )

    @watchlist.command(
        name="remove_filters",
        help="Remove filters from a user on the watchlist.",
        usage="watchlist remove_filters [user] (args)",
        examples=[r"watchlist remove_filters hattyot -f filter 1 -f \sfilter 2\s"],
        command_args=[
            (("--filter", "-f", list), "The regex of the filter to be removed."),
        ],
        cls=commands.Command,
        module_dependency=["watchlist"],
    )
    async def watchlist_remove_filters(
        self, ctx: Context, *, args: Union[ParseArgs, dict] = None
    ):
        if not args:
            return await embed_maker.command_error(ctx)

        user_identifier = args["pre"]
        filters = args["filter"]

        if not filters:
            return await embed_maker.error(ctx, "Missing filters")

        member = await get_member(ctx, user_identifier) if user_identifier else None
        user_filters = await self.bot.watchlist.get_member(member, ctx.guild)
        valid_filters_to_remove = []
        if user_filters:
            user_filters = user_filters["filters"]
            for filter in user_filters:
                if filter.get("regex") in filters:
                    valid_filters_to_remove.append(filter["regex"])

        if not valid_filters_to_remove:
            return await embed_maker.error(ctx, "No valid filters given.")

        if not user_identifier:
            # if no user specified set up generic filter matching for all users. Matching messages will be sent to central watchlist channel
            await self.bot.watchlist.remove_filters(
                None, ctx.guild, valid_filters_to_remove
            )
        else:
            if type(member) == discord.Message:
                return

            watchlist_user = await self.bot.watchlist.get_member(member, ctx.guild)
            if not watchlist_user:
                return await embed_maker.error(ctx, "User is not on the watchlist")

            await self.bot.watchlist.remove_filters(
                member, ctx.guild, valid_filters_to_remove
            )

        filters_str = ", ".join([f"`{filter}`" for filter in valid_filters_to_remove])
        return await embed_maker.message(
            ctx,
            description=f'Filters: {filters_str} have been removed for {member if member else "everybody"}.',
            colour="green",
            send=True,
        )

    @staticmethod
    async def construct_dd_embed(
        ctx: Context,
        daily_debates_data: dict,
        max_page_num: int,
        page_size_limit: int,
        topics: list,
        *,
        page: int,
    ):
        if not topics:
            topics_str = f"Currently there are no debate topics set up"
        else:
            # generate topics string
            topics_str = "**Topics:**\n"
            for i, topic in enumerate(
                topics[page_size_limit * (page - 1) : page_size_limit * page]
            ):
                if i == 10:
                    break

                topic_str = topic["topic"]
                topic_author_id = topic["topic_author_id"]
                topic_options = topic["topic_options"]

                topic_author = None
                if topic_author_id:
                    topic_author = ctx.guild.get_member(int(topic_author_id))
                    if not topic_author:
                        try:
                            topic_author = await ctx.guild.fetch_member(
                                int(topic_author_id)
                            )
                        except Exception:
                            topic_author = None

                topics_str += (
                    f"`#{page_size_limit * (page - 1) + i + 1}`: {topic_str}\n"
                )
                if topic_author:
                    topics_str += f"**Topic Author:** {str(topic_author)}\n"

                if topic_options:
                    topics_str += (
                        "**Poll Options:**"
                        + " |".join(
                            [f" `{o}`" for i, o in enumerate(topic_options.values())]
                        )
                        + "\n"
                    )

        dd_time = (
            daily_debates_data["time"] if daily_debates_data["time"] else "Not set"
        )
        dd_channel = (
            f'<#{daily_debates_data["channel_id"]}>'
            if daily_debates_data["channel_id"]
            else "Not set"
        )
        dd_poll_channel = (
            f'<#{daily_debates_data["poll_channel_id"]}>'
            if daily_debates_data["poll_channel_id"]
            else "Not set"
        )
        dd_role = (
            f'<@&{daily_debates_data["role_id"]}>'
            if daily_debates_data["role_id"]
            else "Not set"
        )
        embed = await embed_maker.message(
            ctx,
            description=topics_str,
            author={"name": "Daily Debates"},
            footer={"text": f"Page {page}/{max_page_num}"},
        )
        embed.add_field(
            name="Attributes",
            value=f"**Time:** {dd_time}\n**Channel:** {dd_channel}\n**Poll Channel:** {dd_poll_channel}\n**Role:** {dd_role}",
        )
        return embed

    def cg_to_string(
        self, tags: bs4.element.Tag, asked_for: list[str], parent: str = ""
    ):
        spacer = f'|{"-" * 4}'
        string = ""
        parent_count = len(parent.split(".")) if parent else 0
        asked_for_cg_number = (
            asked_for[parent_count] if len(asked_for) > parent_count else None
        )

        for i, cg in enumerate(filter(lambda cg: type(cg) == bs4.element.Tag, tags)):
            contents = cg.contents

            cg_number = str(i + 1)
            if asked_for_cg_number is None or asked_for_cg_number == cg_number:
                new_parent = f'{parent + ("." if parent else "")}{cg_number}'
                if len(contents) > 1:
                    sub_cg = self.cg_to_string(contents[1], asked_for, new_parent)
                    string += f"{spacer * parent_count}`{new_parent}.`: {contents[0]}"
                    string += f"{sub_cg}"
                else:
                    string += (
                        f"{spacer * parent_count}`{new_parent}.`: {cg.contents[0]}\n"
                    )

        return string

    async def get_cg(self, asked_for: list[str]):
        # This session needs to be gotten in this weird way cause it's a double underscore variable
        aiohttp_session = getattr(self.bot.http, "_HTTPClient__session")
        async with aiohttp_session.get(
            "https://tldrnews.co.uk/discord-community-guidelines/"
        ) as resp:
            content = await resp.text()

            soup = bs4.BeautifulSoup(content, "html.parser")
            entry = soup.find("div", {"class": "entry-content"})
            cg_list = [*entry.children][15]

            return self.cg_to_string(cg_list, asked_for)

    @group(
        help="Moderation reprimand command. Used to establish a qorum before exacting punishment.",
        usage="reprimand (username) (cg id(s) violated) (link(s) to offending messages)",
        examples=["reprimand poll TheMasteredPanda 1.6 evidence_link,evidence_link"],
        cls=commands.Group,
        invoke_without_command=True,
    )
    async def reprimand(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @reprimand.command(
        help="Reprimand poll command. Used to establish a consensus on user breached CGs.",
        usage="reprimand poll (username) (cg ids)",
        name="poll",
        examples=["reprimand poll TheMasteredPanda 1.6,1.15.6"],
        cls=commands.Command,
    )
    async def reprimand_poll(self, ctx: Context, *, args: Union[ParseArgs, str] = None):
        if args is None or args["pre"] == "":
            return await embed_maker.command_error(ctx)

        settings = self.bot.reprimand.get_settings()

        if settings["reprimand_channel"] == "":
            return await embed_maker.error(ctx, "Reprimand channel not set.")

        split_args = args["pre"].split(" ")
        result = await get_member_from_string(ctx, split_args[0])

        if not result[0]:
            return await embed_maker.error(ctx, f"Can't find user {result[1]}")

        if len(split_args) < 2:
            return await embed_maker.error(
                ctx,
                f"Requires three arguments. Username, cg(s) violated, and image evidence links.",
            )

        cg_ids = split_args[1].split(",")

        invalid_cgs = []
        for cg_id in cg_ids:
            if self.bot.moderation.is_valid_cg(cg_id):
                continue
            invalid_cgs.append(cg_id)

        if len(invalid_cgs) > 0:
            return await embed_maker.error(
                ctx, f"The following aren't valid CG IDs: {', '.join(invalid_cgs)}."
            )

        # Need to find a better way to implement evidence logging.
        # evidence_links = split_args[2].split(",")

        print(result[0])
        print(cg_ids)
        reprimand = await self._reprimand_module.create_reprimand(result[0], cg_ids)

    @reprimand.group(
        help="Reprimand Configuration Command. Used to configure the Reprimand module. Executing this command only will return the modules config.",
        usage="reprimand config (subcommand)",
        examples=["reprimand config set"],
        name="config",
        cls=commands.Group,
        invoke_without_command=True,
    )
    async def reprimand_config(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @reprimand_config.command(
        help="View reprimand modules configuration file.",
        usage="reprimand config view",
        name="view",
        cls=commands.Command,
    )
    async def reprimand_config_view(self, ctx: Context):
        config_copy = copy.deepcopy(self.bot.reprimand.get_settings())
        config_copy.pop("punishments")

        return await embed_maker.message(
            ctx,
            description=f"```{json_util.dumps(config_copy, indent=4)}```",
            title="Reprimand Settings",
            send=True,
        )

    @reprimand_config.group(
        help="View, set, and remove notification announcements made in reprimand threads.",
        usage="reprimand config notif",
        examples=["reprimand config notif view"],
        name="notif",
        cls=commands.Group,
        invoke_without_command=True,
    )
    async def reprimand_config_notification(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @reprimand_config_notification.command(
        help="View currently set notification announcmenets.",
        usage="reprimand config notif view",
        examples=["reprimand config notif view"],
        name="view",
        cls=commands.Command,
    )
    async def config_notification_view(self, ctx: Context):
        notifications_config_copy = copy.deepcopy(
            self.bot.reprimand.get_settings()["notifications"]
        )
        return await embed_maker.message(
            ctx,
            description=f"```{json_util.dumps(notifications_config_copy, indent=4)}```",
            title="Reprimand Poll Notifications",
            send=True,
        )

    @reprimand_config_notification.command(
        help="Add a notification announcement.",
        usage="reprimand config notif add [interval (when it will be announced in the countdown)] [message (what will be announced)]",
        examples=["reprimand config notif add 5m Modpoll will end in 5 minutes"],
        name="notif",
        cls=commands.Command,
    )
    async def config_notification_add(
        self, ctx: Context, interval: str, *, message: str = ""
    ):
        notifications_config_copy = copy.deepcopy(
            self.bot.reprimand.get_settings()["notifications"]
        )
        keys = notifications_config_copy.keys()

        if interval.endswith(("s", "m", "h")) is False:
            return await embed_maker.message(
                ctx,
                description=f"No time unit found. use either h (hours), m (minutes) or s (seconds) to denote the unit of the value supplied immedately after the value. Eg. 10m, 5s, 4h",
                title="Error",
                send=True,
            )

        parsed_interval = format_time.parse(interval)
        if parsed_interval in keys:
            return await embed_maker.message(
                ctx,
                description=f"A notification at interval '{interval}' already exists.",
                title="Error",
                send=True,
            )

        notifications_config_copy[parsed_interval] = message
        self.bot.reprimand.set_setting("notifications", notifications_config_copy)
        return await embed_maker.message(
            ctx,
            description=f"Notification message '{message}' set at interval '{interval}'.",
            title="Notification Set",
            send=True,
        )

    @reprimand_config_notification.command(
        help="Remove a notification announcement by the interval it was meant to be announced at.",
        usage="reprimand config notif remove [interval (when it would have been announced in the countdown)]",
        examples=["reprimand config notif remove 5m"],
        name="remove",
        cls=commands.Command,
    )
    async def config_notification_remove(self, ctx: Context, interval: str = ""):
        notification_config_copy = copy.deepcopy(
            self.bot.reprimand.get_settings()["notifications"]
        )
        keys = notification_config_copy.keys()

        parsed_interval = format_time.parse(interval)
        if parsed_interval not in keys:
            return await embed_maker.message(
                ctx,
                description=f"Interval '{interval}' has no associated notification.",
                title="No Notification Found",
                send=True,
            )

        del notification_config_copy[parsed_interval]
        self.bot.reprimand.set_setting("notifications", notification_config_copy)
        return await embed_maker.message(
            ctx,
            description="Deleted notification at interval '{interval}'.",
            title="Notification Removed",
            send=True,
        )

    @reprimand_config.group(
        help="A command subset for configuring the punishment aspect of reprimands",
        usage="reprimand config pun",
        examples=["reprimand config pun view"],
        name="pun",
        cls=commands.Group,
        invoke_without_command=True,
    )
    async def config_punishments(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @config_punishments.command(
        help="View all set punishments in reprimand",
        usage="reprimand config pun view",
        name="view",
        cls=commands.Command,
    )
    async def punishments_view(self, ctx: Context):
        punishments_config_copy = copy.deepcopy(
            self.bot.reprimand.get_settings()["punishments"]
        )
        return await embed_maker.message(
            ctx,
            description=f"```{json_util.dumps(punishments_config_copy, indent=4)}```",
            title="Punishment Configuration",
            send=True,
        )

    # Search up how to generate a string if from the name of a punishment
    @config_punishments.command(
        help="Add a punishment to reprimand",
        usage="reprimand config pun add [id] [type] [duration] [name] [short description]",
        examples=[
            "reprimand config pun add 3formal formal_warning 0s 3 Formal Warnings"
        ],
        name="add",
        command_args=[
            (("--id", "-id", str), "Id of the punishment (formal1 for example)"),
            (("--type", "-t", str), "Type of punishment (mute, ban, warn)"),
            (
                ("--duration", "-d", str),
                "Duration of the punishment (50m, 1h, 30s, &c)",
            ),
            (
                ("--name", "-n", str),
                "The full capitlised name of the punishment (Formal Warning, Informal Warning, 8 Hour Mute)",
            ),
            (
                ("--shortdescription", "-sd", str),
                "Short description of the punisment (An Informal Warning to the User, for example)",
            ),
            (
                ("--emoji", "-e", str),
                "The emoji used to symbolise this punishment entry in a modpoll",
            ),
        ],
        cls=commands.Command,
    )
    async def punishment_add(self, ctx: Context, *, args: Union[ParseArgs, str] = None):
        print(args)
        if args is None or args["pre"] != "":
            return await embed_maker.command_error(ctx)

        punishment_id = args["id"].lower()
        print(f'Punishment ID is {punishment_id}')

        if self._reprimand_module.is_punishment_id(punishment_id):
            return await embed_maker.message(
                ctx,
                description="Punishment under id already exists.",
                title="ID Already Exists",
                send=True,
            )

        punishments = self._reprimand_module.get_punishments()

        for punishment_id in punishments:
            punishment = punishments[punishment_id]
            if punishment is not None:
                if (
                    punishment["duration"] == format_time.parse(args["duration"])
                    and punishment["type"] == args["type"].lower()
                ):
                    return await embed_maker.message(
                        ctx,
                        description=f"Punishment under id {punishment['id']} has the same punishment type and duration.",
                        title="Punishment Exists",
                        send=True,
                    )


            if punishment['name'].lower() == args['name'].lower():
                return await embed_maker.message(
                        ctx,
                        description=f"{args['name']} already used.",
                        title="Name already taken.",
                        send=True
                        )

            if punishment["emoji"] == args["emoji"]:
                return await embed_maker.message(
                    ctx,
                    description=f"Emoji {args['emoji']} already used for another punishment.",
                    title="Emoji already used.",
                    send=True,
                )

            if args["type"].upper() not in PunishmentType.list():
                return await embed_maker.message(
                    ctx,
                    description=f"Type {args['type'].upper()} doesn't exist in punishment types. Types: {', '.join(PunishmentType.list())}",
                    title="Type not recognised.",
                    send=True,
                )

        short_description = args['shortdescription']
        self._reprimand_module.add_punishment(
                args['id'].lower(),
                PunishmentType.type(args['type']),
                args['duration'],
                args['name'],
                short_description,
                args['emoji'])

        await embed_maker.message(ctx, description=f"Created punishment {args['id'].lower()}.", title="Created.", send=True)

    @config_punishments.command(
        help="Remove a punishment from reprimand",
        usage="reprimand config pun remove [id]",
        name="remove",
        cls=commands.Command,
    )
    async def punishment_remove(self, ctx: Context, punishment_id: str = ""):
        if self._reprimand_module.is_punishment_id(punishment_id) is False:
            return await embed_maker.message(
                ctx,
                description=f"No punishment under id {punishment_id}.",
                title="No Punishment Found.",
                send=True,
            )
        self._reprimand_module.remove_punishment(punishment_id)
        return await embed_maker.message(
            ctx, description="Punishment removed.", title="Removed.", send=True
        )

    @command(
        help="A command used within a reprimand thread to check the time left on the polls within said thread.",
        usage="rtime",
        examples=["rtime"],
        name="rtime",
        cls=commands.Command,
    )
    async def reprimand_time_thread_cmd(
        self, ctx: Context, *, args: Union[ParseArgs, str] = ""
    ):
        channel = ctx.channel

        if channel.type != discord.ChannelType.public_thread:
            return

        if self._reprimand_module.is_reprimand_thread(channel.id) is False:
            return

        reprimand = self._reprimand_module.get_reprimand(channel.id)

        if reprimand is None:
            raise Exception(
                f"Reprimand object supposedly associated with thread under id {channel.id} not found."
            )

        polls = reprimand.get_polls()
        settings = self._reprimand_module.get_settings()
        rtime_messages = settings["messages"]["rtime"]
        gc_poll_entry = rtime_messages["entry"]["gc_poll"]
        p_poll_entry = rtime_messages["entry"]["p_poll"]
        embed_description = ""

        for poll in polls:
            p_type = poll.get_type()

            if p_type == PollType.GC_POLL:
                cg_id = poll.get_cg_id()
                embed_description = (
                    embed_description
                    + "\n"
                    + gc_poll_entry.replace("{cg_id}", cg_id).replace(
                        "{time_remaining}",
                        format_time.seconds(poll.get_seconds_remaining()),
                    )
                )
            else:
                embed_description = (
                    embed_description
                    + "\n"
                    + p_poll_entry.replace(
                        "{time_remaining}",
                        format_time.seconds(poll.get_seconds_remaining()),
                    )
                )

        await embed_maker.message(
            ctx,
            description=embed_description,
            title=rtime_messages["header"],
            send=True,
        )
        print("Sending embed")

    @reprimand_config.command(
        help="Set a configuration value for the Reprimand module.",
        usage="reprimand config set",
        examples=["reprimand config set (config name) (config value)"],
        name="set",
        cls=commands.Command,
    )
    async def reprimand_config_set(
        self, ctx: Context, *, args: Union[ParseArgs, str] = ""
    ):
        if args["pre"] != "":
            split_pre = args["pre"].split(" ")
            args["path"] = split_pre[0]
            args["value"] = " ".join(split_pre[1:])
        else:
            if args["path"] is None:
                return await embed_maker.command_error(ctx, "path")

            if args["value"] is None:
                return await embed_maker.command_error(ctx, "value")

        self._reprimand_module.set_setting(
            args["path"],
            args["value"] if args["value"].isnumeric() is False else int(args["value"]),
        )

        await embed_maker.message(
            ctx,
            description=f"Set value {args['value']} on setting {args['path']}",
            title="Changed Setting",
            send=True,
        )

    @group(
        invoke_without_command=True,
        help="Daily debate scheduler/manager",
        usage="dailydebates (sub command) (arg(s))",
        aliases=["dd", "dailydebate"],
        examples=["dailydebates"],
        cls=commands.Group,
        module_dependency=["timers", "reaction_menus"],
    )
    async def dailydebates(self, ctx: Context, page: str = 1):
        if ctx.subcommand_passed is None:
            daily_debates_data = db.get_daily_debates(ctx.guild.id)

            if type(page) == str and page.isdigit():
                page = int(page)
            else:
                page = 1

            page_size_limit = 10

            # List currently set up daily debate topics
            topics = daily_debates_data["topics"]

            # calculate max page number
            max_page_num = math.ceil(len(topics) / page_size_limit)
            if max_page_num == 0:
                max_page_num = 1

            if page > max_page_num:
                return await embed_maker.error(ctx, "Exceeded maximum page number")

            page_constructor = functools.partial(
                self.construct_dd_embed,
                ctx,
                daily_debates_data,
                max_page_num,
                page_size_limit,
                topics,
            )

            embed = await page_constructor(page=page)
            dd_message = await ctx.send(embed=embed)

            menu = BookMenu(
                dd_message,
                author=ctx.author,
                page=page,
                max_page_num=max_page_num,
                page_constructor=page_constructor,
            )

            self.bot.reaction_menus.add(menu)

    @dailydebates.command(
        name="disable",
        help="Disable the daily debates system, time will be set to 0",
        usage="dailydebates disable",
        examples=["dailydebates disable"],
        cls=commands.Command,
        module_dependency=["timers"],
    )
    async def dailydebates_disable(self, ctx: Context):
        db.daily_debates.update_one({"guild_id": ctx.guild.id}, {"$set": {"time": 0}})

        # cancel timer if active
        daily_debate_timer = db.timers.find_one(
            {
                "guild_id": ctx.guild.id,
                "event": {"$in": ["daily_debate", "daily_debate_final"]},
            }
        )
        if daily_debate_timer:
            db.timers.delete_one({"_id": ObjectId(daily_debate_timer["_id"])})

        return await embed_maker.message(
            ctx, description="Daily debates have been disabled", send=True
        )

    @dailydebates.command(
        name="set_poll_options",
        help="Set the poll options for a daily debate topic",
        usage="dailydebates set_poll_options [index of topic] [args]",
        examples=[
            "dailydebates set_poll_options 1 -o yes -o no -o double yes -o double no",
            "dailydebates set_poll_options 1 -o 🇩🇪: Germany -o 🇬🇧: UK",
        ],
        command_args=[
            (("--option", "-o", list), "Option for the poll"),
        ],
        cls=commands.Command,
        module_dependency=["timers"],
    )
    async def dailydebates_set_poll_options(
        self, ctx: Context, index: str = None, *, args: Union[ParseArgs, dict] = None
    ):
        if index is None:
            return await embed_maker.command_error(ctx)

        if not index.isdigit():
            return await embed_maker.command_error(ctx, "[index of topic]")

        options = args["option"]

        if not options:
            return await embed_maker.error(ctx, "Missing options")

        utility_cog = self.bot.get_cog("Utility")
        emote_options = await utility_cog.parse_poll_options(ctx, options)
        if type(emote_options) == discord.Message:
            return

        daily_debates_data = db.daily_debates.find_one({"guild_id": ctx.guild.id})
        topics = daily_debates_data["topics"]

        index = int(index)
        if len(topics) < index:
            return await embed_maker.error(ctx, "index out of range")

        topic = topics[index - 1]

        topic_obj = {
            "topic": topic["topic"],
            "topic_author_id": topic["topic_author_id"],
            "topic_options": emote_options,
        }

        db.daily_debates.update_one(
            {"guild_id": ctx.guild.id}, {"$set": {f"topics.{index - 1}": topic_obj}}
        )
        options_str = "\n".join(
            [f"{emote}: {option}" for emote, option in emote_options.items()]
        )
        return await embed_maker.message(
            ctx,
            description=f'Along with the topic: **"{topic["topic"]}"**\nwill be sent a poll with these options: {options_str}',
            send=True,
        )

    @dailydebates.command(
        name="add",
        help="add a topic to the list topics along with optional options and topic author",
        usage="dailydebates add [topic] (args)",
        examples=[
            "dailydebates add is ross mega cool? -ta hattyot -o yes -o double yes -o triple yes"
        ],
        command_args=[
            (
                ("--topic_author", "-ta", str),
                "Original author of the topic, that will be mentioned when the dd is sent, they will also be given a 15% boost for 6 hours",
            ),
            (("--option", "-o", list), "Option for the poll"),
        ],
        cls=commands.Command,
        module_dependency=["timers"],
    )
    async def dailydebates_add(
        self, ctx: Context, *, args: Union[ParseArgs, dict] = None
    ):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = await self.parse_dd_args(ctx, args)
        if type(args) == discord.Message:
            return

        topic = args["pre"]
        topic_author = args["topic_author"]
        topic_options = args["option"]

        topic_obj = {
            "topic": topic,
            "topic_author_id": topic_author,
            "topic_options": topic_options,
        }
        db.daily_debates.update_one(
            {"guild_id": ctx.guild.id}, {"$push": {"topics": topic_obj}}
        )
        daily_debate_data = db.daily_debates.find_one({"guild_id": ctx.guild.id})
        await embed_maker.message(
            ctx,
            description=f"`{topic}` has been added to the list of daily debate topics"
            f'\nThere are now **{len(daily_debate_data["topics"])}** topics on the list',
            send=True,
        )

        daily_debate_timer = db.timers.find_one(
            {
                "guild_id": ctx.guild.id,
                "event": {"$in": ["daily_debate", "daily_debate_final"]},
            }
        )
        if not daily_debate_timer:
            return await self.start_daily_debate_timer(
                ctx.guild.id, daily_debate_data["time"]
            )

    @dailydebates.command(
        name="insert",
        help="insert a topic into the first place on the list of topics along with optional options and topic author",
        usage="dailydebates insert [topic] (args)",
        examples=[
            "dailydebates insert is ross mega cool? -ta hattyot -o yes | double yes | triple yes"
        ],
        command_args=[
            (
                ("--topic_author", "-ta", str),
                "Original author of the topic, that will be mentioned when the dd is sent, they will also be given a 15% boost for 6 hours",
            ),
            (("--option", "-o", list), "Option for the poll"),
        ],
        cls=commands.Command,
        module_dependency=["timers"],
    )
    async def _dailydebates_insert(
        self, ctx: Context, *, args: Union[ParseArgs, dict] = None
    ):
        if args is None:
            return await embed_maker.command_error(ctx)

        args = await self.parse_dd_args(ctx, args)
        if type(args) == discord.Message:
            return

        topic = args["pre"]
        topic_author = args["topic_author"]
        topic_options = args["option"]

        topic_obj = {
            "topic": topic,
            "topic_author_id": topic_author,
            "topic_options": topic_options,
        }
        db.daily_debates.update_one(
            {"guild_id": ctx.guild.id},
            {"$push": {"topics": {"$each": [topic_obj], "$position": 0}}},
        )

        daily_debate_data = db.daily_debates.find_one({"guild_id": ctx.guild.id})
        await embed_maker.message(
            ctx,
            description=f"`{topic}` has been inserted into first place in the list of daily debate topics"
            f'\nThere are now **{len(daily_debate_data["topics"])}** topics on the list',
            send=True,
        )

        daily_debate_timer = db.timers.find_one(
            {
                "guild_id": ctx.guild.id,
                "event": {"$in": ["daily_debate", "daily_debate_final"]},
            }
        )
        if not daily_debate_timer:
            return await self.start_daily_debate_timer(
                ctx.guild.id, daily_debate_data["time"]
            )

    @dailydebates.command(
        name="remove",
        help="remove a topic from the topic list",
        usage="dailydebates remove [topic index]",
        examples=["dailydebates remove 2"],
        cls=commands.Command,
        module_dependency=["timers"],
    )
    async def dailydebates_remove(self, ctx: Context, index: str = None):
        if index is None:
            return await embed_maker.command_error(ctx)

        if not index.isdigit():
            return await embed_maker.error(ctx, "Invalid index")

        daily_debate_data = db.daily_debates.find_one({"guild_id": ctx.guild.id})

        index = int(index)
        if index > len(daily_debate_data["topics"]):
            return await embed_maker.error(ctx, "Index too big")

        if index < 1:
            return await embed_maker.error(ctx, "Index cant be smaller than 1")

        topic_to_delete = daily_debate_data["topics"][index - 1]
        db.daily_debates.update_one(
            {"guild_id": ctx.guild.id}, {"$pull": {"topics": topic_to_delete}}
        )

        return await embed_maker.message(
            ctx,
            description=f'`{topic_to_delete["topic"]}` has been removed from the list of daily debate topics'
            f'\nThere are now **{len(daily_debate_data["topics"]) - 1}** topics on the list',
            send=True,
        )

    @dailydebates.command(
        name="set_time",
        help="set the time when topics are announced",
        usage="dailydebates set_time [time]",
        examples=["dailydebates set_time 14:00 GMT+1"],
        cls=commands.Command,
        module_dependency=["timers"],
    )
    async def dailydebates_set_time(self, ctx: Context, *, time_str: str = None):
        if time_str is None:
            return await embed_maker.command_error(ctx)

        parsed_time = dateparser.parse(
            time_str, settings={"RETURN_AS_TIMEZONE_AWARE": True}
        )
        if not parsed_time:
            return await embed_maker.error(ctx, "Invalid time")

        parsed_dd_time = dateparser.parse(
            time_str,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "RELATIVE_BASE": datetime.datetime.now(parsed_time.tzinfo),
            },
        )
        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        if time_diff_seconds < 0:
            return await embed_maker.error(ctx, "Invalid time")

        db.daily_debates.update_one(
            {"guild_id": ctx.guild.id}, {"$set": {"time": time_str}}
        )
        await embed_maker.message(
            ctx,
            description=f"Daily debates will now be announced every day at {time_str}",
            send=True,
        )

        # cancel old timer
        db.timers.delete_many(
            {
                "guild_id": ctx.guild.id,
                "event": {"$in": ["daily_debate", "daily_debate_final"]},
            }
        )

        return await self.start_daily_debate_timer(ctx.guild.id, time_str)

    @dailydebates.command(
        name="set_channel",
        help=f"set the channel where topics are announced",
        usage="dailydebates set_channel [#set_channel]",
        examples=["dailydebates set_channel #daily-debates"],
        cls=commands.Command,
        module_dependency=["timers"],
    )
    async def dailydebates_set_channel(
        self, ctx: Context, channel: discord.TextChannel = None
    ):
        if channel is None:
            return await embed_maker.command_error(ctx)

        db.daily_debates.update_one(
            {"guild_id": ctx.guild.id}, {"$set": {"channel_id": channel.id}}
        )
        return await embed_maker.message(
            ctx,
            description=f"Daily debates will now be announced every day at <#{channel.id}>",
            send=True,
        )

    @dailydebates.command(
        name="set_role",
        help=f"set the role that will be @'d when topics are announced, disable @'s by setting the role to `None`",
        usage="dailydebates set_role [role]",
        examples=["dailydebates set_role Debater"],
        cls=commands.Command,
        module_dependency=["timers"],
    )
    async def dailydebates_set_role(
        self, ctx: Context, *, role: Union[discord.Role, str] = None
    ):
        if role is None:
            return await embed_maker.command_error(ctx)

        if type(role) == str and role.lower() == "none":
            db.daily_debates.update_one(
                {"guild_id": ctx.guild.id}, {"$set": {"role_id": 0}}
            )
            return await embed_maker.message(
                ctx, description="daily debates role has been disabled", send=True
            )
        elif type(role) == str:
            return await embed_maker.command_error(ctx, "[role]")

        db.daily_debates.update_one(
            {"guild_id": ctx.guild.id}, {"$set": {"role_id": role.id}}
        )
        return await embed_maker.message(
            ctx,
            description=f"Daily debates will now be announced every day to <@&{role.id}>",
            send=True,
        )

    @dailydebates.command(
        name="set_poll_channel",
        help=f"Set the poll channel where polls will be sent, disable polls by setting poll channel to `None``",
        usage="dailydebates set_poll_channel [#channel]",
        examples=["dailydebates set_poll_channel #daily_debate_polls"],
        cls=commands.Command,
        module_dependency=["timers"],
    )
    async def dailydebates_set_poll_channel(
        self, ctx: Context, channel: Union[discord.TextChannel, str] = None
    ):
        if channel is None:
            return await embed_maker.command_error(ctx)

        if type(channel) == str and channel.lower() == "none":
            db.daily_debates.update_one(
                {"guild_id": ctx.guild.id}, {"$set": {"role_id": 0}}
            )
            return await embed_maker.message(
                ctx,
                description="daily debates poll channel has been disabled",
                send=True,
            )

        db.daily_debates.update_one(
            {"guild_id": ctx.guild.id}, {"$set": {"poll_channel_id": channel.id}}
        )
        return await embed_maker.message(
            ctx,
            description=f"Daily debate polls will now be sent every day to <#{channel.id}>",
            send=True,
        )

    async def parse_dd_args(self, ctx: Context, args: dict):
        if not args["pre"]:
            return await embed_maker.error(ctx, "Missing topic")

        utility_cog = self.bot.get_cog("Utility")
        args["option"] = (
            await utility_cog.parse_poll_options(ctx, args["option"])
            if args["option"]
            else ""
        )
        if type(args["option"]) == discord.Message:
            return

        if args["topic_author"]:
            member = await get_member(ctx, args["topic_author"])
            if type(member) == discord.Message:
                return member

            args["topic_author"] = member.id

        return args

    async def start_daily_debate_timer(self, guild_id, dd_time):
        # delete old timer
        db.timers.delete_many(
            {
                "guild_id": guild_id,
                "event": {"$in": ["daily_debate", "daily_debate_final"]},
            }
        )

        # creating first parsed_dd_time to grab timezone info
        parsed_dd_time = dateparser.parse(
            dd_time, settings={"RETURN_AS_TIMEZONE_AWARE": True}
        )

        # second one for actual use
        parsed_dd_time = dateparser.parse(
            dd_time,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": True,
                "RELATIVE_BASE": datetime.datetime.now(parsed_dd_time.tzinfo),
            },
        )

        time_diff = parsed_dd_time - datetime.datetime.now(parsed_dd_time.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        # -1h so mods can be warned when there are no daily debate topics set up
        timer_expires = round(time.time()) + time_diff_seconds - 3600  # one hour
        self.bot.timers.create(
            guild_id=guild_id, expires=timer_expires, event="daily_debate", extras={}
        )


def setup(bot):
    bot.add_cog(Mod(bot))
