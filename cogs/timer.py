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
        print('event')
        timer_doc = db.get_timer(guild_id, timer['id'])
        if timer_doc:
            print('in if')
            db.timers.update_one({'guild_id': guild_id}, {'$pull': {'timers': {'id': timer['id']}}})
            self.bot.dispatch(f'{timer["event"]}_timer_over', timer)
            db.get_timer.invalidate(guild_id, timer['id'])

    async def create_timer(self, **kwargs):
        timer_id = str(uuid.uuid4())
        timer_object = {
            'id': timer_id,
            'guild_id': kwargs['guild_id'],
            'expires': kwargs['expires'],
            'event': kwargs['event'],
            'extras': kwargs['extras']
        }

        # Adds timer database if it's missing
        db.get_timer(timer_object['guild_id'], '0')

        db.timers.update_one({'guild_id': timer_object['guild_id']}, {'$push': {f'timers': timer_object}})
        asyncio.create_task(self.run_timer(timer_object['guild_id'], timer_object))

        return timer_object


def setup(bot):
    bot.add_cog(Timer(bot))
