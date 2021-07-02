import discord
import config

from copy import copy
from typing import Union


class Channels:
    def __init__(self, bot):
        self.bot = bot

    def get_channel_access(self, channel):
        if channel.id not in self.bot.clearance.channel_access:
            if channel.category_id not in self.bot.clearance.channel_access:
                return
            else:
                return self.bot.clearance.channel_access[channel.category_id]
        else:
            return self.bot.clearance.channel_access[channel.id]

    def p_leveling(self, channel):
        channel_access = self.get_channel_access(channel)
        return channel_access and channel_access['p_leveling']

    def h_leveling(self, channel):
        channel_access = self.get_channel_access(channel)
        return channel_access and channel_access['h_leveling']

    def compile_discord_permissions(self, level, channel, allow_deny):
        permissions = self.bot.clearance.channel_perm_levels[level]
        perm_list = []
        if type(channel) == discord.TextChannel:
            perm_list = [permission for permission in permissions[allow_deny]['text']]
        if type(channel) == discord.VoiceChannel or type(channel) == discord.StageChannel:
            perm_list = [permission for permission in permissions[allow_deny]['text'] if type(channel) == discord.StageChannel or type(channel) == discord.VoiceChannel and permission != 'request_to_speak']
        if type(channel) == discord.CategoryChannel:
            perm_list = [permission for permission in permissions[allow_deny]['text'] + permissions[allow_deny]['voice']]

        return perm_list

    def permission_split(self, string: str):
        split = string.split(':')
        if len(split) == 2:
            name, allow, deny = split[0], split[1], '-1'
        else:
            name, allow, deny = split

        return name, allow, deny

    async def level_validity(self, channel, level: str, name: str):
        if level not in self.bot.clearance.channel_perm_levels:
            error_text = f'Invalid level [{level}] given to [{name}] for channel [{channel.name}] to [{name}]'
            return await self.bot.critical_error(error_text)

        return True

    async def level_to_permissions(self, levels: str, channel, name: str, allow_deny: str):
        split_level = levels.split(',')
        permissions = []
        for split in split_level:
            split = split.strip()
            if split == '-1':
                continue

            if split.isdigit():
                is_valid = await self.level_validity(channel, split, name)
                if not is_valid:
                    return
                channel_permissions = self.compile_discord_permissions(split, channel, allow_deny)
                permissions += channel_permissions
            else:
                if split not in discord.Permissions.VALID_FLAGS:
                    error = f'Invalid permission [{split}] given to channel [{channel.name}]'
                    return await self.bot.critical_error(error)
                permissions.append(split)

        if allow_deny == 'allow':
            return {perm: True for perm in permissions}
        else:
            return {perm: False for perm in permissions}

    async def channel_overwrites(self, channel: Union[discord.CategoryChannel, discord.TextChannel, discord.VoiceChannel, discord.StageChannel]):
        overwrites = {}
        channel_permissions = self.bot.clearance.channel_access[channel.id]

        for group in self.bot.clearance.channel_defaults['groups'] + channel_permissions['groups']:
            group_name, group_allow, group_deny = self.permission_split(group)
            allow = await self.level_to_permissions(group_allow, channel, group_name, 'allow')
            deny = await self.level_to_permissions(group_deny, channel, group_name, 'deny')
            if not allow and not deny:
                return

            for role_name in self.bot.clearance.groups[group_name]:
                role_id = self.bot.clearance.roles[role_name]
                guild_role = channel.guild.get_role(int(role_id))
                allow.update(deny)
                overwrites[guild_role] = discord.PermissionOverwrite(**allow)

        for role in self.bot.clearance.channel_defaults['roles'] + channel_permissions['roles']:
            role_name, role_allow, role_deny = self.permission_split(role)
            allow = await self.level_to_permissions(role_allow, channel, role_name, 'allow')
            deny = await self.level_to_permissions(role_deny, channel, role_name, 'deny')
            if not allow and not deny:
                return

            role_id = self.bot.clearance.roles[role_name]
            guild_role = channel.guild.get_role(int(role_id))
            allow.update(deny)
            overwrites[guild_role] = discord.PermissionOverwrite(**allow)

        for user in self.bot.clearance.channel_defaults['users'] + channel_permissions['users']:
            user_id, user_allow, user_deny = self.permission_split(user)

            allow = await self.level_to_permissions(user_allow, channel, user_id, 'allow')
            deny = await self.level_to_permissions(user_deny, channel, user_id, 'deny')
            if not allow and not deny:
                return

            guild_user = self.bot.get_user(int(user_id))
            allow.update(deny)
            overwrites[guild_user] = discord.PermissionOverwrite(**allow)

        return overwrites

    async def create_new_overwrites(self) -> dict:
        # TODO: dont completely destroy existing overwrites
        guild: discord.Guild = self.bot.get_guild(config.MAIN_SERVER)

        all_overwrites = {}
        for channel in guild.channels:
            if channel.id == 859440103302889474:
                print(channel.name)

            if channel.id not in self.bot.clearance.channel_access and type(channel) != discord.CategoryChannel:
                if channel.category_id is not None and channel.category_id not in self.bot.clearance.channel_access:
                    continue

                if channel.category:
                    if channel.category_id in all_overwrites:
                        all_overwrites[channel.id] = 'sync'
                        continue

                    category_overwrites = await self.channel_overwrites(channel.category)
                    all_overwrites[channel.category] = category_overwrites
                    if category_overwrites == channel.category.overwrites:
                        continue

                    all_overwrites[channel] = 'sync'

            elif channel.id in self.bot.clearance.channel_access:
                channel_overwrites = await self.channel_overwrites(channel)
                if channel.id == 859440103302889474:
                    print(channel_overwrites)
                if channel_overwrites == channel.overwrites:
                    continue
                all_overwrites[channel] = channel_overwrites

        return all_overwrites

    async def check_permissions(self, overwrites):
        """Check if bot has the permissions to edit all the channels."""
        for channel in overwrites:
            bot_permissions = channel.permissions_for(channel.guild.me)
            if not bot_permissions.manage_permissions:
                error = f"Bot does not have permissions to edit channel [{channel.name}] mentioned in spreadsheet."
                return await self.bot.critical_error(error)

        return True

    async def apply_permissions(self):
        new_overwrites = await self.create_new_overwrites()
        no_error = await self.check_permissions(new_overwrites)
        if not no_error:
            return

        for channel, overwrites in new_overwrites.items():
            if overwrites == 'sync':
                await channel.edit(sync_permissions=True)
                continue

            await channel.edit(overwrites=overwrites)
