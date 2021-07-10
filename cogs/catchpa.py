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


def setup(bot: TLDR):
    bot.add_cog(Catchpa(bot))
