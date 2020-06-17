from discord.ext import commands
from modules import database
from cachetools import TTLCache, Cache
import config
import asyncio
import time
import uuid

db = database.Connection()


class TTLItemCache(TTLCache):
    def __setitem__(self, key, value, cache_setitem=Cache.__setitem__, ttl=None):
        super(TTLItemCache, self).__setitem__(key, value)
        if ttl:
            link = self._TTLCache__links.get(key, None)
            if link:
                link.expire += ttl - self.ttl


class Utils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.loop = self.bot.loop
        self.event = asyncio.Event(loop=self.loop)

        self.menus = TTLItemCache(maxsize=2048, ttl=2*60)

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
