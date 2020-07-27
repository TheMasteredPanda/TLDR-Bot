import discord
import os
import config
import re
import traceback
from time import time
from datetime import  datetime
from modules import database, embed_maker
from cogs.utils import get_user_clearance
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

    async def on_message_delete(self, message):
        # delete reaction menu if message is reaction menu
        db.reaction_menus.find_one_and_delete({'guild_id': message.guild.id, 'message_id': message.id})

    async def on_raw_reaction_remove(self, payload):
        guild_id = payload.guild_id
        if not guild_id:
            return
        guild = self.get_guild(int(guild_id))

        channel_id = payload.channel_id
        channel = guild.get_channel(int(channel_id))

        message_id = payload.message_id

        # check if message is reaction_menu
        reaction_menu_data = db.reaction_menus.find_one({'guild_id': int(guild_id), 'message_id': message_id})
        if not reaction_menu_data:
            return

        message = await channel.fetch_message(int(message_id))

        user_id = payload.user_id
        user = guild.get_member(user_id)
        if user is None:
            user = await guild.fetch_member(user_id)

        if user.bot:
            return

        emote = payload.emoji.name
        if payload.emoji.is_custom_emoji():
            emote = f'<:{payload.emoji.name}:{payload.emoji.id}>'

        if 'role_menu_name' in reaction_menu_data and emote in reaction_menu_data['roles']:
            roles = reaction_menu_data['roles']
            role_id = roles[emote]['role_id']
            role = discord.utils.find(lambda r: r.id == int(role_id), user.guild.roles)
            if not role:
                # delete role from roles if role_id is invalid and update role menu
                db.reaction_menus.update_one({'guild_id': guild_id, 'message_id': message_id}, {'$unset': {f'roles.{emote}': ''}})
                del roles[emote]

                # delete message if last role has been removed
                if not roles:
                    return await message.delete()

                embed_colour = config.EMBED_COLOUR
                embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
                embed.set_author(name=f'Role Menu: {reaction_menu_data["role_menu_name"]}')
                embed.set_footer(icon_url=guild.icon_url)
                description = 'React to give yourself a role\n'

                for emoji in roles:
                    description += f'\n{emoji}: `{roles[emoji]["message"]}`'

                return await message.edit(embed=embed)

            await user.remove_roles(role)

            msg = f'Role Taken: {emote}: `{reaction_menu_data["roles"][emote]["message"]}`'
            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(colour=embed_colour, description=msg, timestamp=datetime.now())
            embed.set_footer(text=f'{user.guild}', icon_url=user.guild.icon_url)

            return await user.send(embed=embed)

    async def on_raw_reaction_add(self, payload):
        guild_id = payload.guild_id
        if not guild_id:
            return
        guild = self.get_guild(int(guild_id))

        channel_id = payload.channel_id
        channel = guild.get_channel(int(channel_id))
        message_id = payload.message_id

        # check if message is reaction_menu
        reaction_menu_data = db.reaction_menus.find_one({'guild_id': int(guild_id), 'message_id': message_id})
        if not reaction_menu_data:
            return

        message = await channel.fetch_message(int(message_id))
        user_id = payload.user_id
        user = guild.get_member(user_id)
        if user is None:
            user = await guild.fetch_member(user_id)

        if user.bot:
            return

        emote = payload.emoji.name
        if payload.emoji.is_custom_emoji():
            emote = f'<:{payload.emoji.name}:{payload.emoji.id}>'

        # react menu is role menu
        if 'role_menu_name' in reaction_menu_data and emote in reaction_menu_data['roles']:
            roles = reaction_menu_data['roles']
            role_id = roles[emote]['role_id']
            role = discord.utils.find(lambda r: r.id == int(role_id), user.guild.roles)
            if not role:
                # delete role from roles if role_id is invalid and update role menu
                db.reaction_menus.update_one({'guild_id': guild_id, 'message_id': message_id}, {'$unset': {f'roles.{emote}': ''}})
                del roles[emote]

                # delete message if last role has been removed
                if not roles:
                    return await message.delete()

                embed_colour = config.EMBED_COLOUR
                embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
                embed.set_author(name=f'Role Menu: {reaction_menu_data["role_menu_name"]}')
                embed.set_footer(icon_url=guild.icon_url)
                description = 'React to give yourself a role\n'

                for emoji in roles:
                    description += f'\n{emoji}: `{roles[emoji]["message"]}`'

                return await message.edit(embed=embed)

            await user.add_roles(role)
            msg = f'Role Given: {emote}: `{reaction_menu_data["roles"][emote]["message"]}`'
            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(colour=embed_colour, description=msg, timestamp=datetime.now())
            embed.set_footer(text=f'{user.guild}', icon_url=user.guild.icon_url)

            return await user.send(embed=embed)

        elif 'poll' in reaction_menu_data and emote in reaction_menu_data['poll']:
            await message.remove_reaction(payload.emoji, user)

            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
            embed.set_footer(text=f'{guild.name}', icon_url=guild.icon_url)
            embed.title = f'**"{reaction_menu_data["question"]}"**'

            if user.id in reaction_menu_data['voted']:
                embed.description = f'You have already voted'
                return await user.send(embed=embed)

            db.reaction_menus.update_one({'guild_id': guild.id, 'message_id': message.id}, {'$inc': {f'poll.{emote}': 1}})
            db.reaction_menus.update_one({'guild_id': guild.id, 'message_id': message.id}, {'$push': {f'voted': user.id}})

            embed.description = f'Your vote has been counted towards: {emote}'
            return await user.send(embed=embed)

    async def on_command_error(self, ctx, exception):
        trace = exception.__traceback__
        verbosity = 4
        lines = traceback.format_exception(type(exception), exception, trace, verbosity)
        traceback_text = ''.join(lines)

        print(traceback_text)
        print(exception)

        # send special message to user if bot lacks perms to send message in channel
        if hasattr(exception, 'original') and isinstance(exception.original, discord.errors.Forbidden):
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

        # checks if message was sent in pms
        if message.guild is None:
            pm_cog = self.get_cog('PrivateMessages')
            return await pm_cog.process_pm(message)

        if message.content.startswith(config.PREFIX):
            await self.process_commands(message)

        watchlist = db.watchlist.find_one({'guild_id': message.guild.id, 'user_id': message.author.id})
        watchlist_data = db.watchlist_data.find_one({'guild_id': message.guild.id})
        if watchlist and watchlist_data:
            filters = watchlist['filters']
            channel_id = watchlist_data['channel_id']
            channel = self.get_channel(int(channel_id))
            if channel:
                embed = discord.Embed(colour=config.EMBED_COLOUR, timestamp=datetime.now())
                embed.set_author(name=f'{message.author}', icon_url=message.author.avatar_url)
                embed.set_footer(text=f'message id: {message.id}', icon_url=message.guild.icon_url)

                embed.description = f'{message.content}\n[Link]({message.jump_url})'

                content = ''
                for f in filters:
                    regex = re.compile(fr'({f})')
                    match = re.findall(regex, str(message.content))
                    if match:
                        content = f'<@&{config.MOD_ROLE_ID}> - Filter Match: `{f}`'
                        break

                await channel.send(embed=embed, content=content)

        # Starts leveling process
        levels_cog = self.get_cog('Leveling')
        await levels_cog.process_message(message)

        # honours leveling
        leveling_data = db.leveling_data.find_one({'guild_id': message.guild.id}, {'honours_channels': 1})
        if leveling_data is None:
            leveling_data = self.add_collections(message.guild.id, 'leveling_data')

        honours_channels = leveling_data['honours_channels']
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

        user_clearance = get_user_clearance(ctx.author)

        command_data = db.commands.find_one({'guild_id': message.guild.id, 'command_name': ctx.command.name})
        if command_data is None:
            command_data = {
                'guild_id': ctx.guild.id,
                'command_name': ctx.command.name,
                'disabled': 0,
                'user_access': {},
                'role_access': {}
            }

        # user access overwrites role access
        user_access = command_data['user_access']
        role_access = command_data['role_access']

        access_to_command_given = False
        access_to_command_taken = False

        # check user_access
        if user_access:
            access_to_command_given = f'{ctx.author.id}' in user_access and user_access[f'{ctx.author.id}'] == 'give'
            access_to_command_taken = f'{ctx.author.id}' in user_access and user_access[f'{ctx.author.id}'] == 'take'

        # check role access
        if role_access:
            role_access_matching_role_ids = set([str(r.id) for r in ctx.author.roles]) & set(role_access.keys())
            if role_access_matching_role_ids:
                # sort role by permission
                roles = [ctx.guild.get_role(int(r_id)) for r_id in role_access_matching_role_ids]
                sorted_roles = sorted(roles, key=lambda r: r.permissions)
                if sorted_roles:
                    role = sorted_roles[-1]
                    access_to_command_given = access_to_command_given or f'{role.id}' in role_access and role_access[f'{role.id}'] == 'give'
                    access_to_command_taken = access_to_command_taken or f'{role.id}' in role_access and role_access[f'{role.id}'] == 'take'

        if ctx.command.clearance not in user_clearance and not access_to_command_given:
            return

        if access_to_command_taken:
            return await embed_maker.message(ctx, f'Your access to this command has been taken away', colour='red')

        if command_data['disabled'] and ctx.author.id not in config.DEV_IDS:
            return await embed_maker.message(ctx, 'This command has been disabled', colour='red')

        return await self.invoke(ctx)

    async def on_guild_join(self, guild):
        self.add_collections(guild.id)

    @staticmethod
    def add_collections(guild_id, col=None):
        return_doc = None
        collections = ['leveling_data', 'watchlist_data', 'daily_debates']
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
            daily_debate_timer = db.timers.find_one({'guild_id': g.id, 'event': {'$in': ['daily_debate', 'daily_debate_final']}})
            if not daily_debate_timer:
                # calculates time until next debate
                daily_debate_data = db.daily_debates.find_one({'guild_id': g.id})
                if not daily_debate_data:
                    return
                dd_time = daily_debate_data['time']
                dd_channel_id = daily_debate_data['channel_id']
                if not dd_time or not dd_channel_id:
                    return

                mod_cog = self.get_cog('Mod')
                await mod_cog.start_daily_debate_timer(g.id, dd_time)

    @staticmethod
    async def on_member_join(member):
        leveling_user = db.leveling_users.find_one({'guild_id': member.guild.id, 'user_id': member.id})
        if leveling_user:
            # delete timer
            db.timers.find_one_and_delete({'guild_id': member.guild.id, 'event': 'delete_user_data', 'extras.user_id': member.id})

            # give user data back
            if 'left' in leveling_user:
                db.leveling_users.update_one({'guild_id': member.guild.id, 'user_id': member.id}, {'$unset': {f'left': ''}})

            leveling_data = db.leveling_data.find_one({'guild_id': member.guild.id}, {'leveling_routes': 1})
            leveling_routes = leveling_data['leveling_routes']
            parliamentary_route = leveling_routes['parliamentary']
            honours_route = leveling_routes['honours']

            user_p_role = [role for role in parliamentary_route if role[0] == leveling_user['p_role']]
            user_p_role_index = parliamentary_route.index(user_p_role[0])

            # add old parliamentary roles to user
            up_to_current_role = parliamentary_route[0:user_p_role_index + 1]
            for role in up_to_current_role:
                role_obj = discord.utils.find(lambda rl: rl.name == role[0], member.guild.roles)
                if role_obj is None:
                    role_obj = await member.guild.create_role(name=role[0])

                await member.add_roles(role_obj)

            if leveling_user['h_role']:
                user_h_role = [role for role in honours_route if role[0] == leveling_user['h_role']]
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

        db.leveling_data.update_one({'guild_id': member.guild.id, 'user_id': member.id}, {'$set': {'left': True}})

        # Delete user data after 5 days
        utils_cog = self.get_cog('Utils')
        expires = int(time()) + (86400 * 5)  # 5 days
        await utils_cog.create_timer(expires=expires, guild_id=member.guild.id, event='delete_user_data', extras={'user_id': member.id})

    async def on_delete_user_data_timer_over(self, timer):
        guild_id = timer['guild_id']
        user_id = timer['extras']['user_id']

        guild = self.get_guild(int(guild_id))
        if guild:
            # check if member joined back
            try:
                await guild.fetch_member(int(user_id))
            except:
                # Delete user levels data
                db.leveling_users.delete_one({'guild_id': guild_id, 'user_id': user_id})
                # Delete user boosts
                db.boosts.delete_many({'guild_id': guild.id, 'user_id': user_id})
                # remove command access data
                db.commands.update_many({'guild_id': guild.id}, {'$unset': {f'user_access.{user_id}': ''}})
                # remove user from watchlist
                db.watchlist.delete_one({'guild_id': guild.id, 'user_id': user_id})

    async def close(self):
        await super().close()

    def run(self):
        super().run(config.BOT_TOKEN, reconnect=False)


def main():
    TLDR().run()


if __name__ == '__main__':
    main()
