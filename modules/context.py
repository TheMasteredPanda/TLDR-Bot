from discord.ext import commands
from modules import database
db = database.Connection()


class Context(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bot = kwargs['bot']
        self.message = kwargs['message']
        if not self.message.author.bot:
            self.author_xp = self.xp
            self.author_level = self.level

    @property
    def session(self):
        return self.bot.session

    @property
    def xp(self):
        return db.get_levels(self.message.guild.id, self.message.author.id, 'xp')

    @property
    def level(self):
        return db.get_levels(self.message.guild.id, self.message.author.id, 'level')
