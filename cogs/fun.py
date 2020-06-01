import discord
import re
import requests
import config
import random
import json
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
        mem = None

        # check for attachments
        if ctx.message.attachments:
            url = ctx.message.attachments[0].url

        # check if source is member
        if source and ctx.message.mentions:
            mem = ctx.message.mentions[0]
        elif source:
            # check if source is emote
            emote_regex = re.compile(r'<:[a-zA-Z0-9_]+:([0-9]+)>$')
            match = re.findall(emote_regex, source)
            if match:
                emote = [emote for emote in ctx.guild.emojis if str(emote.id) == match[0]][0]
                url = str(emote.url)
            else:
                # Check if source is member name or id
                regex = re.compile(fr'({source.lower()})')
                mem = discord.utils.find(lambda m: re.findall(regex, m.name.lower()) or re.findall(regex, m.display_name.lower()) or m.id == source, ctx.guild.members)
                if mem is None:
                    url = source

        if source is None:
            mem = ctx.author

        if mem and url is None:
            url = str(mem.avatar_url).replace('webp', 'png')

        if config.WEB_API_URL:
            response = requests.get(f'{config.WEB_API_URL}/pride?img={url}')
            print(response)
            if not response:
                return await embed_maker.message(ctx, 'Error getting image', colour='red')

            image = BytesIO(response.content)
            image.seek(0)

        else:
            image = await self.do_pride(ctx, url)

        embed = discord.Embed()
        embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        embed.set_image(url='attachment://pride.png')
        return await ctx.send(file=discord.File(fp=image, filename='pride.png'), embed=embed)

    async def do_pride(self, ctx, url):
        response = requests.get(url)
        if not response:
            return await embed_maker.message(ctx, 'Error getting image', colour='red')

        image = BytesIO(response.content)
        image.seek(0)

        with Wand() as blended_image:
            with Wand(file=image) as avatar:
                with Wand(filename='images/pride.png') as pride_image:
                    avatar.resize(width=800, height=800)
                    pride_image.resize(width=800, height=800)
                    pride_image.transparentize(0.5)
                    avatar.composite(pride_image)
                    blended_image.sequence.append(avatar.sequence[0])

            buffer = BytesIO()
            blended_image.save(buffer)
            buffer.seek(0)

        return buffer

    def get_random_image(self, url, json_key):
        response = requests.get(url)
        json_text = response.text.encode("ascii", "ignore").decode('ascii')

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
        url = 'http://aws.random.cat/meow'
        image, extension = self.get_random_image(url, 'file')

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
        mem = None

        # check for attachments
        if ctx.message.attachments:
            url = ctx.message.attachments[0].url

        # check if source is member
        if source and ctx.message.mentions:
            mem = ctx.message.mentions[0]
        elif source:
            # check if source is emote
            emote_regex = re.compile(r'<:[a-zA-Z0-9_]+:([0-9]+)>$')
            match = re.findall(emote_regex, source)
            if match:
                emote = [emote for emote in ctx.guild.emojis if str(emote.id) == match[0]][0]
                url = str(emote.url)
            else:
                # Check if source is member name or id
                regex = re.compile(fr'({source.lower()})')
                mem = discord.utils.find(lambda m: re.findall(regex, m.name.lower()) or re.findall(regex, m.display_name.lower()) or m.id == source, ctx.guild.members)
                if mem is None:
                    url = source

        if source is None:
            mem = ctx.author

        # Choose a random member
        if source == 'random':
            mem = random.choice(ctx.guild.members)

        if mem and url is None:
            url = str(mem.avatar_url).replace('webp', 'png')

        if config.WEB_API_URL:
            response = requests.get(f'{config.WEB_API_URL}/distort?img={url}')
            if not response:
                return await embed_maker.message(ctx, 'Error getting image', colour='red')

            image = BytesIO(response.content)
            image.seek(0)

        else:
            image = await self.do_distort(ctx, url)

        embed = discord.Embed()
        embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        embed.set_image(url='attachment://distorted.png')
        return await ctx.send(file=discord.File(fp=image, filename='distorted.png'), embed=embed)

    async def do_distort(self, ctx, url):
        response = requests.get(url)
        if not response:
            return await embed_maker.message(ctx, 'Error getting image', colour='red')

        _img = BytesIO(response.content)
        _img.seek(0)

        with Wand() as new_image:
            with Wand(file=_img) as img:
                def transform_image(img):
                    img.transform(resize='500x500>')
                    img.liquid_rescale(width=int(img.width * 0.5), height=int(img.height * 0.5), delta_x=1)
                    img.liquid_rescale(width=int(img.width * 1.5), height=int(img.height * 1.5), delta_x=2)
                    img.transform(resize='500x500')

                if len(img.sequence) > 1:
                    transform_image(img.sequence[0])
                    new_image.sequence.append(img.sequence[0])
                else:
                    transform_image(img)
                    new_image.sequence.append(img)

            magikd_buffer = BytesIO()
            new_image.save(magikd_buffer)
            magikd_buffer.seek(0)

        return magikd_buffer

def setup(bot):
    bot.add_cog(Fun(bot))
