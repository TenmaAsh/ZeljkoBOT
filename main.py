import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import datetime
import asyncio
import os
import random
import sys

print("Python verzija:", sys.version)

# --- Intents i bot ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='/', intents=intents)

# --- AFK ---
afk_users = {}  # {user_id: join_time}
SILENT_FILE = "silent.mp3"

# --- Users in-memory storage ---
users_data = {}  # {user_id: {"coins": int, "voice_minutes": int, "played_blackjack": bool, "last_voice_join": datetime}}

# --- Helper: kreiranje/uzimanje korisnika ---
def get_user(user):
    if user.id not in users_data:
        users_data[user.id] = {
            "coins": 1000,
            "voice_minutes": 0,
            "played_blackjack": False,
            "last_voice_join": None
        }
    return users_data[user.id]

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
        await interaction.response.send_message("Željko 🍆 Nije u AFK modu.")

# ----------------- Voice coins 100/sat -----------------
@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    u = get_user(member)

    # ulazak u voice
    if not before.channel and after.channel:
        u["last_voice_join"] = datetime.datetime.utcnow()

    # izlazak iz voice
    if before.channel and not after.channel:
        join = u.get("last_voice_join")
        if join:
            seconds = (datetime.datetime.utcnow() - join).total_seconds()
            hours = int(seconds // 3600)
            if hours > 0:
                coins = hours * 100
                u["coins"] += coins
                u["voice_minutes"] += int(seconds // 60)

# ----------------- Coins komanda -----------------
@bot.tree.command(name="coins", description="Koliko coinsa imaš")
async def coins(interaction: discord.Interaction):
    u = get_user(interaction.user)
    await interaction.response.send_message(
        f"💰 {interaction.user.name} ima **{u['coins']} coinsa**"
    )

# ----------------- Blackjack -----------------
blackjack_games = {}  # {user_id: game_dict}

def create_deck():
    suits = ["♠️", "❤️", "♦️", "♣️"]
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
        value -= 10
        aces -= 1
    return value

# --- Blackjack View sa dugmićima ---
class BlackjackView(ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.split_active = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    async def update_buttons(self, game):
        self.clear_items()
        self.add_item(ui.Button(label="Hit", style=discord.ButtonStyle.green, custom_id="hit"))
        self.add_item(ui.Button(label="Stand", style=discord.ButtonStyle.red, custom_id="stand"))

        if len(game["player"]) == 2 and not self.split_active:
            self.add_item(ui.Button(label="Double", style=discord.ButtonStyle.blurple, custom_id="double"))
            if card_value(game["player"][0]) == card_value(game["player"][1]):
                self.add_item(ui.Button(label="Split", style=discord.ButtonStyle.gray, custom_id="split"))

    async def stand_game(self, interaction):
        game = blackjack_games[self.user_id]

        # Pravilo za dilera: ako je 16 ili manje, povlači kartu; 17 ili više stoji
        while hand_value(game["dealer"]) < 17:
            game["dealer"].append(game["deck"].pop())

        player_val = hand_value(game["player"])
        dealer_val = hand_value(game["dealer"])
        bet = game["bet"]
        blackjack_games.pop(self.user_id)

        u = get_user(interaction.user)
        if dealer_val > 21 or player_val > dealer_val:
            result = "🏆 Pobedio si!"
            u["coins"] += bet * 2
        elif player_val == dealer_val:
            result = "🤝 Nerešeno."
            u["coins"] += bet
        else:
            result = "💀 Izgubio si."

        await interaction.response.edit_message(
            content=f"🃏 **Rezultat**\n"
                    f"Tvoje: {', '.join(game['player'])} ({player_val})\n"
                    f"Dealer: {', '.join(game['dealer'])} ({dealer_val})\n\n"
                    f"{result}",
            view=None
        )

    @ui.button(label="Hit", style=discord.ButtonStyle.green)
    async def hit_button(self, interaction: discord.Interaction, button: ui.Button):
        game = blackjack_games[self.user_id]
        game["player"].append(game["deck"].pop())
        value = hand_value(game["player"])

        if value > 21:
            blackjack_games.pop(self.user_id)
            await interaction.response.edit_message(
                content=f"💥 Bust!\nTvoje karte: {', '.join(game['player'])} ({value})",
                view=None
            )
        elif value == 21:
            await self.stand_game(interaction)
        else:
            await self.update_buttons(game)
            await interaction.response.edit_message(
                content=f"Tvoje karte: {', '.join(game['player'])} ({value})\nDealer: {game['dealer'][0]}, ❓",
                view=self
            )

    @ui.button(label="Stand", style=discord.ButtonStyle.red)
    async def stand_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.stand_game(interaction)

    @ui.button(label="Double", style=discord.ButtonStyle.blurple)
    async def double_button(self, interaction: discord.Interaction, button: ui.Button):
        game = blackjack_games[self.user_id]
        u = get_user(interaction.user)
        bet = game["bet"]

        if u["coins"] < bet:
            return await interaction.response.send_message("Nema dovoljno coinsa za Double!", ephemeral=True)

        u["coins"] -= bet
        game["bet"] *= 2
        game["player"].append(game["deck"].pop())
        await self.stand_game(interaction)

    @ui.button(label="Split", style=discord.ButtonStyle.gray)
    async def split_button(self, interaction: discord.Interaction, button: ui.Button):
        game = blackjack_games[self.user_id]
        self.split_active = True

        first_card = game["player"][0]
        second_card = game["player"][1]
        game["player"] = [first_card, game["deck"].pop()]
        game["split_hand"] = [second_card, game["deck"].pop()]
        game["current_hand"] = "player"

        await interaction.response.edit_message(
            content=f"Ruka podeljena!\nPrva ruka: {', '.join(game['player'])}\nDruga ruka: {', '.join(game['split_hand'])}\nIgraj prvu ruku.",
            view=self
        )


# --- Pokretanje igre ---
@bot.tree.command(name="blackjack", description="Započni blackjack igru")
@app_commands.describe(bet="Koliko želiš da uložiš")
async def blackjack(interaction: discord.Interaction, bet: int):
    u = get_user(interaction.user)
    if bet <= 0:
        return await interaction.response.send_message("Moraš uložiti nešto.")
    if u["coins"] < bet:
        return await interaction.response.send_message("Nemaš dovoljno coinsa.")
    if interaction.user.id in blackjack_games:
        return await interaction.response.send_message("Već igraš blackjack!")

    u["coins"] -= bet
    u["played_blackjack"] = True

    deck = create_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]

    blackjack_games[interaction.user.id] = {
        "deck": deck,
        "player": player,
        "dealer": dealer,
        "bet": bet
    }

    view = BlackjackView(interaction.user.id)
    await view.update_buttons(blackjack_games[interaction.user.id])

    await interaction.response.send_message(
        f"🃏 **Blackjack**\n"
        f"Tvoje karte: {', '.join(player)} ({hand_value(player)})\n"
        f"Dealer: {dealer[0]}, ❓",
        view=view
    )

# ----------------- 8h random reward -----------------
@tasks.loop(hours=8)
async def random_reward_loop():
    eligible = [uid for uid, u in users_data.items() if u.get("played_blackjack")]
    if not eligible:
        return
    winner_id = random.choice(eligible)
    users_data[winner_id]["coins"] += 500
    try:
        user = await bot.fetch_user(winner_id)
        await user.send("🎁 Čestitamo! Dobio si 500 coinsa iz random nagrade!")
    except:
        pass



# ----------------- START -----------------
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("⚠️ DISCORD_TOKEN nije postavljen!")
    exit(1)

bot.run(TOKEN)
