import discord
import re
import dateparser
import datetime
import time
import asyncio
from modules import command, database, embed_maker, format_time
from discord.ext import commands

db = database.Connection()


class Mod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Set up reaction based reminder',
                      usage='react_remind [time before event] [message id of event announcement] [time to event and timzone]',
                      examples=['react_remind 30min 716017189093769237 8pm sunday GMT+1'], clearance='Mod', cls=command.Command)
    async def react_remind(self, ctx, remind_time=None, announcement_id=None, *, to_event=None):
        if remind_time is None:
            return await embed_maker.command_error(ctx)

        parsed_remind_time = format_time.parse(remind_time)
        if parsed_remind_time is None:
            return await embed_maker.command_error(ctx, '[time before event]')

        if announcement_id is None or not announcement_id.isdigit():
            return await embed_maker.command_error(ctx, '[message id of event announcement]')

        announcement_msg = await ctx.channel.fetch_message(int(announcement_id))
        if announcement_msg is None:
            return await embed_maker.command_error(ctx, '[message id of event announcement]')

        if to_event is None:
            return await embed_maker.command_error(ctx, '[time to event]')

        parsed_to_event = dateparser.parse(to_event, settings={'PREFER_DATES_FROM': 'future',
                                                               'RETURN_AS_TIMEZONE_AWARE': True})
        if parsed_to_event is None:
            return await embed_maker.command_error(ctx, '[time to event]')

        time_diff = parsed_to_event - datetime.datetime.now(parsed_to_event.tzinfo)
        time_diff_seconds = round(time_diff.total_seconds())

        msg = f'React with :bell: to get a dm {format_time.seconds(parsed_remind_time)} before the event'
        remind_msg = await embed_maker.message(ctx, msg)
        await remind_msg.add_reaction('🔔')

        utils_cog = self.bot.get_cog('Utils')
        expires = round(time.time()) + time_diff_seconds - parsed_remind_time
        await utils_cog.create_timer(
            expires=expires, guild_id=ctx.guild.id, event='react_remind',
            extras={'message_id': remind_msg.id, 'channel_id': remind_msg.channel.id,
                    'announcement_id': announcement_id, 'remind_time': parsed_remind_time}
        )

    @commands.Cog.listener()
    async def on_react_remind_timer_over(self, timer):
        message_id, channel_id, announcement_id, remind_time = timer['extras'].values()
        guild_id = timer['guild_id']

        guild = self.bot.get_guild(int(guild_id))
        channel = guild.get_channel(int(channel_id))
        message = await channel.fetch_message(int(message_id))

        if message is None:
            return

        reactions = message.reactions
        users = []
        for r in reactions:
            if r.emoji == '🔔':
                users = await r.users().flatten()
                # removes bot from list
                users.pop(0)
                break

        if users:
            asyncio.create_task(self.notify_users(users, remind_time, guild_id, channel_id, announcement_id))

    @staticmethod
    async def notify_users(users, remind_time, guild_id, channel_id, announcement_id):
        for user in users:
            msg = f'In {format_time.seconds(remind_time)}: ' \
                  f'https://discordapp.com/channels/{guild_id}/{channel_id}/{announcement_id}'
            await user.send(msg)
            await asyncio.sleep(0.1)


    @commands.command(help='see what roles are whitelisted for an emote', usage='emote_roles [emote]',
                      examples=['emote_roles :TldrNewsUK:'], clearance='Mod', cls=command.Command)
    async def emote_roles(self, ctx, emote=None):
        if emote is None:
            return await embed_maker.command_error(ctx)

        regex = re.compile(r'<:.*:(\d*)>')
        match = re.findall(regex, emote)
        if not match:
            return await embed_maker.command_error(ctx, '[emote]')
        else:
            emoji = discord.utils.find(lambda e: e.id == int(match[0]), ctx.guild.emojis)

        if emoji.roles:
            embed = embed_maker.message(ctx, f'This emote is restricted to: {", ".join([f"<@&{r.id}>" for r in emoji.roles])}')
            return await ctx.send(embed=embed)
        else:
            embed = embed_maker.message(ctx, 'This emote is available to everyone')
            return await ctx.send(embed=embed)

    @commands.command(help='restrict an emote to specific role(s)', usage='emote_role [action] [emote] [role]',
                      examples=['emote_role add :TldrNewsUK: @Mayor', 'emote_role add :TldrNewsUK: 697184345903071265', 'emote_role remove :TldrNewsUK: Mayor'],
                      clearance='Mod', cls=command.Command)
    async def emote_role(self, ctx, action=None, emote=None, *, role=None):
        if action is None:
            return await embed_maker.command_error(ctx)

        if emote is None:
            return await embed_maker.command_error(ctx, '[emote]')

        regex = re.compile(r'<:.*:(\d*)>')
        match = re.findall(regex, emote)
        if not match:
            return await embed_maker.command_error(ctx, '[emote]')
        else:
            emoji = discord.utils.find(lambda e: e.id == int(match[0]), ctx.guild.emojis)

        if role is None:
            return await embed_maker.command_error(ctx, '[role]')

        if ctx.message.role_mentions:
            role = ctx.message.role_mentions[0]
        elif role.isdigit():
            role = discord.utils.find(lambda rl: rl.id == role, ctx.guild.roles)
        else:
            role = discord.utils.find(lambda rl: rl.name == role, ctx.guild.roles)

        if role is None:
            return await embed_maker.command_error(ctx, '[role]')

        emote_roles = emoji.roles
        if action == 'add':
            emote_roles.append(role)
            await emoji.edit(roles=emote_roles)
            await ctx.guild.fetch_emoji(emoji.id)
            return await embed_maker.message(ctx, f'<@&{role.id}> has been added to whitelisted roles of emote {emote}', colour='green')

        elif action == 'remove':
            for i, r in enumerate(emote_roles):
                if r.id == role.id:
                    emote_roles.pop(i)
                    await emoji.edit(roles=emote_roles)
                    await ctx.guild.fetch_emoji(emoji.id)
                    embed = embed_maker.message(ctx, f'<@&{role.id}> has been removed from whitelisted roles of emote {emote}', colour='green')
                    return await ctx.send(embed=embed)
            else:
                embed = embed_maker.message(ctx, f'<@&{role.id}> is not whitelisted for emote {emote}', colour='red')
                return await ctx.send(embed=embed)
        else:
            return await embed_maker.command_error(ctx, '[action]')


def setup(bot):
    bot.add_cog(Mod(bot))
