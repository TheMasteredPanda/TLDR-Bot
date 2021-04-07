import asyncio
import time

from bson import ObjectId
from modules import database

db = database.get_connection()


class Timers:
    def __init__(self, bot):
        self.bot = bot

    async def run_old(self):
        await self.bot.left_check.wait()

        print(f'running old timers')
        timers = db.timers.find({})
        for timer in timers:
            asyncio.create_task(self.run(timer))

    async def run(self, timer):
        now = round(time.time())

        if timer['expires'] > now:
            await asyncio.sleep(timer['expires'] - now)

        self.call_event(timer)

    def call_event(self, timer):
        timer = db.timers.find_one({'_id': ObjectId(timer['_id'])})
        if not timer:
            return

        db.timers.delete_one({'_id': ObjectId(timer['_id'])})
        self.bot.dispatch(f'{timer["event"]}_timer_over', timer)

    def create(self, *, guild_id: int, expires: int, event: str, extras: dict):
        timer_dict = {
            'guild_id': guild_id,
            'expires': expires,
            'event': event,
            'extras': extras
        }

        result = db.timers.insert_one(timer_dict)
        timer_dict['_id'] = str(result.inserted_id)
        asyncio.create_task(self.run(timer_dict))
