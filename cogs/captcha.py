from bson import json_util
import json
from typing import Union
from bot import TLDR
from modules import commands, embed_maker, captcha
from discord.ext.commands import Cog, command, group, Context
from discord.guild import Guild
from modules.commands import Command, Group
from modules.utils import ParseArgs
from modules.captcha import GatewayGuild


class Captcha(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

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


def setup(bot: TLDR):
    bot.add_cog(Captcha(bot))
