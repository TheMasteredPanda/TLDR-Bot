import discord
import config
import modules.utils
import modules.database

from discord.ext import commands

db = modules.database.Connection()


class Help:
    def __init__(self, **kwargs):
        self.help = kwargs.get('help', '')
        self.examples = kwargs.get('examples', [])
        self.usage = kwargs.get('usage', '')
        self.clearance = kwargs.get('clearance', 'User')
        self.sub_commands = kwargs.get('sub_commands', [])
        self.dm_only = kwargs.get('dm_only', False)
        self.parse_args = kwargs.get('parse_args', False)


class Command(commands.Command):
    def __init__(self, func, **kwargs):
        super().__init__(func, **kwargs)
        self.docs = Help(**kwargs)

        self.special_help = False
        for clearance in [*config.CLEARANCE.keys()]:
            if clearance in kwargs:
                self.__setattr__(clearance, kwargs[clearance])
                self.special_help = True
                break

    def get_help(self, member: discord.Member):
        help_object = self.docs
        user_clearance = modules.utils.get_user_clearance(member)
        if self.special_help:
            # if given member has clearance which has special help defined, switch out help for special help
            clearances = [*config.CLEARANCE.keys()]
            for clearance in user_clearance[::-1][:-clearances.index(self.docs.clearance) - 1]:
                if hasattr(self, clearance):
                    help_object = getattr(self, clearance)
                    help_object.clearance = clearance

        command_data = db.get_command_data(member.guild.id, self.name)

        help_object.access_given, help_object.access_taken = self.command_access(member, command_data)
        help_object.can_run = (help_object.clearance in user_clearance or help_object.access_given) and not help_object.access_taken
        help_object.disabled = bool(command_data['disabled'])

        return help_object

    @staticmethod
    def command_access(member: discord.Member, command_data: dict):
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
    def __init__(self, func, **kwargs):
        super(Group, self).__init__(func, **kwargs)
        super(Command, self).__init__(func, **kwargs)