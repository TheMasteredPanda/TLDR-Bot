from discord.ext import commands
from modules import database
db = database.Connection()


class Context(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bot = kwargs['bot']
        self.message = kwargs['message']
        self.guild_id = self.message.guild.id

    @property
    def session(self):
        return self.bot.session
