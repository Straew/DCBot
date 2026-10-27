import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
from bot_events import setup_events
from music import setup_music_commands
from chat import setup_ollama_commands
load_dotenv()
token = os.getenv('DISCORD_TOKEN')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Setup all features
setup_events(bot)
setup_music_commands(bot)
setup_ollama_commands(bot)
bot.run(token, log_handler=handler, log_level=logging.DEBUG)

