from discord.ext import commands
from modules import database
from cachetools import TTLCache, Cache
from datetime import datetime
import config
import asyncio
import time
import uuid
import discord
import re
db = database.Connection()


class TTLItemCache(TTLCache):
    def __setitem__(self, key, value, cache_setitem=Cache.__setitem__, ttl=None):
        super(TTLItemCache, self).__setitem__(key, value)
        if ttl:
            link = self._TTLCache__links.get(key, None)
            if link:
                link.expire += ttl - self.ttl


async def get_member(ctx, bot, source):
    member = None

    # check if source is member mention
    if ctx.message.mentions:
        member = ctx.message.mentions[0]

    # Check if source is user id
    elif source.isdigit():
        member = ctx.guild.get_member(int(source))
        if member is None:
            try:
                member = await ctx.guild.fetch_member(int(source))
            except:
                return 'Invalid user ID'

    # Check if source is member's name
    elif isinstance(source, str):
        if len(source) < 3:
            return 'User name input needs to be at least 3 characters long'

        regex = re.compile(fr'({source.lower()})')
        members = list(filter(lambda m: re.findall(regex, str(m).lower()) or re.findall(regex, m.display_name.lower()), ctx.guild.members))
        if len(members) > 10:
            return 'Too many username matches'

        if len(members) > 1:
            embed_colour = config.EMBED_COLOUR
            users_embed = discord.Embed(colour=embed_colour, timestamp=datetime.now())
            users_embed.set_author(name=f'Users')
            users_embed.set_footer(text=f'{ctx.author}', icon_url=ctx.author.avatar_url)

            description = 'Found multiple users, which one did you mean? `input digit of user`\n\n'
            for i, user in enumerate(members):
                description += f'`#{i + 1}` | {user}'
                description += f' - **Nickname:** {user.nick}\n' if user.nick else '\n'

            users_embed.description = description

            await ctx.send(embed=users_embed)

            def user_check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            try:
                user_message = await bot.wait_for('message', check=user_check, timeout=20)
            except asyncio.TimeoutError:
                return None

            index = user_message.content
            if index.isdigit() and len(members) >= int(index) - 1 >= 0:
                member = members[int(index) - 1]
            elif not index.isdigit():
                return 'Input is not a number'
            elif int(index) - 1 > len(members) or int(index) - 1 < 0:
                return 'Input number out of range'

        elif len(members) == 1:
            member = members[0]

    return member


class Utils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.loop = self.bot.loop
        self.event = asyncio.Event(loop=self.loop)

        self.menus = TTLItemCache(maxsize=2048, ttl=2*60)
        self.no_expire_menus = {}

    async def new_no_expire_menu(self, message, buttons):
        self.no_expire_menus[message.id] = buttons
        for button in buttons:
            await message.add_reaction(button)

    async def new_menu(self, message, buttons, ttl=None):
        self.menus.__setitem__(message.id, buttons, ttl=ttl)
        for button in buttons:
            await message.add_reaction(button)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        channel_id = payload.channel_id
        message_id = payload.message_id
        user_id = payload.user_id
        emote_name = payload.emoji.name

        user = self.bot.get_user(payload.user_id)
        if user is None:
            user = await self.bot.fetch_user(payload.user_id)

        if message_id in self.menus:
            menu = self.menus
        elif message_id in self.no_expire_menus:
            menu = self.no_expire_menus
        else:
            return

        if user.bot or payload.emoji.is_custom_emoji():
            return

        if emote_name in menu[message_id]:
            channel = self.bot.get_channel(channel_id)
            message = await channel.fetch_message(message_id)
            func = menu[message_id][emote_name]
            await func(user, message, emote_name)

        return await self.bot.http.remove_reaction(channel_id, message_id, emote_name, user_id)

    async def run_old_timers(self):
        timers_collection = db.timers.find({})
        for g in timers_collection:
            timers = g['timers']
            if timers:
                print(f'running old timers for: {g["guild_id"]}')
                for timer in timers:
                    asyncio.create_task(self.run_timer(g['guild_id'], timer))

    async def run_timer(self, guild_id, timer):
        now = round(time.time())

        if timer['expires'] > now:
            if 'timer_cog' in timer['extras'] and 'timer_function' in timer['extras']:
                cog = self.bot.get_cog(timer['extras']['timer_cog'])
                timer_function = getattr(cog, timer['extras']['timer_function'])
                args = timer['extras']['args']
                task = asyncio.create_task(timer_function(args))
                await task
            else:
                await asyncio.sleep(timer['expires'] - now)

        await self.call_timer_event(guild_id, timer)

    async def call_timer_event(self, guild_id, timer):
        # find timer object
        data = db.timers.find_one({'guild_id': guild_id})
        if data is None:
            data = self.bot.add_collections(guild_id, 'timers')

        timers = data['timers']
        timer_obj = [t for t in timers if t['id'] == timer['id']]
        if timer_obj:
            db.timers.update_one({'guild_id': guild_id}, {'$pull': {'timers': {'id': timer['id']}}})
            self.bot.dispatch(f'{timer["event"]}_timer_over', timer)

    async def create_timer(self, **kwargs):
        timer_id = str(uuid.uuid4())
        timer_object = {
            'id': timer_id,
            'guild_id': kwargs['guild_id'],
            'expires': kwargs['expires'],
            'event': kwargs['event'],
            'extras': kwargs['extras']
        }

        db.timers.update_one({'guild_id': timer_object['guild_id']}, {'$push': {f'timers': timer_object}})
        asyncio.create_task(self.run_timer(timer_object['guild_id'], timer_object))

        return timer_object

    async def get_user_clearance(self, guild_id, member_id):
        guild = self.bot.get_guild(guild_id)
        member = guild.get_member(int(member_id))
        if member is None:
            member = await guild.fetch_member(int(member_id))

        permissions = member.guild_permissions
        clearance = []

        if member_id in config.DEV_IDS:
            clearance.append('Dev')
        if permissions.administrator:
            clearance.append('Admin')
        if permissions.manage_messages:
            clearance.append('Mod')
        clearance.append('User')

        return clearance


def setup(bot):
    bot.add_cog(Utils(bot))
