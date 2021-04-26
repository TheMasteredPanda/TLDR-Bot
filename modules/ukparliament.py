from datetime import datetime
import discord
from discord.embeds import Embed
from discord.guild import Guild
import matplotlib.pyplot as plt
import time
import aiofiles
import aiohttp
import random
from discord import File
import string
from typing import Union
import math
from PIL import ImageDraw, Image, ImageFont
from ukparliament.structures.bills import Bill, CommonsDivision, LordsDivision
from ukparliament.structures.members import ElectionResult, Party, PartyMember
from ukparliament.bills_tracker import Conditions, Feed, FeedUpdate, BillsStorage, PublicationUpdate
from ukparliament.divisions_tracker import DivisionStorage
from ukparliament.utils import BetterEnum
from discord.ext import tasks
from ukparliament.ukparliament import UKParliament
from modules import database
import config
import os


class PartyColour(BetterEnum):
    ALBA = {"id": 1034, "colour": '#73BFFA'}
    ALLIANCE = {"id": 1, "colour": '#D5D5D5'}
    CONSERVATIVE = {"id": 4, "colour": '#489FF8'}
    DUP = {"id": 7, "colour": '#3274B5'}
    GREEN = {"id": 44, "colour": '#82D552'}
    INDEPENDENT = {"id": 8, "colour": '#929292'}
    LABOUR = {"id": 15, "colour": '#DB3B26'}
    LIBERAL = {"id": 17, "colour": '#F19937'}
    PLAID_CYMRU = {"id": 22, "colour": '#54AE33'}
    SNP = {"id": 29, "colour": '#EFBD40'}
    SINN_FEIN = {"id": 30, "colour": '#986541'}
    SDLP = {"id": 31, "colour": '#ED6D57'}
    BISHOPS = {"id": 3, "colour": '#8648BA'}
    CONSERVATIVE_IND = {"id": 5, 'colour': "#ED6D57"}
    CROSSBENCH = {"id": 6, 'colour': "#A99166"}
    IND_SOCIAL_DEMOCRATS = {"id": 53, 'colour': '#A62A16'}
    LABOUR_IND = {"id": 43, 'colour': '#DE68A5'}
    ULSTER_UNIONIST = {"id": 38, 'colour': '#8648BA'}
    NONAFFILIATED = {"id": 49, 'colour': '#929292'}

    @classmethod
    def from_id(cls, value: int):
        for p_enum in cls:
            if p_enum.value['id'] == value:
                return p_enum
        return cls.NONAFFILIATED


class BillsMongoStorage(BillsStorage):
    async def add_feed_update(self, bill_id: int, update: FeedUpdate):
        database.get_connection().add_bill_feed_update(bill_id, update)

    async def has_update_stored(self, bill_id: int, update: FeedUpdate):
        return database.get_connection().is_bill_update_stored(bill_id, update)

    async def get_last_update(self, bill_id: int):
        return database.get_connection().get_bill_last_update(bill_id)

    async def add_publication_update(self, bill_id: int, update: PublicationUpdate):
        pass
        
    async def has_publication_update(self, bill_id: int, update: PublicationUpdate):
        pass


class DivisionMongoStorage(DivisionStorage):
    async def add_division(self, division: Union[LordsDivision, CommonsDivision]):
        database.get_connection().add_division(division)

    async def add_bill_division(self, bill_id: int, division: Union[LordsDivision, CommonsDivision]):
        database.get_connection().add_bill_division(bill_id, division)

    async def division_stored(self, division: Union[LordsDivision, CommonsDivision]):
        return database.get_connection().is_division_stored(division)

    async def bill_division_stored(self, bill_id: int, division: Union[LordsDivision, CommonsDivision]):
        return database.get_connection().is_bill_division_stored(bill_id, division)

    async def get_bill_divisions(self, bill_id: int):
        return database.get_connection().get_bill_divisions(bill_id)


class UKParliamentModule:
    def __init__(self, parliament: UKParliament):
        self.parliament = parliament
        self.title_font = ImageFont.truetype('static/Metropolis-Bold.otf', 40)
        self.key_font = ImageFont.truetype('static/Metropolis-SemiBold.otf', 25)
        self.bills_json_storage = BillsMongoStorage()
        self.divisions_json_storage = DivisionMongoStorage()
        parliament.start_bills_tracker(self.bills_json_storage)
        parliament.get_bills_tracker().register(self.on_feed_update, [Conditions.ALL])
        parliament.get_bills_tracker().register(self.on_royal_assent_update, [Conditions.ROYAL_ASSENT])
        parliament.start_divisions_tracker(self.divisions_json_storage)
        parliament.get_divisions_tracker().register(self.on_commons_division)
        parliament.get_divisions_tracker().register(self.on_lords_division, False)
        self.guild: Union[Guild, None] = None
        if os.path.exists('tmpimages') is False:
            os.mkdir('tmpimages')

    def set_guild(self, guild):
        self.guild = guild

    @tasks.loop(seconds=60)
    async def tracker_event_loop(self):
        await self.parliament.get_bills_tracker()._poll()
        await self.parliament.get_divisions_tracker()._poll_commons()
        await self.parliament.get_divisions_tracker()._poll_lords()

    async def on_feed_update(self, feed: Feed, update: FeedUpdate):
        channel = self.guild.get_channel(config.UKPARL_CHANNEL)
        embed = Embed(colour=config.EMBED_COLOUR, timestamp=datetime.now())
        next_line = '\n'
        last_update = await self.bills_json_storage.get_last_update(update.get_bill_id())
        embed.description = (
                f"**Last Stage:**: {last_update['stage']}{next_line}" if last_update is not None else ''
                f"**Next Stage:** {update.get_stage()}{next_line} **Summary:** {update.get_description()}"
                f"{next_line}**Categories:**{', '.join(update.get_categories())}"
                )
        embed.title = update.get_title()
        if self.guild is not None:
            embed.set_author(name='TLDRBot', icon_url=self.guild.icon_url)

        await channel.send(embed=embed)  # type: ignore

    async def on_royal_assent_update(self, feed: Feed, update: FeedUpdate):
        channel = self.guild.get_channel(config.ROYAL_ASSENT_CHANNEL)
        next_line = '\n'
        embed = Embed(colour=discord.Colour.from_rgb(134, 72, 186), timestamp=datetime.now())
        embed.title = f'**Royal Assent Given:** {update.get_title()}'
        embed.description = (
                f"**Signed At:** {update.get_update_date().strftime('%H:%M:%S on %Y:%m:%d')}{next_line}"
                f"**Summary:** {update.get_description()}"
                )
        await channel.send(embed=embed)

    async def on_commons_division(self, division: CommonsDivision, bill: Bill):
        channel = self.guild.get_channel(config.COMMONS_CHANNEL)
        division_infographic = self.generate_division_image(self.parliament, division)
        embed = Embed(color=discord.Colour.from_rgb(84, 174, 51), timestamp=datetime.now())
        did_pass = division.get_aye_count() > division.get_no_count()
        embed.title = f'**{division.get_division_title()}**'
        next_line = '\n'
        description = f"**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division of"
        f" {division.get_aye_count() if did_pass else division.get_no_count()} {'Ayes' if did_pass else 'Noes'}"
        f" to {division.get_no_count() if did_pass else division.get_aye_count()} "
        f"{'Noes' if did_pass else 'Ayes'}{next_line}**Division Date:** "
        f"{division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}"

        if bill is not None:
            description += f"{next_line}**Bill Summary [(Link)](https://bills.parliament.uk/"
            f"bills/{bill.get_bill_id()})**: {bill.get_long_title()}"

        embed.description = description
        embed.set_image(url=f'attachment://{division_infographic.filename}')
        await channel.send(file=division_infographic, embed=embed)

    async def on_lords_division(self, division: LordsDivision, bill: Bill):
        channel = self.guild.get_channel(config.LORDS_CHANNEL)
        division_infographic = self.generate_division_image(self.parliament, division)
        embed = Embed(color=discord.Colour.from_rgb(166, 42, 22), timestamp=datetime.now())
        did_pass = division.get_aye_count() > division.get_no_count()
        embed.title = f'**{division.get_division_title()}**'
        embed.set_image(url=f"attachment://{division_infographic.filename}")
        next_line = '\n'
        description = f"**ID:** {division.get_id()}{next_line}**Summary [(Link)](https://votes.parliament.uk/"
        f"Votes/Lords/Division/{division.get_id()}):** {division.get_amendment_motion_notes()[0:250]}{next_line}"
        f"**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division of "
        f"{division.get_aye_count() if did_pass else division.get_no_count()} "
        f"{'Ayes' if did_pass else 'Noes'} to {division.get_no_count() if did_pass else division.get_aye_count()}"
        f" {'Noes' if did_pass else 'Ayes'}{next_line}**Division Date:** "
        f"{division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}"

        if bill is not None:
            description += f"{next_line}**Bill Summary [(Link)](https://bills.parliament.uk/bills/"
            f"{bill.get_bill_id()})**: {bill.get_long_title()}"
        embed.description = description
        await channel.send(file=division_infographic, embed=embed)

    async def get_mp_portrait(self, url: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                file_id = "".join(random.choice(string.ascii_letters) for i in range(21))
                f = await aiofiles.open(f'tmpimages/{file_id}.jpeg', mode='wb')
                await f.write(await resp.read())
                await f.close()

                while not os.path.exists(f"tmpimages/{file_id}.jpeg"):
                    time.sleep(.5)

                return File(f'tmpimages/{file_id}.jpeg', filename=f'{file_id}.jpeg')

    def generate_election_graphic(
            self, 
            result: ElectionResult,
            include_nonvoters: bool = False,
            generate_table: bool = False):
        under_1k = []
        the_rest = []
        candidates = result.get_candidates()

        for candidate in candidates:
            if candidate['votes'] > 1000:
                the_rest.append(candidate)
            else:
                under_1k.append(candidate)

        nonvoters = result.get_electorate_size() - result.get_turnout()
        under_1k_total = sum([c['votes'] for c in under_1k])
        parent_pie_values = [c['votes'] for c in the_rest]
        parent_pie_labels = []
        for c in the_rest:
            party = self.parliament.get_party_by_id(c['party_id'])
            abbr = party.get_abber() if party is not None else ''
            if abbr == 'UK Independent Party':
                abbr = 'UKIP'
            if abbr == 'Scottish National Party':
                abbr = 'SNP'
            parent_pie_labels.append(f"{abbr} ({c['votes']:,} votes)")

        parent_pie_values.append(under_1k_total)
        parent_pie_labels.append(f'Others ({under_1k_total:,} votes)')
        if nonvoters != 0 and include_nonvoters:
            parent_pie_values.append(nonvoters)
            parent_pie_labels.append(f"Didn't Vote ({nonvoters:,} votes)")

        # make figure and assign axis objects
        plt.tight_layout()
        fig, ax1 = plt.subplots()

        # large pie chart parameters
        # explode = [0.1, 0, 0]
        # rotate so that first wedge is split by the x-axis

        if generate_table is False:
            ax1.pie(
                    parent_pie_values,
                    radius=0.6,
                    labels=parent_pie_labels)
        else:
            ax1.set_axis_off()
            rows = []

            for c in result.get_candidates():
                party_name = c['party_name']
                if party_name == 'UK Independence Party':
                    party_name = 'UKIP'
                if party_name == 'Sccotish National Party':
                    party_name = 'SNP'
                rows.append(
                        [
                            c['name'],
                            party_name,
                            f"{c['votes']:,}",
                            "{:.1%}".format(c['vote_share']),
                            c['vote_share_change']
                            ]
                        )

            table = ax1.table(
                    cellText=rows,
                    loc='upper center',
                    colLabels=['Candidate', 'Party', 'Votes', 'Vote Share', 'Vote Share Change'],
                    cellLoc='center')
            table.auto_set_column_width(col=list(range(len(result.get_candidates()))))
            cells = table.get_celld()

            for i in range(5):
                for j in range(0, 13):
                    cells[(j, i)].set_height(.065)

            table.auto_set_font_size(False)
        file_id = ''.join(random.choice(string.ascii_letters) for i in range(15))
        plt.savefig(f'tmpimages/{file_id}.png')
        image_file = File(f"tmpimages/{file_id}.png", filename=f"{file_id}.png")
        return image_file

    def generate_division_image(self, parliament: UKParliament, division: Union[LordsDivision, CommonsDivision]):
        def draw_ayes(draw: ImageDraw.ImageDraw, members: list[PartyMember]):
            columns = math.ceil(len(members) / 10)
            draw.text((100, 420), "Ayes", font=self.title_font, fill=(0, 0, 0))

            for column in range(columns + 1):
                for j, member in enumerate(members[10 * (column - 1): 10 * column]):
                    draw.ellipse(
                            [
                                (80 + ((20 * column) + (2 * column)), 480 + (20 * j) + (2 * j)),
                                (100 + ((20 * column) + (2 * column)), 500 + (20 * j) + (2 * j) - 2)
                                ],
                            f"{PartyColour.from_id(member._get_party_id()).value['colour']}")

        def draw_noes(draw: ImageDraw.ImageDraw, members: list[PartyMember]):
            columns = math.ceil(len(members) / 10)
            draw.text((100, 120), "Noes", font=self.title_font, fill=(0, 0, 0))
            for column in range(columns + 1):
                for j, member in enumerate(members[10 * (column - 1): 10 * column]):
                    draw.ellipse(
                            [
                                (80 + ((20 * column) + (2 * column)), 180 + (20 * j) + (2 * j)),
                                (100 + ((20 * column) + ((2 * column) - 2)), 200 + (20 * j) + ((2 * j) - 2))
                                ],
                            f"{PartyColour.from_id(member._get_party_id()).value['colour']}")

        def get_parties(division: Union[CommonsDivision, LordsDivision]) -> list[Party]:
            party_ids = []

            for member in division.get_aye_members():
                party_id = member._get_party_id()
                if party_id not in party_ids:
                    party_ids.append(party_id)

            for member in division.get_no_members():
                party_id = member._get_party_id()
                if party_id not in party_ids:
                    party_ids.append(party_id)

            return list(
                    filter(
                        lambda party: party is not None, map(lambda p_id: parliament.get_party_by_id(p_id), party_ids)
                        )
                    )  # type: ignore

        def draw_keys(draw: ImageDraw.ImageDraw, division: Union[CommonsDivision, LordsDivision]):
            parties = get_parties(division)

            for i, party in enumerate(parties):
                name = party.get_name()
                w, h = draw.textsize(name)
                draw.text((1600, 120 + (60 * i)), f"{name}", font=self.key_font, fill='#ffffff', anchor='lt')
                draw.ellipse(
                        [
                            (1520, 110 + (60 * i)),
                            (1570, 150 + (60 * i))
                            ],
                        fill=f"{PartyColour.from_id(party.get_party_id()).value['colour']}")

        def sort_members(members: list[PartyMember]) -> list[PartyMember]:
            parties = {}

            for member in members:
                if member._get_party_id() not in parties:
                    parties[member._get_party_id()] = [member]
                else:
                    parties[member._get_party_id()].append(member)

            results = []

            for key in sorted(parties.keys(), key=lambda k: len(parties[k])):
                results.extend(parties[key])

            results.reverse()
            return results

        im = Image.new('RGB', (2100, 800), '#edebea')
        draw = ImageDraw.Draw(im)
        draw.rectangle([(1450, 0), (2100, 800)], fill='#b7dade')
        draw.polygon([(1300, 0), (1450, 0), (1450, 800)], fill='#b7dade')
        draw_ayes(draw, sort_members(division.get_aye_members()))
        draw_noes(draw, sort_members(division.get_no_members()))
        draw_keys(draw, division)
        file_id = ''.join(random.choice(string.ascii_lowercase) for i in range(20))
        im.save(f"tmpimages/{file_id}.png", "PNG")
        return File(f"tmpimages/{file_id}.png", filename=f"{file_id}.png")
