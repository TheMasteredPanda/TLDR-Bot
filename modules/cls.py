import discord
import config
import modules.utils
import modules.database
import copy

from typing import Tuple
from discord.ext import commands

db = modules.database.get_connection()


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
        self.clearance = kwargs.get('clearance', 'User')
        self.dm_only = kwargs.get('dm_only', False)
        self.command_args = kwargs.get('command_args', [])


class Command(commands.Command):
    """
    Custom implementation of :class:`discord.ext.commands.Command` so that help data can be accessed more easily.

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

        self.special_help = False
        for clearance in [*config.CLEARANCE.keys()]:
            if clearance in kwargs:
                self.__setattr__(clearance, kwargs[clearance])
                self.special_help = True
                break

    def get_help(self, member: discord.Member = None) -> Help:
        """
        A function to get a user specific help object of a command.
        Attaches attributes: access_given, access_taken, can_run, disabled.
        If command has special_help and user has the required clearance for it, it'll also switch out the help values.
        As to not edit the original help object of the command, a copy is made at the beginning.

        Parameters
        ___________
        member: :class:`discord.Member`
            Member to whom the :class:`Help` object will be specified to.

        Returns
        -------
        :class:`Help`
            The expanded help object.
        """
        help_object = copy.copy(self.docs)

        if member is None:
            return help_object

        user_clearance = modules.utils.get_user_clearance(member)
        if self.special_help:
            # if given member has clearance which has special help defined, switch out help for special help
            clearances = [*config.CLEARANCE.keys()]
            for clearance in user_clearance[::-1][:-clearances.index(help_object.clearance) - 1]:
                if hasattr(self, clearance):
                    help_object = getattr(self, clearance)
                    help_object.clearance = clearance
                    break

        command_data = db.get_command_data(member.guild.id, self.name)

        help_object.access_given, help_object.access_taken = self.command_access(member, command_data)
        help_object.can_run = (help_object.clearance in user_clearance or help_object.access_given) and not help_object.access_taken
        help_object.disabled = bool(command_data['disabled'])

        return help_object

    @staticmethod
    def command_access(member: discord.Member, command_data: dict) -> Tuple[bool, bool]:
        """
        A function to see if user has either been given access to command or if their access to the command has been taken away,
        either directly from them, or from a role they have

        Parameters
        ___________
        member: :class:`discord.Member`
            The member who will be checked.
        command_data :class:`dict`
            Data on the command that will be checked.

        Returns
        -------
        Tuple[:class:`bool`, :class:`bool`]
            2 bools: access_given and access_taken
        """
        # user access overwrites role access
        # access taken overwrites access given
        user_access = command_data['user_access']
        role_access = command_data['role_access']

        access_given = False
        access_taken = False

        # check user_access
        if user_access:
            access_given = f'{member.id}' in user_access and user_access[f'{member.id}'] == 'give'
            access_taken = f'{member.id}' in user_access and user_access[f'{member.id}'] == 'take'

        # check role access
        if role_access:
            role_access_matching_role_ids = set([str(r.id) for r in member.roles]) & set(role_access.keys())
            if role_access_matching_role_ids:
                # sort role by permission
                roles = [member.guild.get_role(int(r_id)) for r_id in role_access_matching_role_ids]
                sorted_roles = sorted(roles, key=lambda r: r.permissions)
                if sorted_roles:
                    role = sorted_roles[-1]
                    access_given = access_given or f'{role.id}' in role_access and role_access[f'{role.id}'] == 'give'
                    access_taken = access_taken or f'{role.id}' in role_access and role_access[f'{role.id}'] == 'take'

        return access_given, access_taken


class Group(commands.Group, Command):
    """Basically the same as :class:`Command`, but it also sub classes :class:`discord.ext.commands.Group`."""
    def __init__(self, func, **kwargs):
        super(commands.Group, self).__init__(func, **kwargs)
        super(Command, self).__init__(func, **kwargs)
