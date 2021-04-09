import asyncio
import time

from bson import ObjectId
from modules import database

db = database.get_connection()

# TODO: create separate class for timer.


class Timers:
    """
    Class for implementing functions with timed calls.
    Functions will be called by dispatching bot events by the name `on_{event}_timer_over`.

    Attributes
    __________
    bot: :class:`bot.TLDR`
        The discord bot.
    """

    def __init__(self, bot):
        self.bot = bot
        self.bot.logger.info('Timers module has been initiated')

    async def run_old(self) -> None:
        """Runs all the timers that were cut short, that are still in the database."""
        await self.bot.left_check.wait()

        timers = db.timers.find({})
        self.bot.logger.info(f'Running {timers.count()} old timers.')

        for timer in timers:
            asyncio.create_task(self.run(timer))

    async def run(self, timer) -> None:
        """
        Runs a timer, by sleeping until the timer expires.

        Parameters
        ___________
        timer: :class:`dict`
            Timer dictionary from :func:`create`
        """
        now = round(time.time())

        if timer['expires'] > now:
            await asyncio.sleep(timer['expires'] - now)

        self.call_event(timer)

    def call_event(self, timer) -> None:
        """
        Call timer event.
        Event will be dispatched with the name `on_{event}_timer_over`.

        Parameters
        ___________
        timer: :class:`dict`
            Timer dictionary from :func:`create`
        """
        timer = db.timers.find_one({'_id': ObjectId(timer['_id'])})
        if not timer:
            return

        db.timers.delete_one({'_id': ObjectId(timer['_id'])})
        self.bot.dispatch(f'{timer["event"]}_timer_over', timer)

    def create(self, *, guild_id: int, expires: int, event: str, extras: dict):
        """
        Create a new timer.

        Parameters
        ___________
        guild_id: :class:`int`
            ID of the guild the timer will belong to.
        expires: :class:`int`
            Time when timer will expire and the event will be dispatched.
        event: :class:`str`
            The name of the event that will be dispatched with the name `on_{event}_timer_over`.
        extras: :class:`dict`
            Extra data that can be passed to the timer.
        """
        timer_dict = {
            'guild_id': guild_id,
            'expires': expires,
            'event': event,
            'extras': extras
        }

        result = db.timers.insert_one(timer_dict)
        timer_dict['_id'] = str(result.inserted_id)
        asyncio.create_task(self.run(timer_dict))
