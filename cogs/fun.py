import discord
import re
import mimetypes
import requests
from io import BytesIO
from wand.image import Image as wImage
from modules import command, embed_maker
from discord.ext import commands


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Distort images or peoples profile pictures', usage='distort [image link | @Member]',
                      examples=['disort https://i.imgur.com/75Jr3.jpg', 'distort @Hattyot', 'distort Hattyot'], clearance='User', cls=command.Command)
    async def distort(self, ctx, source=None):
        # check if source is member
        url = None
        mem = None
        if source and ctx.message.mentions:
            mem = ctx.message.mentions[0]
        elif source:
            regex = re.compile(fr'({source.lower()})')
            mem = discord.utils.find(lambda m: re.findall(regex, m.name.lower()) or re.findall(regex, m.display_name.lower()) or m.id == source, ctx.guild.members)
            if mem is None:
                # Check if source is image link
                mimetype, encoding = mimetypes.guess_type(source)
                if mimetype and mimetype.startswith('image'):
                    # source is image url
                    url = source

        if source is None:
            mem = ctx.author

        if source and mem is None and url is None:
            return

        if mem:
            url = str(mem.avatar_url).replace('.webp?size=1024', '.png?size=1024')

        try:
            response = requests.get(url)
            _img = BytesIO(response.content)
            _img.seek(0)
            with wImage(file=_img) as img:
                # img.alpha_channel = True
                if img.size >= (3000, 3000):
                    embed = embed_maker.message(ctx, 'Image exceeds maximum resolution `3000x3000`', colour='red')
                    return await ctx.send(embed=embed)

                img.transform(resize='800x800>')
                img.liquid_rescale(width=int(img.width * 0.5), height=int(img.height * 0.5), delta_x=1)
                img.liquid_rescale(width=int(img.width * 1.5), height=int(img.height * 1.5), delta_x=2)

                magikd_buffer = BytesIO()
                img.save(magikd_buffer)
                magikd_buffer.seek(0)

                embed = discord.Embed()
                embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
                embed.set_image(url='attachment://distorted.png')
                return await ctx.send(file=discord.File(fp=magikd_buffer, filename='distorted.png'), embed=embed)
        except:
            return


def setup(bot):
    bot.add_cog(Fun(bot))
