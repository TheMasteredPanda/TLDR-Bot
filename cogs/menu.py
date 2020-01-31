from cachetools import TTLCache
from discord.ext import commands


class Menu(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.menus = TTLCache(maxsize=2048, ttl=2*60)
        self.menu_ids = []

    async def new_menu(self, message, buttons):
        self.menu_ids.append(message.id)
        self.menus[message.id] = buttons

        for button in self.menus[message.id]:
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

        if message_id in self.menus and emote_name in self.menus[message_id] and not user.bot:
            channel = self.bot.get_channel(channel_id)
            message = await channel.fetch_message(message_id)
            func = self.menus[message_id][emote_name]
            await func(user, message)
            return await self.bot.http.remove_reaction(channel_id, message_id, emote_name, user_id)


def setup(bot):
    bot.add_cog(Menu(bot))