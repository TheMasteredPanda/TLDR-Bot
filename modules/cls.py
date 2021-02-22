from discord.ext import commands


class SpecialHelp:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class Group(commands.Group):
    def __init__(self, func, **kwargs):
        super().__init__(func, **kwargs)
        self.examples = kwargs.get('examples', [])
        self.clearance = kwargs.get('clearance', 'User')
        self.sub_commands = kwargs.get('sub_commands', [])
        self.dm_only = kwargs.get('dm_only', False)
        self.special_help = False
        self.parse_args = kwargs.get('parse_args', [])

        for clearance in ['User', 'Mod', 'Admin', 'Dev']:
            if clearance in kwargs:
                self.__setattr__(clearance, kwargs[clearance])
                self.special_help = True
                break


class Command(commands.Command):
    def __init__(self, func, **kwargs):
        super().__init__(func, **kwargs)
        self.examples = kwargs.get('examples', [])
        self.clearance = kwargs.get('clearance', 'User')
        self.dm_only = kwargs.get('dm_only', False)
        self.special_help = False
        self.parse_args = kwargs.get('parse_args', [])

        for clearance in ['User', 'Mod', 'Admin', 'Dev']:
            if clearance in kwargs:
                self.__setattr__(clearance, kwargs[clearance])
                self.special_help = True
                break
