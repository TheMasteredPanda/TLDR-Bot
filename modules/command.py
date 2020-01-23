from discord.ext import commands


class Command(commands.Command):
    def __init__(self, func, **kwargs):
        super().__init__(func, **kwargs)
        # self.description = kwargs['description']
        # self.usage = kwargs['usage']
        self.examples = kwargs['examples']
        self.clearence = kwargs['clearence']
