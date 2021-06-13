import discord
import time
import functools
import math
import datetime

from modules import cls, embed_maker, format_time, reaction_menus, database, utils
from discord.ext import commands
from bot import TLDR


db = database.get_connection()


class Moderation(commands.Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @staticmethod
    async def construct_cases_embed(ctx: commands.Context, member: discord.Member, cases: dict, case_type: str, max_page_num: int, page_size_limit: int, *, page: int):
        thirty_days_ago = time.time() - (30 * 24 * 60)
        # cases in the past 30 days
        cases_30_days = [*filter(lambda case: case.created_at > thirty_days_ago, cases)]

        description = f'**Total:** `{len(cases)}`\n' \
                      f'**In the pas 30 days:** `{len(cases_30_days)}`\n\n'

        if len(cases) > 0:
            for i, case in enumerate(cases[page_size_limit * (page - 1):page_size_limit * page]):
                # limit it to 5 per page
                if i == page_size_limit:
                    break

                reason = case.reason
                # if reason is too long, cut it off
                if len(reason) > 300:
                    reason = reason[:300] + '...'

                type_str = f'**Type:** {case.type}\n' if not case_type else ''
                duration_str = f'**Duration:** {format_time.seconds(case.extra["duration"])}\n' if case.type == 'mute' else ''
                description += f'**#{page_size_limit * (page - 1) + i + 1}**\n' \
                               f'`{datetime.datetime.fromtimestamp(case.created_at).strftime("%Y/%m/%d - %H:%M:%S")}`\n' \
                               f'`{format_time.seconds(round(time.time()) - case.created_at, accuracy=3)} Ago`\n' \
                               f'{type_str}' \
                               f'{duration_str}' \
                               f'**By:** <@{case.moderator_id}>\n' \
                               f'**Reason:** {reason}\n\n'
        else:
            description = f'This user has no {case_type}s'

        name_switch = {
            'warn': 'Warnings',
            'mute': 'Mutes',
            'ban': 'Bans'
        }

        return await embed_maker.message(
            ctx,
            description=description,
            author={'name': f'{name_switch.get(case_type, "Cases")} - {member}'},
            footer={'text': f'Page {page}/{max_page_num}'}
        )

    async def cases_menu(self, ctx: commands.Context, member: discord.Member, case_type: str, page: int = 1):
        member_cases = self.bot.moderation.cases.get_cases(ctx.guild.id, member_id=member.id, type=case_type)

        page_size_limit = 5
        max_page_num = math.ceil(len(member_cases) / page_size_limit)
        if max_page_num == 0:
            max_page_num = 1

        if page > max_page_num:
            return await embed_maker.error(ctx, 'Exceeded maximum page number')

        page_constructor = functools.partial(
            self.construct_cases_embed,
            ctx,
            member,
            member_cases,
            case_type,
            max_page_num,
            page_size_limit
        )

        embed = await page_constructor(page=page)
        cc_message = await ctx.send(embed=embed)

        menu = reaction_menus.BookMenu(
            cc_message,
            author=ctx.author,
            page=page,
            max_page_num=max_page_num,
            page_constructor=page_constructor,
        )

        self.bot.reaction_menus.add(menu)

    @commands.command(
        help='See the cases (warn/mute/ban) issued to a user',
        usage='cases [member] [case type] (page)',
        examples=['cases hattyot warn', 'warns hattyot ban 2'],
        aliases=['case'],
        clearance='Mod',
        cls=cls.Command
    )
    async def cases(self, ctx: commands.Context, member_and_case_type: str = None):
        if member_and_case_type is None:
            return await embed_maker.command_error(ctx)

        member, case_type = await utils.get_member_from_string(ctx, member_and_case_type)

        # get page number, if any has been provided
        split_member = case_type.split()
        if len(split_member) > 1:
            case_type = ' '.join(split_member[:-1])

            page = split_member[-1]
            if not page.isdigit():
                page = 1
            else:
                page = int(page)
        else:
            page = 1

        if type(member) == discord.Message:
            return

        return await self.cases_menu(ctx, member, case_type, page)

    @commands.command(
        help='Give a member a warning',
        usage='warn [member] [reason]',
        examples=['warn hattyot broke cg 10 several times'],
        aliases=['warning'],
        clearance='Mod',
        cls=cls.Command
    )
    async def warn(self, ctx: commands.Context, *, member_and_reason: str = None):
        if member_and_reason is None:
            return await embed_maker.command_error(ctx)

        member, reason = await utils.get_member_from_string(ctx, member_and_reason)

        if member is None:
            return await embed_maker.error(ctx, 'Unable to find member.')

        if reason is None:
            return await embed_maker.error(ctx, 'You need to give a reason for the warning.')

        if member.bot:
            return await embed_maker.error(ctx, 'You can\'t give a warning to a bot. Bots are good lads')

        if member.id == ctx.author.id:
            return await embed_maker.error(ctx, 'You can\'t warn yourself.')

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(ctx, 'You can\'t warn a member who has a role that is equal or higher than yours.')

        # send user message that they have been warned
        text = f"**{ctx.guild.name}** - You have been warned.:warning:\n**Reason**: {reason}"
        await member.send(text)

        # confirm that user has been warned
        thirty_days_ago = time.time() - (30 * 24 * 60)
        user_warns = self.bot.moderation.cases.get_cases(ctx.guild.id, member_id=member.id, type='warn', after=thirty_days_ago)
        await embed_maker.message(
            ctx,
            description=f'{member.mention} has been warned\n'
                        f'They now have {len(user_warns) + 1} warning{"s" if len(user_warns) != 0 else ""} in the last 30 days.',
            colour='green',
            send=True
        )

        # add case to the database
        self.bot.moderation.cases.add_case(ctx.guild.id, 'warn', reason, member, ctx.author)

    @commands.command(
        help='Unmute a member',
        usage='unmute [member] [reason]',
        examples=['unmute hattyot accidental mute'],
        clearance='Dev',
        cls=cls.Command
    )
    async def unmute(self, ctx: commands.Context, *, member_and_reason: str = None):
        if member_and_reason is None:
            return await embed_maker.command_error(ctx)

        guild_settings = db.get_guild_settings(ctx.guild.id)
        if guild_settings['mute_role_id'] is None:
            return await embed_maker.message(
                ctx,
                description=f'The mute role has not been set yet.\nYou can set it with `{ctx.prefix}setmuterole [role]`',
                colour='orange',
                send=True
            )

        member, reason = await utils.get_member_from_string(ctx, member_and_reason)

        if member is None:
            return await embed_maker.error(ctx, 'Unable to find member.')

        if reason is None:
            return await embed_maker.error(ctx, 'You need to give a reason for the unmute.')

        if member.bot:
            return await embed_maker.error(ctx, 'You can\'t unmute a bot, they can\'t even be muted smh.')

        if member.id == ctx.author.id:
            return await embed_maker.error(ctx, 'You can\'t unmute yourself, how did you even send this message.')

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(ctx, 'You can\'t unmute a member who has a role that is equal or higher than yours.')

        mute_timer = db.timers.find_one({'guild_id': ctx.guild.id, 'event': 'automatic_unmute', 'extras': {'member_id': member.id}})
        if not mute_timer:
            return await embed_maker.message(
                ctx,
                description=f'<@{member.id}> is not muted.',
                colour='orange',
                send=True
            )

        await self.unmute_user(ctx.guild.id, member.id, reason)

        time_left = mute_timer['expires'] - round(time.time())
        return await embed_maker.message(
            ctx,
            description=f'<@{member.id}> has been unmuted.\n**Reason**: {reason}Their mute had **{format_time.seconds(time_left)}** left.\n',
            send=True
        )

    @commands.command(
        help='Mute a member',
        usage='mute [member] [duration] [reason]',
        examples=['mute hattyot 7d 5h 10m 50s abused the bot'],
        clearance='Dev',
        cls=cls.Command
    )
    async def mute(self, ctx: commands.Context, *, member_and_duration_and_reason: str = None):
        if member_and_duration_and_reason is None:
            return await embed_maker.command_error(ctx)

        guild_settings = db.get_guild_settings(ctx.guild.id)
        if guild_settings['mute_role_id'] is None:
            return await embed_maker.message(
                ctx,
                description=f'The mute role has not been set yet.\nYou can set it with `{ctx.prefix}setmuterole [role]`',
                colour='orange',
                send=True
            )

        member, duration_and_reason = await utils.get_member_from_string(ctx, member_and_duration_and_reason)
        duration, reason = format_time.parse(duration_and_reason, return_string=True)

        if member is None:
            return await embed_maker.error(ctx, 'Unable to find member.')

        if duration is None:
            return await embed_maker.error(ctx, 'You need to give a duration for the mute')

        if reason is None:
            return await embed_maker.error(ctx, 'You need to give a reason for the mute.')

        if member.bot:
            return await embed_maker.error(ctx, 'You can\'t mute a bot. Bots are good lads')

        if member.id == ctx.author.id:
            return await embed_maker.error(ctx, 'You can\'t mute yourself.')

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(ctx, 'You can\'t mute a member who has a role that is equal or higher than yours.')

        mute_timer = db.timers.find_one({'guild_id': ctx.guild.id, 'event': 'automatic_unmute', 'extras': {'member_id': member.id}})
        if mute_timer:
            time_left = mute_timer['expires'] - round(time.time())
            return await embed_maker.message(
                ctx,
                description=f'<@{member.id}> is already muted.\nTheir mute will expire in: **{format_time.seconds(time_left)}**',
                colour='orange',
                send=True
            )

        # send user message that they have been muted
        text = f"**{ctx.guild.name}** - You have been muted.:mute:\n**Duration**: {format_time.seconds(duration)}\n**Reason**: {reason}"
        try:
            await member.send(text)
        except:
            return await embed_maker.error(ctx, 'Failed to send mute message to user.')

        # confirm that user has been warned
        thirty_days_ago = time.time() - (30 * 24 * 60)
        user_warns = self.bot.moderation.cases.get_cases(ctx.guild.id, member_id=member.id, type='warn', after=thirty_days_ago)
        await embed_maker.message(
            ctx,
            description=f'{member.mention} has been muted for **{format_time.seconds(duration)}**\n'
                        f'**Reason:** {reason}\n'
                        f'They now have **{len(user_warns) + 1}** mute{"s" * (len(user_warns) != 0)} in the last 30 days.',
            colour='green',
            send=True
        )

        # add case to the database
        self.bot.moderation.cases.add_case(ctx.guild.id, 'mute', reason, member, ctx.author, extra={'duration': duration})

        # add mute role to user
        mute_role = await utils.get_guild_role(ctx.guild, str(guild_settings['mute_role_id']))
        if mute_role is None:
            return await embed_maker.error(ctx, 'Current mute role is not valid.')
        else:
            await member.add_roles(mute_role)

        # start automatic unmute timer
        self.bot.timers.create(
            guild_id=ctx.guild.id,
            expires=round(time.time()) + duration,
            event='automatic_unmute',
            extras={
                'member_id': member.id
            }
        )

    async def unmute_user(self, guild_id: int, member_id: int, reason: str):
        guild = self.bot.get_guild(guild_id)
        member = await utils.get_member_by_id(guild, member_id)

        # send user message that they have been unmuted
        text = f"**{guild.name}** - You have been unmuted.:loud_sound:\n**Reason**: {reason}"
        await member.send(text)

        # remove mute role from member
        mute_role_id = db.get_guild_settings(guild_id=guild_id)['mute_role_id']
        if mute_role_id is None:
            return

        mute_role = await utils.get_guild_role(guild, str(mute_role_id))
        if mute_role is None:
            return

        await member.remove_roles(mute_role)

        # remove mute timer
        db.timers.delete_one({'guild_id': guild.id, 'event': 'automatic_unmute', 'extras': {'member_id': member.id}})

    @commands.Cog.listener()
    async def on_automatic_unmute_timer_over(self, timer: dict):
        guild_id = timer['guild_id']
        member_id = timer['extras']['member_id']
        return await self.unmute_user(guild_id, member_id, 'Mute expired.')

    @commands.command(
        help='Ban a member, their leveling data will be erased',
        usage='ban [member] [reason]',
        examples=['ban hattyot completely ignore cg'],
        clearance='Dev',
        cls=cls.Command
    )
    async def ban(self, ctx: commands.Context, *, member_and_reason: str = None):
        if member_and_reason is None:
            return await embed_maker.command_error(ctx)

        member, reason = await utils.get_member_from_string(ctx, member_and_reason)

        if member is None:
            return await embed_maker.error(ctx, 'Unable to find member.')

        if reason is None:
            return await embed_maker.error(ctx, 'You need to give a reason for the ban.')

        if member.bot:
            return await embed_maker.error(ctx, 'You can\'t ban a bot, they do too much work.')

        if member.id == ctx.author.id:
            return await embed_maker.error(ctx, 'You can\'t ban yourself, why would you even try this')

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            return await embed_maker.error(ctx, 'You can\'t ban a member who has a role that is equal or higher than yours.')

        # send user message that they have been warned
        text = f"**{ctx.guild.name}** - You have been banned.\n**Reason**: {reason}"
        try:
            await member.send(text)
        except:
            return await embed_maker.error(ctx, 'Failed to send ban message to user.')

        await ctx.guild.ban(member, reason=reason)
        self.bot.dispatch('ban', member)

        await embed_maker.message(
            ctx,
            description=f'{member.mention} has been banned.\n'
                        f'**Reason:** {reason}',
            colour='green',
            send=True
        )

        # add case to the database
        self.bot.moderation.cases.add_case(ctx.guild.id, 'ban', reason, member, ctx.author)


def setup(bot: TLDR):
    bot.add_cog(Moderation(bot))
