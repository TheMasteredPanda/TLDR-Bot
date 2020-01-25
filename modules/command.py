from discord.ext import commands


class Command(commands.Command):
    def __init__(self, func, **kwargs):
        super().__init__(func, **kwargs)
        self.examples = kwargs['examples']
        self.clearence = kwargs['clearence']
