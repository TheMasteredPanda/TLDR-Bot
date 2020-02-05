import discord
import time
import re
import config
from modules import command, embed_maker, database, format_time
from discord.ext import commands

db = database.Connection()


class Mod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Mute a user', usage='mute [@member] [length] [reason]', examples=['mute @Hattyot 10m breaking community guidelines'], clearance='Mod', cls=command.Command)
    async def mute(self, ctx, member=None, length=None, reason=None):
        if member is None:
            return await embed_maker.command_error(ctx)
        if not ctx.message.mentions:
            return await embed_maker.command_error(ctx, '[@member]')

        member = ctx.message.mentions[0]
        now = round(time.time())
        timer_cog = self.bot.get_cog('Timer')
        user_timer = db.get_user_timer(ctx.guild.id, member.id, 'mute')

        if user_timer:
            time_left = user_timer['expires'] - now
            embed = embed_maker.message(ctx, f'That user is already muted. They will be unmuted in {format_time.seconds(time_left)}', colour='red')
            return await ctx.send(embed=embed)

        parsed_length = format_time.parse(length)
        if parsed_length is None:
            return await embed_maker.command_error(ctx, '[length]')
        if parsed_length < 60:
            embed = embed_maker.message(ctx, 'Mute time can\'t be less than one minute', colour='red')
            return await ctx.send(embed=embed)

        end_time = now + parsed_length

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            embed = embed_maker.message(ctx, 'Can\'t mute a member who has a role that is equal or higher than yours.', colour='red')
            return await ctx.send(embed=embed)
        if ctx.guild.me.roles[-1].position <= member.roles[-1].position:
            embed = embed_maker.message(ctx, 'That person is higher up than I am, I can\'t mute them.', colour='red')
            return await ctx.send(embed=embed)

        if reason is None:
            embed = embed_maker.message(ctx, 'You need to give a reason for the mute', colour='red')
            return await ctx.send(embed=embed)

        mute_role_id = db.get_server_options(ctx.guild.id, 'mute_role')
        if not mute_role_id:
            # check for mute role
            regex = re.compile(r'mute')
            mute_role = discord.utils.find(lambda r: re.match(regex, r.name.lower()), ctx.guild.roles)
            if mute_role:
                db.server_options.update_one({'guild_id': ctx.guild.id}, {'$set': {'mute_role': mute_role.id}})
                db.get_server_options.invalidate(ctx.guild.id, 'mute_role')
            else:
                embed = embed_maker.message(ctx, f'You don\'t have a mute role set and i couldn\'t find one.\nPlease make one and set it with `{config.DEFAULT_PREFIX}mute_role [role id]`', colour='red ')
                return await ctx.send(embed=embed)
        else:
            mute_role = ctx.guild.get_role(mute_role_id)

        embed = embed_maker.message(ctx, f'<@{member.id}> has been muted for {format_time.seconds(parsed_length)}. Reason: {reason}', colour='green')
        await ctx.send(embed=embed)

        await timer_cog.create_timer(guild_id=ctx.guild.id, expires=end_time, event='mute', extras={'member_id': member.id, 'by': ctx.author.id})
        await member.add_roles(mute_role, reason=reason)
        db.get_user_timer.invalidate(ctx.guild.id, member.id, 'mute')
        self.new_case(ctx, member, reason=reason, length=parsed_length)

        embed = embed_maker.message(ctx, f'You have been muted for: **{format_time.seconds(parsed_length)}**\nReason: **{reason}**', colour='red')
        return await member.send(embed=embed)

    @commands.Cog.listener()
    async def on_mute_timer_over(self, timer):
        member_id = timer['extras']['member_id']
        guild_id = timer['guild_id']
        mute_role_id = db.get_server_options(guild_id, 'mute_role')

        self.bot.http.remove_role(guild_id, member_id, mute_role_id, reason='Automatic unmute')

    @commands.command(help='Unmute a user', usage='unmute [@member] [reason]', examples=['unmute @Hattyot shortened the mute time'], clearance='Mod', cls=command.Command)
    async def unmute(self, ctx, member=None, reason=None):
        if member is None:
            return await embed_maker.command_error(ctx)
        if not ctx.message.mentions:
            return await embed_maker.command_error(ctx, '[@member]')

        member = ctx.message.mentions[0]
        user_timer = db.get_user_timer(ctx.guild.id, member.id, 'mute')

        if not user_timer:
            embed = embed_maker.message(ctx, f'That user is not muted', colour='red')
            return await ctx.send(embed=embed)

        if reason is None:
            embed = embed_maker.message(ctx, 'You need to give a reason for the unmute', colour='red')
            return await ctx.send(embed=embed)

        mute_role_id = db.get_server_options(ctx.guild.id, 'mute_role')
        mute_role = ctx.guild.get_role(mute_role_id)

        await member.remove_roles(mute_role, reason=reason)
        db.get_user_timer.invalidate(ctx.guild.id, member.id, 'mute')
        db.timers.update_one({'guild_id': ctx.guild.id}, {'$pull': {'timers': {'event': 'mute', 'extras.member_id': member.id}}})

        embed = embed_maker.message(ctx, 'user has been unmuted', colour='green')
        return await ctx.send(embed=embed)

    def new_case(self, ctx, member, **kwargs):
        case_doc = {
            'by': ctx.author.id,
        }
        for k, v in kwargs.items():
            case_doc[k] = v

        db.cases.update_one({'guild_id': ctx.guild.id}, {'$push': {f'users.{member.id}.{ctx.command.name}': case_doc}})


def setup(bot):
    bot.add_cog(Mod(bot))
