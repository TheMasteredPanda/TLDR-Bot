import config
import discord
from datetime import datetime
from modules import command, database, embed_maker, pubsub
from discord.ext import commands

db = database.Connection()


class Connectivity(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(hidden=True, help='connect your patreon account to your discord account', usage='link_patreon (account)',
                      examples=['link_patreon US', 'link_patreon UK', 'link_patreon EU'], clearance='Dev', cls=command.Command)
    async def link_patreon(self, ctx, account=None):
        if account is None:
            return await embed_maker.command_error(ctx)
        if account and account.lower() not in ['us', 'uk', 'eu']:
            embed = embed_maker.message(ctx, f'{account} is not a valid TLDR patreon account, please choose between `UK`|`US`|`EU`', colour='red')
            return await ctx.send(embed=embed)

        patreons = db.get_data('patreons', ctx.guild.id)
        if str(ctx.author.id) in patreons:
            patreon = patreons[str(ctx.author.id)]
            if account in patreon['pledges']:
                embed = embed_maker.message(ctx, f'You\'ve already linked your account to TLDR {account} patreon', colour='orange')
                return await ctx.send(embed=embed)

        db.pubsub.delete_one({'discord_id': ctx.author.id})

        embed = embed_maker.message(ctx, f'Please click on this [__link__](http://www.saarts.xyz:5000/link_patreon_{account.lower()}) to connect your discord account to TLDR {account} patreon\n\n'
                                         f'The bot will dm you when the account has been connected')
        await ctx.send(embed=embed)

        db.pubsub.insert_one({
            'discord_id': ctx.author.id,
            'guild_id': ctx.guild.id
        })

        # Patron link sub
        subscriber = pubsub.Subscriber(db.pubsub, 'patreon_link', callback=self.on_patreon_link, matching={'discord_id': ctx.author.id})
        subscriber.listen()

    async def on_patreon_link(self, data):
        print('called')
        patreon_id = data['patreon_id']
        discord_id = data['discord_id']
        pledges = data['pledges']

        # Give user patreon role
        doc = db.pubsub.find_one({'discord_id': discord_id})
        db.pubsub.delete_one({'discord_id': discord_id})

        guild_id = doc['guild_id']
        guild = await self.bot.fetch_guild(int(guild_id))

        member = guild.get_member(int(discord_id))
        if member is None:
            member = await guild.fetch_member(int(discord_id))

        # Sort through pledges, add roles and create string to send to member
        support = []
        for p in pledges:
            support.append(f'TLDR {p.upper()}')
            role_name = f'Patreon - TLDR {p.upper()}'

            role = discord.utils.find(lambda r: r.name == role_name, guild.roles)
            if role is None:
                role = await guild.create_role(name=role_name)

            await member.add_roles(role)

            # add user to patreon db
            db.data.update_one({'guild_id': guild.id}, {'$set': {f'patreons.{discord_id}.patreon_id': patreon_id},
                                                        '$push': {f'patreons.{discord_id}.pledges': p}})

        embed = discord.Embed(colour=config.DEFAULT_EMBED_COLOUR, description=f'Thank you for your support of {"and ".join(support)}, you will now get access to patreon only channels and plenty of other perks',
                              timestamp=datetime.now())
        embed.set_footer(text=f'{member}', icon_url=member.avatar_url)
        return await member.send(embed=embed)


def setup(bot):
    return bot.add_cog(Connectivity(bot))
