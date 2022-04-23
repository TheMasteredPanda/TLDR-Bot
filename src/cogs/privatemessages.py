from datetime import date, datetime

import config
import discord
from discord.ext.commands import Cog, Context, command
from modules import commands, database, embed_maker
from modules.utils import get_member

db = database.get_connection()

# TODO: command to check how much time until mute ends


class PrivateMessages(Cog):
    def __init__(self, bot):
        self.bot = bot
        # when get __getattribute__ is called, instead of people needing to call pm_help, they can call help
        self.help = self.pm_help
        self.commands = ["help", "report_issue", "open_ticket"]

    async def process_pm(self, ctx):
        cmd, args = self.parse_msg(ctx)
        try:
            called_cmd = self.__getattribute__(cmd)
            return await called_cmd(ctx, args)
        except AttributeError as e:
            if ctx.message.content.startswith(config.PREFIX):
                return await self.pm_help(ctx, args)

    @staticmethod
    def parse_msg(ctx: Context):
        content = ctx.message.content
        content_list = content.split(" ")

        cmd = content_list[0].replace(config.PREFIX, "")
        args = " ".join(content_list[1:])

        return cmd, args

    @command(
        dm_only=True,
        help="get some pm help smh. Displays all pm commands or info about a specific pm command",
        usage="pm_help (command)",
        examples=["pm_help", "pm_help report"],
        cls=commands.Command,
    )
    async def pm_help(self, ctx: Context, help_cmd: str = None):
        main_guild: discord.Guild = self.bot.get_guild(config.MAIN_SERVER)
        member = main_guild.get_member(ctx.author.id)

        embed_colour = config.EMBED_COLOUR
        all_commands = self.commands

        # Check if user wants to know about a specific command
        if not help_cmd:
            # Returns list of all pm commands
            embed = discord.Embed(
                colour=embed_colour,
                timestamp=datetime.now(),
                description=f"**Prefix** : `{config.PREFIX}`\n"
                f"For additional info on a command, type `{config.PREFIX}help [command]`",
            )
            embed.set_author(name=f"Help", icon_url=self.bot.user.display_avatar.url)
            embed.set_footer(
                text=f"{ctx.author}", icon_url=ctx.author.display_avatar.url
            )
            embed.add_field(
                name=f">Pm Commands",
                value=r" \| ".join(f"`{cmd}`" for cmd in all_commands),
                inline=False,
            )

            return await ctx.author.send(embed=embed)
        else:
            if help_cmd in all_commands:
                cmd = getattr(self, help_cmd)
                cmd_help = cmd.get_help(member)
                examples = f" | ".join(cmd_help.examples)
                cmd_help = f"""
                        **Description:** {cmd_help.help}
                        **Usage:** {cmd_help.usage}
                        **Examples:** {examples}
                        """
                embed = discord.Embed(
                    colour=embed_colour, timestamp=datetime.now(), description=cmd_help
                )
                embed.set_author(
                    name=f"Help - {cmd.name}", icon_url=self.bot.user.display_avatar.url
                )
                embed.set_footer(
                    text=f"{ctx.author}", icon_url=ctx.author.display_avatar.url
                )
                return await ctx.author.send(embed=embed)
            else:
                embed = discord.Embed(
                    colour=embed_colour,
                    timestamp=datetime.now(),
                    description=f"{help_cmd} is not a valid command",
                )
                return await ctx.author.send(embed=embed)

    async def _open_ticket(self, ctx: Context, issue: str = None):
        if not issue:
            command = ctx.command
            examples_str = "\n".join(command.docs.examples)
            description = f"**Description:** {command.docs.docs}\n**Usage:** {command.usage}\n**Examples:** {examples_str}"
            embed = discord.Embed(
                colour=discord.Colour.orange(),
                description=description,
                title=f">{command.name}",
                timestamp=datetime.now(),
            )
            embed.set_footer(
                text=f"{ctx.author}", icon_url=ctx.author.display_avatar.url
            )
            return await ctx.author.send(embed=embed)

        embed_colour = config.EMBED_COLOUR
        if len(issue) > 1700:
            error_msg = "The issues you typed out were too long, sorry about that, please shorten it and wait for mods to ask for more detail."
            embed = discord.Embed(
                colour=discord.Colour.red(),
                timestamp=datetime.now(),
                description=error_msg,
            )
            embed.set_footer(
                text=f"{ctx.author}", icon_url=ctx.author.display_avatar.url
            )
            return await ctx.author.send(embed=embed)

        main_guild = self.bot.get_guild(config.MAIN_SERVER)
        ticket_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
        ticket_embed.set_footer(text=ctx.author, icon_url=ctx.author.display_avatar.url)
        ticket_embed.set_author(
            name="New Ticket - Reported Issue(s)", icon_url=main_guild.icon.url
        )
        ticket_embed.add_field(
            name=">Reporter", value=f"<@{ctx.author.id}>", inline=False
        )
        ticket_embed.add_field(name=">Issue(s)", value=issue, inline=False)

        # send images sent by user
        files = []
        content = ""
        for a in ctx.message.attachments:
            files.append(await a.to_file())
            content = "Attachments:\n"

        return await self.send_ticket_embed(
            ctx, main_guild, ticket_embed, content=content, files=files
        )

    @command(
        dm_only=True,
        help="Report an issue you have with the server or with a user",
        usage="report_issue [issue]",
        examples=["report_issue member hattyot is breaking cg1"],
        cls=commands.Command,
    )
    async def report_issue(self, ctx: Context, issue: str = None, _=None):
        if not issue:
            return await embed_maker.command_error(ctx)

        return await self._open_ticket(ctx, issue)

    @command(
        dm_only=True,
        help="Open a ticket and forward it to the mods.",
        usage="open_ticket [issue]",
        examples=["open_ticket member hattyot is breaking cg 1.1"],
        cls=commands.Command,
    )
    async def open_ticket(self, ctx: Context, issue: str = None, _=None):
        if not issue:
            return await embed_maker.command_error(ctx)

        return await self._open_ticket(ctx, issue)

    @staticmethod
    async def send_ticket_embed(
        ctx: Context,
        guild: discord.Guild,
        embed: discord.Embed,
        content: str = None,
        files: list = None,
    ):
        ticket_category = discord.utils.find(
            lambda c: c.name == "Open Tickets", guild.categories
        )

        if ticket_category is None:
            # get all staff roles
            staff_roles = filter(lambda r: r.permissions.manage_messages, guild.roles)

            # staff roles can read channels in category, users cant
            overwrites = dict.fromkeys(
                staff_roles,
                discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, read_message_history=True
                ),
            )
            overwrites[guild.default_role] = discord.PermissionOverwrite(
                read_messages=False
            )

            ticket_category = await guild.create_category(
                name="Open Tickets", overwrites=overwrites
            )

        today = date.today()
        date_str = today.strftime("%Y-%m-%d")
        ticket_channel = await guild.create_text_channel(
            f"{date_str}-{ctx.author.name}", category=ticket_category
        )
        await ticket_channel.send(embed=embed, content=content, files=files)

        msg = "This issue has been forwarded to the moderators"
        embed = discord.Embed(
            colour=discord.Colour.green(), timestamp=datetime.now(), description=msg
        )
        embed.set_footer(text=f"{ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.author.send(embed=embed)

        # adds to tickets document
        ticket_doc = {
            "guild_id": guild.id,
            "ticket_channel_id": ticket_channel.id,
            "ticket_author_id": ctx.author.id,
        }
        db.tickets.insert_one(ticket_doc)

    @command(
        help="Closes the current ticket",
        usage="close_ticket",
        examples=["close_ticket"],
        cls=commands.Command,
    )
    async def close_ticket(self, ctx: Context):
        ticket_category = discord.utils.find(
            lambda c: c.name == "Open Tickets", ctx.guild.categories
        )
        if ctx.channel.category == ticket_category:
            await ctx.channel.delete()
            db.tickets.delete_one(
                {"guild_id": ctx.guild.id, "ticket_channel_id": ctx.channel.id}
            )
        else:
            return await embed_maker.error(ctx, "Invalid ticket channel")

    @command(
        help="get user who reported issue into channel",
        usage="get_reporter",
        examples=["get_reporter"],
        cls=commands.Command,
    )
    async def get_reporter(self, ctx: Context):
        ticket_category = discord.utils.find(
            lambda c: c.name == "Open Tickets", ctx.guild.categories
        )
        if ctx.channel.category != ticket_category:
            return await embed_maker.error(ctx, "Invalid ticket channel")

        ticket_data = db.tickets.find_one(
            {"guild_id": ctx.guild.id, "ticket_channel_id": ctx.channel.id}
        )
        if ticket_data is None:
            return await embed_maker.error(ctx, f"This ticket does not have a reporter")

        user_id = int(ticket_data["ticket_author_id"])
        member = await get_member(ctx, user_id)
        if member is None:
            return await embed_maker.error(ctx, f"Reporter has left the server")

        # check if user already has access to channel
        permissions = ctx.channel.permissions_for(member)
        if permissions.read_messages:
            return await embed_maker.error(
                ctx, "User already has access to this channel"
            )

        await ctx.channel.set_permissions(
            member, read_messages=True, send_messages=True, read_message_history=True
        )
        return await ctx.channel.send(f"<@{member.id}>")

    @command(
        help="Give user access to ticket",
        usage="get_user [user]",
        examples=["get_user hattyot"],
        cls=commands.Command,
    )
    async def get_user(self, ctx: Context, *, member: str = None):
        if member is None:
            return await embed_maker.command_error(ctx)

        member = await get_member(ctx, member)
        if type(member) == discord.Message:
            return

        ticket_category = discord.utils.find(
            lambda c: c.name == "Open Tickets", ctx.guild.categories
        )
        if ctx.channel.category != ticket_category:
            return await embed_maker.error(ctx, "Invalid ticket channel")

        # check if user already has access to channel
        permissions = ctx.channel.permissions_for(member)
        if permissions.read_messages:
            return await embed_maker.error(
                ctx, "User already has access to this channel"
            )

        await ctx.channel.set_permissions(
            member, read_messages=True, send_messages=True, read_message_history=True
        )
        return await ctx.channel.send(f"<@{member.id}>")


def setup(bot):
    bot.add_cog(PrivateMessages(bot))
