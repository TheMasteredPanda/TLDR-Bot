import discord
import re
import requests
import config
import random
from io import BytesIO
from modules import command, embed_maker
from discord.ext import commands


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Distort images or peoples profile pictures', usage='distort [image link | @Member]',
                      examples=['disort https://i.imgur.com/75Jr3.jpg', 'distort @Hattyot', 'distort Hattyot'], clearance='User', cls=command.Command)
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
                # Check if source is member
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

        response = requests.get(f'{config.WEB_API_URL}/distort?img={url}')
        if not response:
            embed = embed_maker.message(ctx, 'Error getting image', colour='red')
            return await ctx.send(embed=embed)

        distorted_image = BytesIO(response.content)
        distorted_image.seek(0)

        embed = discord.Embed()
        embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        embed.set_image(url='attachment://distorted.png')
        return await ctx.send(file=discord.File(fp=distorted_image, filename='distorted.png'), embed=embed)


def setup(bot):
    bot.add_cog(Fun(bot))
