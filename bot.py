import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import random
import re
import os
import io
import aiohttp
from datetime import datetime, timezone, timedelta
from PIL import Image

# ───────────────────────────────────────────────
#  CONFIGURATION
# ───────────────────────────────────────────────

TOKEN = os.environ.get("DISCORD_TOKEN")

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
    "zoom_factor": 0.2,       # Başlangıç yakınlık oranı
    "wrong_guesses": 0,
    "skip_msg_id": None       # Üzerinde atlama emojisi olan mesajın ID'si
}

# ───────────────────────────────────────────────
#  QUIZ HELPERS & IMAGE PROCESSING
# ───────────────────────────────────────────────

def normalize_title(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    return re.sub(r'[\s\-_:,\.\!\?\'"”“\(\)]', '', text)


def generate_quiz_image(img_bytes: bytes, angle: int, zoom_factor: float, center_pct: tuple) -> io.BytesIO:
    img = Image.open(io.BytesIO(img_bytes))
    img = img.convert("L")
    
    orig_w, orig_h = img.size
    cx, cy = center_pct
    
    crop_w = max(20, int(orig_w * zoom_factor))
    crop_h = max(20, int(orig_h * zoom_factor))
    
    center_x = int(orig_w * cx)
    center_y = int(orig_h * cy)
    
    left = max(0, min(center_x - crop_w // 2, orig_w - crop_w))
    top = max(0, min(center_y - crop_h // 2, orig_h - crop_h))
    right = left + crop_w
    bottom = top + crop_h
    
    img = img.crop((left, top, right, bottom))
    img = img.rotate(angle, expand=True)
    img = img.resize((orig_w, orig_h), Image.Resampling.LANCZOS)
    
    out_bytes = io.BytesIO()
    img.save(out_bytes, format="PNG")
    out_bytes.seek(0)
    return out_bytes


async def fetch_top_vns() -> list:
    url = "https://api.vndb.org/kana/vn"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "DiscordVNQuizBot/1.0"
    }
    payload = {
        "filters": ["id", ">=", "v1"],
        "fields": "title, alttitle, image.url",
        "sort": "rating",
        "reverse": True,
        "results": 100  # İlk 100 Görsel Romanı çekecek şekilde güncellendi
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    if "application/json" in resp.headers.get("Content-Type", ""):
                        data = await resp.json()
                        return data.get("results", [])
                print(f"[quiz] VNDB API Error HTTP {resp.status}")
                return []
    except Exception as e:
        print(f"[quiz] Connection Error: {e}")
        return []


async def start_quiz_question():
    global quiz_state
    quiz_channel = bot.get_channel(QUIZ_CHANNEL_ID)
    if not quiz_channel:
        print("[quiz] HATA: Quiz kanalı bulunamadı.")
        return

    vns = await fetch_top_vns()
    valid_vns = [v for v in vns if v.get("image") and v.get("image").get("url")]
    
    if not valid_vns:
        print("[quiz] HATA: Geçerli resme sahip VN listesi alınamadı.")
        return

    chosen_vn = random.choice(valid_vns)
    title = chosen_vn.get("title")
    alttitle = chosen_vn.get("alttitle", "")
    img_url = chosen_vn.get("image").get("url")

    async with aiohttp.ClientSession() as session:
        async with session.get(img_url) as resp:
            if resp.status != 200:
                print("[quiz] HATA: Kapak resmi indirilemedi.")
                return
            img_bytes = await resp.read()

    quiz_state["active"] = True
    quiz_state["vn_title"] = title
    quiz_state["vn_alttitle"] = alttitle
    quiz_state["image_bytes"] = img_bytes
    quiz_state["crop_center"] = (random.uniform(0.3, 0.7), random.uniform(0.3, 0.7))
    quiz_state["rotation_angle"] = random.randint(35, 325)
    quiz_state["zoom_factor"] = 0.20
    quiz_state["wrong_guesses"] = 0
    quiz_state["skip_msg_id"] = None

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


async def next_quiz_question_delay(delay: float = 5.0):
    """Belirtilen saniye kadar bekleyip yeni soru tetikler."""
    await asyncio.sleep(delay)
    await start_quiz_question()

# ───────────────────────────────────────────────
#  BUMP HELPERS
# ───────────────────────────────────────────────

async def schedule_bump():
    try:
        await asyncio.sleep(2 * 60 * 60)
        channel = bot.get_channel(BUMP_CHANNEL_ID)
        if channel:
            await channel.send(BUMP_MESSAGE)
    except asyncio.CancelledError:
        pass


async def schedule_bump_in(seconds: float):
    try:
        await asyncio.sleep(max(0, seconds))
        channel = bot.get_channel(BUMP_CHANNEL_ID)
        if channel:
            await channel.send(BUMP_MESSAGE)
    except asyncio.CancelledError:
        pass

# ───────────────────────────────────────────────
#  RANDOM MEDIA HELPERS
# ───────────────────────────────────────────────

async def get_media_queue() -> list:
    try:
        pool_channel = bot.get_channel(EMBED_POOL_CHANNEL_ID)
        if pool_channel is None:
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
        return valid
    except Exception:
        return []


async def post_random_media():
    global media_queue
    try:
        welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
        if welcome_channel is None:
            return
        if not media_queue:
            media_queue = await get_media_queue()
        if not media_queue:
            return
        author_name, media_list = media_queue.pop(0)
        url, filename = random.choice(media_list)
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return
                data = await resp.read()
        await welcome_channel.send(
            f"**{author_name}**",
            file=discord.File(fp=io.BytesIO(data), filename=filename)
        )
    except Exception:
        pass


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
    except Exception:
        return 0


async def run_media_loop(initial_delay: float = 0):
    global media_loop_running
    try:
        if initial_delay > 0:
            await asyncio.sleep(initial_delay)
    except asyncio.CancelledError:
        return

    while media_loop_running:
        try:
            active_users = await get_active_user_count()
            if active_users >= 5:
                interval = 30 * 60
            elif active_users >= 3:
                interval = 60 * 60
            else:
                interval = 3 * 60 * 60
            await post_random_media()
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(60)

# ───────────────────────────────────────────────
#  EVENTS
# ───────────────────────────────────────────────

@bot.event
async def on_ready():
    global media_loop_running, media_loop_task, bump_task, quiz_state
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.clear_commands(guild=guild)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    except Exception:
        pass

    log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send("p")

    try:
        bump_channel = bot.get_channel(BUMP_CHANNEL_ID)
        if bump_channel:
            messages = [msg async for msg in bump_channel.history(limit=10)]
            last_bump = next((m for m in messages if m.author.id == BUMP_BOT_ID), None)
            if last_bump:
                elapsed = (datetime.now(timezone.utc) - last_bump.created_at).total_seconds()
                remaining = (2 * 60 * 60) - elapsed
                if remaining > 0:
                    bump_task = asyncio.ensure_future(schedule_bump_in(remaining))
                else:
                    bump_task = asyncio.ensure_future(schedule_bump_in(0))
    except Exception:
        pass

    if not media_loop_running:
        media_loop_running = True
        media_loop_task = asyncio.ensure_future(run_media_loop(initial_delay=30 * 60))

    # İlk quiz sorusunu bot açıldığında otomatik olarak başlatır
    if not quiz_state["active"]:
        asyncio.create_task(start_quiz_question())
        print("[quiz] Sürekli döngü sistemi başlatıldı, ilk soru yükleniyor.")


@bot.event
async def on_member_join(member: discord.Member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        msg = WELCOME_MESSAGE.replace("{member}", member.mention)
        sent = await channel.send(msg)
        welcome_message_log[member.id] = sent.id


@bot.event
async def on_member_remove(member: discord.Member):
    if member.id not in welcome_message_log:
        return
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        try:
            msg = await channel.fetch_message(welcome_message_log[member.id])
            await msg.edit(content=f"{member.mention} geri gitti... 🥺")
        except Exception:
            pass
        finally:
            del welcome_message_log[member.id]


@bot.event
async def on_message(message: discord.Message):
    global bump_task, quiz_state

    # Quiz Kontrolü
    if quiz_state["active"] and message.channel.id == QUIZ_CHANNEL_ID and not message.author.bot:
        guess_normalized = normalize_title(message.content)
        title_normalized = normalize_title(quiz_state["vn_title"])
        alttitle_normalized = normalize_title(quiz_state["vn_alttitle"])

        if (guess_normalized == title_normalized) or (alttitle_normalized and guess_normalized == alttitle_normalized):
            quiz_state["active"] = False
            await message.channel.send(f"🎉 {message.author.mention} doğru bildi! Doğru Cevap: **{quiz_state['vn_title']}** (+1 puan)")
            
            log_channel = bot.get_channel(QUIZ_LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"{message.author.name} +1 puan")
            
            # Doğru bilindiği için 5 saniye sonra yeni soruya geçer
            asyncio.create_task(next_quiz_question_delay(5.0))
        else:
            await message.add_reaction("❌")
            quiz_state["wrong_guesses"] += 1
            
            # Her 3 yanlış bilmede resmi biraz daha dışa zoomla (Miktar 0.25'ten 0.15'e düşürüldü)
            if quiz_state["wrong_guesses"] % 3 == 0 and quiz_state["zoom_factor"] < 1.0:
                quiz_state["zoom_factor"] = min(1.0, quiz_state["zoom_factor"] + 0.15)
                
                clue_img = generate_quiz_image(
                    quiz_state["image_bytes"],
                    quiz_state["rotation_angle"],
                    quiz_state["zoom_factor"],
                    quiz_state["crop_center"]
                )
                clue_msg = await message.channel.send(
                    "🔍 **İpucu!** Resim biraz uzaklaştırıldı:",
                    file=discord.File(fp=clue_img, filename="quiz_clue.png")
                )
                
                # Resim tamamen dışa zoomlandıysa (1.0 olduysa) atlama emojisi (⏭️) ekle
                if quiz_state["zoom_factor"] >= 1.0:
                    await clue_msg.add_reaction("⏭️")
                    quiz_state["skip_msg_id"] = clue_msg.id
                    await message.channel.send("📢 **Resim tamamen açıldı!** Soruyu atlamak için aşağıdaki ⏭️ emojisine tıklayabilirsiniz (5 kişi gerekli).")

    if not message.author.bot:
        log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
        if log_channel and message.channel.id != IMAGE_LOG_CHANNEL_ID:
            if message.attachments:
                for attachment in message.attachments:
                    await log_channel.send(
                        f"📎 **{message.author.display_name}** (#{message.channel.name})",
                        file=await attachment.to_file()
                    )

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

    if message.channel.id == BUMP_CHANNEL_ID:
        if message.author == bot.user and message.content == BUMP_MESSAGE:
            return
        if message.author.id == BUMP_BOT_ID:
            if bump_task and not bump_task.done():
                bump_task.cancel()
            bump_task = asyncio.ensure_future(schedule_bump())

    await bot.process_commands(message)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Atlama emojisine (⏭️) basıldığında tepkileri kontrol eder."""
    global quiz_state
    if quiz_state["active"] and quiz_state["skip_msg_id"] == payload.message_id:
        if str(payload.emoji) == "⏭️" and payload.user_id != bot.user.id:
            channel = bot.get_channel(payload.channel_id)
            if not channel:
                return
            
            message = await channel.fetch_message(payload.message_id)
            reaction = discord.utils.get(message.reactions, emoji="⏭️")
            
            if reaction:
                # Botun kendi koyduğu tepki + 5 üye = Toplam en az 6 tepki olmalı
                if reaction.count >= 6:
                    quiz_state["active"] = False
                    quiz_state["skip_msg_id"] = None
                    
                    await channel.send(f"⏭️ **Oylama başarılı! Soru atlandı.** Doğru cevap: **{quiz_state['vn_title']}** olacaktı.")
                    
                    # Soru atlandığı için 5 saniye sonra yeni soruya geçer
                    asyncio.create_task(next_quiz_question_delay(5.0))


# ───────────────────────────────────────────────
#  SLASH COMMANDS
# ───────────────────────────────────────────────

@bot.tree.command(name="startquiz", description="Manuel olarak yeni bir quiz sorusu başlatır.")
@app_commands.checks.has_permissions(administrator=True)
async def start_quiz(interaction: discord.Interaction):
    global quiz_state
    await interaction.response.defer(ephemeral=True)
    try:
        if quiz_state["active"]:
            quiz_channel = bot.get_channel(QUIZ_CHANNEL_ID)
            if quiz_channel:
                await quiz_channel.send(f"⏰ **Yeni soru istendi!** Eski soru kapatıldı. Cevap: **{quiz_state['vn_title']}** olacaktı.")
        
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

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("HATA: DISCORD_TOKEN bulunamadı!")
