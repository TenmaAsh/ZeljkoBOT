import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import asyncio
import os
from webserver import keep_alive

# --- Intents i bot ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)

# --- Čuvanje AFK stanja ---
afk_users = {}  # {user_id: join_time}
SILENT_FILE = "silent.mp3"

# --- Task za održavanje VC alive ---
@tasks.loop(seconds=10)
async def keep_vc_alive():
    for vc in bot.voice_clients:
        if not vc.is_connected():
            await vc.disconnect()
        elif not vc.is_playing():
            vc.play(discord.FFmpegPCMAudio(SILENT_FILE))

# --- on_ready ---
@bot.event
async def on_ready():
    print(f"{bot.user} je online (Zeljko AFK)!")
    keep_alive()
    keep_vc_alive.start()

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Greska pri sync-u: {e}")

# ----------------- SLASH KOMANDE -----------------

# /zeljkoafk
@bot.tree.command(name="zeljkooafk", description="Zeljko ulazi u kanal i ide AFK")
async def zeljkoafk(interaction: discord.Interaction):
    if interaction.user.voice and interaction.user.voice.channel:
        channel = interaction.user.voice.channel
        vc = await channel.connect()
        afk_users[interaction.user.id] = datetime.datetime.now()

        await interaction.response.send_message(
            f"Željko 🍆 {interaction.user.name} je sada AFK u kanalu {channel.name}!"
        )

        # --- ORIGINALNI AFK LOOP (NETAKNUT) ---
        async def afk_loop():
            while interaction.user.id in afk_users:
                if not vc.is_playing():
                    vc.play(discord.FFmpegPCMAudio(SILENT_FILE))
                await asyncio.sleep(10)

        asyncio.create_task(afk_loop())
    else:
        await interaction.response.send_message(
            "Željko 🍆: Moraš biti u voice kanalu da koristiš ovu komandu."
        )

# /zeljkoleave
@bot.tree.command(name="zeljkoleave", description="Izađi iz AFK kanala")
async def zeljkoleave(interaction: discord.Interaction):
    if interaction.user.id in afk_users:
        afk_users.pop(interaction.user.id)

        if interaction.user.voice and interaction.user.voice.channel:
            vc = discord.utils.get(bot.voice_clients, guild=interaction.guild)
            if vc:
                await vc.disconnect()

        await interaction.response.send_message("Željko 🍆 Izašao iz AFK kanala!")
    else:
        await interaction.response.send_message("Željko 🍆: Nisi u AFK modu.")

# /zeljkotime
@bot.tree.command(name="zeljkotime", description="Vreme provedeno u AFK")
async def zeljkotime(interaction: discord.Interaction):
    if interaction.user.id in afk_users:
        delta = datetime.datetime.now() - afk_users[interaction.user.id]
        await interaction.response.send_message(
            f"Željko 🍆 je AFK već {str(delta).split('.')[0]}!"
        )
    else:
        await interaction.response.send_message("Željko🍆 Nije u AFK modu.")

# ----------------- START -----------------

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)