from bot import TLDR
from modules import commands, embed_maker, catchpa
from discord.ext.commands import Cog, command, group, Context
from modules.commands import Command, Group


class Catchpa(Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @group(
        help="Catchpa Gateway System. A method of stopping the bot attacks.",
        name="catchpa",
        usage="catchpa [sub command]",
        examples=["catchpa servers"],
        cls=Group,
        invoke_without_command=True,
    )
    async def catchpa_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @catchpa_cmd.group(
        help="For commands relating to creating, deleting, or listing servers.",
        name="servers",
        usage="catchpa servers [sub command]",
        examples=["catchpa servers list"],
        cls=Group,
        invoke_without_command=True,
    )
    async def catchpa_servers_cmd(self, ctx: Context):
        return await embed_maker.command_error(ctx)

    @catchpa_servers_cmd.command(
        help="Lists active gateway servers",
        name="list",
        usage="catchpa servers create",
        examples=["catchpa servers create"],
        cls=Command,
    )
    async def list_servers_cmd(self, ctx: Context):
        bits = []

        for g_guild in self.bot.catchpa_module.get_gateway_guilds():
            g_bits = [f"- **{g_guild.get_name()}", f"**ID:** {g_guild.get_id()}"]
            bits.append("\n".join(g_bits))

        await embed_maker.message(
            ctx=ctx,
            title="Active Gateway Guilds",
            description="\n".join(bits) if len(bits) > 0 else "No Active Guilds.",
            send=True,
        )

    async def create_server_cmd(self, ctx: Context):
        pass


def setup(bot: TLDR):
    bot.add_cog(Catchpa(bot))
