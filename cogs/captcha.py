import re
import functools
import math
from modules.reaction_menus import BookMenu
from time import time
import config
from datetime import datetime, timedelta
from bson import json_util
import json
from typing import Union

from discord.embeds import Embed
from discord.file import File
from discord.member import Member
from bot import TLDR
from modules import commands, embed_maker, captcha
from discord.ext.commands import Cog, command, group, Context
from discord.guild import Guild
from modules.commands import Command, Group
from modules.utils import ParseArgs, get_member_from_string
from modules.captcha import GatewayGuild


class Captcha(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    async def construct_blacklist_embed(
        ctx: Context, blacklist: list, max_page_num: int, page_limit: int, *, page: int
    ):
        if len(blacklist) == 0:
            return await embed_maker.message(
                ctx, description="No blacklist entries found."
            )

        bits = []

        for i, entry in enumerate(
            blacklist[page_limit * (page - 1) : page_limit * page]
        ):
            member = entry["member"]
            member_name = member["name"]
            member_id = member["id"]
            started = entry["started"]
            ends = entry["ends"]
            formatted_started = datetime.fromtimestamp(started).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            formatted_ends = datetime.fromtimestamp(ends).strftime("%Y-%m-%d %H:%M:%S")
            diff = ends - started
            m, s = divmod(diff, 60)
            h, d = divmod(m, 60)

            time_bits = []

            if s != 0:
                time_bits.append(f"{s} {'second' if s != 0 else 'seconds'}")
            if m != 0:
                time_bits.append(f"{m} {'minute' if m != 0 else 'minutes'}")
            if h != 0:
                time_bits.append(f"{h} {'hour' if h != 0 else 'hours'}")
            if d != 0:
                time_bits.append(f"{d} {'day' if d != 0 else 'days'}")

            bits.append(
                "\n".join(
                    [
                        f"- **{member_name}/{member_id}**",
                        f"  **Started:** {formatted_started}",
                        f"  **Ends:** {formatted_ends} (', '.join(time_bits))",
                    ]
                )
            )

        return await embed_maker.message(
            ctx,
            description="\n".join(bits),
            author={"name": "Captcha Gateway"},
            footer={"text": f"Page {page}/{max_page_num}"},
        )

    @group(
        help="Captcha Gateway System. A method of stopping the bot attacks.",
        name="captcha",
        usage="captcha [sub command]",
        examples=["captcha servers"],
        cls=Group,
        module_dependency=["captcha"],
        invoke_without_command=True,
    )
    async def captcha_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @captcha_cmd.group(
        help="For commands relating to creating, deleting, or listing servers.",
        name="servers",
        usage="captcha servers [sub command]",
        examples=["captcha servers list"],
        cls=Group,
        module_dependency=["captcha"],
        invoke_without_command=True,
    )
    async def captcha_servers_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @captcha_servers_cmd.command(
        help="Lists active gateway servers",
        name="list",
        usage="captcha servers create",
        examples=["captcha servers create"],
        module_dependency=["captcha"],
        cls=Command,
    )
    async def list_servers_cmd(self, ctx: Context):
        bits = []

        for g_guild in self.bot.captcha.get_gateway_guilds():
            g_bits = [f"- **{g_guild.get_name()}", f"**ID:** {g_guild.get_id()}"]
            bits.append("\n".join(g_bits))

        await embed_maker.message(
            ctx=ctx,
            title="Active Gateway Guilds",
            description="\n".join(bits) if len(bits) > 0 else "No Active Guilds.",
            send=True,
        )

    @captcha_cmd.group(
        help="A set of commands used to administrate and moderate this feature.",
        name="mod",
        usage="captcha mod [sub command]",
        examples=["captcha mod config set"],
        cls=Group,
        invoke_without_command=True,
    )
    async def mod_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @mod_cmd.group(
        help="A set of commands used to configure the configurable elements of this feature.",
        name="config",
        usage="captcha mod config [sub command]",
        examples=["captcha mod config set landing_channel.name welcome"],
        cls=Group,
        invoke_without_command=True,
    )
    async def config_mod_cmd(self, ctx: Context):
        config = self.bot.captcha.get_settings().copy()
        config.pop("_id")
        return await embed_maker.message(
            ctx,
            description=f"```{json_util.dumps(config['modules']['captcha'], indent=4)}```",
            title="Captcha Gateway Settings",
            send=True,
        )

    @config_mod_cmd.group(
        help="Set a value of a configuration variable.",
        name="set",
        usage="captcha mod config set [variable name] [value]",
        examples=["captcha mod config set landing_channel.name welcome-tldr"],
        cls=Command,
        command_args=[
            (
                ("--path", "-p", str),
                "The path of the setting, with fullspots substituting spaces.",
            ),
            (("--value", "-v", str), "Value to set the setting to."),
        ],
    )
    async def set_config_mod_cmd(
        self, ctx: Context, *, args: Union[ParseArgs, str] = ""
    ):
        if args["pre"] != "":
            split_pre = args["pre"].split(" ")
            args["path"] = split_pre[0]
            args["value"] = split_pre[1]
        else:
            if args["path"] is None:
                return await embed_maker.command_error(ctx, "path")

            if args["value"] is None:
                return await embed_maker.command_error(ctx, "value")

        self.bot.captcha.set_setting(args["path"], args["value"])
        await embed_maker.message(
            ctx,
            description=f"Set value {args['value']} on setting {args['path']}",
            title="Changed Setting",
            send=True,
        )

    @mod_cmd.group(
        help="Blacklist - for users who couldn't pass the first set of Captcha tests. These commands allow the viewing, adding, and removing of users on the Blacklist.",
        name="blacklist",
        usage="captcha mod blacklist [sub-command]",
        examples=[
            "captcha mod blacklist",
            "captcha mod blacklist add TheMasteredPanda 24h",
        ],
        cls=Group,
        invoke_without_command=True,
    )
    async def blacklist_mod_cmd(self, ctx: Context):
        blacklist = self.bot.captcha.get_blacklist()
        max_page_size = 6
        max_page_num = math.ceil(len(blacklist) / max_page_size)
        page_constructor = functools.partial(
            self.construct_blacklist_embed,
            ctx=ctx,
            blacklist=blacklist,
            max_page_num=max_page_num,
            page_limit=max_page_size,
        )

        embed = await page_constructor(page=1)
        message = await ctx.send(embed)
        menu = BookMenu(
            message,
            page=1,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
        )
        self.bot.reaction_menus.add(menu)

    @blacklist_mod_cmd.command(
        help="Add a member to the blacklist.",
        usage="add",
        examples=[
            "captcha mod blacklist add [name of member] [time (40h20m4s)]",
            "captcha mod blacklist add TheMasteredPanda 24h",
        ],
        command_args=[
            (("--name", "-n", str), "Name of the user you want to blacklist."),
            (
                ("--duration", "-d", str),
                "The amount of time you want to blacklist this user for ([integer][time unit]. Time Units: s (seconds), m (minutes), h(hours)",
            ),
        ],
        cls=Command,
    )
    async def blacklist_add_cmd(
        self, ctx: Context, *, args: Union[ParseArgs, str] = ""
    ):
        split_pre = args["pre"].split(" ")

        if len(split_pre) == 0:
            return await embed_maker.command_error(ctx)

        name_string = args["name"] if args["name"] is not None else split_pre[0]

        member_entry = self.bot.captcha.get_data_manager().get_blacklisted_member(
            name=name_string
        )

        if member_entry is None:
            return await embed_maker.message(
                ctx,
                description=f"Can't find member {name_string} in blacklist.",
                title="Can't find member.",
                send=True,
            )

        member_name = member_entry["member"]["name"]

        if member_entry:
            return await embed_maker.message(
                ctx,
                description=f"Member {member_name} is already blacklisted.",
                title="Member already blacklisted.",
                send=True,
            )

        member, rest = get_member_from_string(args["pre"])
        amount_string = args["duration"]
        if amount_string is None:
            if rest is not None:
                amount_string = rest
            else:
                amount_string = split_pre[1]

        amount_string_bits = re.split("(\\d{1,2}\\w{1})", amount_string)

        duration_in_seconds = 0
        for bit in amount_string_bits:
            if bit.endswith("h"):
                duration_in_seconds = duration_in_seconds + (3600 * int(bit.strip("h")))
            if bit.endswith("m"):
                duration_in_seconds = duration_in_seconds + (60 * int(bit.strip("m")))
            if bit.endswith("s"):
                duration_in_seconds = duration_in_seconds + int(bit.strip("s"))

        self.bot.captcha.get_data_manager().add_member_to_blacklist(
            member.id, duration_in_seconds
        )

    @blacklist_mod_cmd.command(
        help="Remove a member from the blacklist.",
        name="remove",
        usage="captcha mod blacklist remove",
        examples=["captcha mod blacklist remove [name of member]"],
        cls=Command,
    )
    async def blacklist_rm_cmd(self, ctx: Context, name: str = ""):
        if name == "":
            return await embed_maker.command_error(ctx)

        member_entry = self.bot.captcha.get_data_manager().get_blacklisted_member(
            name=name
        )

        if member_entry is None:
            return await embed_maker.message(
                ctx,
                description=f"Couldn't find member {name} in blacklist.",
                title="Couldn't find name",
                send=True,
            )

        self.bot.captcha.get_data_manager().rm_member_from_blacklist(
            member_entry["member"]["id"]
        )
        await self.bot.captcha.unban(member_entry["member"]["id"])
        await embed_maker.message(
            ctx,
            description=f"Removed {member_entry['member']['name']} from the blacklist.",
            title="Removed member from blacklist",
            send=True,
        )

    @captcha_cmd.group(
        help="A set of dev commands used when testing this feature.",
        name="dev",
        usage="captcha dev [sub command]",
        examples=["captcha dev create guild"],
        cls=Group,
        module_dependency=["captcha"],
        invoke_without_command=True,
    )
    async def dev_cmds(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @dev_cmds.group(
        help="Create either a new guild or a captcha channel on any guild the bot is connected to.",
        name="create",
        usage="captcha dev create [sub command]",
        examples=["captcha dev create guild", "captcha dev create channel"],
        cls=Group,
        invoke_without_command=True,
    )
    async def dev_create_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @dev_create_cmd.command(
        help="Create a gateway guild.",
        name="guild",
        usage="captcha dev create guild",
        examples=["captcha dev create guild"],
        cls=Command,
        module_dependency=["captcha"],
        invoke_without_command=True,
    )
    async def dev_create_server(self, ctx: Context):
        guild_count = len(self.bot.guilds)
        if guild_count >= 10:
            return await embed_maker.message(
                ctx,
                description="Can't create new guild, bot cannot create new guilds if it is joined to more than 10 guilds.",
                title="Can't create guild.",
                send=True,
            )

        number = len(self.bot.captcha.get_gateway_guilds()) + 1
        g_guild = await self.bot.captcha.create_guild()
        await embed_maker.message(
            ctx, description=f"Created Gateway Guild No. {number}", send=True
        )

    @dev_cmds.command(
        help="List all the guilds the bot is in, not just the Gateway Guilds.",
        name="list",
        usage="captcha dev list",
        examples=["captcha dev list"],
        module_dependency=["captcha"],
        cls=Command,
    )
    async def dev_guild_list(self, ctx: Context):
        guilds = self.bot.guilds
        bits = []

        for guild in guilds:
            bits.append(
                "\n".join(
                    [
                        f"- **{guild.name}**",
                        f"  **ID**: {guild.id}",
                        f"  **User Count:** {len(guild.members)}",
                        f"  **Owner:** {guild.owner.name}/{guild.owner.id}",
                        f"  **Gateway Guild:** {'Yes' if self.bot.captcha.is_gatway_guild(guild.id) else 'No'}",
                    ]
                )
            )

        return await embed_maker.message(
            ctx, description="\n".join(bits), title="Guilds", send=True
        )

    @dev_cmds.command(
        help="Delete a guilds owned by the Bot.",
        name="delete",
        usage="captcha dev delete",
        examples=["captcha dev delete"],
        module_dependency=["captcha"],
        command_args=[
            (("--name", "-n", str), "Guild name"),
            (
                ("--gateway-guild", "-gg", str),
                "If this is true it will check the Gateway Guilds list, if not it will check the guilds the bot is joined to. Used in cases where a guild owned by the bot is not in the gateway guild list.",
            ),
        ],
        cls=Command,
    )
    async def dev_guild_delete(self, ctx: Context, *, args: Union[ParseArgs, str] = ""):
        if args == "":
            return await embed_maker.command_error(ctx)

        guilds: list[Guild] = self.bot.guilds
        name = args["pre"] if args["pre"] != "" else args["name"]

        for guild in guilds:
            if name.lower() == guild.name.lower():
                if args["gateway-guild"] == "no":
                    deleted = await self.bot.captcha.get_gateway_guild(
                        guild.id
                    ).delete()
                    if deleted is False:
                        return await embed_maker.message(
                            ctx,
                            description=f"Failed to delete guild {guild.name}.",
                            title="Couldn't delete gateway guild.",
                            send=True,
                        )
                elif args["gateway-guild"] is None:
                    guilds = self.bot.guilds

                    for guild in guilds:
                        if guild.name.lower() == name.lower():
                            await guild.delete()

                            return await embed_maker.message(
                                ctx,
                                description=f"Deleted guild {guild.name}.",
                                title="Deleted Gateway Guild.",
                                send=True,
                            )
        return await embed_maker.message(
            ctx,
            description=f"Couldn't find guild under name {name}.",
            title="Couldn't findguild.",
            send=True,
        )

    @dev_create_cmd.command(
        help="Create an invitation link for a gateway guild.",
        name="invite",
        uasge="captcha dev create invite [minimum uses] [time to live (in seconds)] [temporary (yes/no)] [name]",
        examples=["captcha dev create invite 1 120 no [guild name]"],
        cls=Command,
        command_args=[
            (
                ("--min-uses", "-mu", int),
                "The amount of times this invite can be used (0 sets this to infinite)",
            ),
            (
                ("--max-age", "-ma", int),
                "The time-to-live value of this invite, in seconds (0 sets this to immortal)",
            ),
            (
                ("--temporary", "-t", bool),
                "If set to temporary, will kick the user off the guild if Discord reloads.",
            ),
            (("--name", "-n", list), "The name of the guild to create the invite on."),
        ],
    )
    async def dev_create_invite(
        self,
        ctx: Context,
        *,
        args: Union[ParseArgs, str] = "",
    ):
        min_uses: int = 1 if args["min-uses"] is None else args["min-uses"]
        max_age: int = 60 if args["max-age"] is None else args["max-age"]
        temporary: bool = False if args["temporary"] is None else args["temporary"]
        name = args["pre"] if args["name"] is None else args["name"]

        g_guilds: list[GatewayGuild] = self.bot.captcha.get_gateway_guilds()

        for g_guild in g_guilds:
            if g_guild.get_name().lower() == name.lower():
                if g_guild.get_landing_channel() is None:
                    return await embed_maker.message(
                        ctx,
                        description="Guild does not have landing channel set.",
                        title="Couldn't create invite.",
                        send=True,
                    )
                invite = await g_guild.get_landing_channel().create_invite(
                    max_age=max_age,
                    min_uses=min_uses,
                    temporary=True if temporary == "yes" else False,
                )
                return await embed_maker.message(
                    ctx, description=invite.url, title="Created invite.", send=True
                )
        return await embed_maker.message(
            ctx,
            description=f"Couldn't find guild {name}",
            title="Couldn't create invite.",
            send=True,
        )

    @dev_create_cmd.command(
        help="Create a captcha channel, for testing.",
        name="channel",
        usage="captcha dev create channel Gateway Guild 1",
        examples=["captcha dev create channel -n Gateway Guild 1 -c 2"],
        command_args=[
            (("--name", "-n", str), "Name of the Gateway Guild"),
            (("--captcha", "-c", int), "What type of captcha to use in the channel"),
        ],
        cls=Command,
    )
    async def dev_create_captcha_channel(
        self, ctx: Context, *, args: Union[ParseArgs, str] = ""
    ):
        if args == "":
            return await embed_maker.command_error(ctx)

        guild_name = args["name"] if args["name"] is not None else args["pre"]
        captcha_id = args["captcha"] if args["captcha"] is not None else 1

    @dev_create_cmd.command(
        help="Create a captch image, for testing",
        name="image",
        usage="captcha dev create image",
        examples=["captcha dev create image"],
        cls=Command,
    )
    async def dec_create_captcha_image(self, ctx: Context):
        captcha_image, captcha_text = self.bot.captcha.create_captcha_image()
        embed: Embed = await embed_maker.message(
            ctx, title="Captcha Image.", description=f"Text: {captcha_text}"
        )
        embed.set_image(url="attachment://captcha.png")
        return await ctx.channel.send(
            file=File(fp=captcha_image, filename="captcha.png"), embed=embed
        )

    @dev_cmds.command(
        help="Add or remove an operator to an operator list. This will allow member on the op list to become operators when they join Gateway Guilds. Affording them admin access on the guild.",
        name="op",
        usage="captcha dev op TheMasteredPanda",
        examples=["captcha dev op TheMasteredPanda"],
        cls=Command,
    )
    async def dev_operator(self, ctx: Context, member_string: str = None):
        if member_string is None:
            return await embed_maker.command_error(ctx)

        member, ignore = await get_member_from_string(ctx, member_string)
        if member is None:
            return await embed_maker.message(
                ctx,
                description=f"Couldn't find member {member_string}",
                title="Couldn't find Member",
                send=True,
            )

        was_op = member.id in self.bot.captcha.get_operators()
        print(f"Id to set: {member.id}.")
        self.bot.captcha.set_operator(member.id)

        if was_op is False:
            await embed_maker.message(
                ctx,
                description=f"Added {member.name} to the Operators list.",
                title="Added Operator.",
                send=True,
            )
        else:
            await embed_maker.message(
                ctx,
                description=f"Removed {member.name} from the Operators list",
                title="Removed Operator.",
                send=True,
            )


def setup(bot: TLDR):
    bot.add_cog(Captcha(bot))
