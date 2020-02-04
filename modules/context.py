from discord.ext import commands
from modules import database
from config import DEV_IDS

db = database.Connection()


class Context(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bot = kwargs['bot']
        self.message = kwargs['message']
        if not self.message.guild:
            return
        if not self.message.author.bot:
            self.author_pp = self.get('pp')
            self.author_p_level = self.get('p_level')
            self.author_clearance = self.clearance
            self.author_hp = self.get('hp')
            self.author_h_level = self.get('h_level')
            self.author_p_role = self.get('p_role')
            self.author_h_role = self.get('h_role')

    @property
    def session(self):
        return self.bot.session

    def get(self, value):
        return db.get_levels(value, self.message.guild.id, self.message.author.id)

    @property
    def clearance(self):
        user_permissions = self.channel.permissions_for(self.message.author)
        clearance = []

        if self.message.author.id in DEV_IDS:
            clearance.append('Dev')
        if user_permissions.administrator:
            clearance.append('Admin')
        if user_permissions.manage_messages:
            clearance.append('Mod')
        clearance.append('User')

        return clearance
