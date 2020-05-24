import discord
import config
from discord.ext import commands
from modules import database, command, embed_maker
from datetime import datetime

db = database.Connection()


class Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Change the channel where level up messages are sent',
                      usage='level_up_channel [#channel]', examples=['level_up_channel #bots'],
                      clearance='Mod', cls=command.Command)
    async def level_up_channel(self, ctx, channel=None):
        data = db.levels.find_one({'guild_id': ctx.guild.id})
        if data is None:
            data = self.bot.add_collections(ctx.guild.id, 'levels')

        current_channel = data['level_up_channel']

        if current_channel == 0:
            current_channel_string = 'None'
        else:
            current_channel_string = f'<#{current_channel}>'

        if channel is None:
            embed_colour = config.EMBED_COLOUR
            embed = discord.Embed(colour=embed_colour, timestamp=datetime.now(),
                                  description='Change the channel where level up announcements are sent.')
            embed.add_field(name='>Current Settings', value=current_channel_string, inline=False)
            embed.add_field(name='>Update', value='**levelUpChannel [#channel]**', inline=False)
            embed.add_field(name='>Valid Input', value='**Channel:** Any text channel | mention only', inline=False)
            embed.set_footer(text=ctx.author, icon_url=ctx.author.avatar_url)
            embed.set_author(name='Level Up Channel', icon_url=ctx.guild.icon_url)
            return await ctx.send(embed=embed)

        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]
            if channel.id == current_channel:
                return await embed_maker.message(
                    ctx, f'Level up channel is already set to <#{channel.id}>',
                    colour='red'
                )

            db.levels.update_one({'guild_id': ctx.guild.id}, {'$set': {f'level_up_channel': channel.id}})
            return await embed_maker.message(ctx, f'Level up channel has been set to <#{channel.id}>', colour='green')
        else:
            return await embed_maker.command_error(ctx, '[#channel]')


def setup(bot):
    bot.add_cog(Settings(bot))
