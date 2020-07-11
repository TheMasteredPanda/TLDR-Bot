import discord
import re
import requests
import config
import json
import aiohttp
import asyncio
from cogs.utils import get_member
from wand.image import Image as Wand
from io import BytesIO
from modules import command, embed_maker
from discord.ext import commands


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='put they gay pride flag on your profile picture', usage='pride', examples=['pride'],
                      clearance='User', cls=command.Command)
    async def pride(self, ctx, source=None):
        url = None

        # check for attachments
        if ctx.message.attachments:
            url = ctx.message.attachments[0].url

        if source is None and url is None:
            url = str(ctx.author.avatar_url)
            url = url.replace('webp', 'png')
        elif url is None:
            # check if source is member
            mem = await get_member(ctx, self.bot, source)
            if mem is None:
                # check if source is emote
                emote_regex = re.compile(r'<:[a-zA-Z0-9_]+:([0-9]+)>$')
                match = re.findall(emote_regex, source)
                if match:
                    emote_id = match[0]
                    url = f'https://cdn.discordapp.com/emojis/{emote_id}.png'
                else:
                    # take source as url
                    url = source
            else:
                url = str(mem.avatar_url)
                url = url.replace('webp', 'png')

        if url is None:
            return

        if config.WEB_API_URL:
            async with aiohttp.ClientSession() as session:
                image_task = asyncio.create_task(self.fetch_image(session, f'{config.WEB_API_URL}/pride?img={url}'))
                content = await image_task

            if not content:
                return await embed_maker.message(ctx, 'Error getting image', colour='red')

            image = BytesIO(content)
            image.seek(0)

        else:
            image = await self.do_pride(ctx, url)
            # checks if do_pride returned message
            if isinstance(image, discord.Message):
                return

        # get file extension
        split = url.split('.')
        extension = split[-1]

        # check if it has arguments after extension
        split = extension.split('?')
        if len(split) > 1:
            extension = split[0]

        embed = discord.Embed()
        embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        embed.set_image(url=f'attachment://pride.{extension}')
        return await ctx.send(file=discord.File(fp=image, filename=f'pride.{extension}'), embed=embed)

    async def do_pride(self, ctx, url):
        async with aiohttp.ClientSession() as session:
            image_task = asyncio.create_task(self.fetch_image(session, url))
            content = await image_task

        if not content:
            return await embed_maker.message(ctx, 'Error getting image', colour='red')

        image = BytesIO(content)
        image.seek(0)

        with Wand() as blended_image:
            with Wand(file=image) as avatar:
                if len(avatar.sequence) > 60:
                    return await embed_maker.message(ctx, 'Too many frames in gif', colour='red')

                with Wand(filename='images/pride.png') as pride_image:
                    pride_image.resize(width=800, height=800)
                    pride_image.transparentize(0.6)

                    def apply_pride(img):
                        img.resize(width=800, height=800)
                        img.composite(pride_image)

                    if len(avatar.sequence) > 1:
                        for frame in avatar.sequence:
                            apply_pride(frame)
                            blended_image.sequence.append(frame)
                    else:
                        apply_pride(avatar)
                        blended_image.sequence.append(avatar)

            buffer = BytesIO()
            blended_image.save(buffer)
            buffer.seek(0)

        return buffer

    def get_random_image(self, url, json_key, *, list_indc=None):
        response = requests.get(url)
        json_text = response.text.encode("ascii", "ignore").decode('ascii')
        if list_indc is not None:
            img_url = json.loads(json_text)[list_indc][json_key]
        else:
            img_url = json.loads(json_text)[json_key]
        # get image extension
        split = img_url.split('.')
        extension = split[-1]

        allowed_extensions = ['jpg', 'jpeg', 'png', 'gif']
        while extension not in allowed_extensions:
            return self.get_random_image(url, json_key)

        image_response = requests.get(img_url)
        image = BytesIO(image_response.content)
        image.seek(0)

        return image, extension

    @commands.command(help='Gets a random dog image', usage='dog', examples=['dog'],
                      clearance='User', cls=command.Command)
    async def dog(self, ctx):
        url = 'https://random.dog/woof.json'
        image, extension = self.get_random_image(url, 'url')

        embed = discord.Embed()
        embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        embed.set_image(url=f'attachment://cat.{extension}')
        return await ctx.send(file=discord.File(fp=image, filename=f'cat.{extension}'), embed=embed)

    @commands.command(help='Gets a random cat image', usage='cat', examples=['cat'],
                      clearance='User', cls=command.Command)
    async def cat(self, ctx):
        url = 'https://api.thecatapi.com/v1/images/search'
        image, extension = self.get_random_image(url, 'url', list_indc=0)

        embed = discord.Embed()
        embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        embed.set_image(url=f'attachment://cat.{extension}')
        return await ctx.send(file=discord.File(fp=image, filename=f'cat.{extension}'), embed=embed)

    @commands.command(help='Gets a random dad joke', usage='dadjoke', examples=['dadjoke'],
                      clearance='User', cls=command.Command)
    async def dadjoke(self, ctx):
        url = "https://icanhazdadjoke.com/"
        response = requests.get(url, headers={"Accept": "text/plain"})
        joke = response.text.encode("ascii", "ignore").decode("ascii")

        return await embed_maker.message(ctx, joke)

    @commands.command(help='Distort images or peoples profile pictures', usage='distort [image link | @Member]',
                      examples=['disort https://i.imgur.com/75Jr3.jpg', 'distort @Hattyot', 'distort Hattyot'],
                      clearance='User', cls=command.Command)
    async def distort(self, ctx, source=None):
        url = None

        # check for attachments
        if ctx.message.attachments:
            url = ctx.message.attachments[0].url

        if source is None and url is None:
            url = str(ctx.author.avatar_url)
            url = url.replace('webp', 'png')
        elif url is None:
            # check if source is member
            mem = await get_member(ctx, self.bot, source)
            if mem is None:
                # check if source is emote
                emote_regex = re.compile(r'<:[a-zA-Z0-9_]+:([0-9]+)>$')
                match = re.findall(emote_regex, source)
                if match:
                    emote_id = match[0]
                    url = f'https://cdn.discordapp.com/emojis/{emote_id}.png'
                else:
                    # take source as url
                    url = source
            else:
                url = str(mem.avatar_url)
                url = url.replace('webp', 'png')

        if url is None:
            return

        if config.WEB_API_URL:
            async with aiohttp.ClientSession() as session:
                image_task = asyncio.create_task(self.fetch_image(session, f'{config.WEB_API_URL}/distort?img={url}'))
                content = await image_task

            if not content:
                return await embed_maker.message(ctx, 'Error getting image', colour='red')

            image = BytesIO(content)
            image.seek(0)

        else:
            image = await self.do_distort(ctx, url)

        # get file extension
        split = url.split('.')
        extension = split[-1]

        # check if it has arguments after extension
        split = extension.split('?')
        if len(split) > 1:
            extension = split[0]

        embed = discord.Embed()
        embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        embed.set_image(url=f'attachment://distorted.{extension}')
        return await ctx.send(file=discord.File(fp=image, filename=f'distorted.{extension}'), embed=embed)

    async def do_distort(self, ctx, url):
        async with aiohttp.ClientSession() as session:
            image_task = asyncio.create_task(self.fetch_image(session, url))
            content = await image_task

        if not content:
            return await embed_maker.message(ctx, 'Error getting image', colour='red')

        _img = BytesIO(content)
        _img.seek(0)

        with Wand() as new_image:
            with Wand(file=_img) as img:
                if len(img.sequence) > 60:
                    return 'Gif has too many frames'

                def transform_image(img):
                    img.resize(width=800, height=800)
                    img.liquid_rescale(width=int(img.width * 0.5), height=int(img.height * 0.5), delta_x=1)
                    img.liquid_rescale(width=int(img.width * 1.5), height=int(img.height * 1.5), delta_x=2)

                if len(img.sequence) > 1:
                    for frame in img.sequence:
                        transform_image(frame)
                        new_image.sequence.append(frame)
                else:
                    transform_image(img)
                    new_image.sequence.append(img)

            magikd_buffer = BytesIO()
            new_image.save(magikd_buffer)
            magikd_buffer.seek(0)

        return magikd_buffer

    @staticmethod
    async def fetch_image(session, url):
        async with session.get(url) as response:
            return await response.read()


def setup(bot):
    bot.add_cog(Fun(bot))
