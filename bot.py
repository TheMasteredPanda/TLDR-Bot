import discord
import os
import aiohttp
import re
from cogs import levels
from time import time
from modules import database, context
from discord.ext import commands
from config import BOT_TOKEN

db = database.Connection()
# Cooldown objects for giving and receiving reactions
receive_cooldown = {}
give_cooldown = {}

async def get_prefix(bot, message):
    prefix = db.get_server_options('prefix', message.guild.id)
    return commands.when_mentioned_or(prefix)(bot, message)


class TLDR(commands.AutoShardedBot):
    def __init__(self):
        super().__init__(command_prefix=get_prefix, case_insensitive=True, help_command=None)

        self.session = aiohttp.ClientSession(loop=self.loop)

        # Load Cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                self.load_extension(f'cogs.{filename[:-3]}')
                print(f'{filename[:-3]} is now loaded')

    async def on_message(self, message):
        ctx = await self.get_context(message, cls=context.Context)

        regex = re.compile(rf'<@!?{self.user.id}>')
        match = re.findall(regex, message.content)
        if match:
            general_cog = self.get_cog('General')
            return await ctx.invoke(general_cog.help)

        await self.process_commands(ctx)

        if not message.author.bot:
            levels_cog = self.get_cog('Levels')
            return await levels_cog.process_message(ctx)

    async def on_raw_reaction_add(self, payload):
        guild = self.get_guild(payload.guild_id)
        channel = self.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        author = message.author
        user = self.get_user(payload.user_id)
        emote = payload.emoji
        ctx = await self.get_context(message, cls=context.Context)

        # skip if user gave reaction to themselves
        if author.id == user.id:
            return

        # check if reaction is either thumbs up or thumbs down
        if emote.name not in ('👍', '👎'):
            return

        # Add xp to user who received reaction
        if self.cooldown_expired(receive_cooldown, guild, author):
            xp_add = 10
            await self.add_reaction_xp(ctx, guild, author, xp_add)

        # Add xp to user who gave reaction
        if self.cooldown_expired(give_cooldown, guild, user):
            xp_add = 5
            await self.add_reaction_xp(ctx, guild, user, xp_add)

    async def add_reaction_xp(self, ctx, guild, user, xp_add):
        new_xp = db.get_levels('xp', guild.id, user.id) + xp_add

        db.levels.update_one({'guild_id': guild.id}, {'$set': {f'users.{user.id}.xp': new_xp}})
        db.get_levels.invalidate('xp', guild.id, user.id)

        xp_until = levels.xpi(guild, user, new_xp)
        if xp_until <= 0:

            levels_cog = self.get_cog('Levels')
            await levels_cog.level_up(ctx, user, 'participation')

    def cooldown_expired(self, cooldown, guild, member):
        if guild.id not in cooldown:
            cooldown[guild.id] = {}
        if member.id in cooldown[guild.id]:
            if round(time()) >= cooldown[guild.id][member.id]:
                del cooldown[guild.id][member.id]
            else:
                return False

        cooldown_expire = round(time()) + 60
        cooldown[guild.id][member.id] = cooldown_expire
        return True

    async def process_commands(self, ctx):
        if ctx.command is None or ctx.guild is None:
            return
        if ctx.command.clearance not in ctx.author_clearance:
            return

        await self.invoke(ctx)

    async def on_ready(self):
        bot_game = discord.Game(f'@me')
        await self.change_presence(activity=bot_game)

        print(f'{self.user} is ready')

    async def on_member_join(self, member):
        # just adds the member to the database
        db.get_levels('xp', member.guild.id, member.id)

    async def close(self):
        await super().close()
        await self.session.close()

    def run(self):
        super().run(BOT_TOKEN, reconnect=False)


def main():
    TLDR().run()


if __name__ == '__main__':
    main()
