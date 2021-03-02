import discord
import os
import config
import asyncio
import modules.utils
import modules.cls
import modules.database
import modules.embed_maker
import copy

from typing import Union
from discord.ext import commands

intents = discord.Intents.all()
db = modules.database.Connection()


async def get_prefix(bot, message):
    return commands.when_mentioned_or(config.PREFIX)(bot, message)


class TLDR(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=get_prefix, case_insensitive=True, help_command=None,
            intents=intents, chunk_guilds_at_startup=True
        )

        self.left_check = asyncio.Event()

        # Load Cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                self.load_extension(f'cogs.{filename[:-3]}')
                print(f'{filename[:-3]} is now loaded')

        self.timers = modules.utils.Timers(self)

    def get_command(self, name: str, member: discord.Member = None):
        if ' ' not in name:
            command = self.all_commands.get(name)
        else:
            names = name.split()
            if not names:
                return None

            command = self.all_commands.get(names[0])
            if isinstance(command, discord.ext.commands.GroupMixin):
                for name in names[1:]:
                    try:
                        command = command.all_commands[name]
                    except (AttributeError, KeyError):
                        return None

        # if given member has clearance which has special help defined, switch out help for special help
        if member and command:
            clearances = ['User', 'Mod', 'Admin', 'Dev']
            user_clearance = modules.utils.get_user_clearance(member)
            for clearance in user_clearance[::-1][:-clearances.index(command.clearance) - 1]:
                if hasattr(command, clearance) and clearance in user_clearance:
                    # create copy of command so we're not modifying the original command values
                    command = copy.copy(command)

                    special_help = getattr(command, clearance)
                    command.__dict__.update(**special_help.__dict__)
                    command.clearance = clearance
                    break

        return command

    @staticmethod
    def command_access(member: discord.Member, command_data: dict):
        # user access overwrites role access
        # access taken overwrites access given
        user_access = command_data['user_access']
        role_access = command_data['role_access']

        access_to_command_given = False
        access_to_command_taken = False

        # check user_access
        if user_access:
            access_to_command_given = f'{member.id}' in user_access and user_access[f'{member.id}'] == 'give'
            access_to_command_taken = f'{member.id}' in user_access and user_access[f'{member.id}'] == 'take'

        # check role access
        if role_access:
            role_access_matching_role_ids = set([str(r.id) for r in member.roles]) & set(role_access.keys())
            if role_access_matching_role_ids:
                # sort role by permission
                roles = [member.guild.get_role(int(r_id)) for r_id in role_access_matching_role_ids]
                sorted_roles = sorted(roles, key=lambda r: r.permissions)
                if sorted_roles:
                    role = sorted_roles[-1]
                    access_to_command_given = access_to_command_given or f'{role.id}' in role_access and role_access[f'{role.id}'] == 'give'
                    access_to_command_taken = access_to_command_taken or f'{role.id}' in role_access and role_access[f'{role.id}'] == 'take'

        return access_to_command_given, access_to_command_taken

    def can_run_command(
            self,
            command: Union[commands.Context, modules.cls.Command],
            member: discord.Member = None, *,
            command_data: dict = None,
            extra: bool = False,
    ):
        if type(command) == commands.Context:
            member = command.author
            command = command.command

        if not command_data:
            command_data = db.get_command_data(member.guild.id, command.name)

        access_to_command_given, access_to_command_taken = self.command_access(member, command_data)
        can_run = (command.clearance in modules.utils.get_user_clearance(member) or access_to_command_given) and not access_to_command_taken

        if extra:
            return can_run, access_to_command_given, access_to_command_taken

        return can_run

    async def on_message(self, message: discord.Message):
        await self.wait_until_ready()

        if not self.left_check.is_set():
            return

        # redirect to private messages cog if message was sent in pms
        if message.guild is None:
            pm_cog = self.get_cog('PrivateMessages')
            ctx = await self.get_context(message)
            return await pm_cog.process_pm(ctx)

        # no bots allowed
        if message.author.bot:
            return

        # invoke command if message starts with prefix
        if message.content.startswith(config.PREFIX) and message.content.replace(config.PREFIX, ''):
            return await self.process_command(message)

    async def process_command(self, message: discord.Message):
        ctx = await self.get_context(message)

        try:
            ctx.command = self.get_command(ctx.command.name, ctx.author)
        except AttributeError:
            return

        command_data = db.get_command_data(ctx.guild.id, ctx.command.name)
        if command_data['disabled']:
            return await modules.embed_maker.error(ctx, 'This command has been disabled')

        # return if command doesnt exist, author doesnt have clearance for command, or if command is dm only
        can_run_command, _, access_taken = self.can_run_command(ctx, command_data=command_data, extra=True)
        if can_run_command and access_taken:
            return await modules.embed_maker.error(ctx, f'Your access to this command has been taken away')

        if ctx.command is None or not can_run_command:
            return

        return await self.invoke(ctx)


if __name__ == '__main__':
    TLDR().run(config.BOT_TOKEN)
