import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import random
import re
import os
import io
import aiohttp
from datetime import datetime, timezone, timedelta, time
from PIL import Image

# ───────────────────────────────────────────────
#  CONFIGURATION
# ───────────────────────────────────────────────

TOKEN = os.environ["DISCORD_TOKEN"]

WELCOME_CHANNEL_ID         = 1488662459009994965
BUMP_CHANNEL_ID            = 1381771230964748370
GUILD_ID                   = 1381768080610426930
BUMP_BOT_ID                = 302050872383242240
IMAGE_LOG_CHANNEL_ID       = 1381770621054091306
ANNOUNCE_SOURCE_CHANNEL_ID = 1489993668126572545
EMBED_POOL_CHANNEL_ID      = 1501344668242280559

# Quiz Kanalları
QUIZ_CHANNEL_ID            = 1517149813085311107
QUIZ_LOG_CHANNEL_ID        = 1517151082529296444

WELCOME_MESSAGE = "{member} aramıza katıldı fln filan iste 😒"
BUMP_MESSAGE    = "buuuuuump"

# ───────────────────────────────────────────────
#  BOT SETUP
# ───────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Runtime state
bump_task          = None
media_loop_running = False
media_loop_task    = None
media_queue        = []
welcome_message_log: dict = {}

# Quiz State
quiz_state = {
    "active": False,
    "vn_title": "",
    "vn_alttitle": "",
    "image_bytes": None,
    "crop_center": (0.5, 0.5),
    "rotation_angle": 0,
    "zoom_factor": 0.2,  # Başlangıçta yakından başlar (0.2 = %20 alan)
    "wrong_guesses": 0
}

# ───────────────────────────────────────────────
#  QUIZ HELPERS & IMAGE PROCESSING
# ───────────────────────────────────────────────

def normalize_title(text: str) -> str:
    """Küçük/büyük harf, boşluk ve özel karakter toleransı sağlar."""
    if not text:
        return ""
    text = text.lower().strip()
    return re.sub(r'[\s\-_:,\.\!\?\'"”“\(\)]', '', text)


def generate_quiz_image(img_bytes: bytes, angle: int, zoom_factor: float, center_pct: tuple) -> io.BytesIO:
    """Görsele gri filtre, rotasyon ve zoom uygulayarak işler."""
    img = Image.open(io.BytesIO(img_bytes))
    img = img.convert("L")  # Gri filtre (Grayscale)
    
    orig_w, orig_h = img.size
    cx, cy = center_pct
    
    # Zoom alanı hesaplama (Crop)
    crop_w = max(20, int(orig_w * zoom_factor))
    crop_h = max(20, int(orig_h * zoom_factor))
    
    center_x = int(orig_w * cx)
    center_y = int(orig_h * cy)
    
    left = max(0, min(center_x - crop_w // 2, orig_w - crop_w))
    top = max(0, min(center_y - crop_h // 2, orig_h - crop_h))
    right = left + crop_w
    bottom = top + crop_h
    
    img = img.crop((left, top, right, bottom))
    img = img.rotate(angle, expand=True)  # Rastgele rotasyon
    img = img.resize((orig_w, orig_h), Image.Resampling.LANCZOS)  # Orijinal boyuta esnetme
    
    out_bytes = io.BytesIO()
    img.save(out_bytes, format="PNG")
    out_bytes.seek(0)
    return out_bytes


async def fetch_top_vns() -> list:
    """VNDB API v2 üzerinden popülerlik sırasına göre ilk 50 VN'yi çeker."""
    url = "https://api.vndb.org/v2/vn"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "DiscordVNQuizBot/1.0"
    }
    payload = {
        "filters": ["and", ["id", ">=", "v1"]],
        "fields": "title, alttitle, image.url",
        "sort": "popularity",
        "reverse": True,
        "results": 50
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("results", [])
                print(f"[quiz] VNDB API Error: {resp.status}")
                return []
    except Exception as e:
        print(f"[quiz] Connection Error: {e}")
        return []


async def start_quiz_question():
    """Yeni bir quiz sorusu oluşturur ve ilgili kanala gönderir."""
    global quiz_state
    quiz_channel = bot.get_channel(QUIZ_CHANNEL_ID)
    if not quiz_channel:
        print("[quiz] HATA: Quiz kanalı bulunamadı.")
        return

    # Eğer aktif bir soru varsa ve yeni soru tetiklendiyse eskisini kapatıp cevabı açıkla
    if quiz_state["active"]:
        await quiz_channel.send(f"⏰ **Süre doldu / Yeni soru istendi!** Kimse doğru yanıtı veremedi. Cevap: **{quiz_state['vn_title']}** olacaktı.")
        quiz_state["active"] = False

    vns = await fetch_top_vns()
    valid_vns = [v for v in vns if v.get("image") and v.get("image").get("url")]
    
    if not valid_vns:
        print("[quiz] HATA: Geçerli resme sahip VN listesi alınamadı.")
        return

    chosen_vn = random.choice(valid_vns)
    title = chosen_vn.get("title")
    alttitle = chosen_vn.get("alttitle", "")
    img_url = chosen_vn.get("image").get("url")

    # Resmi indir
    async with aiohttp.ClientSession() as session:
        async with session.get(img_url) as resp:
            if resp.status != 200:
                print("[quiz] HATA: Kapak resmi indirilemedi.")
                return
            img_bytes = await resp.read()

    # Quiz durumunu ayarla
    quiz_state["active"] = True
    quiz_state["vn_title"] = title
    quiz_state["vn_alttitle"] = alttitle
    quiz_state["image_bytes"] = img_bytes
    quiz_state["crop_center"] = (random.uniform(0.3, 0.7), random.uniform(0.3, 0.7)) # Sabit bir merkez seç
    quiz_state["rotation_angle"] = random.randint(35, 325)
    quiz_state["zoom_factor"] = 0.20
    quiz_state["wrong_guesses"] = 0

    # Görseli oluştur ve gönder
    quiz_img = generate_quiz_image(
        img_bytes, 
        quiz_state["rotation_angle"], 
        quiz_state["zoom_factor"], 
        quiz_state["crop_center"]
    )

    await quiz_channel.send(
        "🎮 **Yeni Soru!** Bu hangi seri?",
        file=discord.File(fp=quiz_img, filename="quiz_question.png")
    )
    print(f"[quiz] Soru hazırlandı: {title}")

# ───────────────────────────────────────────────
#  BUMP HELPERS
# ───────────────────────────────────────────────

async def schedule_bump():
    try:
        await asyncio.sleep(2 * 60 * 60)
        channel = bot.get_channel(BUMP_CHANNEL_ID)
        if channel:
            await channel.send(BUMP_MESSAGE)
            print("[bump] Reminder sent.")
    except asyncio.CancelledError:
        pass


async def schedule_bump_in(seconds: float):
    try:
        await asyncio.sleep(max(0, seconds))
        channel = bot.get_channel(BUMP_CHANNEL_ID)
        if channel:
            await channel.send(BUMP_MESSAGE)
            print("[bump] Reminder sent.")
    except asyncio.CancelledError:
        pass


# ───────────────────────────────────────────────
#  RANDOM MEDIA HELPERS
# ───────────────────────────────────────────────

async def get_media_queue() -> list:
    try:
        pool_channel = bot.get_channel(EMBED_POOL_CHANNEL_ID)
        if pool_channel is None:
            print("[random_media] ERROR: Pool channel not found.")
            return []
        image_extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".webm")
        valid = []
        async for msg in pool_channel.history(limit=200):
            media = [
                (a.url, a.filename)
                for a in msg.attachments
                if a.filename.lower().endswith(image_extensions)
            ]
            if media:
                valid.append((msg.author.name, media))
        random.shuffle(valid)
        print(f"[random_media] Built queue with {len(valid)} items.")
        return valid
    except Exception as e:
        print(f"[random_media] ERROR building queue: {e}")
        return []


async def post_random_media():
    global media_queue
    try:
        welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
        if welcome_channel is None:
            print("[random_media] ERROR: Welcome channel not found.")
            return
        if not media_queue:
            print("[random_media] Queue empty, rebuilding...")
            media_queue = await get_media_queue()
        if not media_queue:
            print("[random_media] No media found in pool channel.")
            return
        author_name, media_list = media_queue.pop(0)
        url, filename = random.choice(media_list)
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"[random_media] Failed to fetch media: HTTP {resp.status}")
                    return
                data = await resp.read()
        await welcome_channel.send(
            f"**{author_name}**",
            file=discord.File(fp=io.BytesIO(data), filename=filename)
        )
        print(f"[random_media] Posted. {len(media_queue)} remaining in queue.")
    except Exception as e:
        print(f"[random_media] ERROR posting: {e}")


async def get_active_user_count() -> int:
    try:
        welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
        if welcome_channel is None:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        users = set()
        async for msg in welcome_channel.history(limit=100, after=cutoff):
            if not msg.author.bot:
                users.add(msg.author.id)
        return len(users)
    except Exception as e:
        print(f"[random_media] ERROR counting users: {e}")
        return 0


async def run_media_loop(initial_delay: float = 0):
    global media_loop_running
    try:
        if initial_delay > 0:
            print(f"[random_media] Waiting {int(initial_delay // 60)} minutes before first post.")
            await asyncio.sleep(initial_delay)
    except asyncio.CancelledError:
        print("[random_media] Loop cancelled during initial delay.")
        return

    while media_loop_running:
        try:
            active_users = await get_active_user_count()
            print(f"[random_media] Active users in last 30min: {active_users}")
            if active_users >= 5:
                interval = 30 * 60
            elif active_users >= 3:
                interval = 60 * 60
            else:
                interval = 3 * 60 * 60
            await post_random_media()
            print(f"[random_media] Next post in {interval // 60} minutes.")
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            print("[random_media] Loop cancelled.")
            break
        except Exception as e:
            print(f"[random_media] Unexpected error in loop: {e}")
            await asyncio.sleep(60)


# ───────────────────────────────────────────────
#  SCHEDULED QUIZ TASK (TSİ 10:00 & 20:00)
# ───────────────────────────────────────────────

# TSİ (UTC+3) 10:00 ve 20:00 saatleri, UTC olarak sırasıyla 07:00 ve 17:00'ye denk gelir.
quiz_times = [
    time(hour=7, minute=0, tzinfo=timezone.utc),
    time(hour=17, minute=0, tzinfo=timezone.utc)
]

@tasks.loop(time=quiz_times)
async def scheduled_quiz():
    await start_quiz_question()


# ───────────────────────────────────────────────
#  EVENTS
# ───────────────────────────────────────────────

@bot.event
async def on_ready():
    global media_loop_running, media_loop_task, bump_task
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.clear_commands(guild=guild)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced)} slash command(s) to guild.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # Restart olunca image log kanalına "p" atar
    log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send("p")
        print("[restart] Sent 'p' to image log channel.")

    # Auto-restart bump reminder
    try:
        bump_channel = bot.get_channel(BUMP_CHANNEL_ID)
        if bump_channel:
            messages = [msg async for msg in bump_channel.history(limit=10)]
            last_bump = next((m for m in messages if m.author.id == BUMP_BOT_ID), None)
            if last_bump:
                elapsed = (datetime.now(timezone.utc) - last_bump.created_at).total_seconds()
                remaining = (2 * 60 * 60) - elapsed
                if remaining > 0:
                    print(f"[bump] Resuming — sending reminder in {int(remaining // 60)} minutes.")
                    bump_task = asyncio.ensure_future(schedule_bump_in(remaining))
                else:
                    print("[bump] Time already passed, sending reminder now.")
                    bump_task = asyncio.ensure_future(schedule_bump_in(0))
    except Exception as e:
        print(f"[bump] Error resuming bump timer: {e}")

    # Auto-start random media (30 dk gecikmeli)
    if not media_loop_running:
        media_loop_running = True
        media_loop_task = asyncio.ensure_future(run_media_loop(initial_delay=30 * 60))
        print("[random_media] Auto-started on ready (first post in 30 minutes).")


@bot.event
async def on_member_join(member: discord.Member):
    print(f"[welcome] {member} joined.")
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel is None:
        print(f"[welcome] ERROR: Channel {WELCOME_CHANNEL_ID} not found.")
        return
    msg = WELCOME_MESSAGE.replace("{member}", member.mention)
    sent = await channel.send(msg)
    welcome_message_log[member.id] = sent.id
    print(f"[welcome] Message sent for {member}.")


@bot.event
async def on_member_remove(member: discord.Member):
    print(f"[welcome] {member} left.")
    if member.id not in welcome_message_log:
        return
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(welcome_message_log[member.id])
        await msg.edit(content=f"{member.mention} geri gitti... 🥺")
        print(f"[welcome] Edited welcome message for {member}.")
    except Exception as e:
        print(f"[welcome] Could not edit message: {e}")
    finally:
        if member.id in welcome_message_log:
            del welcome_message_log[member.id]


@bot.event
async def on_message(message: discord.Message):
    global bump_task, quiz_state

    # ── Quiz Yanıt Kontrolü ──
    if quiz_state["active"] and message.channel.id == QUIZ_CHANNEL_ID and not message.author.bot:
        guess_normalized = normalize_title(message.content)
        title_normalized = normalize_title(quiz_state["vn_title"])
        alttitle_normalized = normalize_title(quiz_state["vn_alttitle"])

        # Doğru tahmin kontrolü
        if (guess_normalized == title_normalized) or (alttitle_normalized and guess_normalized == alttitle_normalized):
            quiz_state["active"] = False
            await message.channel.send(f"{message.author.mention} doğru bildi! +1 puan")
            
            # Skor kanalına log gönderme
            log_channel = bot.get_channel(QUIZ_LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"{message.author.name} +1 puan")
        else:
            # Yanlış tahmin durumunda çarpı emojisi bas
            await message.add_reaction("❌")
            quiz_state["wrong_guesses"] += 1
            
            # Her 3 yanlış bilmede resmi biraz daha dışa doğru zoomla (uzaklaştır)
            if quiz_state["wrong_guesses"] % 3 == 0 and quiz_state["zoom_factor"] < 1.0:
                quiz_state["zoom_factor"] = min(1.0, quiz_state["zoom_factor"] + 0.25)
                
                clue_img = generate_quiz_image(
                    quiz_state["image_bytes"],
                    quiz_state["rotation_angle"],
                    quiz_state["zoom_factor"],
                    quiz_state["crop_center"]
                )
                await message.channel.send(
                    "🔍 **İpucu!** 3 yanlış tahminden sonra resim biraz daha dışa doğru zoomlandı:",
                    file=discord.File(fp=clue_img, filename="quiz_clue.png")
                )

    # ── Media & file logger (all channels) ──
    if not message.author.bot:
        log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
        if log_channel and message.channel.id != IMAGE_LOG_CHANNEL_ID:
            if message.attachments:
                for attachment in message.attachments:
                    await log_channel.send(
                        f"📎 **{message.author.display_name}** (#{message.channel.name})",
                        file=await attachment.to_file()
                    )
                print(f"[log] Logged {len(message.attachments)} attachment(s) from {message.author}.")

    # ── Announce to welcome channel ──
    if message.channel.id == ANNOUNCE_SOURCE_CHANNEL_ID and not message.author.bot:
        welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
        if welcome_channel:
            if message.content:
                await welcome_channel.send(message.content)
            for attachment in message.attachments:
                await welcome_channel.send(file=await attachment.to_file())
            for embed in message.embeds:
                if embed.type not in ("image", "gifv", "video"):
                    await welcome_channel.send(embed=embed)
            print(f"[announce] Mirrored message from {message.author} to welcome channel.")

    # ── Bump reminder ──
    if message.channel.id == BUMP_CHANNEL_ID:
        if message.author == bot.user and message.content == BUMP_MESSAGE:
            return
        if message.author.id == BUMP_BOT_ID:
            if bump_task and not bump_task.done():
                bump_task.cancel()
            bump_task = asyncio.ensure_future(schedule_bump())
            print("[bump] Timer reset by bump bot.")

    await bot.process_commands(message)


# ───────────────────────────────────────────────
#  SLASH COMMANDS
# ───────────────────────────────────────────────

@bot.tree.command(name="startquiz", description="Manuel olarak yeni bir quiz sorusu başlatır.")
@app_commands.checks.has_permissions(administrator=True)
async def start_quiz(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        await start_quiz_question()
        await interaction.followup.send("✅ Yeni quiz sorusu başarıyla başlatıldı!", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Soru başlatılırken bir hata oluştu: {e}", ephemeral=True)


@bot.tree.command(name="setwelcome", description="Hoşgeldin mesajını değiştir. {member} yeni üyeyi etiketler.")
@app_commands.checks.has_permissions(administrator=True)
async def set_welcome(interaction: discord.Interaction, message: str):
    global WELCOME_MESSAGE
    WELCOME_MESSAGE = message
    await interaction.response.send_message(f"✅ Güncellendi:\n> {WELCOME_MESSAGE}", ephemeral=True)


@bot.tree.command(name="testwelcome", description="Mevcut hoşgeldin mesajını önizle.")
@app_commands.checks.has_permissions(administrator=True)
async def test_welcome(interaction: discord.Interaction):
    msg = WELCOME_MESSAGE.replace("{member}", interaction.user.mention)
    await interaction.response.send_message(f"**Önizleme:**\n{msg}", ephemeral=True)


@bot.tree.command(name="setbump", description="Bump hatırlatma mesajını değiştir.")
@app_commands.checks.has_permissions(administrator=True)
async def set_bump(interaction: discord.Interaction, message: str):
    global BUMP_MESSAGE
    BUMP_MESSAGE = message
    await interaction.response.send_message(f"✅ Güncellendi:\n> {BUMP_MESSAGE}", ephemeral=True)


@bot.tree.command(name="startmedia", description="Start posting random images/gifs based on chat activity.")
@app_commands.checks.has_permissions(administrator=True)
async def start_media(interaction: discord.Interaction):
    global media_loop_running, media_loop_task
    if media_loop_running:
        await interaction.response.send_message("⚠️ Already running!", ephemeral=True)
        return
    media_loop_running = True
    media_loop_task = asyncio.ensure_future(run_media_loop())
    await interaction.response.send_message("✅ Started.", ephemeral=True)


@bot.tree.command(name="stopmedia", description="Stop posting random images/gifs.")
@app_commands.checks.has_permissions(administrator=True)
async def stop_media(interaction: discord.Interaction):
    global media_loop_running, media_loop_task
    if not media_loop_running:
        await interaction.response.send_message("⚠️ Not running.", ephemeral=True)
        return
    media_loop_running = False
    if media_loop_task and not media_loop_task.done():
        media_loop_task.cancel()
    await interaction.response.send_message("🛑 Stopped.", ephemeral=True)


# ───────────────────────────────────────────────
#  RUN
# ───────────────────────────────────────────────

bot.run(TOKEN)
