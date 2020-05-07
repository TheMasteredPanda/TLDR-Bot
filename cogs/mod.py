import discord
import time
import re
import config
from datetime import datetime
from modules import command, embed_maker, database, format_time
from discord.ext import commands

db = database.Connection()


def ordinal(num):
    suffix = ["th", "st", "nd", "rd"]

    if num % 10 in [1, 2, 3] and num not in [11, 12, 13]:
        return suffix[num % 10]
    else:
        return suffix[0]


class Mod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='see what roles are whitelisted for an emote', usage='emote_roles [emote]', examples=['emote_roles :TldrNewsUK:'], clearance='Mod', cls=command.Command)
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
            role = discord.utils.find(lambda r: r.id == role, ctx.guild.roles)
        else:
            role = discord.utils.find(lambda r: r.name == role, ctx.guild.roles)

        if role is None:
            return await embed_maker.command_error(ctx, '[role]')

        emote_roles = emoji.roles
        if action == 'add':
            emote_roles.append(role)
            await emoji.edit(roles=emote_roles)
            await ctx.guild.fetch_emoji(emoji.id)
            embed = embed_maker.message(ctx, f'<@&{role.id}> has been added to whitelisted roles of emote {emote}', colour='green')
            return await ctx.send(embed=embed)

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

    @commands.command(help='Warn a user', usage='warn [@member] [warning]', examples=['warn @Hattyot breaking community guidelines'], clearance='Mod', cls=command.Command)
    async def warn(self, ctx, member=None, *, warning=None):
        if member is None:
            return await embed_maker.command_error(ctx)
        if not ctx.message.mentions:
            return await embed_maker.command_error(ctx, '[@member]')

        member = ctx.message.mentions[0]

        if warning is None:
            return await embed_maker.command_error(ctx, '[warning]')

        if ctx.author.roles[-1].position <= member.roles[-1].position:
            embed = embed_maker.message(ctx, 'Can\'t warn a member who has a role that is equal or higher than yours.', colour='red')
            return await ctx.send(embed=embed)
        if ctx.guild.me.roles[-1].position <= member.roles[-1].position:
            embed = embed_maker.message(ctx, 'That person is higher up than I am, I won\'t warn them.', colour='red')
            return await ctx.send(embed=embed)

        user_warns = db.get_cases('warn', ctx.guild.id, member.id)
        warn_count = len(user_warns)

        embed = embed_maker.message(ctx, f'<@{member.id}> has been warned', footer=f'This is their {warn_count + 1}{ordinal(warn_count + 1)} warning', colour='green')
        await ctx.send(embed=embed)

        embed = discord.Embed(colour=config.DEFAULT_EMBED_COLOUR, description=f'**Warning:** {warning}', timestamp=datetime.now(), title='You have been warned')
        embed.set_footer(text=f'This is your {warn_count+1}{ordinal(warn_count + 1)} warning', icon_url=ctx.guild.icon_url)
        await member.send(embed=embed)

        self.new_case(ctx, member, warning=warning, time=round(time.time()))

    @commands.command(help='See the list of warnings a user has received', usage='warnings [@members]', examples=['warnings @Hattyot'], clearance='Mod', cls=command.Command)
    async def warnings(self, ctx, member=None):
        if member is None:
            return await embed_maker.command_error(ctx)
        if not ctx.message.mentions:
            return await embed_maker.command_error(ctx, '[@member]')

        member = ctx.message.mentions[0]
        return await self.cases_menu(ctx, member, 'warn', 'warning')

    @commands.command(help='See the list of mutes a user has received', usage='mutes [@members]', examples=['mutes @Hattyot'], clearance='Mod', cls=command.Command)
    async def mutes(self, ctx, member=None):
        if member is None:
            return await embed_maker.command_error(ctx)
        if not ctx.message.mentions:
            return await embed_maker.command_error(ctx, '[@member]')

        member = ctx.message.mentions[0]
        return await self.cases_menu(ctx, member, 'mute', 'mute')

    async def cases_menu(self, ctx, member, case_name, case_str):
        cases = db.get_cases(case_name, ctx.guild.id, member.id)
        cases_count = len(cases)
        if cases_count > 0:
            desc = f'To view more info about a {case_str}, choose to corresponding reaction number\n\n'
            k_switch = {
                'mute': 'reason',
                'warn': 'warning'
            }
            k = k_switch.get(case_name)
            desc += '\n'.join(f'**#{i + 1}** - {m[k]}' for i, m in enumerate(cases))
        else:
            desc = f'This user has no {case_str}s'

        embed = embed_maker.message(ctx, desc, title=f'{member.name}\'s {case_str}s')
        list_msg = await ctx.send(embed=embed)

        if cases_count < 1:
            return

        if cases_count > 9:
            embed = embed_maker.message(ctx, desc, title=f'This user has way too many {case_str}s')
            return await ctx.send(embed=embed)

        all_num_emotes = ['⬅️', '1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
        emotes = all_num_emotes[:cases_count + 1]

        async def info(user, msg, emote):
            if ctx.author.id != user.id or msg.channel.id != ctx.channel.id or msg.id != list_msg.id:
                return
            case_info = cases[emotes.index(emote) - 1]
            new_description = ''
            for k, v in case_info.items():
                if k == 'time':
                    ago = round(time.time()) - v
                    v = f'{format_time.seconds(ago)} ago'
                if k == 'by' or re.match(r'id', k):
                    v = f'<@{v}>'
                if k == 'length':
                    v = f'{format_time.seconds(v)}'
                new_description += f'\n**{k}:** {v}'

            new_embed = msg.embeds[0]
            new_embed.description = new_description
            return await msg.edit(embed=new_embed)

        async def back(user, msg, emote):
            if ctx.author.id != user.id or msg.channel.id != ctx.channel.id or msg.id != list_msg.id:
                return
            new_description = desc
            new_embed = msg.embeds[0]
            if new_description == new_embed.description:
                return
            new_embed.description = new_description
            return await msg.edit(embed=new_embed)

        buttons = dict.fromkeys(emotes, info)
        buttons['⬅️'] = back

        menu_cog = self.bot.get_cog('Menu')
        return await menu_cog.new_menu(list_msg, buttons)

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
            else:
                embed = embed_maker.message(ctx, f'You don\'t have a mute role set and i couldn\'t find one.\nPlease make one and set it with `{config.DEFAULT_PREFIX}mute_role [role id]`', colour='red ')
                return await ctx.send(embed=embed)
        else:
            mute_role = ctx.guild.get_role(mute_role_id)

        embed = embed_maker.message(ctx, f'<@{member.id}> has been muted for {format_time.seconds(parsed_length)}', colour='green')
        await ctx.send(embed=embed)

        user_mutes = db.get_cases('mute', ctx.guild.id, member.id)
        mute_count = len(user_mutes)
        embed = discord.Embed(colour=config.DEFAULT_EMBED_COLOUR, description=f'**Length:** {format_time.seconds(parsed_length)}\n**Reason:** {reason}', timestamp=datetime.now(), title='You have been muted')
        embed.set_footer(text=f'This is your {mute_count+1}{ordinal(mute_count + 1)} mute', icon_url=ctx.guild.icon_url)
        await member.send(embed=embed)

        self.new_case(ctx, member, reason=reason, length=parsed_length, time=round(time.time()))
        await timer_cog.create_timer(guild_id=ctx.guild.id, expires=end_time, event='mute', extras={'member_id': member.id, 'by': ctx.author.id})
        await member.add_roles(mute_role, reason=reason)

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
