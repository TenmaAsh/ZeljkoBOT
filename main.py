import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import asyncio
import os
import random
import certifi
from pymongo import MongoClient
from webserver import keep_alive  # pretpostavljam da ovo imaš
import sys
print(sys.version)

# --- Intents i bot ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)

# --- AFK ---
afk_users = {}  # {user_id: join_time}
SILENT_FILE = "silent.mp3"

# --- MongoDB ---
MONGO_URI = os.getenv("MONGO_URI")
mongo = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = mongo["discordbot"]
users = db["users"]

# --- Helper: kreiranje korisnika u bazi ---
def get_user(user):
    u = users.find_one({"user_id": user.id})
    if not u:
        users.insert_one({
            "user_id": user.id,
            "coins": 1000,
            "voice_minutes": 0,
            "played_blackjack": False,
            "last_voice_reward": datetime.datetime.utcnow(),
            "joined_at": datetime.datetime.utcnow()
        })
        return get_user(user)
    return u

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

    if not random_reward_loop.is_running():
        random_reward_loop.start()

# ----------------- AFK komande -----------------
@bot.tree.command(name="zeljkoafk", description="Zeljko ulazi u kanal i ide AFK")
async def zeljkoafk(interaction: discord.Interaction):
    if interaction.user.voice and interaction.user.voice.channel:
        channel = interaction.user.voice.channel
        vc = await channel.connect()
        afk_users[interaction.user.id] = datetime.datetime.now()

        await interaction.response.send_message(
            f"Željko 🍆 {interaction.user.name} je sada AFK u kanalu {channel.name}!"
        )

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

@bot.tree.command(name="zeljkotime", description="Vreme provedeno u AFK")
async def zeljkotime(interaction: discord.Interaction):
    if interaction.user.id in afk_users:
        delta = datetime.datetime.now() - afk_users[interaction.user.id]
        await interaction.response.send_message(
            f"Željko 🍆 je AFK već {str(delta).split('.')[0]}!"
        )
    else:
        await interaction.response.send_message("Željko🍆 Nije u AFK modu.")

# ----------------- Voice coins 100/sat -----------------
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    # ulazak u voice
    if not before.channel and after.channel:
        get_user(member)
        users.update_one(
            {"user_id": member.id},
            {"$set": {"last_voice_join": datetime.datetime.utcnow()}},
            upsert=True
        )

    # izlazak iz voice
    if before.channel and not after.channel:
        u = get_user(member)
        join = u.get("last_voice_join")
        if join:
            seconds = (datetime.datetime.utcnow() - join).total_seconds()
            hours = int(seconds // 3600)
            if hours > 0:
                coins = hours * 100
                users.update_one(
                    {"user_id": member.id},
                    {
                        "$inc": {"coins": coins, "voice_minutes": int(seconds // 60)}
                    }
                )

# ----------------- Coins komanda -----------------
@bot.tree.command(name="coins", description="Koliko coinsa imaš")
async def coins(interaction: discord.Interaction):
    u = get_user(interaction.user)
    await interaction.response.send_message(
        f"💰 {interaction.user.name} ima **{u['coins']} coinsa**"
    )

# ----------------- Blackjack -----------------
blackjack_games = {}  # {user_id: {"deck":[],"player":[],"dealer":[],"bet":int}}

def create_deck():
    suits = ["♠", "♥", "♦", "♣"]
    values = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
    deck = [f"{v}{s}" for v in values for s in suits]
    random.shuffle(deck)
    return deck

def card_value(card):
    v = card[:-1]
    if v in ["J","Q","K"]: return 10
    if v == "A": return 11
    return int(v)

def hand_value(hand):
    value = sum(card_value(c) for c in hand)
    aces = sum(1 for c in hand if c[:-1]=="A")
    while value>21 and aces:
        value-=10
        aces-=1
    return value

@bot.tree.command(name="blackjack", description="Započni blackjack igru")
@app_commands.describe(bet="Koliko želiš da uložiš")
async def blackjack(interaction: discord.Interaction, bet: int):
    u = get_user(interaction.user)
    if bet <=0:
        return await interaction.response.send_message("Moraš uložiti nešto.")
    if u["coins"]<bet:
        return await interaction.response.send_message("Nemaš dovoljno coinsa.")
    if interaction.user.id in blackjack_games:
        return await interaction.response.send_message("Već igraš blackjack!")

    # oduzmi bet i oznaci da je igrao
    users.update_one(
        {"user_id": interaction.user.id},
        {"$inc":{"coins": -bet}, "$set":{"played_blackjack": True}}
    )

    deck = create_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]

    blackjack_games[interaction.user.id] = {
        "deck": deck,
        "player": player,
        "dealer": dealer,
        "bet": bet
    }

    await interaction.response.send_message(
        f"🃏 **Blackjack**\n"
        f"Tvoje karte: {', '.join(player)} ({hand_value(player)})\n"
        f"Dealer: {dealer[0]}, ❓\n\n"
        f"Koristi /hit ili /stand"
    )

@bot.tree.command(name="hit", description="Uzmi novu kartu")
async def hit(interaction: discord.Interaction):
    if interaction.user.id not in blackjack_games:
        return await interaction.response.send_message("Nisi u blackjack igri.")
    game = blackjack_games[interaction.user.id]
    game["player"].append(game["deck"].pop())
    value = hand_value(game["player"])

    if value>21:
        blackjack_games.pop(interaction.user.id)
        await interaction.response.send_message(
            f"💥 Bust!\nTvoje karte: {', '.join(game['player'])} ({value})"
        )
    else:
        await interaction.response.send_message(
            f"Tvoje karte: {', '.join(game['player'])} ({value})\n"
            f"Dealer: {game['dealer'][0]}, ❓"
        )

@bot.tree.command(name="stand", description="Stani i završi rundu")
async def stand(interaction: discord.Interaction):
    if interaction.user.id not in blackjack_games:
        return await interaction.response.send_message("Nisi u blackjack igri.")
    game = blackjack_games[interaction.user.id]

    while hand_value(game["dealer"])<17:
        game["dealer"].append(game["deck"].pop())

    player_val = hand_value(game["player"])
    dealer_val = hand_value(game["dealer"])
    bet = game["bet"]
    blackjack_games.pop(interaction.user.id)

    if dealer_val>21 or player_val>dealer_val:
        result="🏆 Pobedio si!"
        users.update_one({"user_id": interaction.user.id}, {"$inc":{"coins": bet*2}})
    elif player_val==dealer_val:
        result="🤝 Nerešeno."
        users.update_one({"user_id": interaction.user.id}, {"$inc":{"coins": bet}})
    else:
        result="💀 Izgubio si."

    await interaction.response.send_message(
        f"🃏 **Rezultat**\n"
        f"Tvoje: {', '.join(game['player'])} ({player_val})\n"
        f"Dealer: {', '.join(game['dealer'])} ({dealer_val})\n\n"
        f"{result}"
    )

# ----------------- 8h random reward -----------------
@tasks.loop(hours=8)
async def random_reward_loop():
    # uzmi sve koji su igrali blackjack
    eligible = list(users.find({"played_blackjack": True}))
    if not eligible:
        return
    winner = random.choice(eligible)
    users.update_one({"user_id": winner["user_id"]}, {"$inc":{"coins":500}})
    try:
        user = await bot.fetch_user(winner["user_id"])
        await user.send("🎁 Čestitamo! Dobio si 500 coinsa iz random nagrade!")
    except:
        pass

# ----------------- START -----------------
TOKEN = os.getenv("_TOKDISCORDEN")
bot.run(TOKEN)
