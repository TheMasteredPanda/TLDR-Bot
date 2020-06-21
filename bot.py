import discord
import os
import config
import dateparser
import traceback
import time
from datetime import datetime
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

    async def on_raw_reaction_add(self, payload):
        guild_id = payload.guild_id
        guild = self.get_guild(int(guild_id))

        channel_id = payload.channel_id
        channel = guild.get_channel(int(channel_id))

        message_id = payload.message_id
        message = await channel.fetch_message(int(message_id))

        user_id = payload.user_id
        user = guild.get_member(user_id)
        if user is None:
            user = await guild.fetch_member(user_id)

        emote = payload.emoji.name

        data = db.server_data.find_one({'guild_id': user.guild.id})
        role_menus = data['role_menus']
        if str(message.id) in role_menus:
            role_menu = role_menus[str(message.id)]
            rl = [rl for rl in role_menu['roles'] if rl['emote'] == emote]
            if rl:
                role = discord.utils.find(lambda r: r.id == int(rl[0]['role_id']), user.guild.roles)
                await user.add_roles(role)

                msg = f'{rl[0]["message"]}'
                embed_colour = config.EMBED_COLOUR
                embed = discord.Embed(colour=embed_colour, description=msg, timestamp=datetime.now())
                embed.set_author(name='Role Given')
                embed.set_footer(text=f'{user.guild}', icon_url=user.guild.icon_url)

                return await user.send(embed=embed)

    async def on_raw_reaction_remove(self, payload):
        guild_id = payload.guild_id
        guild = self.get_guild(int(guild_id))

        channel_id = payload.channel_id
        channel = guild.get_channel(int(channel_id))

        message_id = payload.message_id
        message = await channel.fetch_message(int(message_id))

        user_id = payload.user_id
        user = guild.get_member(user_id)
        if user is None:
            user = await guild.fetch_member(user_id)

        emote = payload.emoji.name

        data = db.server_data.find_one({'guild_id': user.guild.id})
        role_menus = data['role_menus']
        if str(message.id) in role_menus:
            role_menu = role_menus[str(message.id)]
            rl = [rl for rl in role_menu['roles'] if rl['emote'] == emote]
            if rl:
                role = discord.utils.find(lambda r: r.id == int(rl[0]['role_id']), user.guild.roles)
                await user.remove_roles(role)

                msg = f'{rl[0]["message"]}'
                embed_colour = config.EMBED_COLOUR
                embed = discord.Embed(colour=embed_colour, description=msg, timestamp=datetime.now())
                embed.set_author(name='Role Roved')
                embed.set_footer(text=f'{user.guild}', icon_url=user.guild.icon_url)

                return await user.send(embed=embed)

    async def on_command_error(self, ctx, exception):
        trace = exception.__traceback__
        verbosity = 4
        lines = traceback.format_exception(type(exception), exception, trace, verbosity)
        traceback_text = ''.join(lines)

        print(traceback_text)
        print(exception)

        # send special message to user if bot lacks perms to send message in channel
        if isinstance(exception.original, discord.errors.Forbidden):
            await ctx.author.send('It appears that I am not allowed to send messages in that channel')

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

        # collect message data
        data = db.server_data.find_one({'guild_id': message.guild.id})
        if 'message_spike' in data:
            if 'messages' not in data:
                db.server_data.update_one({'guild_id': message.guild.id}, {'$set': {'messages': {}}})
                data['messages'] = {}

            message_data = data['messages']
            now = datetime.now()
            if str(message.channel.id) not in message_data:
                db.server_data.update_one({'guild_id': message.guild.id}, {'$set': {f'messages.{message.channel.id}.{now.hour}.{now.minute}': 1}})
                message_data[f'{message.channel.id}'] = {}
                message_data[f'{message.channel.id}'][f'{now.hour}'] = {}
                message_data[f'{message.channel.id}'][f'{now.hour}'][f'{now.minute}'] = 1
            elif str(now.hour) not in message_data[f'{message.channel.id}']:
                db.server_data.update_one({'guild_id': message.guild.id}, {'$set': {f'messages.{message.channel.id}.{now.hour}.{now.minute}': 1}})
                message_data[f'{message.channel.id}'][f'{now.hour}'] = {}
                message_data[f'{message.channel.id}'][f'{now.hour}'][f'{now.minute}'] = 1
            elif str(now.minute) not in message_data[f'{message.channel.id}'][f'{now.hour}']:
                db.server_data.update_one({'guild_id': message.guild.id}, {'$set': {f'messages.{message.channel.id}.{now.hour}.{now.minute}': 1}})
                message_data[f'{message.channel.id}'][f'{now.hour}'][f'{now.minute}'] = 1

            db.server_data.update_one({'guild_id': message.guild.id}, {'$inc': {f'messages.{message.channel.id}.{now.hour}.{now.minute}': 1}})

            previous_minute = list(range(0, 60))[now.minute - 1]
            if str(previous_minute) not in message_data[f'{message.channel.id}'][f'{now.hour}']:
                db.server_data.update_one({'guild_id': message.guild.id}, {'$set': {f'messages.{message.channel.id}.{now.hour}.{previous_minute}': 0}})
                message_data[f'{message.channel.id}'][f'{now.hour}'][f'{previous_minute}'] = 0

            # return if message count went over the limit previous minute
            previous_min_msg_count = message_data[f'{message.channel.id}'][f'{now.hour}'][f'{previous_minute}']
            if not previous_min_msg_count >= 1:
                current_min_msg_count = message_data[f'{message.channel.id}'][f'{now.hour}'][f'{now.minute}']
                if current_min_msg_count == 4:
                    channel_id = data['message_spike']['channel']
                    channel = message.guild.get_channel(int(channel_id))

                    msg = f'<#{message.channel.id}> is experiencing a message spike'
                    embed_colour = config.EMBED_COLOUR
                    embed = discord.Embed(colour=embed_colour, description=msg, timestamp=datetime.now())
                    embed.set_footer(text=f'{message.guild.name}', icon_url=message.guild.icon_url)
                    await channel.send(embed=embed)

                # do a bit of cleanup so the database doesnt get too filled
                if str(list(range(0, 60))[now.minute - 2]) in message_data[f'{message.channel.id}'][f'{now.hour}']:
                    db.server_data.update_one({'guild_id': message.guild.id}, {'$unset': {f'messages.{message.channel.id}.{now.hour}.{str(list(range(0, 60))[now.minute - 2])}': ''}})

                if str(list(range(0, 24))[now.hour - 1]) in message_data[f'{message.channel.id}'][f'{now.hour}']:
                    db.server_data.update_one({'guild_id': message.guild.id}, {'$unset': {f'messages.{message.channel.id}.{now.hour}.{str(list(range(0, 24))[now.hour - 1])}': ''}})

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

        utils = self.get_cog('Utils')
        clearance = await utils.get_user_clearance(ctx.guild.id, ctx.author.id)

        data = db.server_data.find_one({'guild_id': ctx.guild.id})
        if 'users' not in data:
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'users': {}}})
            data['users'] = {}
        if 'roles' not in data:
            db.server_data.update_one({'guild_id': ctx.guild.id}, {'$set': {'roles': {}}})
            data['roles'] = {}

        if str(message.author.id) not in data['users']:
            data['users'][str(message.author.id)] = []

        if ctx.command.clearance not in clearance and \
           ctx.command.name not in data['users'][str(message.author.id)] and \
           not set([str(r.id) for r in ctx.author.roles]) & set(data['roles'].keys()):
            return

        await self.invoke(ctx)

    async def on_guild_join(self, guild):
        self.add_collections(guild.id)

    @staticmethod
    def add_collections(guild_id, col=None):
        return_doc = None
        collections = ['levels', 'timers', 'polls', 'tickets', 'server_data']
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

        # run old timers
        utils_cog = self.get_cog('Utils')
        await utils_cog.run_old_timers()

        for g in self.guilds:
            # Check if guild documents in collections exist if not, it adds them
            self.add_collections(g.id)

            # start daily debate timer if it doesnt exist
            timer_data = db.timers.find_one({'guild_id': g.id})
            daily_debate_timer = [timer for timer in timer_data['timers'] if timer['event'] == 'daily_debate' or timer['event'] == 'daily_debate_final']
            if not daily_debate_timer:
                # calculates time until next debate -1 hour
                daily_debate_data = db.server_data.find_one({'guild_id': g.id})

                dd_time = daily_debate_data['daily_debates']['time']
                dd_channel = daily_debate_data['daily_debates']['channel']
                if not dd_time or not dd_channel:
                    return

                mod_cog = self.get_cog('Mod')
                await mod_cog.start_daily_debate_timer(g.id, dd_time)

    @staticmethod
    async def on_member_join(member):
        data = db.levels.find_one({'guild_id': member.guild.id})
        if str(member.id) in data['users']:
            # delete timer
            timer_data = db.timers.find_one({'guild_id': member.guild.id})
            delete_timer = [timer for timer in timer_data['timers'] if timer['event'] == 'delete_user_data' and int(timer['extras']['user_id']) == int(member.id)]
            timer_id = delete_timer[0]['id']
            db.timers.update_one({'guild_id': member.guild.id}, {'$pull': {'timers': {'id': timer_id}}})

            # give user data back
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
                user_h_role_index = honours_route.index(user_h_role[0])

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

        # Delete user data after 5 days
        utils_cog = self.get_cog('Utils')
        expires = int(time.time()) + (86400 * 5)  # 5 days
        await utils_cog.create_timer(
            expires=expires, guild_id=member.guild.id, event='delete_user_data',
            extras={'user_id': member.id}
        )

    async def on_delete_user_data_timer_over(self, timer):
        guild_id = timer['guild_id']
        user_id = timer['extras']['user_id']

        guild = self.get_guild(int(guild_id))
        if guild:
            # check if member joined back
            mem = guild.get_member(int(user_id))
            if mem is None:
                mem = await guild.fetch_member(int(user_id))

            if mem is None:
                return

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
