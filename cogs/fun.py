import re
import config
import aiohttp
import asyncio
import discord

from modules.utils import get_member
from modules import cls, embed_maker
from discord.ext import commands
from io import BytesIO


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        help="put they gay pride flag on a picture",
        usage="pride",
        examples=["pride"],
        clearance="User",
        cls=cls.Command,
    )
    async def pride(self, ctx: commands.Context, *, source: str = None):
        url = None

        # check for attachments
        if ctx.message.attachments:
            url = ctx.message.attachments[0].url

        if source is None and url is None:
            url = str(ctx.author.avatar_url)
            url = url.replace("webp", "png")
        elif url is None:
            # check if source is member
            mem = await get_member(ctx, source)
            if mem is None or isinstance(mem, str):
                # check if source is emote
                emote_regex = re.compile(r"<:[a-zA-Z0-9_]+:([0-9]+)>$")
                match = re.findall(emote_regex, source)
                if match:
                    emote_id = match[0]
                    url = f"https://cdn.discordapp.com/emojis/{emote_id}.png"
                else:
                    # take source as url
                    url = source
            else:
                url = str(mem.avatar_url)
                url = url.replace("webp", "png")

        if url is None:
            return

        if config.WEB_API_URL:
            async with aiohttp.ClientSession() as session:
                image_task = asyncio.create_task(
                    self.fetch_image(session, f"{config.WEB_API_URL}/pride?img={url}")
                )
                content = await image_task

            if not content:
                return await embed_maker.error(ctx, "Error getting image", colour="red")

            image = BytesIO(content)
            image.seek(0)

        else:
            return

        # get file extension
        split = url.split(".")
        extension = split[-1]

        # check if it has arguments after extension
        split = extension.split("?")
        if len(split) > 1:
            extension = split[0]

        embed = discord.Embed()
        embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
        embed.set_image(url=f"attachment://pride.{extension}")
        return await ctx.send(
            file=discord.File(fp=image, filename=f"pride.{extension}"), embed=embed
        )

    @commands.command(
        help="Gets a random dog image",
        usage="dog",
        examples=["dog"],
        clearance="User",
        aliases=["doggo"],
        cls=cls.Command,
    )
    async def dog(self, ctx):
        url = "https://dog.ceo/api/breeds/image/random"
        response = requests.get(url)
        json_text = response.text.encode("ascii", "ignore").decode("ascii")
        img_url = json.loads(json_text)["message"]

        return await ctx.send(img_url)

    @commands.command(
        help="Gets a random cat image",
        usage="cat",
        examples=["cat"],
        clearance="User",
        cls=cls.Command,
    )
    async def cat(self, ctx):
        url = "https://api.thecatapi.com/v1/images/search"
        response = requests.get(url)
        json_text = response.text.encode("ascii", "ignore").decode("ascii")
        img_url = json.loads(json_text)[0]["url"]

        return await ctx.send(img_url)

    @commands.command(
        help="Gets a random dad joke",
        usage="dadjoke",
        examples=["dadjoke"],
        clearance="User",
        cls=cls.Command,
    )
    async def dadjoke(self, ctx: commands.Context):
        url = "https://icanhazdadjoke.com/"
        response = requests.get(url, headers={"Accept": "text/plain"})
        joke = response.text.encode("ascii", "ignore").decode("ascii")

        return await embed_maker.message(ctx, description=joke, send=True)

    @staticmethod
    async def fetch_image(session, url):
        async with session.get(url) as response:
            return await response.read()


def setup(bot):
    bot.add_cog(Fun(bot))
