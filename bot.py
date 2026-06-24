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
    "zoom_factor": 0.2,       # Başlangıç yakınlık oranı
    "current_msg_id": None    # Üzerinde etkileşim beklenen son ipucu mesajı
}

# ───────────────────────────────────────────────
#  QUIZ HELPERS & IMAGE PROCESSING
# ───────────────────────────────────────────────

def normalize_title(text: str) -> str:
    """Tüm boşlukları ve noktalama işaretlerini silip sadece harf ve rakamları bırakır."""
    if not text:
        return ""
    return "".join(c for c in text.lower() if c.isalnum())


def generate_quiz_image(img_bytes: bytes, zoom_factor: float, center_pct: tuple) -> io.BytesIO:
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
    
    # 1. ve 2. sayfanın seçilme ihtimalini belirgin şekilde artırıyoruz
    weighted_pages = [1, 1, 1, 1, 2, 2, 2, 2, 3, 4, 5]
    selected_page = random.choice(weighted_pages)
    
    payload = {
        "filters": ["and", ["id", ">=", "v1"], ["votecount", ">=", 1000]],
        "fields": "title, alttitle, image.url",
        "sort": "votecount",
        "reverse": True,
        "results": 100,
        "page": selected_page
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


async def fetch_random_top_anime():
    """MyAnimeList ilk 100 animesi arasından rastgele birini seçer."""
    # Jikan API her sayfada 25 anime verir. İlk 100 anime için 1 ile 4 arasında bir sayfa seçiyoruz.
    page = random.randint(1, 4)
    url = f"https://api.jikan.moe/v4/top/anime?page={page}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    anime_list = data.get("data", [])
                    if anime_list:
                        chosen = random.choice(anime_list)
                        title = chosen.get("title", "")
                        alttitle = chosen.get("title_english") or ""
                        
                        # Mümkünse büyük kaliteli resmi, yoksa normalini al
                        images = chosen.get("images", {}).get("jpg", {})
                        img_url = images.get("large_image_url") or images.get("image_url")
                        
                        return {"title": title, "alttitle": alttitle, "image_url": img_url}
    except Exception as e:
        print(f"[quiz] Jikan API Error: {e}")
    return None


async def start_quiz_question():
    global quiz_state
    quiz_channel = bot.get_channel(QUIZ_CHANNEL_ID)
    if not quiz_channel:
        print("[quiz] HATA: Quiz kanalı bulunamadı.")
        return

    # %70 ihtimalle VN, %30 ihtimalle Anime seçecek
    source_type = random.choices(["vn", "anime"], weights=[70, 30])[0]
    title, alttitle, img_url = "", "", None

    if source_type == "vn":
        vns = await fetch_top_vns()
        valid_vns = [v for v in vns if v.get("image") and v.get("image").get("url")]
        if valid_vns:
            chosen_vn = random.choice(valid_vns)
            title = chosen_vn.get("title")
            alttitle = chosen_vn.get("alttitle", "")
            img_url = chosen_vn.get("image").get("url")
    else:
        anime = await fetch_random_top_anime()
        if anime:
            title = anime["title"]
            alttitle = anime["alttitle"]
            img_url = anime["image_url"]

    if not img_url:
        print(f"[quiz] HATA: Resim bulunamadı. Kaynak: {source_type}. Tekrar deneniyor...")
        asyncio.create_task(next_quiz_question_delay(5.0))
        return

    async with aiohttp.ClientSession() as session:
        async with session.get(img_url) as resp:
            if resp.status != 200:
                print(f"[quiz] HATA: Kapak resmi indirilemedi ({source_type}).")
                asyncio.create_task(next_quiz_question_delay(5.0))
                return
            img_bytes = await resp.read()

    quiz_state["active"] = True
    quiz_state["vn_title"] = title
    quiz_state["vn_alttitle"] = alttitle
    quiz_state["image_bytes"] = img_bytes
    quiz_state["crop_center"] = (random.uniform(0.3, 0.7), random.uniform(0.3, 0.7))
    quiz_state["zoom_factor"] = 0.20
    quiz_state["current_msg_id"] = None

    quiz_img = generate_quiz_image(
        img_bytes, 
        quiz_state["zoom_factor"], 
        quiz_state["crop_center"]
    )

    msg = await quiz_channel.send(
        "🎮 **Yeni Soru!** Bu hangi seri?\n*(Resmi uzaklaştırmak için 🔍, soruyu atlamak için ⏭️ emojisine tıklayın)*",
        file=discord.File(fp=quiz_img, filename="quiz_question.png")
    )
    
    quiz_state["current_msg_id"] = msg.id
    await msg.add_reaction("🔍")
    await msg.add_reaction("⏭️")
    print(f"[quiz] Soru hazırlandı: {title} ({source_type})")


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

    # Quiz Doğru Yanıt Kontrolü (Esnek ve Kısmi Eşleşme)
    if quiz_state["active"] and message.channel.id == QUIZ_CHANNEL_ID and not message.author.bot:
        guess_normalized = normalize_title(message.content)
        title_normalized = normalize_title(quiz_state["vn_title"])
        alttitle_normalized = normalize_title(quiz_state["vn_alttitle"])

        is_correct = False

        if len(guess_normalized) >= 4:
            # En az 4 harf girilmişse ismin içinde herhangi bir yerde geçmesi yeterlidir
            if (guess_normalized in title_normalized) or (alttitle_normalized and guess_normalized in alttitle_normalized):
                is_correct = True
        elif len(guess_normalized) > 0:
            # 4 harften kısa isimler için birebir eşleşme istenir
            if (guess_normalized == title_normalized) or (alttitle_normalized and guess_normalized == alttitle_normalized):
                is_correct = True

        if is_correct:
            quiz_state["active"] = False
            quiz_state["current_msg_id"] = None
            
            await message.channel.send(f"🎉 {message.author.mention} doğru bildi! Doğru Cevap: **{quiz_state['vn_title']}** (+1 puan)")
            
            log_channel = bot.get_channel(QUIZ_LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"{message.author.name} +1 puan")
            
            asyncio.create_task(next_quiz_question_delay(5.0))
        else:
            await message.add_reaction("❌")

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
    global quiz_state
    
    if quiz_state["active"] and quiz_state["current_msg_id"] == payload.message_id:
        if payload.user_id == bot.user.id:
            return

        channel = bot.get_channel(payload.channel_id)
        if not channel:
            return
            
        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception:
            return

        # 🔍 Zoom Out Kontrolü (1 Kullanıcı = Toplam 2 oy bot dahil)
        if str(payload.emoji) == "🔍":
            reaction = discord.utils.get(message.reactions, emoji="🔍")
            if reaction and reaction.count >= 2:
                if quiz_state["zoom_factor"] < 1.0:
                    quiz_state["zoom_factor"] = min(1.0, quiz_state["zoom_factor"] + 0.15)
                    
                    clue_img = generate_quiz_image(
                        quiz_state["image_bytes"],
                        quiz_state["zoom_factor"],
                        quiz_state["crop_center"]
                    )
                    clue_msg = await channel.send(
                        "🔍 **İpucu!** Biri büyütece tıkladı, resim biraz daha uzaklaştırıldı:",
                        file=discord.File(fp=clue_img, filename="quiz_clue.png")
                    )
                    
                    quiz_state["current_msg_id"] = clue_msg.id
                    
                    if quiz_state["zoom_factor"] >= 1.0:
                        await clue_msg.add_reaction("⏭️")
                        await channel.send("📢 **Resim tamamen açıldı!** Soruyu atlamak için ⏭️ emojisine tıklayabilirsiniz (2 kişi gerekli).")
                    else:
                        await clue_msg.add_reaction("🔍")
                        await clue_msg.add_reaction("⏭️")

        # ⏭️ Atlama Kontrolü (2 Kullanıcı = Toplam 3 oy bot dahil)
        elif str(payload.emoji) == "⏭️":
            reaction = discord.utils.get(message.reactions, emoji="⏭️")
            if reaction and reaction.count >= 3:
                quiz_state["active"] = False
                quiz_state["current_msg_id"] = None
                
                await channel.send(f"⏭️ **Oylama başarılı! Soru atlandı.** Doğru cevap: **{quiz_state['vn_title']}** olacaktı.")
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
