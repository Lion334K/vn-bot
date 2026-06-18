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
    img = img.resize((orig_w, orig_h), Image.Resampling.LANCZOS)  # Tekrar orijinal boyuta esnetme
    
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
            print
