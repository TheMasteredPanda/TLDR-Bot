from datetime import datetime
import json
import os
import random
import time
from enum import Enum
from typing import Union

import bs4
from discord.guild import Guild
from discord.role import Role
from discord.types.channel import ThreadChannel
from discord.ui.button import button
from pytz import NonExistentTimeError
import config
import discord
import pymongo
from bot import TLDR
from bs4.element import Tag
from bson import json_util
from discord.channel import TextChannel
from discord.emoji import Emoji
from discord.enums import ChannelType
from discord.ext.commands import Bot, bot_has_any_role
from discord.message import Message
from discord.threads import Thread
from pyasn1.type.univ import Null
from pymongo.collection import Collection

import modules.database as database
import modules.format_time as format_time
from modules import database, embed_maker
from discord.ext.tasks import loop
from modules.utils import SettingsHandler

db = database.get_connection()


class Case:
    def __init__(self, data: dict):
        self.guild_id: int = data.get("guild_id")
        self.type: str = data.get("type")
        self.reason: str = data.get("reason")
        self.member_id: int = data.get("member_id")
        self.moderator_id: int = data.get("moderator_id")
        self.created_at = data.get("created_at")
        self.extra = data.get("extra", {})


class Cases:
    def __init__(self, bot):
        self.bot = bot

    def get_cases(
            self, guild_id: int, *, before: int = 0, after: int = 0, **kwargs
    ) -> list[Case]:
        """
        Get cases based on given kwargs.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the guild.
        before: :class:`int`
            Retrieve cases before this unix time.
        after: :class:`int`
            Retrieve cases after this unix time.
        kwargs: :class:`dict`
            Different values to search for cases by.

        Returns
        -------
        :class:`list`
           All the found cases.
        """
        kwargs = {key: value for key, value in kwargs.items() if value}
        query = {"guild_id": guild_id, **kwargs}
        if before:
            query["created_at"] = {"$lt": before}
        if after:
            query["created_at"] = {"$gt": after}

        return [Case(c) for c in db.cases.find(query).sort("created_at", -1)]

    def add_case(
            self,
            guild_id: int,
            case_type: str,
            reason: str,
            member: discord.member,
            moderator: discord.Member,
            extra: dict = {},
    ) -> Case:
        """
        Adds a case to the database.

        Parameters
        ----------------
        guild_id: :class:`int`
            ID of the guild.
        case_type: :class:`str`
            Type of the case => mute | ban | kick | warn
        reason: :class:`str`
            Reason behind the case.
        member: :class:`discord.Member`
            Member who had the action taken upon.
        moderator: :class:`discord.Member`
            Member who took action on member.
        extra: :class:`dict`
            Any extra info that needs to be added.

        Returns
        -------
        :class:`dict`
            The case's data.
        """
        case_data = {
            "guild_id": guild_id,
            "member_id": member.id,
            "type": case_type,
            "reason": reason,
            "created_at": time.time(),
            "moderator_id": moderator.id,
            "extra": extra,
        }
        result = db.cases.insert_one(case_data)
        case_data["_id"] = result.inserted_id

        return Case(case_data)


class PollType(Enum):
    GC_POLL = 1
    PUNISHMENT_POLL = 2


class ReprimandDataManager:
    """
    A class dedicated to addeding, removing, and updating temporal information associated with reprimand polls.
    """

    def __init__(self):
        self._db = database.get_connection()
        self._reprimand_collection: Collection = self._db.reprimands

    def get_reprimand(self, thread_id: int):
        """
        Fetch a saved reprimand via an associated thread's id (polling or discussion)

        Parameters
        ----------
        thread_id: :class:`int`
            The id othe thread the reprimand is associated with.
        """
        return self._reprimand_collection.find_one({'thread_ids': thread_id})

    def get_reprimands(self):
        """
        Fetches all live reprimands from the database.
        """
        return self._reprimand_collection.find({'$not': {'complete': True}})

    def save_reprimand(self, reprimand):
        """
        Updates or inserts a reprimand into the database.

        Parameters
        ----------
        document: :class:`object`
            Mongodb document.
        """

        poll_time = {}
        polls = reprimand.get_polls()

        # Fetches poll embed message id and seconds remaining from countdown.
        for poll in polls:
            poll_time[poll.get_message().id] = poll.get_seconds_remaining()

        self._reprimand_collection.update_one({"thread_id": reprimand.get_discussion_thread().id},
                                              {'completed': reprimand.is_completed(),
                                               'gc_approved': reprimand.has_gc_approved(),
                                               'gc_voted': reprimand.has_gc_vetoed(), 'poll_countdown': poll_time,
                                               'thread_ids': [reprimand.get_discussion_thread().id,
                                                              reprimand.get_polling_thread().id],
                                               'accused_id': reprimand.get_accused().id}, upsert=True)


class Poll:
    async def load(self):
        pass

    def get_ayes(self) -> int:
        pass

    def get_noes(self) -> int:
        pass

    def get_type(self) -> PollType:
        pass

    async def tick(self, reprimand):
        pass

    def get_seconds_remaining(self) -> int:
        pass

    def _has_countdown_elapsed(self) -> bool:
        pass


    def get_message(self):
        pass
    def name(self):
        pass


class PunishmentType(Enum):
    INFORMAL = 0
    FORMAL = 1
    MUTE = 2
    BAN = 3


class GCPoll(Poll):
    def __init__(self, reprimand, cg_id: int, **kwargs):
        """
        A class representing a GC id. The responsibility of this class will vary depending on the amount of GC IDs that are provided to
        a Reprimand object. If there are multiple IDs, then this class will output the description of the ID that this class itself has
        been provided, in addition to voting options that will determine whether this GC has indeed been broken on the basis of a qorum.

        However, if only one ID has been provided, this will provide only the description of the GC and leave the voting to the Punishm-
        entPoll class, which will provide only the various punishment options to the members of the qorum.


        Parameters
        -----------
        reprimand: :class:`Reprimand`
            The reprimand object.
        cg_id: :class:`str`
            The id of the CG dedicated for this poll.
        message_id: :class:`int`
            The id of a preexisting embed that is maintained by a GCPoll. If none if provided, it is assumed this is a new poll.

        """
        self._reprimand = reprimand
        self._cg_id = cg_id
        self._message: discord.Message = None
        self._countdown: int = 0
        self._name = None

    async def load(self, **kwargs):
        """
        Loads the GCPoll object, populating parameters vital for it's functioning. If this is a new poll, it will
        create the embed and other relevant points of data for this object.


        Parameters
        ----------
        message_id: :class:`int`
            The id of an embed message, provided there is one. If this value is not provided it will create
            a new embed.
        countdown: :class:`int`
            The amount of time left until the poll concludes. If this value is not provided it will start a new
            countdown.
        singular: :class:`bool`
            A boolean noting whether this poll is part of a multi CG or singular CG reprimand process. If this
            value is singular, then this poll will be considered the only GCPoll in the process and will not
            add the reaction emojis. If this parameter is not provided (or false; default value) it will add
            these reaction emojis.
        name: :class:`str`
            For debugging purposes.
        """
        if 'message_id' in kwargs.keys():
            self._message = self._reprimand.get_polling_thread().fetch_message(kwargs['message_id'])

        if 'countdown' in kwargs.keys():
            self._countdown = kwargs['countdown']
        else:
            self._countdown = self._reprimand._module.get_settings()['duration']['cg_poll']

        if 'name' in kwargs.keys():
            self._name = kwargs['name']

        if self._message is not None:
            return

        # Assuming no message is found it will create the embed, starting here.
        cg_poll_embed = self._reprimand._module.get_settings()["messages"]["cg_poll_embed"]
        accused: discord.Member = self._reprimand.get_accused()
        parsed_cgs = self._reprimand._module._get_bot().moderation.get_parsed_cgs()
        selected_cgs = {}
        for key in parsed_cgs.keys():
            if self._cg_id.startswith(key):
                selected_cgs[key] = parsed_cgs[key]

        desc = ""

        for key, value in selected_cgs.items():
            desc = desc + f"`{key}` {value}"

        accused: discord.Member = self._reprimand.get_accused()
        body_embed = cg_poll_embed['body']

        if 'singular' not in kwargs.keys() or ('singular' in kwargs.keys() and kwargs['singular'] is False):
            body_embed = body_embed.replace('{options}', cg_poll_embed['options'])
        else:
            body_embed = body_embed.replace('{options}', '')

        embed = discord.Embed(
            colour=config.EMBED_COLOUR,
            description=body_embed
            .replace("{cg_description}", desc)
            .replace("{duration}", format_time.seconds(self._countdown)),
            title=cg_poll_embed["title"]
            .replace("{cg_id}", self._cg_id)
            .replace("{user}", f"{accused.name}#{accused.discriminator}")
            .replace('{options}', ""))

        self._message: Message = await self._reprimand.get_polling_thread().send(embed=embed)
        # Will only add these if the parameter 'singular' is not present.

        if 'singular' not in kwargs.keys() or ('singular' in kwargs.keys() and kwargs['singular'] is False):
            await self._message.add_reaction("👍")
            await self._message.add_reaction("👎")

        # Add saving functions here.

    async def tick(self, reprimand):
        if self._countdown > 0:
            self._countdown = self._countdown - 1

            # if self._countdown % 60 == 0:
            self._reprimand.save()

    # print(f"GCPoll (CG: {self._cg_id}): {self._countdown})")

    def get_message(self):
        return self._message

    def get_cg_id(self):
        return self._cg_id

    def get_ayes(self) -> int:
        reactions = self._message.reactions

        for reaction in reactions:
            if reaction.emoji == "👍":
                return reaction.count  # Accounting for the bot emoji.
        return 0

    def get_noes(self) -> int:
        reactions = self._message.reactions

        for reaction in reactions:

            if reaction.emoji == "👎":
                return reaction.count - 1  # Accounting for the bot emoji.
        return 0

    def get_type(self):
        return PollType.GC_POLL

    def name(self):
        # For debugging purposes.
        return self._name

    def get_seconds_remaining(self) -> int:
        return self._countdown

    def _has_countdown_elapsed(self) -> bool:
        return self._countdown <= 0

class GCApprovalView(discord.ui.View):
    def __init__(self, module):
        super().__init__(timeout=None)
        """
        A button view used for the GC Approval process. This view is persistent, but will be used thoroughout the polling threads
        as the sole method of approving or rejecting the conclusion of an agreed quorum.

        """
        self._module = module


    def checks(self, interaction):
        channel: discord.PartialMessageable = interaction.channel

        if channel.type != ChannelType.public_thread:
            return

        channel_id = channel.id
        if self._module.is_reprimand_thread(channel_id) is False:
            return

        reprimand = self._module.get_reprimand_from_thread_id(channel_id)
        if reprimand is None:
            raise Exception(f"Attempted to fetch reprimand using channel/thread id {channel_id}, returned no reprimand object.")

        interactor = interaction.user
        if type(interactor) is not discord.Member:
            raise Exception(f"Interactor to GCApprovalView in channel/thread id {channel_id} is not canonical Member type.")
        interactor_roles: list[discord.Role] = interactor.roles

        m_settings = self._module.get_settings()
        gc_role_id = m_settings['gc_member_role']


        for role in interactor_roles:
            if role.id == gc_role_id:
                return reprimand
        return None



    @button(label="Approved", style=discord.ButtonStyle.green, emoji="👍", custom_id="approval_button")
    async def approved_callback(self, button, interaction):
        reprimand = self.checks(interaction)
        if reprimand:
            reprimand.approve()

    @button(label="Rejected", style=discord.ButtonStyle.red, emoji="👎", custom_id="rejection_button")
    async def rejected_callback(self, button, interaction):
        reprimand = self.checks(interaction)
        if reprimand:
            reprimand.reject()

class PunishmentPoll(Poll):
    def __init__(self, reprimand, accused_member: discord.Member):
        """
        A class producing and counting the available configurable puishment options for qorum members to vote on.

        Parameters
        ----------
        reprimand: :class:`Reprimand`
            The reprimand object
        accused_member: :class:`Member`
            The member object of the accused.
        countdown: :class:`int`
            The amount of seconds until this poll ends.
        """
        self._reprimand: Reprimand = reprimand
        self._accused_member = accused_member
        self._countdown: int = 0
        self._settings = reprimand._module.get_settings()
        self._message_id = 0
        self._name = None

    async def load(self, **kwargs):
        """
        Loads the punishment poll.

        Parameters
        -----------
        message_id: :class:`int`
            The saved mesasge id of a punishment poll embed. This is provided if this class is loading a preexisting embed.
            If this isn't supplied it is assumed that this is a new punishment poll, and an embed will be created.
        countdown: :class:`int`
            The amount of seconds left until this poll concludes. If no countdown is provided, it is assumed that this is a
            new puishment poll.
        name: :class:`str`
            For debugging purposes.
        """

        if 'message_id' in kwargs.keys():
            self._message_id = kwargs['message_id']
            #self._message = await self._reprimand.get_polling_thread().fetch_message(kwargs['message_id'])

        if 'name' in kwargs.keys():
            self._name = kwargs['name']

        if 'countdown' in kwargs.keys():
            self._countdown = kwargs['countdown']
        else:
            self._countdown = self._reprimand._module.get_settings()['duration']['pun_poll']

        if self._message_id != 0:
            return

        # Assuming that no embed is found or previously loaded, this is the stage where a new embed is
        # created and posted in the polling thread associated with this reprimand process.
        punishment_embed_msgs = self._settings["messages"]["punishment_poll_embed"]
        punishment_entry = punishment_embed_msgs["punishment_entry"]
        punishments = self._settings["punishments"]
        punishment_poll_description_format = punishment_embed_msgs[
            "description_format"
        ]

        punishment_entries = ""

        for p_id, entry in punishments.items():
            punishment_entries = (
                    punishment_entries
                    + punishment_entry.replace("{emoji}", entry["emoji"])
                    .replace("{name}", entry["name"].capitalize())
                    .replace("{short_description}", entry["short_description"])
                    .replace("{type}", entry["punishment_type"])
                    + "\n"
            )

        embed = discord.Embed(colour=config.EMBED_COLOUR, title='Punishment Poll',
                              description=punishment_poll_description_format.replace("{punishment_entries}",
                                                                                     punishment_entries).replace(
                                  '{duration}', format_time.seconds(self._countdown)))
        message = await self._reprimand.get_polling_thread().send(embed=embed)

        # Adds the emojis associated to each option.
        for entry in punishments.values():
            await message.add_reaction(entry['emoji'])

        self._message_id = message.id
        ##Here, add the functions for storing the poll, or do this in the reprimand object.

    async def get_message(self):
        return await self._reprimand.get_polling_thread().fetch_message(self._message_id)

    def name(self):
        # For debugging purposes.
        return self._name

    def get_ayes(self) -> int:
        raise Exception('Not required.')

    def get_noes(self) -> int:
        raise Exception('Not required.')

    async def get_reaction_counts(self) -> dict:
        """
        Returns a count of all voting options in a punishment poll.
        """

        count = {}
        punishments = self._settings['punishments']
        message = await self.get_message()

        for p_id, entry in punishments.items():

            emoji = entry['emoji']
            print(emoji)
            print('------')
            message_reactions = message.reactions
            print(f'Reactions: {message_reactions}')
            print(f'Message ID: {message.id}')
            for reaction in message.reactions:
                print(reaction.emoji)
                if reaction.emoji == emoji:
                    print('Reaction is emoji')
                    if p_id in count.keys():
                        count[p_id] = count[p_id] + 1
                    else:
                        count[p_id] = 1
        return count

    def get_type(self) -> PollType:
        return PollType.PUNISHMENT_POLL

    # A function called per tick, where a tick is a second elapsed.
    async def tick(self, reprimand):
        if self._countdown > 0:
            self._countdown = self._countdown - 1

        if self._countdown == 0 and reprimand.is_awaiting_approval() is False:
            #Contains code executed for the end of the reprimand, setting up the gc approval process.
            #This assumines that the GCPolls have too been completed, and the PunishmentPoll be the last
            #poll to complete.
            m_settings = self._reprimand._module.get_settings()
            messages_settings = m_settings['messages']
            gc_approval_embed = messages_settings['gc_approval_embed']

            counts = await self.get_reaction_counts()
            if max(counts.values()) >= m_settings['quorum_minimum']:
                await self._reprimand.get_polling_thread().send(messages_settings['qourum_met'])
                embed = discord.Embed(colour=config.EMBED_COLOUR, description=gc_approval_embed['body'], title=gc_approval_embed['title'])
                await self._reprimand.get_polling_thread().send(embed=embed, view=GCApprovalView(self._reprimand))
                reprimand._gc_awaiting_approval = True
            else:
                await self._reprimand.get_polling_thread().send(messages_settings['qourum_not_met'])
                await self._reprimand.get_polling_thread().edit(locked=True)
                await self._reprimand.get_discussion_thread().edit(locked=True)
                reprimand.module.get_reprimand_manager().delete_reprimand(reprimand)



    def get_seconds_remaining(self) -> int:
        return self._countdown

    def _has_countdown_elapsed(self) -> bool:
        return self._countdown <= 0


class Reprimand:
    def __init__(self, manager, accused: discord.Member, cg_ids: list[int]):
        """
        Class representing a reprimand, and it's polls. This will be the object that contains all functions of both the polling thread
        and discussion thread. This will also handle any executed events between the two threads, the countdown, notifications, and eventually,
        execution of the reprimand conclusions.

        Parameters
        -----------
        _manager: :class:`ReprimandManager'
            The reprimand manager class.
        _bot: :class:`TLDRBot`
            The bot class.
        _module: :class:`ReprimandModule`
            The reprimand module.
        _countdown: :class:`int`
            The number of seconds remaining until the reprimand concludes.
        _paused: :class:`bool`
            A boolean, denoting whether the reprimand countdown has been paused or not.
        _accused_member: :class:`Member`
            The id of the member currently being accused of breaking one or more CGs.
        _polls: :class:`list`
            A list of punishment polls/CG polls.
        """
        self._manager = manager
        self._bot = manager._bot
        self._module: ReprimandModule = manager._module
        self._accused_member: discord.Member = accused
        self._polls: list[Poll] = []
        self._discussion_thread: Thread = None
        self._polling_thread: Thread = None
        self._cg_ids = cg_ids
        self._gc_approved = False
        self._gc_awaiting_approval = True
        self._chosen_punishment_id = None

    async def load(self, discussion_thread_id: int = 0, polling_thread_id: int = 0, **kwargs):
        guild: discord.Guild = self._module._get_main_guild()

        # Creates a thread for both discussion and polling if none currently exists.
        string_date = datetime.now().strftime("%m%d%Y")
        if polling_thread_id == 0:
            self._polling_thread = await self._module.get_polling_channel().create_thread(
                name=f"{string_date}/{self._accused_member.name.lower()}/poll", type=ChannelType.public_thread)
        else:
            self._polling_thread = guild.get_thread(polling_thread_id)

        if discussion_thread_id == 0:
            self._discussion_thread = await self._module.get_discussion_channel().create_thread(
                name=f"{string_date}/{self._accused_member.name.lower()}/discussion", type=ChannelType.public_thread)
            await self._discussion_thread.send(f"Polling Thread: {self._polling_thread.mention}")
        else:
            self._discussion_thread = guild.get_thread(discussion_thread_id)


        if 'gc_awaiting_approval' in kwargs.keys():
            self._gc_awaiting_approval = kwargs['gc_awaiting_approval']

        if 'chosen_punishment_id' in kwargs.keys():
            self._chosen_punishment_id = 'chosen_punishment_id'


        # Checks if all voting members are added to all threads for active reprimands.
        voting_members = self._module.get_voting_members()
        discussion_members = self._discussion_thread.members
        polling_members = self._polling_thread.members

        for v_member in voting_members:
            is_dm = False
            is_pm = False

            # This is really sloppy, research and see if you can't use lambda to make more efficent
            # the execution of this process.

            for d_member in discussion_members:
                if d_member.id == v_member.id:
                    is_dm = True

            for p_member in polling_members:
                if p_member.id == v_member.id:
                    is_pom = True

            if is_dm is False:
                await self._discussion_thread.add_user(v_member)

            if is_pm is False:
                await self._polling_thread.add_user(v_member)

        # Creates the polls used to decide which GC is applied, and what punishment they will feel.

        if len(self._cg_ids) == 1:
            gc_poll_singular = GCPoll(self, self._cg_ids[0])
            await gc_poll_singular.load(singular=True, name="GCPoll")
            self._polls.append(gc_poll_singular)
        else:
            iteration = 0
            for cg_id in self._cg_ids:
                iteration = iteration + 1
                gc_poll = GCPoll(self, cg_id)
                await gc_poll.load(name=f"GCPoll {iteration}")
                self._polls.append(gc_poll)

        p_poll = PunishmentPoll(self, self._accused_member)
        await p_poll.load(name="PunishmentPoll")
        self._polls.append(p_poll)


        if len(kwargs.keys()) > 0:
            message_settings = self._module.get_settings()['messages']
            discussion_reprimand_resumed = message_settings['discussion_resumed']
            polls_resumed_embed = message_settings['polls_resumed_embed']


            poll_entries: list[str] = []

            for poll in self._polls:
                poll_entries.append(polls_resumed_embed['poll_entry'].replace('{type}',
                                                                              'GC Poll' if poll.get_type() == PollType.GC_POLL else 'Punishment Poll').replace(
                    '{time_remaining}', format_time.seconds(poll.get_seconds_remaining())))

            embed: discord.Embed = discord.Embed(colour=config.EMBED_COLOUR,
                                                 description=polls_resumed_embed['description'].replace('{poll_entries}',
                                                                                                        '\n'.join(
                                                                                                            poll_entries)),
                                                 title=polls_resumed_embed['title'])

            await self._polling_thread.send(embed=embed)
            await self._discussion_thread.send(
                discussion_reprimand_resumed.replace('{poll_thread}', self._polling_thread.mention))

    def save(self):
        """
        Saves data values of the reprimand and associated objects to the collection.
        """
        pass
        #self._module.get_data_manager().save_reprimand(self)

    def get_accused(self) -> discord.Member:
        """
        Returns the member id of the accused.
        """

        return self._accused_member

    def is_awaiting_approval(self) -> bool:
        return self._gc_awaiting_approval

    async def approve(self):
        """
        Executed when the approval calledback in GCApprovalView is executed successfully. This executes the punishment phase
        of the reprimand. Executing the agreed upon punishment and deleting the reprimand from the collection. This also archives
        both polling and discussion threads.
        """

        if self._module.is_punishment_id(self._chosen_punishment_id) is False:
            raise Exception(f"Assumed punishment id {self._chosen_punishment_id} is no longer a punishment id.")

        punishments = self._module.get_punishments()
        chosen_punishment = punishments[self._chosen_punishment_id]
        ppn_message = self._module.get_settings()['messages']['punished_player_notification_message']
        pa_message = self._module.get_settings()['messages']['punishment_approved']

        if self._accused_member.can_send():
            message = ppn_message['message']

            if 'duration' in chosen_punishment.keys():
                duration = chosen_punishment['punishment_duration']
                message = message.replace('{temporal_entry}', ppn_message['temporal_entry'].replace('{time}', format_time.seconds(duration)))
            else:
                message = message.replace('{temporal_entry}', '')


            parsed_cgs = self._module._bot.moderation.get_parsed_cgs()
            selected_cgs = {}
            for key in parsed_cgs.keys():
                if key in self._cg_ids:
                    selected_cgs[key] = parsed_cgs[key]

            desc = ""

            for key, value in selected_cgs.items():
                desc = desc + f"`{key}` {value}"

            await self._accused_member.send(message.replace("{cgs_violated}", desc))

        duration = 0

        if chosen_punishment['punishment_type'] == 'MUTE':
            mute_role = self._module._guild.get_role(self._module.get_settings()['mute_role'])

            if mute_role is None:
                raise Exception("Mute role is not set.")

            await self._accused_member.add_roles(mute_role)


        if chosen_punishment['punishment_type'] == 'BAN':
            await self._accused_member.ban()

        await self._discussion_thread.send(pa_message)
        await self._polling_thread.send(pa_message)
        await self._discussion_thread.edit(locked=True)
        await self._polling_thread.edit(locked=True)
        self._module.get_reprimand_manager().delete_reprimand(self)


    async def reject(self):
        """
        Executed when the rejection callback in GCApprovalView is executed successfully. This executes the rejection phase of the
        reprimand. Locking the thread and waiting for the thread to automatically archive.
        """
        pr_message = self._module.get_settings()['messages']['punishment_rejcted']
        await self._discussion_thread.send(pr_message)
        await self._polling_thread.send(pr_message)
        await self._discussion_thread.edit(locked=True)
        await self._polling_thread.edit(locked=True)
        self._module.get_reprimand_manager().delete_reprimand(self)

    async def veto(self, vetod_by: discord.Member):
        """
        Executed when a GC has chosen to veto a reprimand. Veto will end and lock the reprimand.
        """
        vetoed_message = self._module.get_settings()['mesasge']['punishment_vetoed'].replace("{gc_name}", vetod_by.name)
        await self._polling_thread.send(vetoed_message)
        await self._discussion_thread.send(vetoed_message)
        await self._polling_thread.edit(locked=True)
        await self._discussion_thread.edit(locked=True)
        self._module.get_reprimand_manager().delete_reprimand(self)


    def get_polling_thread(self) -> Thread:
        return self._polling_thread

    def get_discussion_thread(self) -> Thread:
        return self._discussion_thread

    def get_polls(self) -> list[Poll]:
        return self._polls


class ReprimandManager:
    def __init__(self, module, bot):
        """
        Manager class used to manage live reprimands. This includes the creation of reprimands, maintaining reprimands,
        executing reprimand conclusions, and deleting reprimands.
        """
        self._bot = bot
        self._module = module
        self._reprimands: list[Reprimand] = []

    def is_already_accused(self, accused_id: int):
        """
        A fucntion that tells you if a member is already being accused, and therefore is under a modpoll.

        Parameters
        -----------
        accused_id: :class:`int`
            The id of the member.
        """
        for reprimand in self._reprimands:
            if reprimand.get_accused().id == accused_id:
                return True
        return False

    async def create_reprimand(self, accused: discord.Member, cg_ids: list):
        reprimand = Reprimand(self, accused, cg_ids)
        await reprimand.load()
        self._reprimands.append(reprimand)
        return reprimand

    def get_reprimand(self, thread_id: int) -> Union[Reprimand, None]:
        """
        A function to return a reprimand object attached to a thread, discussion or polling.

        Parameters
        ----------
        thread_id: :class:`int`
            The id of a discussion or polling thread.
        """
        for reprimand in self._reprimands:
            if reprimand.get_polling_thread().id == thread_id:
                return reprimand

            if reprimand.get_discussion_thread().id == thread_id:
                return reprimand
        return None

    def delete_reprimand(self, thread_id: int):
        """
        Deletes a reprimand and it's associated thread.

        Parameters
        ----------
        thread_id: :class:`int`
            Id of a thread associated with the reprimand you want to delete.
        """

        pass

    def is_reprimand_thread(self, thread_id: int) -> bool:
        """
        Checks if a thread is a thread attached to a live reprimand object.

        Parameters
        ----------
        thread_id: :class:`int`
            The id of a thread.
        """
        for reprimand in self._reprimands:
            if reprimand.get_polling_thread().id == thread_id:
                return True

            if reprimand.get_discussion_thread().id == thread_id:
                return True
        return False

    async def load(self):
        """Loads saved reprimands from MongoDB Collections into memory.

        """
        self.ticker.start()


    @loop(seconds=1)
    async def ticker(self):
        """
        A one second interval loop that executes the function respondibile for reducing
        the countdown. Aka, a ticker.
        """
        for reprimand in self._reprimands:
            for poll in reprimand.get_polls():
                await poll.tick(reprimand)

                poll_countdown = poll.get_seconds_remaining()
                poll_notifications = self._module.get_settings()['notifications']

                for notification_key in poll_notifications.keys():
                    parsed_key = format_time.parse(notification_key, False)

                    if poll_countdown == parsed_key:
                        await reprimand.get_polling_thread().send(poll_notifications[notification_key].replace('{voting_role_mention}', self._module.get_voting_role().mention).replace("{type}", "GC Poll" if poll.get_type() == PollType.GC_POLL else 'Punishment Poll'))


    def get_reprimand_from_thread_id(self, thread_id: int) -> Union[Thread, None]:
        """
        Gets a reprimand from a thread id, either discussion or polling thread id.

        Parameters
        ----------
        thread_id: :class:`int`
            Thread id.

        """
        for reprimand in self._reprimands:
            if reprimand.get_polling_thread().id == thread_id:
                return reprimand

            if reprimand.get_discussion_thread().id == thread_id:
                return reprimand
        return None


class ReprimandModule:
    def __init__(self, bot):
        self._bot: Bot = bot
        self._bot.logger.info("Reprimand Module has been initiated.")
        self._settings_handler: SettingsHandler = bot.settings_handler
        self._logger = bot.logger
        self._db = database.get_connection()
        self._data_manager = ReprimandDataManager()
        self._reprimand_manager = ReprimandManager(self, bot)
        self._discussion_channel = None
        self._polling_channel = None
        self._gc_approval_channel = None
        self._guild = None

        self._settings = {
            "punishments": {
                "informal": {
                    "description": "An informal warning, often a word said to them thorough a ticket or direct messages. This form of punishment doesn't appear on their record.",
                    "short_description": "Informal warning.",
                    "emoji": "1️⃣",
                    "name": "Informal Warning",
                    "punishment_type": "WARNING",
                    "punishment_duration": "",
                },
                "1formal": {
                    "description": "A formal warning. Unlike informal warnings this does appear on their record, and is given thorough the bot to the user on a ticket or thorough DMs",
                    "emoji": "2️⃣",
                    "name": "1 Formal Warning",
                    "punishment_type": "WARNING",
                    "short_description": "Formal warning.",
                    "punishment_duration": "",
                },
                "2formal": {
                    "description": "Two formal warnings",
                    "name": "2 Formal Warnings",
                    "short_description": "Two formal warnings.",
                    "punishment_type": "WARNING",
                    "emoji": "3️⃣",
                },
                "mute": {
                    "description": "Mutes a user for an alloted amount of time, this will obviously appear on their record. The amount of time a person gets can be determined thorough a poll or preestablished times.",
                    "emoji": "4️⃣",
                    "name": "Mute",
                    "short_description": "Mute",
                    "punishment_type": "MUTE",
                },
                "ban": {
                    "description": "Bans a user from the server, this will appear on their record too.",
                    "short_description": "Ban",
                    "name": "Ban",
                    "punishment_type": "BAN",
                    "emoji": "5️⃣",
                },
            },
            "voting_member_role": 0,
            "gc_member_role": 0,
            "mute_role": 0,
            "quorum_minimum": 0,
            "polling_channel": 0,
            "discussion_channel": 0,
            "gc_approval_channel": 0,
            "duration": {
                "cg_poll": 500,
                "pun_poll": 600
            },
            "gc_notification": {"interval": "5m", "message": "{reprimand_polling_channel_mention} awaiting approval. {gc_role_mention}."},
            "notifications": {"5m": "{type} will close in 5 minutes. {voting_role_mention}."},
            "messages": {
                "punishment_approved": "Punishment agreed upon has been approved and executed. Threads locked.",
                "punishment_rejected": "Punishment agreed upon has been rejected. Threads locked.",
                "punishment_vetoed": "Reprimand vetoed by {gc_name}. Threads locked.",
                "qourum_met": "Qourum met on option {option_name}. Awaiting GC approval before execution.",
                "qourum_not_met": "Quorum not met. Locking threads.",
                "polls_resumed_embed": {
                    "title": "Reprimand Polls Resumed.",
                    "poll_entry": "{type} Poll has resumed with {time_remaining} left.",
                    "description": "{poll_entries}"
                },
                "discussion_resumed": "Reprimand resumed, see {poll_thread} for remaining active polls.",
                "rtime": {
                    "header": "Time Remaining",
                    "entry": {
                        "gc_poll": "{cg_id} GCPoll has {time_remaining}",
                        "p_poll": "Poll has {time_remaining}",
                    },
                },
                "cg_poll_embed": {
                    "title": "Has {user} breached {cg_id}?",
                    "footer": "",
                    "body": "{cg_description}\n\nPoll Duration: {duration} (execute >rtime to see current time){options}",
                    "options": "\n\n**Options**\n👍 to vote in the affirmative\n👎 to vote in the negative",
                },
                "gc_approval_embed": {
                    "title": "Approve Agreed Punishment.",
                    "footer": "",
                    "body": "Do you approve of {punishment_name} on this Reprimand?"
                },
                "punished_player_notification_message": {
                    "temporal_entry": "for {time} ",
                    "message": "You have been {punishment_type} {temporal_entry}for violating the following CGs:\n{cgs_violated}",
                },
                "punishment_poll_embed": {
                    "title": {
                        "singular": "{accused_name} accused of breaching {cg_id}. What action should be taken?",
                        "multiple": "{accused_name} accused of breaching multiple CGs. What action should be taken?.",
                    },
                    "footer": "",
                    "punishment_entry": "{emoji} | **{name}:**  {short_description}",
                    "description_format": "{punishment_entries} \n Poll Duration: {duration} (execute >time to see current time)",
                },
                "evidence_messages": {
                    "header": "-- Evidence --",
                },
            },
        }

        if config.MAIN_SERVER == 0:
            bot.logger.info(
                "Reprimand Module required the MAIN_SERVER variable in config.py to be set to a non zero value (a valid guild id). Will not initiate until this is rectified."
            )
            return

        settings = self._settings_handler.get_settings(config.MAIN_SERVER)

        if "reprimand" not in settings["modules"].keys():
            self._logger.info(
                "Reprimand Module settings not found in Guild dsettings. Adding default settings now."
            )
            settings["modules"]["reprimand"] = self._settings
            self._settings_handler.save(settings)
        self._settings_handler.update("reprimand", self._settings, config.MAIN_SERVER)

    def _get_bot(self):
        return self._bot

    def _get_main_guild(self):
        if self._guild is None:
            self._guild = self._bot.get_guild(config.MAIN_SERVER)

        return self._guild

    def get_voting_role(self) -> Union[Role, None]:
        voting_member_role = self.get_settings()['voting_member_role']
        guild = self._guild

        return guild.get_role(voting_member_role)


    def get_voting_members(self) -> list[discord.Member]:
        """
        Returns a list of members that can vote in a qorum.

        """
        role_id = self.get_settings()['voting_member_role']
        role = self._guild.get_role(role_id)
        if role is None:
            raise Exception(f'Voting member role {role_id} for Reprimand not found.')
        return role.members

    def get_data_manager(self) -> ReprimandDataManager:
        return self._data_manager

    def get_reprimand_manager(self) -> ReprimandManager:
        return self._reprimand_manager

    def set_setting(self, path: str, value: object):
        settings = self._settings_handler.get_settings(config.MAIN_SERVER)

        def keys():
            def walk(key_list: list, branch: dict, full_branch_key: str):
                walk_list = []
                for key in branch.keys():
                    if type(branch[key]) is dict:
                        walk(key_list, branch[key], f"{full_branch_key}.{key}")
                    else:
                        walk_list.append(f"{full_branch_key}.{key}".lower())

                key_list.extend(walk_list)
                return key_list

            key_list = []

            for key in settings.keys():
                if type(settings[key]) is dict:
                    key_list = walk(key_list, settings[key], key)
                else:
                    key_list.append(key.lower())
            return key_list

        path = f"modules.reprimand.{path}"
        if path.lower() in keys():
            split_path = path.split(".")
            parts_count = len(split_path)

            def walk(parts: list[str], part: str, branch: dict):
                if parts.index(part) == (parts_count - 1):
                    branch[part] = value
                    self._settings_handler.save(settings)
                else:
                    walk(parts, parts[parts.index(part) + 1], branch[part])

            if parts_count == 1:
                settings[path] = value
            else:
                walk(split_path, split_path[0], settings)

    async def on_ready(self):
        # Here, load up reprimands from MongoDB collection and start the ticker.
        self._bot.logger.info("Reprimand loaded.")
        await self._reprimand_manager.load()
        self._bot.add_view(GCApprovalView(self))

    def get_discussion_channel(self):
        channel = None

        if self._discussion_channel is None:
            discussion_channel_id = self.get_settings()['discussion_channel']
            channel = self._bot.get_guild(config.MAIN_SERVER).get_channel(discussion_channel_id)

            if channel is None:
                raise Exception(f"Couldn't find discussion channel id {discussion_channel_id}")

            self._discussion_channel = channel

        return self._discussion_channel

    def get_polling_channel(self):
        channel = None

        if self._polling_channel is None:
            polling_channel_id = self.get_settings()['polling_channel']
            channel = self._bot.get_guild(config.MAIN_SERVER).get_channel(polling_channel_id)

            if channel is None:
                raise Exception(f"Couldn't find polling channel id {polling_channel_id}")

            self._polling_channel = channel

        return self._polling_channel

    def get_gc_approval_channel(self):
        channel = None

        if self._gc_approval_channel is None:
            gc_approval_channel_id = self.get_settings()['gc_approval_channel']
            channel = self._bot.get_guild(config.MAIN_SERVER).get_channel(gc_approval_channel_id)

            if channel is None:
                raise Exception(f"Couldn't find gc approval channel id {gc_approval_channel_id}")

            self._gc_approval_channel = channel

        return self._gc_approval_channel

    def get_punishments(self):
        return self.get_settings()["punishments"]

    def is_punishment_id(self, possible_id: str):
        return possible_id in self.get_punishments().keys()

    def get_punishment(self, punishment_id: str):
        return self.get_punishments()[punishment_id]

    def add_punishment(
            self,
            punishment_id: str,
            punishment_type: PunishmentType,
            duration: str,
            name: str,
            short_description: str,
            emoji: Emoji,
    ):
        """
        Add a punishment to the reprimand config file.

        Parameters
        ----------
        punishment_id: :class:`str`
            The id of the punishment.
        punishment_type: :class:`PunishmentType`
            The type of punishment th is entry is.
        duration: :class:`str`
            The duration of the punishmen in string form (5m, 1h, 30s, 0s, &c)
        name: :class:`str`
            The formal name of the punishment.
        short_description: :class:`str`
            A very brief description of the punishment (One Formal Warning - for example)
        emoji: :class:`Emoji`
            The emoji used in a modpoll to sympolise a vote for this punishment/
        """

        punishment_settings = self.get_settings()["punishments"]

        punishment_settings[punishment_id] = {
            "short_description": short_description,
            "type": punishment_type,
            "duration": format_time.parse(duration),
            "emoji": str(emoji),
            "name": name,
        }

        self.set_setting("punishments", punishment_settings)

    def remove_punishment(self, punishment_id: str):
        """
        Removes a punishment from the reprimand config file.

        Parameters
        ----------
        punishment_id: :class:`str`
            The id of the punishment being removed.
        """
        punishment_settings = self.get_settings()["punishments"]
        p_ids = punishment_settings.keys()

        if punishment_id in p_ids:
            del punishment_settings[punishment_id]
            self.set_setting("punishments", punishment_settings)

    def get_settings(self):
        return self._settings_handler.get_settings(config.MAIN_SERVER)["modules"][
            "reprimand"
        ]

    def get_main_guild(self):
        if self._guild == None:
            self._guild = self._bot.get_guild(config.MAIN_SERVER)
        return self._guild


class ModerationSystem:
    def __init__(self, bot):
        self.bot: Bot = bot
        self.cases = Cases(bot)
        self.bot.logger.info("Moderation System module has been initiated")
        self.bot.add_listener(self.on_ready, "on_ready")

    async def on_ready(self):
        await self.parse_cgs()

    async def parse_cgs(self):
        if os.path.exists("../cgs.json"):
            with open("../cgs.json", "r") as cg_json_file:
                self.parsed_cgs = json.load(cg_json_file)
        else:
            aiohttp_session = getattr(self.bot.http, "_HTTPClient__session")
            async with aiohttp_session.get(
                    "https://tldrnews.co.uk/discord-community-guidelines/"
            ) as response:
                html = await response.text()
                soup = bs4.BeautifulSoup(html, "html.parser")
                entry = soup.find("div", {"class": "entry-content"})
                if entry is None:
                    raise Exception(
                        "Couldn't find entry with CGs. Is the website down?"
                    )
                cg_list = [*entry.children][15]

                cg: bs4.element.Tag
                i: int

                def walk(step_str: str, cg_id: int, parent: Tag, branch: Tag) -> dict:
                    contents = branch.contents
                    result = {}

                    if len(contents) > 1:
                        step_str = f"{step_str}.{cg_id}"

                        for i, cg_c in enumerate(
                                filter(lambda cg_c: type(cg_c) == Tag, contents[1])
                        ):
                            result[step_str] = contents[0]
                            result = result | walk(step_str, i + 1, branch, cg_c)

                    else:
                        step_str = f"{step_str}.{cg_id}"
                        result[step_str] = contents[0]
                    return result

                parsed_cg = {}
                for i, cg in enumerate(filter(lambda cg: type(cg) == Tag, cg_list)):
                    cg_id = i + 1
                    str_cg_id = f"{cg_id}"
                    contents = cg.contents
                    parsed_cg[str_cg_id] = contents[0]

                    if len(contents) > 1:
                        cg_c: Tag
                        j: int
                        for j, cg_c in enumerate(
                                filter(lambda cg_c: type(cg_c) == Tag, contents[1])
                        ):
                            parsed_cg = parsed_cg | walk(str_cg_id, j + 1, cg, cg_c)

                self.parsed_cgs = parsed_cg
                if os.path.exists("cgs.json") is False:
                    with open("cgs.json", "w") as cg_json_file:
                        cg_json_file.write(json.dumps(self.parsed_cgs, indent=4))

    def is_valid_cg(self, cg_id: str) -> bool:
        return cg_id in self.parsed_cgs.keys()

    def get_parsed_cgs(self):
        return self.parsed_cgs

    def get_cg(self, cg_id: str) -> str:
        return self.parsed_cgs[cg_id]
