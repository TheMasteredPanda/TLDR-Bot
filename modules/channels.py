import discord
import config

from typing import Union


class Channels:
    def __init__(self, bot):
        self.bot = bot

        self.default_level = {
            discord.CategoryChannel: '2',
            discord.TextChannel: '2',
            discord.VoiceChannel: '5',
            discord.StageChannel: '5'
        }

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

    def compile_discord_permissions(self, level, channel):
        permissions = self.bot.clearance.channel_perm_levels[level]
        perm_dict = {}
        if level == '0':
            return discord.Permissions(view_channel=False)

        if type(channel) == discord.TextChannel:
            perm_dict = {permission: True for permission in permissions['text']}
        if type(channel) == discord.VoiceChannel or type(channel) == discord.StageChannel:
            perm_dict = {permission: True for permission in permissions['text'] if type(channel) == discord.StageChannel or type(channel) == discord.VoiceChannel and permission != 'request_to_speak'}
        if type(channel) == discord.CategoryChannel:
            perm_dict = {permission: True for permission in permissions['text'] + permissions['voice']}

        return discord.PermissionOverwrite(**perm_dict)

    def permission_split(self, string: str, channel):
        split = string.split(':')
        if len(split) == 1:
            name, level = split[0], self.default_level.get(type(channel))
        else:
            name, level = split

        return name, level

    async def level_validity(self, channel, level: str, name: str):
        if level not in self.bot.clearance.channel_perm_levels:
            error_text = f'Invalid level [{level}] given to [{name}] for channel [{channel.name}]'
            return await self.bot.critical_error(error_text)

        text_error = type(channel) == discord.TextChannel and level == '4'
        if text_error:
            error_text = f'Invalid level [{level}] given for channel [{channel.name}] with [{name}:{level}]'
            return await self.bot.critical_error(error_text)

    async def create_overwrites(self, channel: Union[discord.CategoryChannel, discord.TextChannel, discord.VoiceChannel, discord.StageChannel]):
        overwrites = {}
        channel_permissions = self.bot.clearance.channel_access[channel.id]

        for group in channel_permissions['groups']:
            group_name, group_level = self.permission_split(group, channel)
            await self.level_validity(channel, group_level, group_name)

            for role_name in self.bot.clearance.groups[group_name]:
                role_id = self.bot.clearance.roles[role_name]
                guild_role = channel.guild.get_role(int(role_id))
                overwrites[guild_role] = self.compile_discord_permissions(group_level, channel)

        for role in channel_permissions['roles']:
            role_name, role_level = self.permission_split(role, channel)
            await self.level_validity(channel, role_level, role_name)

            role_id = self.bot.clearance.roles[role_name]
            guild_role = channel.guild.get_role(int(role_id))
            overwrites[guild_role] = self.compile_discord_permissions(role_level, channel)

        for user in channel_permissions['users']:
            user_id, user_level = self.permission_split(user, channel)
            await self.level_validity(channel, user_level, user_id)

            guild_user = self.bot.get_user(int(user_id))
            overwrites[guild_user] = self.compile_discord_permissions(user_level, channel)

        return overwrites

    async def apply_permissions(self):
        guild: discord.Guild = self.bot.get_guild(config.MAIN_SERVER)

        for channel in guild.channels:
            if channel.id not in self.bot.clearance.channel_access and type(channel) != discord.CategoryChannel:
                if channel.category_id is not None and channel.category_id not in self.bot.clearance.channel_access:
                    continue

                if channel.category:
                    category_overwrites = await self.create_overwrites(channel.category)
                    if category_overwrites == channel.category.overwrites:
                        continue
                    await channel.edit(overwrites=category_overwrites)

            elif channel.id in self.bot.clearance.channel_access:
                channel_overwrites = await self.create_overwrites(channel)
                if channel_overwrites == channel.overwrites:
                    continue
                await channel.edit(overwrites=channel_overwrites)
