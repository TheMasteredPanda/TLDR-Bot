import discord
import config
import copy

from discord.ext import commands
from modules import database
from typing import Callable, Union

db = database.get_connection()


class Clearance:
    def __init__(self, bot):
        self.bot = bot

        # raw data from the excel spreadsheet
        self.groups = {}
        self.roles = {}
        self.command_access = {}

        self.bot.logger.debug(f'Downloading clearance spreadsheet')
        self.clearance_spreadsheet = self.bot.google_drive.download_spreadsheet(config.CLEARANCE_SPREADSHEET_ID)
        self.spreadsheet_link = f'https://docs.google.com/spreadsheets/d/{config.CLEARANCE_SPREADSHEET_ID}'
        self.bot.logger.debug(f'Clearance spreadsheet has been downloaded')
        self.bot.logger.info(f'Clearance module has been initiated')

    @staticmethod
    def split_comma(value: str, *, value_type: Callable = str):
        """Split string of comma separated values into a list."""
        return [value_type(v.strip()) for v in value.split(',') if v and v.strip() and value_type(v.strip())]

    async def parse_clearance_spreadsheet(self):
        """Function for parsing the clearance spreadsheet and sorting the values in it."""
        guild: discord.Guild = self.bot.get_guild(config.MAIN_SERVER)
        guild_roles = [525670590997331968, 853245179451801620, 832560628715225090, 809108388419207240, 809845377783169106, 762300271652372500, 762300212165214278, 762300157932470295, 762300109231751169, 754769152656277543, 737412661049819206, 735180544232521798, 843222522551205909, 700084296781922376, 696358506403594360, 697793877049868308, 685432173234356224, 685432395712692234, 685432115051102208, 685431871131222025, 685216316977578044, 697184342614474785, 697184343663312936, 697184344501911602, 689958081920237698, 697184345353617520, 697184345903071265, 697184346670628936, 697184347710685224, 697184348465791025, 697184349379887264, 697184350399365180, 697184351632228424, 798902000300720128, 798902039148232774, 798902068768145471, 697194468117577859, 697194579321028639, 697194631179403344, 697194824906047519, 697194892232884395, 697194958742093844, 769688080595943474, 697194997719498857, 769688323740270642, 769687602600869899, 769686764524011592, 769686973224845372, 769687345947344936, 646726492281110529, 644182117051400220, 662036345526419486, 644181559548706836, 685207680826081318, 685207974309789708, 843221333877850162, 843220709319901214, 756231512307007520, 685230896466755585, 843208854895722566, 810787506022121533, 843208012198051901, 685260904828633159, 772529489681842176, 692460423076773898, 703264202063872040, 663009650815533087, 662033657950896139, 697179706994327552, 693520575435374629, 725429090965913670, 658274389971697675, 698274709170815099, 837346636350357524, 843235332837474344, 728664009414279190, 525723610674102322]
        # parse roles
        # ignore the first 2 rows cause they are for users viewing/editing the spreadsheet
        for row in self.clearance_spreadsheet['Roles'][1:]:
            if not row:
                break

            role_name = row[0]
            # ignore the default user
            if role_name == 'User':
                continue

            role_id = next((int(value) for value in row[1:] if value.isdigit()), None)

            role = discord.utils.find(lambda role: role == role_id, guild_roles)
            if not role:
                error = f'Invalid Role [{role_name}] in the clearance spreadsheet: https://docs.google.com/spreadsheets/d/{config.CLEARANCE_SPREADSHEET_ID}'
                return await self.bot.critical_error(error)

            self.roles[role_name] = role_id

        # parse groups
        for row in self.clearance_spreadsheet['Groups'][1:]:
            group_name = row[0]
            roles = row[1]

            split_roles = self.split_comma(roles)
            for role_name in split_roles:
                if role_name not in self.roles:
                    error = f'Invalid role [{role_name}] in group [{group_name}] in clearance spreadsheet: https://docs.google.com/spreadsheets/d/{config.CLEARANCE_SPREADSHEET_ID}'
                    return await self.bot.critical_error(error)

            self.groups[group_name] = split_roles

        # parse commands
        for cog_name in self.bot.cogs:
            cog = self.bot.cogs[cog_name]
            # ignore cogs which dont have any commands like Events
            if not cog.__cog_commands__:
                continue

            if cog_name not in self.clearance_spreadsheet:
                error = f'Cog {cog_name} not in the clearance spreadsheet: https://docs.google.com/spreadsheets/d/{config.CLEARANCE_SPREADSHEET_ID}'
                return await self.bot.critical_error(error)

            for row in self.clearance_spreadsheet[cog_name][1:]:
                command_name = row[0]

                command = self.bot.get_command(command_name)
                if not command:
                    error = f'Invalid command [{command_name}] in clearance spreadsheet: https://docs.google.com/spreadsheets/d/{config.CLEARANCE_SPREADSHEET_ID}'
                    return await self.bot.critical_error(error)

                groups = self.split_comma(row[2]) if len(row) > 2 else []
                roles = self.split_comma(row[3]) if len(row) > 3 else []
                users = self.split_comma(row[4], value_type=int) if len(row) > 4 else []

                self.command_access[command_name] = {
                    'groups': groups,
                    'roles': roles,
                    'users': users
                }

        # check if any commands are missing from the clearance spreadsheet
        for command_name, command in self.bot.command_system.commands.items():
            if command.root_parent is None and command_name not in self.command_access:
                error = f'Command [{command_name}] missing from clearance spreadsheet: https://docs.google.com/spreadsheets/d/{config.CLEARANCE_SPREADSHEET_ID}'
                return await self.bot.critical_error(error)

            if command.root_parent is None:
                continue

            if command.root_parent != command and command.root_parent.name not in self.command_access:
                error = f'Command [{command.root_parent.name}] missing from clearance spreadsheet: https://docs.google.com/spreadsheets/d/{config.CLEARANCE_SPREADSHEET_ID}'
                return await self.bot.critical_error(error)

            if command.root_parent != command and command_name not in self.command_access and command.root_parent.name in self.command_access:
                self.command_access[command_name] = self.command_access[command.root_parent.name]
                continue

        self.bot.logger.debug(f'Clearance spreadsheet has been parsed')

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
        # member_role_ids = [role.id for role in member.roles]
        member_role_ids = [525670590997331968, 853245179451801620, 685216316977578044, 697184342614474785,
                           697184343663312936,
                           697184344501911602, 689958081920237698, 697184345353617520, 697184345903071265,
                           697184346670628936,
                           697184347710685224, 697194468117577859, 697194579321028639, 697194631179403344,
                           697194824906047519,
                           646726492281110529, 662036345526419486, 685207680826081318, 685230896466755585,
                           843208854895722566, 728664009414279190]

        # assign roles
        for role_name, role_id in self.roles.items():
            if role_id in member_role_ids:
                clearance['roles'].append(role_name)

                # assign a group in role is in a group
                for group_name, roles in self.groups.items():
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

    def command_clearance(self, command: Union['Group', 'Command']):
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
        return self.command_access[command.name]

    @staticmethod
    def member_has_clearance(member_clearance: dict, command_clearance: dict):
        """Function for checking id member clearance and command clearance match"""
        return member_clearance['user_id'] in command_clearance['users'] or \
                set(command_clearance['roles']) & set(member_clearance['roles']) or \
                set(command_clearance['groups']) & set(member_clearance['groups'])

    async def refresh_data(self):
        """Refreshes data from the spreadsheet"""
        self.bot.logger.debug(f'Refreshing clearance spreadsheet')
        self.clearance_spreadsheet = self.bot.google_drive.download_spreadsheet(config.CLEARANCE_SPREADSHEET_ID)
        await self.parse_clearance_spreadsheet()


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
        command_clearance = self.bot.clearance.command_clearance(self)
        return member.id in command_clearance['users']

    def can_use(self, member: discord.Member):
        """Returns True if member can use command, otherwise return False."""
        command_clearance = self.bot.clearance.command_clearance(self)
        member_clearance = self.bot.clearance.member_clearance(member)
        return self.bot.clearance.member_has_clearance(member_clearance, command_clearance)

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

        member_clearance = self.bot.clearance.member_clearance(member)
        if self.special_help_group and self.special_help_group in member_clearance['groups']:
            help_object = self.__original_kwargs__[self.special_help_group]
            help_object.clearance = self.special_help_group
        else:
            command_clearance = self.bot.clearance.command_clearance(self)
            help_object.clearance = self.bot.clearance.highest_member_clearance(member_clearance)

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

    def initialize_cog(self, cog):
        """Add all the commands of a cog to the dict of commands."""
        self.bot.logger.info(f'Adding cog {type(cog).__name__} into the CommandSystem')
        for command in cog.__cog_commands__:
            command.bot = self.bot
            self.commands[command.name] = command

        self.bot.logger.debug(f'Added {len(cog.__cog_commands__)} commands')
