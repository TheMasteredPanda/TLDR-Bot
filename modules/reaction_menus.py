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
    """
    Class that manages reaction menus.

    Attributes
    __________
    bot: :class:`bot.TLDR`
        The discord bot.
    menus: :class:`TTLOrderedDict`
        Dict with TTL of five minutes
    """
    def __init__(self, bot: bot.TLDR):
        self.bot = bot
        self.bot.add_listener(self._on_reaction_add, 'on_reaction_add')

        five_minutes = 5 * 60
        self.menus = TTLOrderedDict(default_ttl=five_minutes)

    def add(self, menu: Union[ReactionMenu, BookMenu]):
        """
        Adds menu to :attr:`menus`.

        Parameters
        ___________
        menu: Union[:class:`ReactionMenu`, :class:`BookMenu`]
            The menu that will be added to :attr:`menus`
        """
        self.menus[menu.message.id] = menu

    async def _on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        """Event listener that handles reactions."""
        if user.bot:
            return

        menu = self.menus.get(reaction.message.id, None)
        if menu is None:
            return

        await menu.call_function(reaction, user)


class ReactionMenu:
    """
    Implements reaction menu.

    Attributes
    __________
    message: :class:`discord.Message`
        Message that acts as the menu.
    buttons: :class:`dict`
        All the buttons attached to the menu.
    """
    def __init__(self, message: discord.Message, buttons: dict):
        self.message = message
        self.buttons = buttons

        for emote in buttons:
            asyncio.create_task(self.message.add_reaction(emote))

    async def call_function(self, reaction: discord.Reaction, user: discord.User):
        """
        Calls a button function of the menu by it's reaction.

        Parameters
        ___________
        reaction: :class:`discord.Reaction`
            Reaction that will be used to call the function of a button.
        user: :class:`discord.User`
            User who pressed the button.
        """
        # get emote in string format
        emote_str = reaction.emoji if type(reaction.emoji) == str else f'<:{reaction.emoji.name}:{reaction.emoji.id}>'

        function = self.buttons.get(emote_str, None)
        if not function:
            return

        await function(reaction, user)


class BookMenu(ReactionMenu):
    """
    Implements a special type of reaction menu which makes it easier to create a book style reaction menu.
    It automatically adds buttons and their functions.

    Attributes
    __________
    buttons: :class:`list`
        All the buttons attached to the menu.
    author: :class:`discord.Member`
        Member who created the menu.
    page: :class:`int`
        Current page of the BookMenu.
    max_page_num: :class:`int`
        The number of the last page of the BookMenu.
    page_constructor: :func:
        Function that creates the page embed.
    """
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

        # if extra_back or extra_forward are set, add extra buttons which moves the pages by n
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
        """
        Moves the BookMenu back by pages_back amount.

        Parameters
        ___________
        user: :class:`discord.User`
            User that pressed the button.
        pages_back: :class:`int`
            How many pages to go back by, defaults to 1
        """
        if self.author.id != user.id:
            return

        self.page -= pages_back
        self.page %= self.max_page_num

        if self.page == 0:
            self.page = self.max_page_num

        new_embed = await self.page_constructor(page=self.page)
        await self.message.edit(embed=new_embed)

    async def page_forward(self, _, user: discord.User, *, pages_forward: int = 1):
        """
        Moves the BookMenu forward by pages_forward amount.

        Parameters
        ___________
        user: :class:`discord.User`
            User that pressed the button.
        pages_forward: :class:`int`
            How many pages to go forward by, defaults to 1
        """
        if self.author.id != user.id:
            return

        self.page += pages_forward
        self.page %= self.max_page_num

        if self.page == 0:
            self.page = self.max_page_num

        new_embed = await self.page_constructor(page=self.page)
        return await self.message.edit(embed=new_embed)
