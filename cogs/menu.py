from cachetools import TTLCache, LRUCache,Cache
from discord.ext import commands


class TTLItemCache(TTLCache):
    def __setitem__(self, key, value, cache_setitem=Cache.__setitem__, ttl=None):
        super(TTLItemCache, self).__setitem__(key, value)
        if ttl:
            link = self._TTLCache__links.get(key, None)
            if link:
                link.expire += ttl - self.ttl


class Menu(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.menus = TTLItemCache(maxsize=2048, ttl=2*60)
        self.no_expire_menus = LRUCache(maxsize=2048)

    async def new_no_expire_menu(self, message, buttons):
        self.no_expire_menus[message.id] = buttons
        return await self.add_buttons(message, buttons)

    async def new_menu(self, message, buttons, ttl=None):
        self.menus.__setitem__(message.id, buttons, ttl=ttl)
        return await self.add_buttons(message, buttons)

    async def add_buttons(self, message, buttons):
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

        menu = None
        if message_id in self.menus:
            menu = self.menus
        elif message_id in self.no_expire_menus:
            menu = self.no_expire_menus

        if menu is None or user.bot or payload.emoji.is_custom_emoji():
            return
        
        if emote_name in menu[message_id]:
            channel = self.bot.get_channel(channel_id)
            message = await channel.fetch_message(message_id)
            func = menu[message_id][emote_name]
            await func(user, message, emote_name)

        return await self.bot.http.remove_reaction(channel_id, message_id, emote_name, user_id)


def setup(bot):
    bot.add_cog(Menu(bot))
