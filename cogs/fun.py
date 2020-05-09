import discord
import re
import requests
import config
from io import BytesIO
from modules import command, embed_maker
from discord.ext import commands


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def do_distort(self, ctx, url, img, layers):
        magikd_buffer = BytesIO()

        with wImage() as new_image:
            with wImage(file=img) as source:
                if source.size >= (3000, 3000):
                    embed = embed_maker.message(ctx, 'Image exceeds maximum resolution `3000x3000`', colour='red')
                    return None, embed

                def transform_image(image):
                    image.transform(resize=f'400x400<')
                    image.transform(resize=f'400x400<')
                    for j in range(layers):
                        image.liquid_rescale(width=int(image.width * 0.5), height=int(image.height * 0.5), delta_x=1)
                        image.liquid_rescale(width=int(image.width * 1.5), height=int(image.height * 1.5), delta_x=2)

                if len(source.sequence) > 1:
                    for i, frame in enumerate(source.sequence):
                        transform_image(frame)
                        new_image.sequence.append(frame)
                else:
                    transform_image(source)
                    source.transform(resize='800x800')
                    new_image.sequence.append(source)

            new_image.save(magikd_buffer)
            magikd_buffer.seek(0)

            embed = discord.Embed()
            embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
            ext = 'gif' if url.endswith('.gif') else 'png'
            embed.set_image(url=f'attachment://distorted.{ext}')

            return discord.File(fp=magikd_buffer, filename=f'distorted.{ext}'), embed

    @commands.command(help='Distort images or peoples profile pictures', usage='distort [image link | @Member]',
                      examples=['disort https://i.imgur.com/75Jr3.jpg', 'distort @Hattyot', 'distort Hattyot'], clearance='User', cls=command.Command)
    async def distort(self, ctx, source=None):
        url = None
        mem = None

        # check if source is member
        if source and ctx.message.mentions:
            mem = ctx.message.mentions[0]
        elif source:
            regex = re.compile(fr'({source.lower()})')
            mem = discord.utils.find(lambda m: re.findall(regex, m.name.lower()) or re.findall(regex, m.display_name.lower()) or m.id == source, ctx.guild.members)
            if mem is None:
                url = source

        if source is None:
            mem = ctx.author

        if source and mem is None and url is None:
            return

        if mem:
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
