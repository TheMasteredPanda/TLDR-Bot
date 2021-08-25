import asyncio
import inspect
import time
from igramscraper.instagram import Account, Instagram as Igram
from typing import Union, Callable, Awaitable


class Instagram:
    def __init__(self, bot):
        self.bot = bot
        self.igram = Igram()
        self.listeners: dict[str, Listener] = {}

    def get_user(self, *, username: str = None, user_id: str = None) -> Account:
        if user_id:
            return self.igram.get_account_by_id(user_id)
        if username:
            return self.igram.get_account(username)

    def create_listener(self, user_id: str, callback: Union[Callable, Awaitable], *, interval: int = 300):
        listener = Listener(self, user_id, callback, interval=interval)
        self.bot.loop.create_task(listener.runner())
        self.listeners[user_id] = listener


class Listener:
    def __init__(self, instagram: Instagram, user_id: str, callback: Union[Callable, Awaitable], *, interval: int = 300):
        self.instagram = instagram
        self.user_id = user_id
        self.callback = callback
        self.interval = interval

        self.last_post_code = None

        self.stop_event = asyncio.Event()

    def stop(self):
        self.stop_event.set()
        if self.user_id in self.instagram.listeners:
            del self.instagram.listeners[self.user_id]

    async def runner(self):
        while not self.stop_event.is_set():
            start = time.time()
            if not self.last_post_code:
                self.get_last_post()

            self.last_post_code = 'CS9vm37su1i'

            await self.new_posts()
            end = time.time()

            await asyncio.sleep(self.interval - (end - start))

    def get_last_post(self):
        last_post = self.instagram.igram.get_medias_by_user_id(self.user_id, count=1)

        if last_post:
            last_post = last_post[0]
            self.last_post_code = last_post.short_code

    async def new_posts(self):
        if not self.last_post_code:
            return

        posts = self.instagram.igram.get_medias_by_user_id(self.user_id, count=12)
        if not posts or posts[0].short_code == self.last_post_code:
            return

        new_posts = []
        for post in posts:
            if post.short_code != self.last_post_code:
                new_posts.append(post)
            else:
                break

        new_posts = new_posts[::-1]

        self.last_post_code = new_posts[0].short_code
        is_await = inspect.iscoroutinefunction(self.callback)
        if is_await:
            await self.callback(new_posts)
        else:
            self.callback(new_posts)
