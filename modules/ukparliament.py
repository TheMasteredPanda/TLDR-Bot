from io import BytesIO
from cachetools.ttl import TTLCache
from bot import TLDR
from datetime import datetime
import discord
from discord.embeds import Embed
from discord.guild import Guild
import time
import aiofiles
import aiohttp
import random
from discord import File
import string
from typing import Union
from ukparliament.structures.bills import Bill, CommonsDivision, LordsDivision
from ukparliament.structures.members import ElectionResult, PartyMember
from ukparliament.bills_tracker import (
    Conditions,
    Feed,
    FeedUpdate,
    BillsStorage,
    PublicationUpdate,
)
from ukparliament.divisions_tracker import DivisionStorage
from ukparliament.utils import BetterEnum
from discord.ext import tasks
from ukparliament.ukparliament import UKParliament
from ukparliament import bills_tracker
from modules import database
from modules import embed_maker
import config
import os
import configparser


class UKParliamentConfig:
    def __init__(self):
        self.config = configparser.ConfigParser()

        if os.path.exists("static/ukparliament.ini"):
            self.config.read("static/ukparliament.ini")
        else:
            self.config["CHANNELS"] = {  # type: ignore
                "RoyalAssent": 0,
                "LordsDivisions": 0,
                "CommonsDivisions": 0,
                "Publications": 0,
                "Feed": 0,
            }

            self.save()

    def set_channel(self, tracker_name: str, channel_id: int):
        if tracker_name not in self.config["CHANNELS"]:
            return
        self.config["CHANNELS"][tracker_name] = str(channel_id)

    def save(self):
        with open("static/ukparliament.ini", "w") as config_file:
            self.config.write(config_file)

    def get_channel_id(self, tracker_id):
        return self.config["CHANNELS"][tracker_id]


class PartyColour(BetterEnum):
    ALBA = {"id": 1034, "colour": "#73BFFA"}
    ALLIANCE = {"id": 1, "colour": "#D5D5D5"}
    CONSERVATIVE = {"id": 4, "colour": "#489FF8"}
    DUP = {"id": 7, "colour": "#3274B5"}
    GREEN = {"id": 44, "colour": "#82D552"}
    INDEPENDENT = {"id": 8, "colour": "#929292"}
    LABOUR = {"id": 15, "colour": "#DB3B26"}
    LIBERAL = {"id": 17, "colour": "#F19937"}
    PLAID_CYMRU = {"id": 22, "colour": "#54AE33"}
    SNP = {"id": 29, "colour": "#EFBD40"}
    SINN_FEIN = {"id": 30, "colour": "#986541"}
    SDLP = {"id": 31, "colour": "#ED6D57"}
    BISHOPS = {"id": 3, "colour": "#8648BA"}
    CONSERVATIVE_IND = {"id": 5, "colour": "#ED6D57"}
    CROSSBENCH = {"id": 6, "colour": "#A99166"}
    IND_SOCIAL_DEMOCRATS = {"id": 53, "colour": "#A62A16"}
    LABOUR_IND = {"id": 43, "colour": "#DE68A5"}
    ULSTER_UNIONIST = {"id": 38, "colour": "#8648BA"}
    NONAFFILIATED = {"id": 49, "colour": "#929292"}

    @classmethod
    def from_id(cls, value: int):
        for p_enum in cls:
            if p_enum.value["id"] == value:
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

    async def add_bill_division(
        self, bill_id: int, division: Union[LordsDivision, CommonsDivision]
    ):
        database.get_connection().add_bill_division(bill_id, division)

    async def division_stored(self, division: Union[LordsDivision, CommonsDivision]):
        return database.get_connection().is_division_stored(division)

    async def bill_division_stored(
        self, bill_id: int, division: Union[LordsDivision, CommonsDivision]
    ):
        return database.get_connection().is_bill_division_stored(bill_id, division)

    async def get_bill_divisions(self, bill_id: int):
        return database.get_connection().get_bill_divisions(bill_id)


class ConfirmManager:
    def __init__(self):
        self.cache = TTLCache(maxsize=30, ttl=90)

    def gen_code(self, member: discord.Member):
        code = "".join(random.choice(string.ascii_lowercase) for i in range(5))
        self.cache[member.id] = code
        return code

    def confirm_code(self, member: discord.Member, code: str):
        c_code = self.cache.get(member.id)
        if c_code is None:
            return False
        confirmed = c_code == code
        if confirmed:
            self.cache.pop(member.id)
        return confirmed

    def has_code(self, member: discord.Member):
        return self.cache.get(member.id) is not None


class UKParliamentModule:
    def __init__(self, bot: TLDR):
        self._bot = bot
        self.config = UKParliamentConfig()
        self._divisions_storage = DivisionMongoStorage()
        self._bills_storage = BillsMongoStorage()
        self.confirm_manager = ConfirmManager()
        self.tracker_status = {
            "lordsdivisions": {"started": False, "confirmed": False},
            "commonsdivisions": {"started": False, "confirmed": False},
            "royalassent": {"started": False, "confirmed": False},
            "feed": {"started": False, "confirmed": False},
            "publications": {"started": False, "confirmed": False},
        }

        self._guild: Union[Guild, None] = None
        if os.path.exists("tmpimages") is False:
            os.mkdir("tmpimages")

    async def load(self):
        self.aiohttp_session = getattr(self._bot.http, "_HTTPClient__session")
        self.parliament = UKParliament(self.aiohttp_session)
        await self.parliament.load()
        await self.load_trackers()

    async def load_trackers(self):
        config = self.config.config

        if (
            config["CHANNELS"]["lordsdivisions"] != 0
            or config["CHANNELS"]["commonsdivisions"] != 0
            or config["CHANNELS"]["royaalassent"]
            or config["CHANNELS"]["feed"]
        ):
            self.parliament.start_bills_tracker(self._bills_storage)

            if config["CHANNELS"]["feed"] != 0:
                self.parliament.get_bills_tracker().register(
                    self.on_feed_update, [Conditions.ALL]
                )
                self.tracker_status["feed"]["started"] = True

            if config["CHANNELS"]["royalassent"]:
                self.parliament.get_bills_tracker().register(
                    self.on_royal_assent_update, [Conditions.ROYAL_ASSENT]
                )
                self.tracker_status["royalassent"]["started"] = True

        if (
            config["CHANNELS"]["lordsdivisions"] != 0
            or config["CHANNELS"]["commonsdivisions"] != 0
        ):
            self.parliament.start_divisions_tracker(self._divisions_storage)
            if config["CHANNELS"]["commonsdivisions"] != 0:
                self.parliament.get_divisions_tracker().register(
                    self.on_commons_division
                )
                self.tracker_status["commonsdivisions"]["started"] = True

            if config["CHANNELS"]["lordsdivisions"] != 0:
                self.parliament.get_divisions_tracker().register(
                    self.on_lords_division, False
                )
                self.tracker_status["lordsdivisions"]["started"] = True

        if (
            config["CHANNELS"]["publications"] != 0
            and self.parliament.get_bills_tracker() is not None
        ):
            b_tracker = self.parliament.get_bills_tracker()
            if b_tracker is None:
                return
            self.parliament.start_publications_tracker(b_tracker)
            self.tracker_status["publications"]["started"] = True

    def set_guild(self, guild):
        self._guild = guild

    @tasks.loop(seconds=60)
    async def tracker_event_loop(self):
        if self.parliament.get_publications_tracker() is not None:
            await self.parliament.get_publications_tracker().poll()

        if self.parliament.get_bills_tracker() is not None:
            await self.parliament.get_bills_tracker().poll()

        if self.parliament.get_divisions_tracker() is not None:
            await self.parliament.get_divisions_tracker().poll_commons()
            await self.parliament.get_divisions_tracker().poll_lords()

    async def on_feed_update(self, feed: Feed, update: FeedUpdate):
        channel = self._guild.get_channel(int(self.config.get_channel_id("feed")))
        if channel is None:
            return
        embed = Embed(colour=config.EMBED_COLOUR, timestamp=datetime.now())
        next_line = "\n"
        last_update = await self._bills_storage.get_last_update(update.get_bill_id())
        embed.description = (
            f"**Last Stage:**: {last_update['stage']}{next_line}"
            if last_update is not None
            else ""
            f"**Next Stage:** {update.get_stage()}{next_line} **Summary:** {update.get_description()}"
            f"{next_line}**Categories:**{', '.join(update.get_categories())}"
        )
        embed.title = update.get_title()
        if self._guild is not None:
            embed.set_author(name="TLDRBot", icon_url=self._guild.icon_url)

        self.tracker_status["feed"]["confirmed"] = True
        await channel.send(embed=embed)  # type: ignore

    async def on_royal_assent_update(self, feed: Feed, update: FeedUpdate):
        channel = self._guild.get_channel(
            int(self.config.get_channel_id("royalassent"))
        )
        if channel is None:
            return
        next_line = "\n"
        embed = Embed(
            colour=discord.Colour.from_rgb(134, 72, 186), timestamp=datetime.now()
        )
        embed.title = f"**Royal Assent Given:** {update.get_title()}"
        embed.description = (
            f"**Signed At:** {update.get_update_date().strftime('%H:%M:%S on %Y:%m:%d')}{next_line}"
            f"**Summary:** {update.get_description()}"
        )
        self.tracker_status["royalassent"]["confirmed"] = True
        await channel.send(embed=embed)

    async def on_commons_division(self, division: CommonsDivision, bill: Bill):
        channel = self._guild.get_channel(
            int(self.config.get_channel_id("commonsdivisions"))
        )
        if channel is None:
            return
        division_bytes = await self.generate_division_image(self.parliament, division)
        embed = Embed(
            color=discord.Colour.from_rgb(84, 174, 51), timestamp=datetime.now()
        )
        did_pass = division.get_aye_count() > division.get_no_count()
        embed.title = f"**{division.get_division_title()}**"
        next_line = "\n"
        description = (
            f"**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division of"
            f" {division.get_aye_count() if did_pass else division.get_no_count()} {'Ayes' if did_pass else 'Noes'}"
            f" to {division.get_no_count() if did_pass else division.get_aye_count()} "
            f"{'Noes' if did_pass else 'Ayes'}{next_line}**Division Date:** "
            f"{division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        if bill is not None:
            description += (
                f"{next_line}**Bill Summary [(Link)](https://bills.parliament.uk/"
                f"bills/{bill.get_bill_id()})**: {bill.get_long_title()}"
            )

        embed.description = description
        embed.set_image(url="attachment://divisionimage.png")
        self.tracker_status["commonsdivisions"]["confirmed"] = True
        await channel.send(
            file=discord.File(fp=division_bytes, filename="divisionimage.png"),
            embed=embed,
        )

    async def on_lords_division(self, division: LordsDivision, bill: Bill):
        channel = self._guild.get_channel(
            int(self.config.get_channel_id("lordsdivisions"))
        )
        if channel is None:
            return
        division_buffer = await self.generate_division_image(self.parliament, division)
        embed = Embed(
            color=discord.Colour.from_rgb(166, 42, 22), timestamp=datetime.now()
        )
        did_pass = division.get_aye_count() > division.get_no_count()
        embed.title = f"**{division.get_division_title()}**"
        embed.set_image(url="attachment://divisionimage.png")
        next_line = "\n"
        description = (
            f"**ID:** {division.get_id()}{next_line}**Summary [(Link)](https://votes.parliament.uk/"
            f"Votes/Lords/Division/{division.get_id()}):** {division.get_amendment_motion_notes()[0:250]}...{next_line}"
            f"**Division Result:** {'Passed' if did_pass else 'Not passed'} by a division of "
            f"{division.get_aye_count() if did_pass else division.get_no_count()} "
            f"{'Ayes' if did_pass else 'Noes'} to {division.get_no_count() if did_pass else division.get_aye_count()}"
            f" {'Noes' if did_pass else 'Ayes'}{next_line}**Division Date:** "
            f"{division.get_division_date().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        if bill is not None:
            description += (
                f"{next_line}**Bill Summary [(Link)](https://bills.parliament.uk/bills/"
                f"{bill.get_bill_id()})**: {bill.get_long_title()}**"
            )
        embed.description = description
        self.tracker_status["lordsdivisions"]["confirmed"] = True
        await channel.send(
            file=discord.File(fp=division_buffer, filename="divisionimage.png"),
            embed=embed,
        )

    async def get_mp_portrait(self, url: str):
        async with self.aiohttp_session.get(url) as resp:
            if resp.status != 200:
                return None
            file_id = "".join(random.choice(string.ascii_letters) for i in range(21))
            f = await aiofiles.open(f"tmpimages/{file_id}.jpeg", mode="wb")
            await f.write(await resp.read())
            await f.close()

            while not os.path.exists(f"tmpimages/{file_id}.jpeg"):
                time.sleep(0.5)

            return File(f"tmpimages/{file_id}.jpeg", filename=f"{file_id}.jpeg")

    async def generate_election_graphic(
        self,
        result: ElectionResult,
        include_nonvoters: bool = False,
        generate_table: bool = False,
    ):
        serialized_candidates = []

        for candidate in result.get_candidates():
            party = self.parliament.get_party_by_id(candidate["party_id"])
            party_name = party.get_abber() if party is not None else ""
            if party_name == "UK Independent Party":
                party_name = "UKIP"
            if party_name == "Scottish National Party":
                party_name = "SNP"

            serialized_candidates.append(
                {
                    "party_name": party_name,
                    "votes": candidate["votes"],
                    "vote_share": candidate["vote_share"],
                    "vote_share_change": candidate["vote_share_change"],
                    "name": candidate["name"],
                }
            )

        async with self.aiohttp_session.post(
            f"{config.WEB_API_URL}/electionimage",
            json={
                "candidates": serialized_candidates,
                "electorate_size": result.get_electorate_size(),
                "turnout": result.get_turnout(),
                "include_nonvoters": include_nonvoters,
                "generate_table": generate_table,
            },
        ) as resp:
            if resp.status != 200:
                raise Exception("Failed to get election image for election result.")
            response = await resp.read()
            return response

    async def generate_division_image(
        self, parliament: UKParliament, division: Union[LordsDivision, CommonsDivision]
    ):
        def serialize_members(members: list[PartyMember]) -> dict[str, str]:
            serialized_members: dict[str, str] = {}

            for member in members:
                serialized_members[str(member.get_id())] = PartyColour.from_id(
                    member.get_party_id()
                ).value["colour"]

            return serialized_members

        def sort_members(members: list[PartyMember]) -> list[PartyMember]:
            parties = {}

            for member in members:
                if member.get_party_id() not in parties:
                    parties[member.get_party_id()] = [member]
                else:
                    parties[member.get_party_id()].append(member)

            results = []

            for key in sorted(parties.keys(), key=lambda k: len(parties[k])):
                results.extend(parties[key])

            results.reverse()
            return results

        aye_serialized_members = serialize_members(
            sort_members(division.get_aye_members())
        )
        no_serialized_members = serialize_members(
            sort_members(division.get_no_members())
        )
        serialized_parties = {}

        members = division.get_aye_members()
        members.extend(division.get_no_members())

        for member in members:
            party_id = member.get_party_id()
            if party_id in serialized_parties:
                continue
            party = self.parliament.get_party_by_id(party_id)
            if party is None:
                continue
            party_name = party.get_abber()
            if party_name == "UK Independent Party":
                party_name = "UKIP"
            if party_name == "Scottish National Party":
                party_name = "SNP"

            serialized_parties[str(party_id)] = {
                "name": party_name,
                "colour": PartyColour.from_id(party_id).value["colour"],
            }

        async with self.aiohttp_session.post(
            f"{config.WEB_API_URL}/divisionimage",
            json={
                "aye_members": aye_serialized_members,
                "no_members": no_serialized_members,
                "parties": serialized_parties,
            },
        ) as resp:
            if resp.status != 200:
                raise Exception(
                    f"Couldn't fetch division image. Status Code: {resp.status}"
                )
            buffer = BytesIO(await resp.read())
            buffer.seek(0)
            return buffer
