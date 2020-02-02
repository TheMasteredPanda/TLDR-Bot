import time
import asyncio
import uuid
from modules import database
from discord.ext import commands

db = database.Connection()


class Timer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.loop = self.bot.loop
        self.event = asyncio.Event(loop=self.loop)

    async def run_old_timers(self):
        timers_collection = db.timers.find({})
        for g in timers_collection:
            timers = g['timers']
            if timers:
                print(f'running old {g["guild_id"]} timers')
                for timer_id in timers:
                    asyncio.create_task(self.run_timer(g['guild_id'], timers[timer_id], timer_id))

    async def run_timer(self, guild_id, timer, timer_id):
        now = round(time.time())

        if timer['expires'] > now:
            await asyncio.sleep(timer['expires'] - now)

        await self.call_timer_event(guild_id, timer, timer_id)

    async def call_timer_event(self, guild_id, timer, timer_id):
        timer_doc = db.get_timers(guild_id, timer_id)
        if timer_doc:
            db.timers.update_one({'guild_id': guild_id}, {'$unset': {f'timers.{timer_id}': timer}})
            self.bot.dispatch(f'{timer["event"]}_timer_over', timer)

    async def create_timer(self, **kwargs):
        guild_id = kwargs['guild_id']
        timer_id = str(uuid.uuid4())
        timer_object = {
            'expires': kwargs['expires'],
            'event': kwargs['event'],
            'extras': kwargs['extras']
        }

        # Adds timer database if it's missing
        db.get_timers(guild_id, '0')

        db.timers.update_one({'guild_id': guild_id}, {'$set': {f'timers.{timer_id}': timer_object}})
        asyncio.create_task(self.run_timer(guild_id, timer_object, timer_id))

        return timer_object


def setup(bot):
    bot.add_cog(Timer(bot))
