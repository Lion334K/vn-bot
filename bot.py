import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import random
import re
import os
import io
import aiohttp
import json
from collections import deque
from datetime import datetime, timezone, timedelta
from PIL import Image
from typing import Literal

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

# Posting Kanalı ve Hafıza Ayarları
TRIGGER_CHANNEL_ID         = 1522166468936990841
TRIGGER_MESSAGE_ID         = 1522168210718195752
POSTING_CATEGORY_ID        = 1519120736290340924
LOG_HEADER                 = "---POSTING_REGISTRY_DATA---"

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

messages_since_last_media = 50  

# ARTIK SADECE MİSAFİRLERİ (Komutla Eklenenleri) TUTAR
# Format: {"Kanal_ID": [misafir_id1, misafir_id2, ...]}
posting_registry   = {}

asked_series_history = deque(maxlen=50)
quiz_state = {
    "active": False,
    "vn_title": "",
    "vn_alttitle": "",
    "image_bytes": None,
    "crop_center": (0.5, 0.5),
    "zoom_factor": 0.2,       
    "current_msg_id": None    
}

# ───────────────────────────────────────────────
#  POSTING SİSTEMİ YARDIMCI FONKSİYONLARI
# ───────────────────────────────────────────────

def check_is_owner(channel: discord.TextChannel, user_id: int) -> bool:
    """Bir kullanıcının, belirtilen kanalın 'sahibi' olup olmadığını Discord izinlerine göre denetler."""
    if channel.category_id != POSTING_CATEGORY_ID:
        return False
        
    for target, overwrite in channel.overwrites.items():
        if isinstance(target, discord.Member) and target.id == user_id:
            # Kullanıcının bu kanalda mesaj atma izni var mı?
            if overwrite.send_messages:
                # Log kayıtlarında bu kanalın "misafiri" (komutla ekleneni) olarak mı listelenmiş kontrol et
                guests = posting_registry.get(str(channel.id), [])
                if not isinstance(guests, list):
                    guests = []
                
                # Eğer misafir listesinde yoksa ve mesaj atma izni varsa, bu kişi KANAL SAHİBİDİR.
                if user_id not in guests:
                    return True
    return False

async def save_registry_to_log():
    """Misafir kayıtlarını image log kanalına JSON mesajı olarak yazar."""
    log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
    if not log_channel:
        return
    try:
        async for msg in log_channel.history(limit=100):
            if msg.author == bot.user and LOG_HEADER in msg.content:
                await msg.delete()
        
        data_str = json.dumps(posting_registry)
        await log_channel.send(f"{LOG_HEADER}\n{data_str}")
    except Exception as e:
        print(f"[sistem] Veri kaydedilirken hata oluştu: {e}")

async def load_registry():
    """Bot açıldığında misafir kayıtlarını yükler."""
    global posting_registry
    log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
    if not log_channel:
        return
    try:
        async for msg in log_channel.history(limit=100):
            if msg.author == bot.user and LOG_HEADER in msg.content:
                lines = msg.content.split("\n")
                if len(lines) > 1:
                    raw_data = json.loads(lines[1])
                    
                    # Eski (sahip tabanlı) verileri temizlemek için yapısal bir kontrol yapıyoruz
                    posting_registry = {}
                    for k, v in raw_data.items():
                        if isinstance(v, list):
                            posting_registry[k] = v
                    
                    print(f"[sistem] Kanalların misafir verileri başarıyla hafızaya yüklendi.")
                    return
    except Exception as e:
        print(f"[sistem] Eski kayıtlar yüklenirken hata oluştu: {e}")

# ───────────────────────────────────────────────
#  QUIZ HELPERS & IMAGE PROCESSING
# ───────────────────────────────────────────────

def check_answer(guess: str, title: str) -> bool:
    if not title or not guess: 
        return False
    
    def clean_text(t):
        t = t.lower()
        t = "".join(c if c.isalnum() else " " for c in t)
        return " ".join(t.split())
        
    clean_guess = clean_text(guess)
    clean_title = clean_text(title)
    
    if not clean_guess:
        return False
        
    if clean_guess == clean_title:
        return True
        
    if len(clean_guess.replace(" ", "")) >= 4:
        pattern = r'\b' + re.escape(clean_guess) + r'\b'
        if re.search(pattern, clean_title):
            return True
            
    return False

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
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "DiscordVNQuizBot/1.0"}
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
        await asyncio.sleep(1.5)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    if "application/json" in resp.headers.get("Content-Type", ""):
                        data = await resp.json()
                        return data.get("results", [])
                return []
    except Exception: return []

async def fetch_random_top_anime():
    page = random.randint(1, 4)
    url = f"https://api.jikan.moe/v4/top/anime?page={page}"
    try:
        await asyncio.sleep(1.5)
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    anime_list = data.get("data", [])
                    formatted_list = []
                    for chosen in anime_list:
                        t = chosen.get("title", "")
                        alt = chosen.get("title_english") or ""
                        images = chosen.get("images", {}).get("jpg", {})
                        img_url = images.get("large_image_url") or images.get("image_url")
                        if img_url:
                            formatted_list.append({"title": t, "alttitle": alt, "image_url": img_url})
                    return formatted_list
    except Exception: pass
    return []

async def start_quiz_question():
    global quiz_state, asked_series_history
    quiz_channel = bot.get_channel(QUIZ_CHANNEL_ID)
    if not quiz_channel: return

    source_type = random.choices(["vn", "anime"], weights=[70, 30])[0]
    title, alttitle, img_url = "", "", None

    if source_type == "vn":
        vns = await fetch_top_vns()
        valid_vns = [v for v in vns if v.get("image") and v.get("image").get("url") and v.get("title") not in asked_series_history]
        if not valid_vns and vns: valid_vns = [v for v in vns if v.get("image") and v.get("image").get("url")]
        if valid_vns:
            chosen_vn = random.choice(valid_vns)
            title = chosen_vn.get("title"); alttitle = chosen_vn.get("alttitle", ""); img_url = chosen_vn.get("image").get("url")
    else:
        animes = await fetch_random_top_anime()
        valid_animes = [a for a in animes if a["title"] not in asked_series_history]
        if not valid_animes and animes: valid_animes = animes
        if valid_animes:
            chosen = random.choice(valid_animes)
            title = chosen["title"]; alttitle = chosen["alttitle"]; img_url = chosen["image_url"]

    if not img_url:
        asyncio.create_task(next_quiz_question_delay(2.0))
        return

    try:
        await asyncio.sleep(1.0)
        async with aiohttp.ClientSession() as session:
            async with session.get(img_url) as resp:
                if resp.status != 200:
                    asyncio.create_task(next_quiz_question_delay(2.0))
                    return
                img_bytes = await resp.read()
    except Exception:
        asyncio.create_task(next_quiz_question_delay(2.0))
        return

    asked_series_history.append(title)
    quiz_state.update({"active": True, "vn_title": title, "vn_alttitle": alttitle, "image_bytes": img_bytes, "crop_center": (random.uniform(0.3, 0.7), random.uniform(0.3, 0.7)), "zoom_factor": 0.20, "current_msg_id": None})
    
    quiz_img = generate_quiz_image(img_bytes, quiz_state["zoom_factor"], quiz_state["crop_center"])
    await asyncio.sleep(1.0)
    msg = await quiz_channel.send(f"🎮 **Yeni Soru!** Bu hangi seri?\n*(Resmi uzaklaştırmak için 🔍, soruyu atlamak için ⏭️ emojisine tıklayın)*", file=discord.File(fp=quiz_img, filename="quiz_question.png"))
    quiz_state["current_msg_id"] = msg.id
    await msg.add_reaction("🔍")
    await msg.add_reaction("⏭️")

async def next_quiz_question_delay(delay: float = 2.0):
    await asyncio.sleep(delay)
    await start_quiz_question()

# ───────────────────────────────────────────────
#  BUMP & MEDIA HELPERS
# ───────────────────────────────────────────────

async def schedule_bump():
    try:
        await asyncio.sleep(2 * 60 * 60)
        channel = bot.get_channel(BUMP_CHANNEL_ID)
        if channel: await channel.send(BUMP_MESSAGE)
    except asyncio.CancelledError: pass

async def schedule_bump_in(seconds: float):
    try:
        await asyncio.sleep(max(0, seconds))
        channel = bot.get_channel(BUMP_CHANNEL_ID)
        if channel: await channel.send(BUMP_MESSAGE)
    except asyncio.CancelledError: pass

async def build_media_queue():
    pool_channel = bot.get_channel(EMBED_POOL_CHANNEL_ID)
    if not pool_channel: return []
    image_extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".webm")
    items = []
    async for msg in pool_channel.history(limit=500):
        for a in msg.attachments:
            if a.filename.lower().endswith(image_extensions):
                items.append({"author": msg.author.name, "url": a.url, "filename": a.filename, "created_at": msg.created_at})
    return items

def get_seconds_until_next_hour():
    now = datetime.now(timezone.utc)
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (next_hour - now).total_seconds() + 1 

async def post_random_media():
    global media_queue
    try:
        welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
        if not welcome_channel: return
        
        if not media_queue: media_queue = await build_media_queue()
        if not media_queue: return
        
        threshold_date = datetime.now(timezone.utc) - timedelta(days=30)
        weights = [1.3 if item["created_at"] >= threshold_date else 1.0 for item in media_queue]
        chosen_item = random.choices(media_queue, weights=weights, k=1)[0]
        media_queue.remove(chosen_item)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(chosen_item["url"]) as resp:
                if resp.status != 200: return
                data = await resp.read()
                
        await welcome_channel.send(f"**{chosen_item['author']}**", file=discord.File(fp=io.BytesIO(data), filename=chosen_item["filename"]))
    except Exception as e: print(f"[media] Hata: {e}")

async def run_media_loop():
    global media_loop_running, messages_since_last_media
    while media_loop_running:
        try:
            sleep_sec = get_seconds_until_next_hour()
            await asyncio.sleep(sleep_sec)
            if not media_loop_running: break
            
            if messages_since_last_media >= 50:
                await post_random_media()
                messages_since_last_media = 0
        except asyncio.CancelledError: break
        except Exception: await asyncio.sleep(60)

# ───────────────────────────────────────────────
#  EVENTS
# ───────────────────────────────────────────────

@bot.event
async def on_ready():
    global media_loop_running, media_loop_task, bump_task, quiz_state
    
    await load_registry()
    print(f"✅ Logged in as {bot.user}")
    
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.clear_commands(guild=guild)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    except Exception: pass

    try:
        trigger_channel = bot.get_channel(TRIGGER_CHANNEL_ID)
        if trigger_channel:
            trigger_msg = await trigger_channel.fetch_message(TRIGGER_MESSAGE_ID)
            await trigger_msg.add_reaction("➕")
    except Exception: pass

    log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
    if log_channel: await log_channel.send("p")

    try:
        bump_channel = bot.get_channel(BUMP_CHANNEL_ID)
        if bump_channel:
            messages = [msg async for msg in bump_channel.history(limit=10)]
            last_bump = next((m for m in messages if m.author.id == BUMP_BOT_ID), None)
            if last_bump:
                elapsed = (datetime.now(timezone.utc) - last_bump.created_at).total_seconds()
                remaining = (2 * 60 * 60) - elapsed
                bump_task = asyncio.ensure_future(schedule_bump_in(max(0, remaining)))
    except Exception: pass

    if not media_loop_running:
        media_loop_running = True
        media_loop_task = asyncio.ensure_future(run_media_loop())

    if not quiz_state["active"]: asyncio.create_task(start_quiz_question())

@bot.event
async def on_member_join(member: discord.Member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        sent = await channel.send(WELCOME_MESSAGE.replace("{member}", member.mention))
        welcome_message_log[member.id] = sent.id

@bot.event
async def on_member_remove(member: discord.Member):
    if member.id not in welcome_message_log: return
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        try:
            msg = await channel.fetch_message(welcome_message_log[member.id])
            await msg.edit(content=f"{member.mention} geri gitti... 🥺")
        except Exception: pass
        finally: del welcome_message_log[member.id]

@bot.event
async def on_message(message: discord.Message):
    global bump_task, quiz_state, messages_since_last_media
    
    if not message.author.bot: messages_since_last_media += 1

    if quiz_state["active"] and message.channel.id == QUIZ_CHANNEL_ID and not message.author.bot:
        is_correct = check_answer(message.content, quiz_state["vn_title"])
        if not is_correct and quiz_state["vn_alttitle"]: is_correct = check_answer(message.content, quiz_state["vn_alttitle"])

        if is_correct:
            quiz_state.update({"active": False, "current_msg_id": None})
            await message.channel.send(f"🎉 {message.author.mention} doğru bildi! Doğru Cevap: **{quiz_state['vn_title']}** (+1 puan)")
            
            log_channel = bot.get_channel(QUIZ_LOG_CHANNEL_ID)
            if log_channel: await log_channel.send(f"{message.author.name} +1 puan")
            asyncio.create_task(next_quiz_question_delay(2.0))
        else: await message.add_reaction("❌")

    if not message.author.bot:
        log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
        if log_channel and message.channel.id != IMAGE_LOG_CHANNEL_ID and message.attachments:
            for a in message.attachments: await log_channel.send(f"📎 **{message.author.display_name}** (#{message.channel.name})", file=await a.to_file())

    if message.channel.id == ANNOUNCE_SOURCE_CHANNEL_ID and not message.author.bot:
        welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
        if welcome_channel:
            if message.content: await welcome_channel.send(message.content)
            for a in message.attachments: await welcome_channel.send(file=await a.to_file())
            for embed in message.embeds:
                if embed.type not in ("image", "gifv", "video"): await welcome_channel.send(embed=embed)

    if message.channel.id == BUMP_CHANNEL_ID:
        if message.author == bot.user and message.content == BUMP_MESSAGE: return
        if message.author.id == BUMP_BOT_ID:
            if bump_task and not bump_task.done(): bump_task.cancel()
            bump_task = asyncio.ensure_future(schedule_bump())

    await bot.process_commands(message)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    global quiz_state
    
    # ─── OTOMATİK POSTING KANALI OLUŞTURMA SİSTEMİ ───
    if payload.channel_id == TRIGGER_CHANNEL_ID and payload.message_id == TRIGGER_MESSAGE_ID:
        if str(payload.emoji) == "➕":
            guild = bot.get_guild(payload.guild_id)
            if not guild: return
            member = guild.get_member(payload.user_id)
            if not member or member.bot: return

            category = guild.get_channel(POSTING_CATEGORY_ID)
            if not category: return

            # Tıklayan kişinin halihazırda sahibi olduğu bir kanal var mı kontrol et
            has_channel = False
            for ch in category.text_channels:
                if check_is_owner(ch, member.id):
                    has_channel = True
                    break

            if has_channel:
                try:
                    ch = bot.get_channel(payload.channel_id)
                    if ch:
                        msg = await ch.fetch_message(payload.message_id)
                        await msg.remove_reaction(payload.emoji, member)
                except Exception: pass
                return

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            try:
                new_channel = await guild.create_text_channel(
                    name=f"﹛{member.name}-posting﹜",
                    category=category,
                    overwrites=overwrites,
                    reason="Otomatik posting kanalı talebi."
                )
                await new_channel.send(member.mention)
            except Exception as e: print(f"[sistem] Hata: {e}")

            try:
                ch = bot.get_channel(payload.channel_id)
                if ch:
                    msg = await ch.fetch_message(payload.message_id)
                    await msg.remove_reaction(payload.emoji, member)
            except Exception: pass
            return

    # ─── QUIZ SİSTEMİ ───
    if not quiz_state["active"] or quiz_state["current_msg_id"] != payload.message_id or payload.user_id == bot.user.id: return
    channel = bot.get_channel(payload.channel_id)
    if not channel: return
    try: message = await channel.fetch_message(payload.message_id)
    except Exception: return

    if str(payload.emoji) == "🔍":
        reaction = discord.utils.get(message.reactions, emoji="🔍")
        if reaction and reaction.count >= 2:
            quiz_state["current_msg_id"] = None 
            if quiz_state["zoom_factor"] < 1.0:
                quiz_state["zoom_factor"] = min(1.0, quiz_state["zoom_factor"] + 0.15)
                await asyncio.sleep(0.5)
                clue_img = generate_quiz_image(quiz_state["image_bytes"], quiz_state["zoom_factor"], quiz_state["crop_center"])
                clue_msg = await channel.send("🔍 **İpucu!** Biri büyütece tıkladı, resim biraz daha uzaklaştırıldı:", file=discord.File(fp=clue_img, filename="quiz_clue.png"))
                quiz_state["current_msg_id"] = clue_msg.id
                if quiz_state["zoom_factor"] >= 1.0:
                    await clue_msg.add_reaction("⏭️")
                    await channel.send("📢 **Resim tamamen açıldı!** Soruyu atlamak için ⏭️ emojisine tıklayabilirsiniz.")
                else:
                    await clue_msg.add_reaction("🔍"); await clue_msg.add_reaction("⏭️")
            else: quiz_state["current_msg_id"] = message.id
    elif str(payload.emoji) == "⏭️":
        reaction = discord.utils.get(message.reactions, emoji="⏭️")
        if reaction and reaction.count >= 2:
            quiz_state["active"] = False
            quiz_state["current_msg_id"] = None 
            await channel.send(f"⏭️ **Oylama başarılı! Soru atlandı.** Doğru cevap: **{quiz_state['vn_title']}** olacaktı.")
            asyncio.create_task(next_quiz_question_delay(2.0))

# ───────────────────────────────────────────────
#  SLASH COMMANDS
# ───────────────────────────────────────────────

@bot.tree.command(name="izin", description="Sadece kendi posting kanalınızda birine mesaj yazma izni verebilir/alabilirsiniz.")
@app_commands.describe(islem="'ver' veya 'al'", kullanici="İşlem yapılacak kişi")
async def izin(interaction: discord.Interaction, islem: Literal["ver", "al"], kullanici: discord.Member):
    global posting_registry
    
    is_owner = check_is_owner(interaction.channel, interaction.user.id)
    if not is_owner and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ **Hata:** Bu komutu yalnızca size ait olan posting kanalında kullanabilirsiniz.", ephemeral=True)
        return
        
    if kullanici.id == interaction.user.id or kullanici.bot:
        await interaction.response.send_message("⚠️ Kendiniz veya botlar üzerinde işlem yapamazsınız.", ephemeral=True)
        return
        
    try:
        ch_id_str = str(interaction.channel.id)
        if islem == "ver":
            await interaction.channel.set_permissions(kullanici, read_messages=True, send_messages=True)
            
            # Kişiyi Misafir Listesine Ekle
            if ch_id_str not in posting_registry or not isinstance(posting_registry[ch_id_str], list):
                posting_registry[ch_id_str] = []
            if kullanici.id not in posting_registry[ch_id_str]:
                posting_registry[ch_id_str].append(kullanici.id)
                
            await save_registry_to_log()
            await interaction.response.send_message(f"✅ {kullanici.mention} kullanıcısına bu kanalda yazma izni verildi.", ephemeral=True)
            
        elif islem == "al":
            await interaction.channel.set_permissions(kullanici, overwrite=None)
            
            # Kişiyi Misafir Listesinden Çıkar
            if ch_id_str in posting_registry and isinstance(posting_registry[ch_id_str], list):
                if kullanici.id in posting_registry[ch_id_str]:
                    posting_registry[ch_id_str].remove(kullanici.id)
                    if not posting_registry[ch_id_str]:
                        del posting_registry[ch_id_str]
                        
            await save_registry_to_log()
            await interaction.response.send_message(f"✅ {kullanici.mention} kullanıcısının bu kanaldaki yazma erişimi kaldırıldı.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ İşlem sırasında bir hata oluştu: {e}", ephemeral=True)

@bot.tree.command(name="nsfw", description="Kendi posting kanalınızı yaş sınırlı (NSFW) yapın veya kaldırın.")
@app_commands.describe(durum="'evet' yaş sınırı ekler, 'hayır' kaldırır")
async def nsfw(interaction: discord.Interaction, durum: Literal["evet", "hayır"]):
    is_owner = check_is_owner(interaction.channel, interaction.user.id)
    if not is_owner and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ **Hata:** Bu komutu yalnızca size ait olan posting kanalında kullanabilirsiniz.", ephemeral=True)
        return
        
    try:
        is_nsfw = (durum == "evet")
        await interaction.channel.edit(nsfw=is_nsfw)
        if is_nsfw:
            await interaction.response.send_message("🔞 **Kanalınız yaş sınırlı (NSFW) olarak ayarlandı.**", ephemeral=True)
        else:
            await interaction.response.send_message("✅ **Kanalınızın yaş sınırı (NSFW) kaldırıldı.**", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Hata: {e}", ephemeral=True)

@bot.tree.command(name="eslestir", description="Mevcut bir posting kanalını el ile bir kullanıcıya tam yetkili olarak atar.")
@app_commands.checks.has_permissions(administrator=True)
async def eslestir(interaction: discord.Interaction, member: discord.Member, channel: discord.TextChannel):
    global posting_registry
    try:
        # İzni ver
        await channel.set_permissions(member, read_messages=True, send_messages=True)
        
        # Eğer bu kişi önceden misafir listesine eklendiyse, tam yetkili görünmesi için onu listeden çıkar
        ch_id_str = str(channel.id)
        if ch_id_str in posting_registry and isinstance(posting_registry[ch_id_str], list):
            if member.id in posting_registry[ch_id_str]:
                posting_registry[ch_id_str].remove(member.id)
                if not posting_registry[ch_id_str]:
                    del posting_registry[ch_id_str]
                await save_registry_to_log()
                
        await interaction.response.send_message(f"✅ **Başarılı!** {member.mention} kullanıcısı {channel.mention} kanalıyla eşleştirildi (Sahip yapıldı).", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ İzinler güncellenirken hata: {e}", ephemeral=True)

@bot.tree.command(name="startquiz", description="Manuel quiz başlatır.")
@app_commands.checks.has_permissions(administrator=True)
async def start_quiz(interaction: discord.Interaction):
    global quiz_state
    await interaction.response.defer(ephemeral=True)
    if quiz_state["active"]:
        ch = bot.get_channel(QUIZ_CHANNEL_ID)
        if ch: await ch.send(f"⏰ Yeni soru istendi! Eski cevap: **{quiz_state['vn_title']}**")
    await start_quiz_question()
    await interaction.followup.send("✅ Başlatıldı!", ephemeral=True)

@bot.tree.command(name="setwelcome", description="Hoşgeldin mesajı değiştir.")
@app_commands.checks.has_permissions(administrator=True)
async def set_welcome(interaction: discord.Interaction, message: str):
    global WELCOME_MESSAGE
    WELCOME_MESSAGE = message
    await interaction.response.send_message(f"✅ Güncellendi.", ephemeral=True)

@bot.tree.command(name="setbump", description="Bump mesajı değiştir.")
@app_commands.checks.has_permissions(administrator=True)
async def set_bump(interaction: discord.Interaction, message: str):
    global BUMP_MESSAGE
    BUMP_MESSAGE = message
    await interaction.response.send_message(f"✅ Güncellendi.", ephemeral=True)

@bot.tree.command(name="startmedia", description="Medya döngüsünü başlat.")
@app_commands.checks.has_permissions(administrator=True)
async def start_media(interaction: discord.Interaction):
    global media_loop_running, media_loop_task
    if media_loop_running: return await interaction.response.send_message("⚠️ Zaten çalışıyor!", ephemeral=True)
    media_loop_running = True
    media_loop_task = asyncio.ensure_future(run_media_loop())
    await interaction.response.send_message("✅ Başlatıldı.", ephemeral=True)

@bot.tree.command(name="stopmedia", description="Medya döngüsünü durdur.")
@app_commands.checks.has_permissions(administrator=True)
async def stop_media(interaction: discord.Interaction):
    global media_loop_running, media_loop_task
    if not media_loop_running: return await interaction.response.send_message("⚠️ Zaten durmuş.", ephemeral=True)
    media_loop_running = False
    if media_loop_task: media_loop_task.cancel()
    await interaction.response.send_message("🛑 Durduruldu.", ephemeral=True)

if __name__ == "__main__":
    if TOKEN: bot.run(TOKEN)
