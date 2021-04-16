import functools
import math
from modules.custom_commands import Message

from ukparliament.structures.members import PartyMember
from modules.reaction_menus import BookMenu
from typing import Union
from discord import embeds

from ukparliament.structures.bills import Bill, BillType, CommonsDivision, LordsDivision
from bot import TLDR
from modules import cls, embed_maker
from modules.utils import ParseArgs
from discord.ext import commands
from discord.ext.commands import Context
from ukparliament.bills import SearchBillsBuilder, SearchBillsSortOrder
from collections import namedtuple

Pair = namedtuple("Pair", ["enum", "max_page_num"])

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
        for i, bill in enumerate(bills[page_limit * (page - 1):page_limit * page]):
            bill_title = bill.get_title()
            description = bill.get_long_title()[0:160] + '...'
            stage = bill.get_current_stage()
            bill_id = bill.get_bill_id()
            bill_url = f"https://bills.parliament.uk/bills/{bill.get_bill_id()}"
            bits.append(f"**{(i + 1) + (page_limit * (page - 1))}. [{bill_title}]({bill_url}) | ID: {bill_id}**{next_line}**Description:** {description}")

        embed = await embed_maker.message(ctx, description=next_line.join(bits), 
                author={'name': 'UKParliament Bills'}, 
                footer={'text': f'Page {page}/{max_page_num}'}) 
        return embed

    @staticmethod
    async def construct_bill_info_embed(ctx: Context, bill: Bill, c_divisions: list[CommonsDivision], l_divisions: list[LordsDivision], page_limit: int, *, page: int):
        formatted_bill_information = [
                f"**Title:** {bill.get_title()}",
                f"**Description:** {bill.get_long_title()}",
                f"**Introduced:** {bill.get_date_introduced().strftime('%Y-%m-%d %H:%M:%S')}",
                f"**Last Update:** {bill.get_last_update().strftime('%Y-%m-%d %H:%M:%S')}",
                f"**Act of Parliament:** {'Yes' if bill.is_act() else 'No'}"
                ]

        if bill.has_royal_assent():
            formatted_bill_information.append(f"**Current Stage:** Received Royal Assent")
        else:
            formatted_bill_information.extend([
                f"**Current Stage:** {bill.get_current_stage().get_name()}",
                f"**Current House:** {bill.get_current_house()}"
                ])

        total_length = len(l_divisions) + len(c_divisions) + len(formatted_bill_information)
        max_pages = math.ceil(total_length / page_limit)
        pages: list[embeds.Embed] = []

        async def template(description: str, title: str) -> embeds.Embed:
            return await embed_maker.message(ctx, title=title, description=description, author= {'name': 'UKParliament Bill'}, footer={'text': f'Page: {page}/{max_pages}'}) # type: ignore
               
        next_line = '\n'
        if len(l_divisions) > 0:
            l_d_pages = math.ceil(len(l_divisions) / page_limit)
            bits = []
            for i, division in enumerate(l_divisions):
                did_pass = division.get_aye_count() > division.get_no_count()
                bits.append(f"**{i + 1}. [{division.get_division_title()}](https://votes.parliament.uk/Votes/Lords/Division/{division.get_id()})**{next_line}" + f"**ID:** {division.get_id()}{next_line}" + (f"**Summary:** {division.get_amendment_motion_notes()[0:150].replace('<p>', '').replace('</p>', '')}..." if division.get_amendment_motion_notes() is not None and division.get_amendment_motion_notes() != '' else '') + f"{next_line}**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division of {division.get_aye_count() if did_pass else division.get_no_count()} {'Ayes' if did_pass else 'Noes'} to {division.get_aye_count() if did_pass is False else division.get_no_count()} {'Noes' if did_pass else 'Ayes'}" + f"{next_line}**Division Date:** {division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}") 
                if i == (page_limit - 1) or i == (len(l_divisions) - 1):
                    pages.append(await template(title='Lords Divisions', description='\n'.join(bits)))
                    bits.clear()

        if len(c_divisions) > 0:
            c_d_pages = math.ceil(len(l_divisions) / page_limit)

            bits = []
            for i, division in enumerate(c_divisions):
                did_pass = division.get_aye_count() > division.get_no_count()
                bits.append(f"**{i + 1}. [{division.get_division_title()}](https://votes.parliament.uk/Votes/Lords/Division/{division.get_id()})**{next_line}" + f"**ID:** {division.get_id()}" + f"{next_line}**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division of {division.get_aye_count() if did_pass else division.get_no_count()} {'Ayes' if did_pass else 'Noes'} to {division.get_aye_count() if did_pass is False else division.get_no_count()} {'Noes' if did_pass else 'Ayes'}" + f"{next_line}**Division Date:** {division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}")
                if i == (page_limit - 1) or i == (len(l_divisions) - 1):
                    pages.append(await template(title='Commons Divisions', description='\n'.join(bits)))
                    bits.clear()
        

        first_page: embeds.Embed = await embed_maker.message(ctx, description='\n'.join(formatted_bill_information), author={'name': 'UKParliament Bill'}, footer={'text': f'Page: {page}/{max_pages}'}) #type: ignore 
        pages.insert(0, first_page)
        return (pages[(page - 1)], len(pages))

    @staticmethod
    async def construct_divisions_lords_embed(ctx: commands.Context, divisions: list[LordsDivision], page_limit: int, *, page:int):
        max_pages = math.ceil(len(divisions) / page_limit)

        bits = []
        next_line = '\n'
        for i, division in enumerate(divisions[page_limit * (page - 1):page_limit * page]):
            did_pass = division.get_aye_count() > division.get_no_count()
            bits.append(f"**{(page_limit * (page -1)) + i + 1}. {division.get_division_title()}**{next_line}**ID:** {division.get_id()}{next_line}**Summary:** {division.get_amendment_motion_notes()[0:150]}{next_line}**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division of {division.get_aye_count() if did_pass else division.get_no_count()} {'Ayes' if did_pass else 'Notes'} to {division.get_no_count() if did_pass else division.get_aye_count()} {'Noes' if did_pass else 'Ayes'}{next_line}**Division Date:** {division.get_division_date().strftime('%Y-%m-%s %H:%M:%S')}")

        embed = await embed_maker.message(ctx, description=next_line.join(bits), author={'name': 'UKParliament Division'}, footer={'text': f'Page  {page}/{max_pages}'})
        return (embed, max_pages)

    @staticmethod
    async def construct_divisions_commons_embed(ctx: commands.Context, divisions: list[CommonsDivision], page_limit: int, *, page: int):
        max_pages = math.ceil(len(divisions) / page_limit)
        next_line = '\n'
        bits = []
        for i, division in enumerate(divisions[page_limit * (page - 1):page_limit * page]):
            did_pass = division.get_aye_count() > division.get_no_count()
            bits.append(f"**{(page_limit * (page -1)) + i + 1}. [{division.get_division_title()[0:100]}](https://votes.parliament.uk/Votes/Commons/Division/{division.get_id()})**{next_line}**ID:** {division.get_id()}{next_line}**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division of {division.get_aye_count() if did_pass else division.get_no_count()} {'Ayes' if did_pass else 'Notes'} to {division.get_no_count() if did_pass else division.get_aye_count()} {'Noes' if did_pass else 'Ayes'}{next_line}**Division Date:** {division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}")

        embed: embeds.Embed = await embed_maker.message(ctx, description=next_line.join(bits), author={'name': 'UKParliament Division'}, footer={'text': f'Page {page}/{max_pages}'}) # type: ignore
        return (embed, max_pages)

    @commands.group(
                help='To access the commands interfacing the UK Parliament Site.',
                invoke_without_command=True,
                clearance='User',
                sub_commands=[
                        'bills',
                        'divisions',
                        'mps'
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

    @uk.group(
            help='For commands relating to divisions',
            invoke_without_command=True,
            clearance='User',
            sub_commands=[
                'lsearch',
                'csearch',
                'linfo',
                'cinfo'
                ],
            cls=cls.Group
            )
    async def divisions(self, ctx: commands.Context):
        pass

    @divisions.command(
            name='csearch',
            help='Search for commons divisions',
            clearence='User'
            )
    async def division_commons_search(self, ctx: commands.Context, *, search_term = ""):
        divisions = await self.parliament.search_for_commons_divisions(search_term)
        if len(divisions) == 0:
            await embed_maker.message(ctx, description=f"Couldn't find any Commons divisions under search term '{search_term}'.")

        page_constructor = functools.partial(self.construct_divisions_commons_embed, ctx=ctx, divisions=divisions, page_limit=5)
        pair = await page_constructor(page=1)
        message = await ctx.send(embed=pair[0])

        async def temp_page_constructor(page: int):
            pair = await page_constructor(page=page)
            return pair[0]
        
        menu = BookMenu(message=message, author=ctx.author, max_page_num=pair[1], page_constructor=temp_page_constructor, page=1) # type: ignore
        self.bot.reaction_menus.add(menu)


    @divisions.command(
                name='lsearch',
                help='Search for lords divisions',
                clearence='User'
            )
    async def division_lords_search(self, ctx: commands.Context, *, search_term = ""):
        divisions = await self.parliament.search_for_lords_division(search_term)
        if len(divisions) == 0: 
            await embed_maker.message(ctx, description=f"Couldn't find any Lords divisions under the search term '{search_term}'.")
            return


        page_constructor = functools.partial(self.construct_divisions_lords_embed, ctx=ctx, divisions=divisions, page_limit=10)
        pair = await page_constructor(page=1)
        embed = pair[0]
        max_pages = pair[1]

        async def temp_page_constructor(page: int):
            pair = await page_constructor(page=page)
            return pair[0]

        message = await ctx.send(embed=embed)
        menu = BookMenu(message=message, author=ctx.author, max_page_num=max_pages, page_constructor=temp_page_constructor, page=1) # type: ignore
        self.bot.reaction_menus.add(menu)

    @bills.command(
            name='info',
            help='To display in more detail information about a bill.',
            cls=cls.Command
            )
    async def bill_info(self, ctx: commands.Context, bill_id: int):
        try:
            bill = await self.parliament.get_bill(bill_id)
            c_divisions = await self.parliament.search_for_commons_divisions(bill.get_title())
            l_divisions = await self.parliament.search_for_lords_division(bill.get_title())
            page_constructor = functools.partial(self.construct_bill_info_embed, ctx=ctx, bill=bill, l_divisions=l_divisions, c_divisions=c_divisions, page_limit=10)
            pair: tuple[embeds.Embed, int] = await page_constructor(page=1)
            message = await ctx.send(embed=pair[0])
            async def temp_page_constructor(page: int): #Due to the unique nature of ther result, this is needed ot return only the embed.
                pair = await page_constructor(page=page)
                return pair[0]

            menu = BookMenu(message, author=ctx.author, page=1, max_page_num=pair[1], page_constructor=temp_page_constructor) # type: ignore
            self.bot.reaction_menus.add(menu)

        except Exception as ignore:
            await embed_maker.message(ctx, description=f"Couldn't fetch bill {bill_id}.", send=True)
            raise ignore

    @bills.command(
            help='Seach for bills using certain values and search terms',
            usage='uk bills search <search terms>',
            name='search',
            clearence='User',
            command_args=[
                    (('--query', None, str), 'Search Term to search for'),
                    (('--sponsor', None, str), 'The name of the bill sponsor'),
                    (('--types', None, str), 'The type of bill to search for'),
                    (('--order', None, str), 'The order to display the searches in'),
                    (('--currenthouse', None, str), 'The house the bill is currently in'),
                    (('--originatinghouse', None, str), 'The house the bill originated in'),
                    (('--stage', None, str), 'What stage the bill to search for is in')
                ],
            cls=cls.Command
            )
    async def bills_search(self, ctx: commands.Context, *, args: ParseArgs = None):
        builder = SearchBillsBuilder.builder() 
        if args is None: return

        if args['pre'] is not None:
            builder.set_search_term(args['pre'])
        else:
            if args['query'] is not None:
                builder.set_search_term(args['query'])
            if args['sponsor'] is not None:
                member = self.parliament.get_member_by_name(args['sponsor'])
                if member is None:
                    await embed_maker.message(ctx, description=f"Couldn't find member {args['sponsor']}", send=True)
                builder.set_member_id(member.get_id())
            if args['types'] is not None:
                split_types = args['types'].split(' ')
                types = self.parliament.get_bill_types()
                arg_types = []
                for t_type in split_types:
                    for b_type in types:
                        if b_type.get_name().lower() == t_type.lower():
                            arg_types.append(b_type)
                builder.set_bill_type(arg_types)
            if args['order'] is not None:
                try:
                    order_enum = SearchBillsSortOrder.from_name(args['order'])
                except Exception as ignore:
                    formatted_acceptable_args = list(map(lambda order: order.name.lower(), SearchBillsSortOrder))
                    next_line = '\n'
                    await embed_maker.message(ctx, description=f"Couldn't find order type {args['order']}. Acceptable arguments: {next_line}{next_line.join(formatted_acceptable_args)}", send=True)
            if args['currenthouse'] is not None:
                if args['currenthouse'].lower() not in ['all', 'commons', 'lords', 'unassigned']:
                    await embed_maker.message(ctx, description=f"Incorrect house value. Accepted arguments: 'all', 'commons', 'lords', 'unassigned'", send=True)
                    return
                builder.set_current_house(args['currenthouse'])
            if args['originatinghouse'] is not None:
                if args['originatinghouse'] not in ['all', 'commons', 'lords', 'unassigned']:
                    await embed_maker.message(ctx, description=f"Incorrect house value. Accepted arguments: 'all', 'commons', 'lords', 'unassigned'", send=True)
                    return
                builder.set_originating_house(args['originatinghouse'])


        bills = await self.parliament.search_bills(builder.set_sort_order(SearchBillsSortOrder.DATE_UPDATED_DESENDING).build())
        formatted_bills = []
        next_line = '\n'
        
        max_page_size = 4
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
