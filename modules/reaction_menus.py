from __future__ import annotations

import bot
import discord
import time
import functools
import asyncio

from collections import OrderedDict
from typing import Callable, Union
from ttldict import TTLOrderedDict


class ReactionMenus:
    def __init__(self, bot: bot.TLDR):
        self.bot = bot
        self.bot.add_listener(self.on_reaction_add, 'on_reaction_add')

        five_minutes = 5 * 60
        self.menus = TTLOrderedDict(default_ttl=five_minutes)

    def add(self, menu: Union[ReactionMenu, BookMenu]):
        self.menus[menu.message.id] = menu

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return

        menu = self.menus.get(reaction.message.id, None)
        if menu is None:
            return

        await menu.call_function(reaction, user)


class ReactionMenu:
    def __init__(self, message: discord.Message, buttons: dict):
        self.message = message
        self.buttons = buttons
        self.cooldown = time.time()

        for emote in buttons:
            asyncio.create_task(self.message.add_reaction(emote))

    async def call_function(self, reaction: discord.Reaction, user: discord.User):
        # add a 2 second cooldown, so the buttons cant be spammed
        if self.cooldown > time.time():
            return
        else:
            self.cooldown = time.time() + 2

        # get emote in string format
        emote_str = reaction.emoji if type(reaction.emoji) == str else f'<:{reaction.emoji.name}:{reaction.emoji.id}>'

        function = self.buttons.get(emote_str, None)
        if not function:
            return

        await function(reaction, user)


class BookMenu(ReactionMenu):
    def __init__(
            self,
            message: discord.Message, *,
            author: discord.Member,
            page: int,
            max_page_num: int,
            page_constructor: Callable,
            extra_back: int = None,
            extra_forward: int = None
    ):
        self.buttons = [
            ('⬅️', self.page_back),
            ('➡️', self.page_forward),
        ]

        if extra_back:
            self.buttons.insert(0, ('⏪', functools.partial(self.page_back, pages_back=extra_back)))

        if extra_forward:
            self.buttons.append(('⏩', functools.partial(self.page_forward, pages_forward=extra_forward)))

        self.buttons = OrderedDict(self.buttons)

        super().__init__(message, self.buttons)

        self.author = author
        self.page = page
        self.max_page_num = max_page_num
        self.page_constructor = page_constructor

    async def page_back(self, _, user: discord.User, *, pages_back: int = 1):
        if self.author.id != user.id:
            return

        self.page -= pages_back
        self.page %= self.max_page_num

        if self.page == 0:
            self.page = self.max_page_num

        new_embed = await self.page_constructor(page=self.page)
        return await self.message.edit(embed=new_embed)

    async def page_forward(self, _, user: discord.User, *, pages_forward: int = 1):
        if self.author.id != user.id:
            return

        self.page += pages_forward
        self.page %= self.max_page_num

        if self.page == 0:
            self.page = self.max_page_num

        new_embed = await self.page_constructor(page=self.page)
        return await self.message.edit(embed=new_embed)
