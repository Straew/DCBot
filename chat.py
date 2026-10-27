import discord
from discord import app_commands
from ollama import AsyncClient

MODEL = "llama3.2"
client = AsyncClient()  # or AsyncClient(host="http://other-pc-ip:11434")

SYSTEM_PROMPT = "You are a chill, funny Discord bot. Keep answers short."

def split_text(text, limit=1900):
    # Discord has a 2000 char limit per message
    return [text[i:i + limit] for i in range(0, len(text), limit)] or ["..."]

def setup_ollama_commands(bot):

    @bot.tree.command(name="ask", description="Ask the AI something")
    @app_commands.describe(prompt="What you wanna ask")
    async def ask(interaction: discord.Interaction, prompt: str):
        await interaction.response.defer(thinking=True)  # gives you more than 3s to reply
        try:
            response = await client.chat(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            reply = response["message"]["content"]
        except Exception as e:
            print(f"Ollama error: {e}")
            await interaction.followup.send("ollama ain't responding 💀 is it running?")
            return

        for chunk in split_text(reply):
            await interaction.followup.send(chunk)

    # Optional: reply when someone @mentions the bot
    @bot.listen("on_message")
    async def on_mention(message: discord.Message):
        if message.author.bot or bot.user not in message.mentions:
            return
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not prompt:
            return
        async with message.channel.typing():
            try:
                response = await client.chat(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                )
                reply = response["message"]["content"]
            except Exception as e:
                print(f"Ollama error: {e}")
                reply = "ollama ain't responding 💀"
        for chunk in split_text(reply):
            await message.reply(chunk)
