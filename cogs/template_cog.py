from bot import TLDR
from modules import cls, embed_maker
from modules.utils import ParseArgs
from typing import Union
from discord.ext import commands


class Template(commands.Cog):
    def __init__(self, bot: TLDR):
        self.bot = bot

    @commands.command(
        help='General description of the command/what the command does',
        usage='template_command [arg that is required] (arg that is optional)',
        examples=['template_command needed_arg', 'template_command needed_arg2 optional_arg'],
        clearance='Mod',  # Clearances: User, Mod, Admin, Dev, can be seen/edited in config.py
        Admin=cls.Help(
            # clearance in here will be set to Admin automatically, it doesnt need to be defined
            help='You can specify different help for people with higher perms, specially defined help like this one needs to be a higher clearance than the base one',
            usage='template_command [args]',
            examples=['template_command --arg1'],
            command_args=[
                # the third value in the arg tuple is the type the arg value will be converted to, if the type is a list, multiple of the same arg will be pushed to a list
                # the type can also be a command, like modules.format_time.parse
                # If the shorter arg is set to None, the user will only be presented with the long option
                (('--arg1', '-a1', str), 'Description of arg1'),  # These need to be defined when using ParseArgs, otherwise it won't know what to look for
                (('--arg2', None, list), 'Description of arg2')
            ]
        ),
        cls=cls.Command  # here so we can actually use all the custom kwargs\
    )
    # when giving an arg a type, discord.py will attempt to convert that arg to the given type
    # rest_of_the_args will attempt to convert to ParseArgs, if it fails, it'll convert to str
    def template_command(self, ctx: commands.Context, first_arg: str = None, *, rest_of_the_args: Union[ParseArgs, str] = None):
        # if the command doesnt do anything without args, it's best to include this line in the beginning
        # it'll send info about the command and how to use it
        if first_arg is None:
            return await embed_maker.command_error(ctx)

        # if you want to send a response, please use embed_maker.message or embed_maker.error
        # with embed_maker.message you will need to give it `send` kwarg, if send is missing, it'll return an embed
        if first_arg.isdigit():
            return await embed_maker.error(ctx, 'Error message')
        else:
            return await embed_maker.message(ctx, description='Description or whatever', send=True)

    @commands.group(
        invoke_without_command=True, # this kwarg needs to be here, otherwise subcommands will be ignored
        help='General description of the command/what the command does',
        usage='template_group_command [required arg]',
        examples=['template_command needed_arg 123'],
        clearance='Mod',  # Clearances: User, Mod, Admin, Dev, can be seen/edited in config.py
        cls=cls.Group  # don't forget to change this to cls.Group
    )
    async def template_group_command(self, ctx: commands.Context, *, args: str):
        pass

    @template_group_command.command(
        name='sub_command', # the name needs to be defined on sub commands
        help='Description',
        usage='template_group_command sub_command [args]',
        examples=['template_group_command sub_command hello 123'],
        clearance='Mod',
        cls=cls.Command,
    )
    async def template_group_command_sub_command(self, ctx: commands.Context, *, args: str):
        pass


def setup(bot: TLDR):
    bot.add_cog(Template(bot))
