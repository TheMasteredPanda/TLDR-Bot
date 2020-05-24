import discord
import re
from modules import command, embed_maker, database
from discord.ext import commands

db = database.Connection()


class Mod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
