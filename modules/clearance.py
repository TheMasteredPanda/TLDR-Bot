import discord
import config

from typing import Callable


class Clearance:
    def __init__(self, bot):
        self.bot = bot

        # raw data from the excel spreadsheet
        self.groups = {}
        self.roles = {}
        self.command_access = {}
        self.channel_perm_levels = {}
        self.channel_access = {}
        self.channel_defaults = {}

        self.bot.logger.debug(f'Downloading clearance spreadsheet')
        self.clearance_spreadsheet = self.bot.google_drive.download_spreadsheet(config.CLEARANCE_SPREADSHEET_ID)
        self.spreadsheet_link = f'https://docs.google.com/spreadsheets/d/{config.CLEARANCE_SPREADSHEET_ID}'
        self.bot.logger.debug(f'Clearance spreadsheet has been downloaded')
        self.bot.logger.info(f'Clearance module has been initiated')

    @staticmethod
    def split_comma(value: str, *, value_type: Callable = str):
        """Split string of comma separated values into a list."""
        return [value_type(v.strip()) for v in value.split(', ') if v and v.strip() and value_type(v.strip())]

    async def parse_clearance_spreadsheet(self):
        """Function for parsing the clearance spreadsheet and sorting the values in it."""
        guild: discord.Guild = self.bot.get_guild(config.MAIN_SERVER)
        await self.parse_roles(guild)
        await self.parse_groups()

        await self.parse_commands()

        await self.parse_channel_perm_levels()
        await self.parse_channels(guild)

    async def parse_roles(self, guild: discord.Guild):
        # ignore the first 2 rows cause they are for users viewing/editing the spreadsheet
        for row in self.clearance_spreadsheet['Roles'][1:]:
            if not row:
                break

            role_name = row[0]
            # ignore the default user
            if role_name == 'User':
                guild = self.bot.get_guild(config.MAIN_SERVER)
                self.roles['User'] = guild.default_role.id
                continue

            role_id = next((int(value) for value in row[1:] if value.isdigit()), None)

            role = discord.utils.find(lambda role: role.id == role_id, guild.roles)
            if not role:
                error = f'Invalid Role [{role_name}] in the clearance spreadsheet: https://docs.google.com/spreadsheets/d/{config.CLEARANCE_SPREADSHEET_ID}'
                return await self.bot.critical_error(error)

            self.roles[role_name] = role_id

    async def parse_groups(self):
        for row in self.clearance_spreadsheet['Role Groups'][1:]:
            group_name = row[0]
            roles = row[1]

            split_roles = self.split_comma(roles)
            for role_name in split_roles:
                if role_name not in self.roles:
                    error = f'Invalid role [{role_name}] in group [{group_name}] in clearance spreadsheet: https://docs.google.com/spreadsheets/d/{config.CLEARANCE_SPREADSHEET_ID}'
                    return await self.bot.critical_error(error)

            self.groups[group_name] = split_roles

    def permissions_addition(self, permissions: str, allow_deny: str, channel_type: str):
        split = permissions.split('+')
        if len(split) == 1:
            return self.split_comma(permissions)

        base_permissions_level = split[0].strip()
        base_permissions = self.channel_perm_levels[base_permissions_level][allow_deny][channel_type]
        permissions_split = self.split_comma(split[1])
        return base_permissions + permissions_split

    async def parse_channel_perm_levels(self):
        for row in self.clearance_spreadsheet['Channel Perm Levels'][1:]:
            if not row:
                continue

            permission_level = row[0]
            if permission_level == 'Rules:':
                break

            text_allow = self.permissions_addition(row[1], 'allow', 'text') if len(row) > 1 else []
            voice_allow = self.permissions_addition(row[2], 'allow', 'voice') if len(row) > 2 else []
            text_deny = self.permissions_addition(row[4], 'deny', 'text') if len(row) > 4 else []
            voice_deny = self.permissions_addition(row[5], 'deny', 'voice') if len(row) > 5 else []

            for permission in text_allow + voice_allow + text_deny + voice_deny:
                if permission not in [*discord.Permissions.VALID_FLAGS.keys()]:
                    error = f'Invalid permission [{permission}] in level [{permission_level}] in clearance spreadsheet: {self.spreadsheet_link}'
                    return await self.bot.critical_error(error)

            self.channel_perm_levels[permission_level] = {
                'allow': {
                    'text': text_allow,
                    'voice': voice_allow
                },
                'deny': {
                    'text': text_deny,
                    'voice': voice_deny
                }
            }

    async def parse_channels(self, guild: discord.Guild):
        for row in self.clearance_spreadsheet['Channels'][1:]:
            if not row:
                continue

            channel_name = row[0]
            channel_id = row[1]

            if channel_id:
                guild_channel = guild.get_channel(int(channel_id))
                if not guild_channel:
                    error = f'Invalid channel [{channel_name}] in clearance spreadsheet: {self.spreadsheet_link}'
                    return await self.bot.critical_error(error)

            groups = self.split_comma(row[3]) if len(row) > 3 else []
            roles = self.split_comma(row[4]) if len(row) > 4 else []
            users = self.split_comma(row[5]) if len(row) > 5 else []

            if channel_name == 'Defaults':
                self.channel_defaults = {
                    'groups': groups,
                    'roles': roles,
                    'users': users,
                }
                continue

            p_leveling = bool(row[6]) if len(row) > 6 else False
            h_leveling = bool(row[7]) if len(row) > 7 else False

            self.channel_access[int(channel_id)] = {
                'groups': groups,
                'roles': roles,
                'users': users,
                'p_leveling': p_leveling,
                'h_leveling': h_leveling
            }

    async def parse_commands(self):
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

    async def refresh_data(self):
        """Refreshes data from the spreadsheet"""
        self.bot.logger.debug(f'Refreshing clearance spreadsheet')
        self.clearance_spreadsheet = self.bot.google_drive.download_spreadsheet(config.CLEARANCE_SPREADSHEET_ID)
        await self.parse_clearance_spreadsheet()
