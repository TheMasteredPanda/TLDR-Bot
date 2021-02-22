import json
import requests
from modules import cls, embed_maker
from discord.ext import commands


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        help='Gets a random dog image',
        usage='dog',
        examples=['dog'],
        clearance='User',
        cls=cls.Command
    )
    async def dog(self, ctx):
        url = 'https://random.dog/woof.json'
        response = requests.get(url)
        json_text = response.text.encode("ascii", "ignore").decode('ascii')
        img_url = json.loads(json_text)['url']

        return await ctx.send(img_url)

    @commands.command(
        help='Gets a random cat image',
        usage='cat',
        examples=['cat'],
        clearance='User',
        cls=cls.Command
    )
    async def cat(self, ctx):
        url = 'https://api.thecatapi.com/v1/images/search'
        response = requests.get(url)
        json_text = response.text.encode("ascii", "ignore").decode('ascii')
        img_url = json.loads(json_text)[0]['url']

        return await ctx.send(img_url)

    @commands.command(
        help='Gets a random dad joke',
        usage='dadjoke',
        examples=['dadjoke'],
        clearance='User',
        cls=cls.Command
    )
    async def dadjoke(self, ctx):
        url = "https://icanhazdadjoke.com/"
        response = requests.get(url, headers={"Accept": "text/plain"})
        joke = response.text.encode("ascii", "ignore").decode("ascii")

        return await embed_maker.message(ctx, description=joke)

    @staticmethod
    async def fetch_image(session, url):
        async with session.get(url) as response:
            return await response.read()


def setup(bot):
    bot.add_cog(Fun(bot))
