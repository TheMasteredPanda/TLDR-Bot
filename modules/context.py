from discord.ext import commands
from modules import database, cache
from config import DEV_IDS

db = database.Connection()


class Context(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bot = kwargs['bot']
        self.message = kwargs['message']

        if not self.message.guild or self.message.author.bot:
            return

        self.author_pp = self.get('pp')
        self.author_hp = self.get('hp')
        self.author_clearance = self.clearance

    @property
    def session(self):
        return self.bot.session

    def get(self, value):
        return db.get_levels(value, self.message.guild.id, self.message.author.id)

    @property
    def clearance(self):
        user_permissions = self.message.channel.permissions_for(self.message.author)
        clearance = []

        if self.message.author.id in DEV_IDS:
            clearance.append('Dev')
        if user_permissions.administrator:
            clearance.append('Admin')
        if user_permissions.manage_messages:
            clearance.append('Mod')
        clearance.append('User')

        return clearance
