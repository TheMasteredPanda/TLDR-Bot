from discord.ext import commands
from modules import database
from config import DEV_IDS

db = database.Connection()


class Context(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bot = kwargs['bot']
        self.message = kwargs['message']
        if not self.message.author.bot:
            self.author_pp = self.pp
            self.author_p_level = self.p_level
            self.author_clearance = self.clearance
            self.author_hp = self.hp
            self.author_h_level = self.h_level
            self.author_role = self.role
            self.author_h_role = self.h_role

    @property
    def session(self):
        return self.bot.session

    @property
    def role(self):
        return db.get_levels('p_role', self.message.guild.id, self.message.author.id)

    @property
    def h_role(self):
        return db.get_levels('h_role', self.message.guild.id, self.message.author.id)

    @property
    def hp(self):
        return db.get_levels('hp', self.message.guild.id, self.message.author.id)

    @property
    def h_level(self):
        return db.get_levels('h_level', self.message.guild.id, self.message.author.id)

    @property
    def pp(self):
        return db.get_levels('pp', self.message.guild.id, self.message.author.id)

    @property
    def p_level(self):
        return db.get_levels('p_level', self.message.guild.id, self.message.author.id)

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
