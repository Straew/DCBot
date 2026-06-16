import discord
from discord.ext import commands

def setup_events(bot):
    
    @bot.event
    async def on_ready():
        print(f"wsp, {bot.user.name}!")
        await bot.tree.sync()  # Sync slash commands

    @bot.event
    async def on_message(message):
        if "dream" in message.content.lower():
            await message.channel.send(f"{message.author.mention} - Bro is not Aremsu AKA arnav jhung bahadur dahalal 😭 🙏 ")
            
        await bot.process_commands(message)

    @bot.command()
    async def hello(ctx):
        await ctx.send(f"wzzzpppp {ctx.author.mention}! wait wait waaiiiii omenomame hentekabaina.")
