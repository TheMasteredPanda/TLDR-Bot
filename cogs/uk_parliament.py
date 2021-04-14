from typing import Union
from bot import TLDR
from modules import cls, embed_maker
from modules.utils import ParseArgs
from discord.ext import commands
from ukparliament.bills import SearchBillsBuilder

class UKCommand(commands.Cog):
    def __init__(self, bot: TLDR):
        self.parliament = bot.ukparliament

    async def load_parliament_data(self):
        await self.parliament.load()

    @commands.group(
                invoke_wihtout_command=True,
                clearance='User',
                sub_commands=[
                        'bills'
                    ],
                cls=cls.Group
            )
    async def uk(self, ctx: commands.Context):
        pass

    @uk.group(
                invoke_without_command=True,
                clearance='User',
                sub_commands=[
                    'search'
                    ],
                cls=cls.Group
            )
    async def bills(self, ctx: commands.Context):
        pass

    @bills.command(
            help='Seach for bills using certain values and search terms',
            name='search',
            clearence='User',
            command_args=[
                    (('--query', None, str), 'Search Term to search for'),
                    (('--session', None, str), 'The session to search in'),
                    (('--sponsor-id', None, str), 'The id of the member that sponsored the bill'),
                    (('--sponsor', None, str), 'The name of the bill sponsor'),
                    (('--type', None, str), 'The type of bill to search for'),
                    (('--order', None, str), 'The order to display the searches in'),
                    (('--currenthouse', None, str), 'The house the bill is currently in'),
                    (('--originatinghouse', None, str), 'The house the bill originated in'),
                    (('--department', None, str), 'The department to search in'),
                    (('--stage', None, str), 'What stage the bill to search for is in')
                ]
            )
    async def bills_search(self, ctx: commands.Context, args: Union[ParseArgs, str] = None):
        builder = SearchBillsBuilder.builder() 

        print(args)

        
def setup(bot: TLDR):
    bot.add_cog(UKCommand(bot))
