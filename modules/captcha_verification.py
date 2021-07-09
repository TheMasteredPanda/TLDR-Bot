import re
import time

import discord
import config
import random
import string
import io

from modules.reaction_menus import ReactionMenu
from captcha.image import ImageCaptcha
from datetime import datetime
from modules import database

if False:
    from bot import TLDR

db = database.get_connection()

# TODO: prevent command usage in captcha channels


class Captcha:
    def __init__(self, bot: 'TLDR'):
        self.bot = bot
        self.image_captcha = ImageCaptcha(width=280, height=120)

        self.main_guild = None
        self.gateway_guild = None
        self.invite_channel = None
        self.main_captcha_category = None
        self.gateway_captcha_category = None

    async def initialize(self):
        if 'GATEWAY_GUILD_ID' not in config.__dict__:
            return await self.bot.critical_error('GATEWAY_GUILD_ID value missing from config.py')

        self.main_guild: discord.Guild = self.bot.get_guild(config.MAIN_SERVER)
        self.gateway_guild: discord.Guild = self.bot.get_guild(config.GATEWAY_GUILD_ID)

        if self.gateway_guild is None:
            return await self.bot.critical_error(f'Unable to get gateway guild via ID [{config.GATEWAY_GUILD_ID}]')

        # channel for which the invite will be created
        self.invite_channel: discord.TextChannel = self.main_guild.get_channel(config.INVITE_CHANNEL_ID)

        # check if captcha category exists on both guilds
        self.main_captcha_category = discord.utils.find(
            lambda channel: channel.type == discord.ChannelType.category and channel.name == "Captcha Verification",
            self.main_guild.channels
        )
        self.gateway_captcha_category = discord.utils.find(
            lambda channel: channel.type == discord.ChannelType.category and channel.name == "Captcha Verification",
            self.gateway_guild.channels
        )

        # create categories if they doesnt exist
        if self.main_captcha_category is None:
            overwrites = {self.main_guild.default_role: discord.PermissionOverwrite(view_channel=False)}
            self.main_captcha_category = await self.main_guild.create_category("Captcha Verification", overwrites=overwrites)

        if self.gateway_captcha_category is None:
            overwrites = {self.gateway_guild.default_role: discord.PermissionOverwrite(view_channel=False)}
            self.gateway_captcha_category = await self.gateway_guild.create_category("Captcha Verification", overwrites=overwrites)

        self.bot.add_listener(self.on_member_join, 'on_member_join')
        self.bot.add_listener(self.on_member_remove, 'on_member_remove')
        self.bot.add_listener(self.on_message, 'on_message')
        self.bot.add_listener(self.on_captcha_timeout_timer_over, 'on_captcha_timeout_timer_over')

    def get_guild(self, guild_id: int) -> discord.Guild:
        if guild_id == self.main_guild.id:
            return self.main_guild
        elif guild_id == self.gateway_guild.id:
            return self.gateway_guild

    async def on_captcha_timeout_timer_over(self, timer: dict):
        # delete channel
        channel = self.bot.get_channel(timer['extras']['channel_id'])
        await channel.delete()

        # kick user
        guild = self.get_guild(timer['guild_id'])
        await guild.kick(discord.Object(id=timer['extras']['member_id']))

    async def on_member_join(self, member: discord.Member):
        if member.guild.id not in [self.main_guild.id, self.gateway_guild.id]:
            return

        timer = db.timers.find_one({'event': 'captcha_timeout', 'extras.member_id': member.id})
        if timer:
            db.timers.delete_one({'event': 'captcha_timeout', 'extras.member_id': member.id})
            channel = self.bot.get_channel(timer['extras']['channel_id'])
            await channel.delete()

        # start 15 minute timer, after which the user will be kicked
        fifteen_minutes = 15 * 60
        expires = round(time.time()) + fifteen_minutes
        self.bot.timers.create(
            guild_id=member.guild.id,
            expires=expires,
            event='captcha_timeout',
            extras={
                'member_id': member.id,
                'tries': 3
            }
        )

        overwrites = {
            member.guild.default_role: discord.PermissionOverwrite(view_channel=False, read_messages=False),
            member: discord.PermissionOverwrite(view_channel=True, read_messages=True, send_messages=True, read_message_history=True)
        }
        category = self.gateway_captcha_category if member.guild == self.gateway_guild else self.main_captcha_category
        user_channel = await member.guild.create_text_channel(member.name, overwrites=overwrites, category=category)
        await self.send_captcha_message(member, user_channel, content=member.mention)

    @staticmethod
    def random_string():
        """Function for generating a random string for the captcha image."""
        # removes characters that dont look that different in lower and upper case
        letters = re.sub(r'[cCkKoOvVwWxXzZsS]*', '', (string.ascii_letters + string.digits + '!@#$%^&*+'))
        result = ''.join((random.choice(letters) for _ in range(10)))
        return result

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        timer = db.timers.find_one({'event': 'captcha_timeout', 'extras.member_id': message.author.id})
        if not timer:
            return

        user_channel_id = timer['extras']['channel_id']
        if message.channel.id != user_channel_id:
            return

        if message.content != timer['extras']['captcha_text']:
            tries = self.get_tries(message.author.id)
            if tries == 1:
                return await self.on_captcha_timeout_timer_over(timer)

            captcha_message = await message.channel.fetch_message(timer['extras']['message_id'])
            await captcha_message.delete()

            db.timers.update_one({'event': 'captcha_timeout', 'extras.member_id': message.author.id}, {'$inc': {'extras.tries': -1}})
            return await self.send_captcha_message(message.author, message.channel)

        await self.invite_channel.create_invite(max_uses=1, unique=True)
        # TODO: check if invite was used by the person who made it

    async def on_member_remove(self, member: discord.Member):
        timer = db.timers.find_one({'event': 'captcha_timeout', 'extras.member_id': member.id})
        if timer:
            # delete user channel
            channel_id = timer['extras']['channel_id']
            try:
                await self.bot.http.delete_channel(channel_id)
            except:
                # ignore error
                pass

            # delete timer
            db.timers.delete_one({'event': 'captcha_timeout', 'extras.member_id': member.id})

    def create_captcha_image(self) -> tuple[io.BytesIO, str]:
        captcha_text = self.random_string()
        captcha_image = self.image_captcha.generate_image(captcha_text)
        image_bytes = io.BytesIO()
        captcha_image.save(image_bytes, 'PNG')
        image_bytes.seek(0)

        return image_bytes, captcha_text

    def construct_captcha_embed(self, member_id) -> discord.Embed:
        embed = discord.Embed(colour=config.EMBED_COLOUR, timestamp=datetime.now())
        embed.set_author(name='Captcha Verification', icon_url=self.main_guild.icon_url)
        embed.set_image(url=f'attachment://captcha.png')
        tries = self.get_tries(member_id)
        embed.set_footer(text=f'Tries Left: {tries}')

        return embed

    def get_tries(self, member_id: int):
        timer = db.timers.find_one({'event': 'captcha_timeout', 'extras.member_id': member_id})
        tries = timer['extras']['tries'] if timer else 3
        return tries

    async def send_captcha_message(self, member: discord.Member, channel: discord.TextChannel, content: str = '') -> str:
        captcha_embed = self.construct_captcha_embed(member.id)
        captcha_image, captcha_text = self.create_captcha_image()
        captcha_message = await channel.send(file=discord.File(fp=captcha_image, filename=f'captcha.png'), embed=captcha_embed, content=content)

        async def reload(*_):
            await captcha_message.delete()
            await self.send_captcha_message(member, channel)

        db.timers.update_one(
            {'event': 'captcha_timeout', 'extras.member_id': member.id},
            {'$set': {
                'extras.captcha_text': captcha_text,
                'extras.message_id': captcha_message.id,
                'extras.channel_id': channel.id
            }}
        )

        buttons = {'🔄': reload}
        reaction_menu = ReactionMenu(captcha_message, buttons)
        self.bot.reaction_menus.add(reaction_menu)

        return captcha_text