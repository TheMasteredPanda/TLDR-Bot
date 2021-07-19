import discord
import config
import copy

from discord.ext.commands.core import hooked_wrapped_callback
from modules import database, embed_maker
from typing import Callable, Union

db = database.get_connection()


class Help:
    """
    Class for holding the help data of commands.

    Attributes
    __________
    help: :class:`str`
        The general description of what the command does.
    examples: :class:`list`
        List of examples on how to run/use the command.
    usage: :class:`str`
        Shows different arguments of the commend.
    clearance: :class:`str`
        The clearance level needed for the command.
    dm_only: :class:`bool`
        If True, command can be used in dms.
    command_args: :class:`list`
        List of different arguments that will be used in :class:`modules.utils.ParseArgs`, which when used as a type
        on a command arg, will be called.
        Examples: (("--longform", "-s", str), "Description of the argument")
                  (("--longform", "-s", list), "Description of the argument. Since the type given is list, multiple of the same arg can be given.")
    """

    def __init__(self, **kwargs):
        self.help = kwargs.get('help', '')
        self.examples = kwargs.get('examples', [])
        self.usage = kwargs.get('usage', '')
        self.dm_only = kwargs.get('dm_only', False)
        self.command_args = kwargs.get('command_args', [])
        self.clearance = None


class Command(discord.ext.commands.Command):
    """
    Custom implementation of :class:`discord.ext.commands.Command` so that help data, along with functions associated with that data can be accessed more easily.

    Attributes
    __________
    help: :class:`Help`
        The help data of the command.
    special_help: :class:`bool`
        Only True if command decorator has a clearance :class:`Help` object defined.
        Example: cogs.template_cog line 17
    """

    def __init__(self, func, **kwargs):
        super().__init__(func, **kwargs)
        self.docs = Help(**kwargs)
        self.special_help_group = next((key for key, value in kwargs.items() if type(value) == Help), None)
        self.bot = None
        self.data = {}
        self.initialize_command_data()

    def update_command_data(self, guild_id: int):
        """Update command data."""
        data = db.get_command_data(guild_id, self.name, insert=True)
        self.data = data

    @property
    def disabled(self):
        """Returns True if command has been disabled, otherwise returns False"""
        return self.data['disabled']

    def initialize_command_data(self):
        """Cache all the command_data in self.data"""
        data = db.get_command_data(self.name, insert=True)
        self.data = data

    def access_given(self, member: discord.Member):
        """Return True if member has been given access to command, otherwise return False."""
        command_clearance = self.bot.command_system.command_clearance(self)
        return member.id in command_clearance['users']

    def can_use(self, member: discord.Member):
        """Returns True if member can use command, otherwise return False."""
        command_clearance = self.bot.command_system.command_clearance(self)
        member_clearance = self.bot.command_system.member_clearance(member)
        return self.bot.command_system.member_has_clearance(member_clearance, command_clearance)

    def get_help(self, member: discord.Member = None) -> Help:
        """
        A function to get a user specific help object of a command.
        If command has special_help and user has the required clearance for it, it'll switch out the help values.
        As to not edit the original help object of the command, a copy is made at the beginning.

        Parameters
        ___________
        member: :class:`discord.Member`
            Member to whom the :class:`Help` object will be specified to.

        Returns
        -------
        :class:`Help`
            The default help object if the special help group doesnt exist or user doesnt have clearance for it, otherwise
            the modified help object.
        """
        help_object = copy.copy(self.docs)

        if member is None:
            return help_object

        member_clearance = self.bot.command_system.member_clearance(member)
        if self.special_help_group and self.special_help_group in member_clearance['groups']:
            help_object = self.__original_kwargs__[self.special_help_group]
            help_object.clearance = self.special_help_group
        else:
            help_object.clearance = self.bot.command_system.highest_member_clearance(member_clearance)

        return help_object

    def sub_commands(self):
        """Empty method."""


class Group(discord.ext.commands.Group, Command):
    """Basically the same as :class:`Command`, but it also sub classes :class:`discord.ext.commands.Group`."""
    def __init__(self, func, **kwargs):
        super(Group, self).__init__(func, **kwargs)
        super(Command, self).__init__(func, **kwargs)

    def sub_commands(self):
        """Function for getting all the sub commands of a group command without the aliases."""
        aliases = []
        sub_commands = []
        for command_name, command in self.all_commands.items():
            aliases.append(command.aliases)
            if command_name in aliases:
                continue

            sub_commands.append(command)

        return sub_commands


class CommandSystem:
    def __init__(self, bot):
        self.bot = bot
        self.commands: dict[str, [Union[Command, Group]]] = {}
        self.bot.logger.info('CommandSystem module has been initiated')

    def member_clearance(self, member: discord.Member):
        """
        Returns dict with info about what group user belongs to and what roles they have.

        Parameters
        ----------------
        member: :class:`discord.Member`
            The member.

        Returns
        -------
        :class:`dict`
            Clearance info about the user.
        """
        clearance = {'groups': [], 'roles': ['User'], 'user_id': member.id}
        member_role_ids = [role.id for role in member.roles]

        # assign roles
        for role_name, role_id in self.bot.clearance.roles.items():
            if role_id in member_role_ids:
                clearance['roles'].append(role_name)

                # assign a group in role is in a group
                for group_name, roles in self.bot.clearance.groups.items():
                    if role_name in roles and group_name not in clearance['groups']:
                        clearance['groups'].append(group_name)

        return clearance

    @staticmethod
    def highest_member_clearance(member_clearance: dict):
        """Function that returns the highest group or role user has."""
        highest_group = 'User'
        if member_clearance['groups']:
            if member_clearance['groups'][0] != 'Staff':
                highest_group = member_clearance['groups'][0]
            elif member_clearance['roles']:
                highest_group = member_clearance['roles'][0]

        return highest_group

    def command_clearance(self, command: Union[commands.Group, commands.Command]):
        """
        Return dict with info about what groups, roles and users have access to command.

        Parameters
        ----------------
        command: :class:`Command`
            The Command.

        Returns
        -------
        :class:`dict`
            Clearance info about the command.
        """
        return self.bot.clearance.command_access[command.name]

    @staticmethod
    def member_has_clearance(member_clearance: dict, command_clearance: dict):
        """Function for checking id member clearance and command clearance match"""
        return member_clearance['user_id'] in command_clearance['users'] or \
               bool(set(command_clearance['roles']) & set(member_clearance['roles'])) or \
               bool(set(command_clearance['groups']) & set(member_clearance['groups']))

    def initialize_cog(self, cog):
        """Add all the commands of a cog to the dict of commands."""
        self.bot.logger.info(f'Adding cog {type(cog).__name__} into the CommandSystem')
        for command in cog.__cog_commands__:
            command.bot = self.bot
            self.commands[command.name] = command

        self.bot.logger.debug(f'Added {len(cog.__cog_commands__)} commands')
