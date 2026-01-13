import discord
from discord import app_commands
from discord.ext import commands, tasks
import datetime
import asyncio
import os
from discord.ui import View, Button
from webserver import keep_alive
import random

# --- Intents i bot ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)

# --- Čuvanje AFK stanja ---
afk_users = {}  # {user_id: join_time}
SILENT_FILE = "silent.mp3"

# --- Users in-memory ---
users_data = {}  # {user_id: {"coins": int, "voice_minutes": int, "played_blackjack": bool, "last_voice_join": datetime}}

# --- Helper: korisnik ---
def get_user(user):
    if user.id not in users_data:
        users_data[user.id] = {
            "coins": 100000,
            "voice_minutes": 0,
            "played_blackjack": False,
            "last_voice_join": None
        }
    return users_data[user.id]

# --- Task za VC ---
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

# ----------------- Emoji helper -----------------
CARD_EMOJIS = {
    "A": "🇦",  # :regional_indicator_a:
    "J": "🇯",  # :regional_indicator_j:
    "Q": "🇶",  # :regional_indicator_q:
    "K": "🇰",  # :regional_indicator_k:
    "2": "2️⃣",
    "3": "3️⃣",
    "4": "4️⃣",
    "5": "5️⃣",
    "6": "6️⃣",
    "7": "7️⃣",
    "8": "8️⃣",
    "9": "9️⃣",
    "10": "🔟"
}
SUIT_EMOJIS = {"♠": "♠️", "♥": "❤️", "♦": "♦️", "♣": "♣️"}

def card_to_emoji(card: str) -> str:
    value = card[:-1]
    suit = card[-1]
    return f"{CARD_EMOJIS.get(value,value)}{SUIT_EMOJIS.get(suit,suit)}"

def hand_to_emoji(hand: list) -> str:
    return " ".join(card_to_emoji(c) for c in hand)

# ----------------- Blackjack storage -----------------
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

# ----------------- Blackjack View -----------------
class BlackjackView(View):
    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.green)
    async def hit_button(self, interaction: discord.Interaction, button: Button):
        await self.process_hit(interaction)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.red)
    async def stand_button(self, interaction: discord.Interaction, button: Button):
        await self.process_stand(interaction)

    async def process_hit(self, interaction):
        game = blackjack_games.get(self.user_id)
        if not game: 
            await interaction.response.send_message("Nisi u igri.", ephemeral=True)
            return

        game["player"].append(game["deck"].pop())
        value = hand_value(game["player"])

        if value > 21:
            blackjack_games.pop(self.user_id)
            await interaction.response.edit_message(
                content=f"💥 Bust!\nTvoje karte: {hand_to_emoji(game['player'])} ({value})\nDealer: {card_to_emoji(game['dealer'][0])}, ❓",
                view=None
            )
        elif value == 21:
            await self.process_stand(interaction)
        else:
            await interaction.response.edit_message(
                content=f"🃏 Blackjack\nTvoje karte: {hand_to_emoji(game['player'])} ({value})\nDealer: {card_to_emoji(game['dealer'][0])}, ❓",
                view=self
            )

    async def process_stand(self, interaction):
        game = blackjack_games.get(self.user_id)
        if not game: 
            await interaction.response.send_message("Nisi u igri.", ephemeral=True)
            return

        # Dealer igra
        while hand_value(game["dealer"]) < 17:
            game["dealer"].append(game["deck"].pop())

        player_val = hand_value(game["player"])
        dealer_val = hand_value(game["dealer"])
        bet = game["bet"]
        blackjack_games.pop(self.user_id)
        user_data = get_user(interaction.user)

        if dealer_val>21 or player_val>dealer_val:
            result="🏆 Pobedio si!"
            user_data["coins"] += bet*2
        elif player_val==dealer_val:
            result="🤝 Nerešeno."
            user_data["coins"] += bet
        else:
            result="💀 Izgubio si."

        await interaction.response.edit_message(
            content=f"🃏 **Rezultat**\nTvoje karte: {hand_to_emoji(game['player'])} ({player_val})\nDealer: {hand_to_emoji(game['dealer'])} ({dealer_val})\n\n{result}",
            view=None
        )

# ----------------- Slash komanda Blackjack -----------------
@bot.tree.command(name="blackjack", description="Započni blackjack igru")
@app_commands.describe(bet="Koliko želiš da uložiš")
async def blackjack(interaction: discord.Interaction, bet: int):
    u = get_user(interaction.user)
    if bet <=0: return await interaction.response.send_message("Moraš uložiti nešto.")
    if u["coins"] < bet: return await interaction.response.send_message("Nemaš dovoljno coinsa.")
    if interaction.user.id in blackjack_games: return await interaction.response.send_message("Već igraš!")

    u["coins"] -= bet
    u["played_blackjack"] = True

    deck = create_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]

    blackjack_games[interaction.user.id] = {"deck": deck, "player": player, "dealer": dealer, "bet": bet}

    view = BlackjackView(interaction.user.id)

    await interaction.response.send_message(
        f"🃏 Blackjack\nTvoje karte: {hand_to_emoji(player)} ({hand_value(player)})\nDealer: {card_to_emoji(dealer[0])}, ❓",
        view=view
    )

# ----------------- AFK komande (netaknute) -----------------
@bot.tree.command(name="zeljkoafk", description="Zeljko ulazi u kanal i ide AFK")
async def zeljkoafk(interaction: discord.Interaction):
    if interaction.user.voice and interaction.user.voice.channel:
        channel = interaction.user.voice.channel
        vc = await channel.connect()
        afk_users[interaction.user.id] = datetime.datetime.now()
        await interaction.response.send_message(f"Zeljko 🎲 {interaction.user.name} je sada AFK u kanalu {channel.name}!")

        async def afk_loop():
            while interaction.user.id in afk_users:
                if not vc.is_playing():
                    vc.play(discord.FFmpegPCMAudio(SILENT_FILE))
                await asyncio.sleep(10)

        asyncio.create_task(afk_loop())
    else:
        await interaction.response.send_message("Zeljko 🎲: Moraš biti u voice kanalu da koristiš ovu komandu.")

@bot.tree.command(name="zeljkoleave", description="Izađi iz AFK kanala")
async def zeljkoleave(interaction: discord.Interaction):
    if interaction.user.id in afk_users:
        afk_users.pop(interaction.user.id)
        vc = discord.utils.get(bot.voice_clients, guild=interaction.guild)
        if vc: await vc.disconnect()
        await interaction.response.send_message("Zeljko 🎲 Izašao iz AFK kanala!")
    else:
        await interaction.response.send_message("Zeljko 🎲: Nisi u AFK modu.")

@bot.tree.command(name="zeljkotime", description="Vreme provedeno u AFK")
async def zeljkotimetime(interaction: discord.Interaction):
    if interaction.user.id in afk_users:
        delta = datetime.datetime.now() - afk_users[interaction.user.id]
        await interaction.response.send_message(f"Zeljko 🎲 je AFK već {str(delta).split('.')[0]}!")
    else:
        await interaction.response.send_message("Zeljko 🎲 Nije u AFK modu.")

# ----------------- Coins komanda -----------------
@bot.tree.command(name="coins", description="Koliko coinsa imaš")
async def coins(interaction: discord.Interaction):
    u = get_user(interaction.user)
    await interaction.response.send_message(f"💰 {interaction.user.name} ima **{u['coins']} coinsa**")

# ----------------- START -----------------
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
