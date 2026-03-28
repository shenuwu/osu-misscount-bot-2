import discord
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

required_vars = ["DISCORD_TOKEN", "OSU_CLIENT_ID", "OSU_CLIENT_SECRET"]
missing = [v for v in required_vars if not os.getenv(v)]
if missing:
    print(f"ERROR: Ontbrekende environment variables: {', '.join(missing)}")
    exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot online als {bot.user}")
    await bot.load_extension("cogs.contest")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 {len(synced)} slash commands gesynchroniseerd")
    except Exception as e:
        print(f"Sync error: {e}")

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN niet gevonden in .env")
    else:
        asyncio.run(bot.start(token))
