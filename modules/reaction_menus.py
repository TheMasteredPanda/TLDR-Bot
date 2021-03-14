import bot
import discord
import time

from typing import Callable, Awaitable
from ttldict import TTLOrderedDict


class ReactionMenus:
    def __init__(self, bot: bot.TLDR):
        self.bot = bot
        self.bot.add_listener(self.on_reaction_add, 'on_reaction_add')

        five_minutes = 5 * 60
        self.menus = TTLOrderedDict(default_ttl=five_minutes)

    async def add(
            self,
            menu_message: discord.Message,
            buttons: dict[str, Callable[[discord.Reaction, discord.User], Awaitable]]
    ):
        self.menus[menu_message.id] = {
            'cooldown': time.time(),
            'buttons': buttons
        }
        for emote in buttons:
            await menu_message.add_reaction(emote)

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return

        if reaction.message.id in self.menus:
            menu = self.menus[reaction.message.id]

            # add a 2 second cooldown, so the buttons cant be spammed
            if menu['cooldown'] > time.time():
                return
            else:
                menu['cooldown'] = time.time() + 2

            # get emote in string format
            emote = reaction.emoji
            emote_str = emote if type(emote) == str else f'<:{emote.name}:{emote.id}>'

            if emote_str not in menu['buttons']:
                return

            function = menu['buttons'][emote_str]
            await function(reaction, user)
