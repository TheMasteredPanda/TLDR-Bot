import discord
import os
import config
import re
import traceback
import time
from modules import database
from discord.ext import commands

db = database.Connection()


async def get_prefix(bot, message):
    return commands.when_mentioned_or(config.PREFIX)(bot, message)


class TLDR(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=get_prefix, case_insensitive=True, help_command=None)

        # Load Cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                self.load_extension(f'cogs.{filename[:-3]}')
                print(f'{filename[:-3]} is now loaded')

    async def on_command_error(self, ctx, exception):
        trace = exception.__traceback__
        verbosity = 4
        lines = traceback.format_exception(type(exception), exception, trace, verbosity)
        traceback_text = ''.join(lines)

        print(traceback_text)
        print(exception)

        # send error message to certain channel in a guild if error happens during bot runtime
        if config.ERROR_SERVER in [g.id for g in self.guilds]:
            guild = self.get_guild(config.ERROR_SERVER)
        else:
            return print('Invalid error server id')

        if guild is not None:
            if config.ERROR_CHANNEL in [c.id for c in guild.channels]:
                channel = self.get_channel(config.ERROR_CHANNEL)
            else:
                return print('Invalid error channel id')

            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(colour=embed_colour, title=f'{ctx.command.name} - Command Error', description=f'```{exception}\n{traceback_text}```')
            embed.add_field(name='Message', value=ctx.message.content)
            embed.add_field(name='User', value=ctx.message.author)
            embed.add_field(name='Channel', value=f'{ctx.message.channel.name}')

            return await channel.send(embed=embed)

    async def on_message(self, message):
        if message.author.bot:
            return

        # just checks if message was sent in pms
        if message.guild is None:
            pm_cog = self.get_cog('PrivateMessages')
            return await pm_cog.process_pm(message)

        if message.content.startswith(config.PREFIX):
            return await self.process_commands(message)

        # Starts leveling process
        levels_cog = self.get_cog('Leveling')
        await levels_cog.process_message(message)

        # honours leveling
        data = db.levels.find_one({'guild_id': message.guild.id})
        if data is None:
            data = self.add_collections(message.guild.id, 'tickets')

        honours_channels = data['honours_channels']
        if message.channel.id in honours_channels:
            await levels_cog.process_hp_message(message)

        # checks if bot was mentioned, if it was invoke help command
        bot_mention = f'<@{self.user.id}>'
        bot_mention_nickname = f'<@!{self.user.id}>'

        if message.content == bot_mention or message.content == bot_mention_nickname:
            ctx = await self.get_context(message)
            utility_cog = self.get_cog('Utility')
            return await utility_cog.help(ctx)

    async def process_commands(self, message):
        ctx = await self.get_context(message)

        if ctx.command is None:
            return

        if ctx.guild is None:
            return

        await self.invoke(ctx)

    async def on_guild_join(self, guild):
        self.add_collections(guild.id)

    @staticmethod
    def add_collections(guild_id, col=None):
        return_doc = None
        collections = ['levels', 'timers', 'polls', 'tickets']
        for c in collections:
            collection = db.__getattribute__(c)
            doc = collection.find_one({'guild_id': guild_id})

            if not doc:
                new_doc = database.schemas[c]
                new_doc['guild_id'] = guild_id

                # return doc if asked for
                if col == c:
                    return_doc = new_doc

                # .copy() is there to prevent pymongo from creating duplicate "_id"'s
                collection.insert_one(new_doc.copy())

        return return_doc

    async def on_ready(self):
        bot_game = discord.Game(f'@me')
        await self.change_presence(activity=bot_game)

        print(f'{self.user} is ready')

        # Check if guild documents in collections exist if not, it adds them
        for g in self.guilds:
            self.add_collections(g.id)

    @staticmethod
    async def on_member_join(member):
        data = db.levels.find_one({'guild_id': member.guild.id})
        if str(member.id) in data['users']:
            levels_user = data['users'][f'{member.id}']
            leveling_routes = data['leveling_routes']
            parliamentary_route = leveling_routes['parliamentary']
            honours_route = leveling_routes['honours']

            user_p_role = [role for role in parliamentary_route if role[0] == levels_user['p_role']]
            user_p_role_index = parliamentary_route.index(user_p_role[0])

            # add old parliamentary roles to user
            up_to_current_role = parliamentary_route[0:user_p_role_index + 1]
            for role in up_to_current_role:
                role_obj = discord.utils.find(lambda rl: rl.name == role[0], member.guild.roles)
                if role_obj is None:
                    role_obj = await member.guild.create_role(name=role[0])

                await member.add_roles(role_obj)

            if levels_user['h_role']:
                user_h_role = [role for role in honours_route if role[0] == levels_user['h_role']]
                user_h_role_index = honours_route.index(user_p_role[0])

                # add old honours roles to user
                up_to_current_role = honours_route[0:user_h_role_index + 1]
                for role in up_to_current_role:
                    role_obj = discord.utils.find(lambda rl: rl.name == role[0], member.guild.roles)
                    if role_obj is None:
                        role_obj = await member.guild.create_role(name=role[0])

                    await member.add_roles(role_obj)

    async def on_member_remove(self, member):
        if member.bot:
            return

        # Delete user data after 48h
        utils_cog = self.get_cog('Utils')
        expires = int(time.time()) + 172800  # 48h
        await utils_cog.create_timer(
            expires=expires, guild_id=member.guild.id, event='delete_user_data',
            extras={'user_id': member.id}
        )

    @staticmethod
    def on_delete_user_data_timer_over(timer):
        guild_id = timer['guild_id']
        user_id = timer['extras']['user_id']
        # Delete user levels data
        db.levels.update_one({'guild_id': guild_id}, {'$unset': {f'users.{user_id}': ''}})

    async def close(self):
        await super().close()

    def run(self):
        super().run(config.BOT_TOKEN, reconnect=False)


def main():
    TLDR().run()


if __name__ == '__main__':
    main()
