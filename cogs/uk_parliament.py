import functools
import math
from modules.reaction_menus import BookMenu
from typing import Union
from discord import embeds

from ukparliament.structures.bills import Bill
from bot import TLDR
from modules import cls, embed_maker
from modules.utils import ParseArgs
from discord.ext import commands
from discord.ext.commands import Context
from ukparliament.bills import SearchBillsBuilder, SearchBillsSortOrder

class UKCommand(commands.Cog):
    def __init__(self, bot: TLDR):
        self.parliament = bot.get_parliament()
        self.bot = bot

    async def load_parliament_data(self):
        await self.parliament.load()

    @staticmethod
    async def construct_bills_search_embed(ctx: Context, bills: list[Bill], max_page_num: int, page_limit: int, *, page: int):
        if len(bills) == 0: return await embed_maker.message(ctx, description='No bills found.')

        bits = []
        next_line = '\n'
        print(f'Limits: {page_limit * (page - 1)}:{page_limit * page}')
        for i, bill in enumerate(bills[page_limit * (page - 1):page_limit * page]):
            bill_title = bill.get_title()
            print(bill_title)
            description = bill.get_long_title()
            stage = bill.get_current_stage()
            bill_url = f"https://bills.parliament.uk/bills/{bill.get_bill_id()}"
            bits.append(f"**{(i + 1) + (page_limit * (page - 1))}. [{bill_title}]({bill_url})**{next_line}**Description:** {description}")

        embed = await embed_maker.message(ctx, description=next_line.join(bits), 
                author={'name': 'UKParliament Bills'}, 
                footer={'text': f'Page {page}/{max_page_num}'}) 
        return embed

    @commands.group(
                help='To access the commands interfacing the UK Parliament Site.',
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
                help='For commands relating to bills',
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
            usage='uk bills search <search terms>',
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
                ],
            cls=cls.Command
            )
    async def bills_search(self, ctx: commands.Context, *, args: ParseArgs = None):
        builder = SearchBillsBuilder.builder() 
        if args is None: return

        if args['pre'] is not None:
            builder.set_search_term(args['pre'])

        bills = await self.parliament.search_bills(builder.set_sort_order(SearchBillsSortOrder.DATE_UPDATED_DESENDING).build())
        formatted_bills = []
        next_line = '\n'
        
        print(f"Found {len(bills)} Bills")
        print('\n'.join(list(map(lambda bill: bill.get_title(), bills))))
        max_page_size = 5
        max_page_num = math.ceil(len(bills) / max_page_size)
        if max_page_num == 0: max_page_num = 1
        page_constructor = functools.partial(
                self.construct_bills_search_embed,
                ctx=ctx,
                bills=bills,
                max_page_num=max_page_num,
                page_limit=max_page_size
                )

        embed = await page_constructor(page=1)
        message = await ctx.send(embed=embed)
        menu = BookMenu(message, author=ctx.author, page=1, max_page_num=max_page_num, page_constructor=page_constructor) # type: ignore 
        self.bot.reaction_menus.add(menu)
        
def setup(bot: TLDR):
    bot.add_cog(UKCommand(bot))
