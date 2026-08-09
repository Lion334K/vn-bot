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
#  1. KANAL & ID AYARLARI
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

# Emoji & Webhook Tetikleyici Ayarları
EMOJI_TRIGGER_USER_ID      = 689780831488573450
EMOJI_TRIGGER_ID           = 1507819144735756298
EMOJI_RESPONSE_ID          = 1529887965265002618
WEBHOOK_URL                = "https://discord.com/api/webhooks/1529887030144929923/iyBvXY9kALb9j62G7s9xjHTPdjFzg-Fnm3B0hY_pxlAGf8KtHMaHtdRovkpwi-XAcDuy"

# Özel Ses Kanalı Ayarları
VOICE_CATEGORY_ID          = 1381768081428185290
VOICE_GENERATOR_NAME       = "Oda Oluştur"
VOICE_GENERATOR_CHANNEL_ID = None

# ───────────────────────────────────────────────
#  2. MESAJ VE METİN AYARLARI
# ───────────────────────────────────────────────

# -- Karşılama ve Çıkış --
MSG_WELCOME           = "{member} aramıza katıldı fln filan iste 😒"
MSG_LEAVE             = "{member} geri gitti... 🥺"
MSG_BUMP              = "buuuuuump"

# -- Quiz Sistemi Mesajları --
MSG_QUIZ_NEW          = "🎮 **yeeni soru** ney bu?\n*(resmi uzaklastirmak icin 🔍, soruyu atlamak icin ⏭️ tepkısıne tiklayin)*"
MSG_QUIZ_CORRECT      = "🎉 {member} bildi hll olsun! cevap **{title}** idi (+1 puan)"
MSG_QUIZ_CLUE         = "🔍 **ipucu** biri tepkiye basti, resim biras daha uzaklastirild"
MSG_QUIZ_FULL_OPEN    = "📢 **resim tamamen acildi!** bulamadiysanis ⏭️ basip atlayabılirsinis."
MSG_QUIZ_SKIP         = "⏭️ **tepkiye tiklandi! soru atlandi.** cevap **{title}** idi."
MSG_QUIZ_FORCE_NEW    = "⏰ yeni soriya gecildi! eskısinin cevabi **{title}** idi"
MSG_QUIZ_LOG_POINT    = "{name} +1 puan"

# -- İzin ve Hata Mesajları --
MSG_ERR_NOT_OWNER     = "❌ **düüt:** sadece kendı kanalinizda kulanabılırsınis."
MSG_ERR_SELF_BOT      = "⚠️ kimi ariyon ?."
MSG_ERR_GENERIC       = "❌ düüüüt hata: {error}"

# -- Komut Yanıtları (Posting) --
MSG_PERM_GIVEN        = "✅ {member} kisisine yazma ıznı verildi."
MSG_PERM_TAKEN        = "✅ {member} kisininin yazma ıznı alindi."
MSG_NSFW_ON           = "🔞 **kanalinis yas sinirli kanal olarak ayarlandi.**"
MSG_NSFW_OFF          = "✅ **kanaliniz tekrar normal kanal oldi.**"
MSG_RECOVER_SUCCESS   = "✅ **düt!** {member} kullanıcısı {channel} a atandi."

# -- Sistem Komut Yanıtları --
MSG_STARTED           = "✅ basladi!"
MSG_STOPPED           = "🛑 durdu."
MSG_UPDATED           = "✅ guncelendi."
MSG_ALREADY_RUNNING   = "⚠️ zaten calisiyo!"
MSG_ALREADY_STOPPED   = "⚠️ zaten durmus."

# -- Özel Ses Kanalı Mesajları --
MSG_VOICE_UNLOCKED    = "🔓 ses kanali topluma acildi."
MSG_VOICE_LOCKED      = "🔒 ses kanali kiltlendi. sadece /ekle komutuylan izin verilenler katilabilır."
MSG_VOICE_ADDED       = "✅ {member} kisisine izin verıldı."
MSG_VOICE_REMOVED     = "❌ {member} kisisinin izni alindi."
MSG_VOICE_ERR_OWNER   = "⚠️ bu komtu **kendi** kanalinda kulanabılırsın sadece."
MSG_VOICE_HIDDEN      = "👻 ses kanali artik gizli, sadece icerdekiler gorebilir."
MSG_VOICE_VISIBLE     = "👀 ses kanali artik herkes tarafindan gorulebilr."

# -- Diğer Formatlar --
FORMAT_POSTING_NAME   = "﹛{name}-posting﹜" 
FORMAT_VOICE_NAME     = "{name} özel kanal" 
FORMAT_LOG_ATTACHMENT = "📎 **{name}** (#{channel})" 


# ───────────────────────────────────────────────
#  BOT SETUP
# ───────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.reactions = True
intents.voice_states = True 

bot = commands.Bot(command_prefix="!", intents=intents)

# Runtime state
bump_task          = None
media_loop_running = False
media_loop_task    = None
media_queue        = []
welcome_message_log: dict = {}

active_users_this_hour = set()
posting_registry       = {}
active_voice_channels  = {} 
erikafur_listesi       = []

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
#  WEBHOOK HELPER
# ───────────────────────────────────────────────

async def send_webhook_message(webhook_url: str, content: str):
    async with aiohttp.ClientSession() as session:
        payload = {"content": content}
        try:
            async with session.post(webhook_url, json=payload) as resp:
                pass
        except Exception as e:
            print(f"[webhook] Mesaj gönderilirken hata oluştu: {e}")

# ───────────────────────────────────────────────
#  POSTING SİSTEMİ YARDIMCI FONKSİYONLARI
# ───────────────────────────────────────────────

def check_is_owner(channel: discord.TextChannel, user_id: int) -> bool:
    if channel.category_id != POSTING_CATEGORY_ID:
        return False
        
    for target, overwrite in channel.overwrites.items():
        if isinstance(target, discord.Member) and target.id == user_id:
            if overwrite.send_messages:
                guests = posting_registry.get(str(channel.id), [])
                if not isinstance(guests, list):
                    guests = []
                if user_id not in guests:
                    return True
    return False

async def save_registry_to_log():
    log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
    if not log_channel: return
    try:
        async for msg in log_channel.history(limit=100):
            if msg.author == bot.user and LOG_HEADER in msg.content:
                await msg.delete()
        data_str = json.dumps(posting_registry)
        await log_channel.send(f"{LOG_HEADER}\n{data_str}")
    except Exception as e:
        print(f"[sistem] Veri kaydedilirken hata oluştu: {e}")

async def load_registry():
    global posting_registry
    log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
    if not log_channel: return
    try:
        async for msg in log_channel.history(limit=100):
            if msg.author == bot.user and LOG_HEADER in msg.content:
                lines = msg.content.split("\n")
                if len(lines) > 1:
                    raw_data = json.loads(lines[1])
                    posting_registry = {k: v for k, v in raw_data.items() if isinstance(v, list)}
                    print(f"[sistem] Kanalların misafir verileri başarıyla hafızaya yüklendi.")
                    return
    except Exception as e: print(f"[sistem] Eski kayıtlar yüklenirken hata oluştu: {e}")

# ───────────────────────────────────────────────
#  QUIZ HELPERS & IMAGE PROCESSING
# ───────────────────────────────────────────────

def check_answer(guess: str, title: str) -> bool:
    if not title or not guess: return False
    def clean_text(t):
        t = t.lower()
        t = "".join(c if c.isalnum() else " " for c in t)
        return " ".join(t.split())
    clean_guess = clean_text(guess)
    clean_title = clean_text(title)
    if not clean_guess: return False
    if clean_guess == clean_title: return True
    if len(clean_guess.replace(" ", "")) >= 4:
        pattern = r'\b' + re.escape(clean_guess) + r'\b'
        if re.search(pattern, clean_title): return True
    return False

def generate_quiz_image(img_bytes: bytes, zoom_factor: float, center_pct: tuple) -> io.BytesIO:
    img = Image.open(io.BytesIO(img_bytes)).convert("L")
    orig_w, orig_h = img.size
    cx, cy = center_pct
    crop_w, crop_h = max(20, int(orig_w * zoom_factor)), max(20, int(orig_h * zoom_factor))
    center_x, center_y = int(orig_w * cx), int(orig_h * cy)
    left, top = max(0, min(center_x - crop_w // 2, orig_w - crop_w)), max(0, min(center_y - crop_h // 2, orig_h - crop_h))
    img = img.crop((left, top, left + crop_w, top + crop_h)).resize((orig_w, orig_h), Image.Resampling.LANCZOS)
    out_bytes = io.BytesIO()
    img.save(out_bytes, format="PNG")
    out_bytes.seek(0)
    return out_bytes

async def fetch_top_vns() -> list:
    url = "https://api.vndb.org/kana/vn"
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "DiscordVNQuizBot/1.0"}
    payload = {"filters": ["and", ["id", ">=", "v1"], ["votecount", ">=", 1000]], "fields": "title, alttitle, image.url", "sort": "votecount", "reverse": True, "results": 100, "page": random.choice([1, 1, 1, 1, 2, 2, 2, 2, 3, 4, 5])}
    try:
        await asyncio.sleep(1.5)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200 and "application/json" in resp.headers.get("Content-Type", ""):
                    return (await resp.json()).get("results", [])
    except Exception: pass
    return []

async def fetch_random_top_anime():
    url = f"https://api.jikan.moe/v4/top/anime?page={random.randint(1, 4)}"
    try:
        await asyncio.sleep(1.5)
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return [{"title": c.get("title", ""), "alttitle": c.get("title_english") or "", "image_url": c.get("images", {}).get("jpg", {}).get("large_image_url") or c.get("images", {}).get("jpg", {}).get("image_url")} for c in (await resp.json()).get("data", []) if (c.get("images", {}).get("jpg", {}).get("large_image_url") or c.get("images", {}).get("jpg", {}).get("image_url"))]
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
        valid_vns = [v for v in vns if v.get("image") and v.get("image").get("url") and v.get("title") not in asked_series_history] or [v for v in vns if v.get("image") and v.get("image").get("url")]
        if valid_vns:
            chosen = random.choice(valid_vns)
            title, alttitle, img_url = chosen.get("title"), chosen.get("alttitle", ""), chosen.get("image").get("url")
    else:
        animes = await fetch_random_top_anime()
        valid_animes = [a for a in animes if a["title"] not in asked_series_history] or animes
        if valid_animes:
            chosen = random.choice(valid_animes)
            title, alttitle, img_url = chosen["title"], chosen["alttitle"], chosen["image_url"]

    if not img_url: return asyncio.create_task(next_quiz_question_delay(2.0))

    try:
        await asyncio.sleep(1.0)
        async with aiohttp.ClientSession() as session:
            async with session.get(img_url) as resp:
                if resp.status != 200: return asyncio.create_task(next_quiz_question_delay(2.0))
                img_bytes = await resp.read()
    except Exception: return asyncio.create_task(next_quiz_question_delay(2.0))

    asked_series_history.append(title)
    quiz_state.update({"active": True, "vn_title": title, "vn_alttitle": alttitle, "image_bytes": img_bytes, "crop_center": (random.uniform(0.3, 0.7), random.uniform(0.3, 0.7)), "zoom_factor": 0.20, "current_msg_id": None})
    
    msg = await quiz_channel.send(MSG_QUIZ_NEW, file=discord.File(fp=generate_quiz_image(img_bytes, quiz_state["zoom_factor"], quiz_state["crop_center"]), filename="quiz_question.png"))
    quiz_state["current_msg_id"] = msg.id
    await msg.add_reaction("🔍"); await msg.add_reaction("⏭️")

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
        if channel: await channel.send(MSG_BUMP)
    except asyncio.CancelledError: pass

async def schedule_bump_in(seconds: float):
    try:
        await asyncio.sleep(max(0, seconds))
        channel = bot.get_channel(BUMP_CHANNEL_ID)
        if channel: await channel.send(MSG_BUMP)
    except asyncio.CancelledError: pass

async def build_media_queue():
    pool_channel = bot.get_channel(EMBED_POOL_CHANNEL_ID)
    if not pool_channel: return []
    items = []
    async for msg in pool_channel.history(limit=500):
        for a in msg.attachments:
            if a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".webm")):
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
        chosen_item = random.choices(media_queue, weights=[1.3 if item["created_at"] >= threshold_date else 1.0 for item in media_queue], k=1)[0]
        media_queue.remove(chosen_item)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(chosen_item["url"]) as resp:
                if resp.status != 200: return
                data = await resp.read()
                
        await welcome_channel.send(f"**{chosen_item['author']}**", file=discord.File(fp=io.BytesIO(data), filename=chosen_item["filename"]))
    except Exception as e: print(f"[media] Hata: {e}")

async def run_media_loop():
    global media_loop_running, active_users_this_hour
    while media_loop_running:
        try:
            sleep_sec = get_seconds_until_next_hour()
            await asyncio.sleep(sleep_sec)
            if not media_loop_running: break
            if len(active_users_this_hour) >= 6: await post_random_media()
            active_users_this_hour.clear()
        except asyncio.CancelledError: break
        except Exception as e:
            print(f"[media loop] Hata: {e}")
            await asyncio.sleep(60)

# ───────────────────────────────────────────────
#  EVENTS
# ───────────────────────────────────────────────

@bot.event
async def on_ready():
    global media_loop_running, media_loop_task, bump_task, quiz_state, VOICE_GENERATOR_CHANNEL_ID
    
    await load_registry()
    print(f"✅ Logged in as {bot.user}")
    
    guild = bot.get_guild(GUILD_ID)
    if guild:
        category = guild.get_channel(VOICE_CATEGORY_ID)
        if category:
            generator_channel = discord.utils.get(category.voice_channels, name=VOICE_GENERATOR_NAME)
            
            if not generator_channel:
                try:
                    generator_channel = await guild.create_voice_channel(name=VOICE_GENERATOR_NAME, category=category)
                    print(f"✅ Özel oda oluşturma kanalı yaratıldı. ID: {generator_channel.id}")
                except Exception as e:
                    print(f"❌ Kategoriye ses kanalı oluşturulurken hata: {e}")
            
            if generator_channel:
                VOICE_GENERATOR_CHANNEL_ID = generator_channel.id
                print(f"✅ Aktif Jeneratör Kanal ID'si: {VOICE_GENERATOR_CHANNEL_ID}")

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
                bump_task = asyncio.ensure_future(schedule_bump_in(max(0, (2 * 60 * 60) - elapsed)))
    except Exception: pass

    if not media_loop_running:
        media_loop_running = True
        media_loop_task = asyncio.ensure_future(run_media_loop())

    if not quiz_state["active"]: asyncio.create_task(start_quiz_question())

@bot.event
async def on_member_join(member: discord.Member):
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        sent = await channel.send(MSG_WELCOME.replace("{member}", member.mention))
        welcome_message_log[member.id] = sent.id

@bot.event
async def on_member_remove(member: discord.Member):
    if member.id not in welcome_message_log: return
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        try:
            msg = await channel.fetch_message(welcome_message_log[member.id])
            await msg.edit(content=MSG_LEAVE.replace("{member}", member.mention))
        except Exception: pass
        finally: del welcome_message_log[member.id]

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    global active_voice_channels, VOICE_GENERATOR_CHANNEL_ID
    
    if after.channel and after.channel.id == VOICE_GENERATOR_CHANNEL_ID:
        guild = member.guild
        category = guild.get_channel(VOICE_CATEGORY_ID) or after.channel.category

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
            member: discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True)
        }

        channel_name = FORMAT_VOICE_NAME.replace("{name}", member.display_name)
        try:
            new_channel = await guild.create_voice_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites
            )
            await member.move_to(new_channel)
            active_voice_channels[new_channel.id] = member.id
        except Exception as e:
            print(f"[voice] Kanal oluşturma hatası: {e}")

    if before.channel and before.channel.id in active_voice_channels:
        if len(before.channel.members) == 0:
            try:
                await before.channel.delete()
                del active_voice_channels[before.channel.id]
            except Exception as e:
                print(f"[voice] Kanal silme hatası: {e}")


@bot.event
async def on_message(message: discord.Message):
    global bump_task, quiz_state, active_users_this_hour

    if message.channel.id == VERIFY_CHANNEL_ID and not message.author.bot:
        try:
            await message.delete()
        except:
            pass
    
    if not message.author.bot: 
        active_users_this_hour.add(message.author.id)

        if message.author.id == EMOJI_TRIGGER_USER_ID and str(EMOJI_TRIGGER_ID) in message.content:
            target_emoji = bot.get_emoji(EMOJI_RESPONSE_ID)
            emoji_str = str(target_emoji) if target_emoji else f"<:emoji:{EMOJI_RESPONSE_ID}>"
            asyncio.create_task(send_webhook_message(WEBHOOK_URL, emoji_str))

    if quiz_state["active"] and message.channel.id == QUIZ_CHANNEL_ID and not message.author.bot:
        is_correct = check_answer(message.content, quiz_state["vn_title"]) or (quiz_state["vn_alttitle"] and check_answer(message.content, quiz_state["vn_alttitle"]))
        if is_correct:
            quiz_state.update({"active": False, "current_msg_id": None})
            await message.channel.send(MSG_QUIZ_CORRECT.replace("{member}", message.author.mention).replace("{title}", quiz_state['vn_title']))
            log_channel = bot.get_channel(QUIZ_LOG_CHANNEL_ID)
            if log_channel: await log_channel.send(MSG_QUIZ_LOG_POINT.replace("{name}", message.author.name))
            asyncio.create_task(next_quiz_question_delay(2.0))
        else: await message.add_reaction("❌")

    if not message.author.bot:
        log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
        if log_channel and message.channel.id != IMAGE_LOG_CHANNEL_ID and message.attachments:
            log_text = FORMAT_LOG_ATTACHMENT.replace("{name}", message.author.display_name).replace("{channel}", message.channel.name)
            for a in message.attachments: await log_channel.send(log_text, file=await a.to_file())

    if message.channel.id == ANNOUNCE_SOURCE_CHANNEL_ID and not message.author.bot:
        welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
        if welcome_channel:
            if message.content: await welcome_channel.send(message.content)
            for a in message.attachments: await welcome_channel.send(file=await a.to_file())
            for embed in message.embeds:
                if embed.type not in ("image", "gifv", "video"): await welcome_channel.send(embed=embed)

    if message.channel.id == BUMP_CHANNEL_ID:
        if message.author == bot.user and message.content == MSG_BUMP: return
        if message.author.id == BUMP_BOT_ID:
            if bump_task and not bump_task.done(): bump_task.cancel()
            bump_task = asyncio.ensure_future(schedule_bump())

    await bot.process_commands(message)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    global quiz_state
    
    if payload.channel_id == TRIGGER_CHANNEL_ID and payload.message_id == TRIGGER_MESSAGE_ID:
        if str(payload.emoji) == "➕":
            guild = bot.get_guild(payload.guild_id)
            if not guild: return
            member = guild.get_member(payload.user_id)
            if not member or member.bot: return
            category = guild.get_channel(POSTING_CATEGORY_ID)
            if not category: return

            has_channel = any(check_is_owner(ch, member.id) for ch in category.text_channels)
            if has_channel:
                try:
                    ch = bot.get_channel(payload.channel_id)
                    if ch: await (await ch.fetch_message(payload.message_id)).remove_reaction(payload.emoji, member)
                except Exception: pass
                return

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            try:
                ch_name = FORMAT_POSTING_NAME.replace("{name}", member.name)
                new_channel = await guild.create_text_channel(name=ch_name, category=category, overwrites=overwrites, reason="Otomatik posting kanalı talebi.")
                await new_channel.send(member.mention)
            except Exception as e: print(f"[sistem] Hata: {e}")

            try:
                ch = bot.get_channel(payload.channel_id)
                if ch: await (await ch.fetch_message(payload.message_id)).remove_reaction(payload.emoji, member)
            except Exception: pass
            return

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
                clue_msg = await channel.send(MSG_QUIZ_CLUE, file=discord.File(fp=generate_quiz_image(quiz_state["image_bytes"], quiz_state["zoom_factor"], quiz_state["crop_center"]), filename="quiz_clue.png"))
                quiz_state["current_msg_id"] = clue_msg.id
                if quiz_state["zoom_factor"] >= 1.0:
                    await clue_msg.add_reaction("⏭️"); await channel.send(MSG_QUIZ_FULL_OPEN)
                else: await clue_msg.add_reaction("🔍"); await clue_msg.add_reaction("⏭️")
            else: quiz_state["current_msg_id"] = message.id
    elif str(payload.emoji) == "⏭️":
        reaction = discord.utils.get(message.reactions, emoji="⏭️")
        if reaction and reaction.count >= 2:
            quiz_state["active"] = False
            quiz_state["current_msg_id"] = None 
            await channel.send(MSG_QUIZ_SKIP.replace("{title}", quiz_state['vn_title']))
            asyncio.create_task(next_quiz_question_delay(2.0))

# ───────────────────────────────────────────────
#  SES KANALI İÇİN YARDIMCI KONTROL
# ───────────────────────────────────────────────
def check_voice_ownership(interaction: discord.Interaction) -> discord.VoiceChannel:
    if not interaction.user.voice or not interaction.user.voice.channel:
        return None
    vc = interaction.user.voice.channel
    if vc.id in active_voice_channels and active_voice_channels[vc.id] == interaction.user.id:
        return vc
    return None

# ───────────────────────────────────────────────
#  SLASH COMMANDS
# ───────────────────────────────────────────────

@bot.tree.command(name="kilidiac", description="Özel ses kanalınızı herkese açık hale getirir.")
async def kilidiac(interaction: discord.Interaction):
    vc = check_voice_ownership(interaction)
    if not vc: return await interaction.response.send_message(MSG_VOICE_ERR_OWNER, ephemeral=True)
    await vc.set_permissions(interaction.guild.default_role, connect=True)
    await interaction.response.send_message(MSG_VOICE_UNLOCKED, ephemeral=True)

@bot.tree.command(name="kilitle", description="Özel ses kanalınızı tekrar kilitler.")
async def kilitle(interaction: discord.Interaction):
    vc = check_voice_ownership(interaction)
    if not vc: return await interaction.response.send_message(MSG_VOICE_ERR_OWNER, ephemeral=True)
    await vc.set_permissions(interaction.guild.default_role, connect=False)
    await interaction.response.send_message(MSG_VOICE_LOCKED, ephemeral=True)

@bot.tree.command(name="gizle", description="Özel ses kanalınızı diğerlerinden gizler.")
async def gizle(interaction: discord.Interaction):
    vc = check_voice_ownership(interaction)
    if not vc: return await interaction.response.send_message(MSG_VOICE_ERR_OWNER, ephemeral=True)
    await vc.set_permissions(interaction.guild.default_role, view_channel=False)
    await interaction.response.send_message(MSG_VOICE_HIDDEN, ephemeral=True)

@bot.tree.command(name="göster", description="Özel ses kanalınızı tekrar herkese görünür yapar.")
async def goster(interaction: discord.Interaction):
    vc = check_voice_ownership(interaction)
    if not vc: return await interaction.response.send_message(MSG_VOICE_ERR_OWNER, ephemeral=True)
    await vc.set_permissions(interaction.guild.default_role, view_channel=True)
    await interaction.response.send_message(MSG_VOICE_VISIBLE, ephemeral=True)

@bot.tree.command(name="ekle", description="Özel ses kanalınıza birini eklersiniz.")
async def ekle(interaction: discord.Interaction, uye: discord.Member):
    vc = check_voice_ownership(interaction)
    if not vc: return await interaction.response.send_message(MSG_VOICE_ERR_OWNER, ephemeral=True)
    await vc.set_permissions(uye, connect=True)
    await interaction.response.send_message(MSG_VOICE_ADDED.replace("{member}", uye.mention), ephemeral=True)

@bot.tree.command(name="çıkar", description="Özel ses kanalınızdan birinin iznini alırsınız.")
async def cikar(interaction: discord.Interaction, uye: discord.Member):
    vc = check_voice_ownership(interaction)
    if not vc: return await interaction.response.send_message(MSG_VOICE_ERR_OWNER, ephemeral=True)
    await vc.set_permissions(uye, overwrite=None)
    await interaction.response.send_message(MSG_VOICE_REMOVED.replace("{member}", uye.mention), ephemeral=True)

@bot.tree.command(name="kanal_kurtar", description="Sunucudan çık-gir yapan kişiyi tekrar kanalının lideri (sahibi) yapar.")
@app_commands.checks.has_permissions(administrator=True)
async def kanal_kurtar(interaction: discord.Interaction, member: discord.Member, channel: discord.TextChannel):
    global posting_registry
    try:
        await channel.set_permissions(member, read_messages=True, send_messages=True)
        ch_id_str = str(channel.id)
        if ch_id_str in posting_registry and isinstance(posting_registry[ch_id_str], list):
            if member.id in posting_registry[ch_id_str]:
                posting_registry[ch_id_str].remove(member.id)
                if not posting_registry[ch_id_str]:
                    del posting_registry[ch_id_str]
                await save_registry_to_log()
                
        yeni_isim = FORMAT_POSTING_NAME.replace("{name}", member.name)
        if channel.name != yeni_isim:
            await channel.edit(name=yeni_isim)
            
        await interaction.response.send_message(MSG_RECOVER_SUCCESS.replace("{member}", member.mention).replace("{channel}", channel.mention), ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(MSG_ERR_GENERIC.replace("{error}", str(e)), ephemeral=True)

@bot.tree.command(name="izin", description="Sadece kendi posting kanalınızda birine mesaj yazma izni verebilir/alabilirsiniz.")
@app_commands.describe(islem="'ver' veya 'al'", kullanici="İşlem yapılacak kişi")
async def izin(interaction: discord.Interaction, islem: Literal["ver", "al"], kullanici: discord.Member):
    global posting_registry
    is_owner = check_is_owner(interaction.channel, interaction.user.id)
    if not is_owner and not interaction.user.guild_permissions.administrator: return await interaction.response.send_message(MSG_ERR_NOT_OWNER, ephemeral=True)
    if kullanici.id == interaction.user.id or kullanici.bot: return await interaction.response.send_message(MSG_ERR_SELF_BOT, ephemeral=True)
        
    try:
        ch_id_str = str(interaction.channel.id)
        if islem == "ver":
            await interaction.channel.set_permissions(kullanici, read_messages=True, send_messages=True)
            if ch_id_str not in posting_registry or not isinstance(posting_registry[ch_id_str], list): posting_registry[ch_id_str] = []
            if kullanici.id not in posting_registry[ch_id_str]: posting_registry[ch_id_str].append(kullanici.id)
            await save_registry_to_log()
            await interaction.response.send_message(MSG_PERM_GIVEN.replace("{member}", kullanici.mention), ephemeral=True)
        elif islem == "al":
            await interaction.channel.set_permissions(kullanici, overwrite=None)
            if ch_id_str in posting_registry and isinstance(posting_registry[ch_id_str], list) and kullanici.id in posting_registry[ch_id_str]:
                posting_registry[ch_id_str].remove(kullanici.id)
                if not posting_registry[ch_id_str]: del posting_registry[ch_id_str]
            await save_registry_to_log()
            await interaction.response.send_message(MSG_PERM_TAKEN.replace("{member}", kullanici.mention), ephemeral=True)
    except Exception as e: await interaction.response.send_message(MSG_ERR_GENERIC.replace("{error}", str(e)), ephemeral=True)

@bot.tree.command(name="nsfw", description="Kendi posting kanalınızı yaş sınırlı (NSFW) yapın veya kaldırın.")
@app_commands.describe(durum="'evet' yaş sınırı ekler, 'hayır' kaldırır")
async def nsfw(interaction: discord.Interaction, durum: Literal["evet", "hayır"]):
    if not check_is_owner(interaction.channel, interaction.user.id) and not interaction.user.guild_permissions.administrator: return await interaction.response.send_message(MSG_ERR_NOT_OWNER, ephemeral=True)
    try:
        is_nsfw = (durum == "evet")
        await interaction.channel.edit(nsfw=is_nsfw)
        await interaction.response.send_message(MSG_NSFW_ON if is_nsfw else MSG_NSFW_OFF, ephemeral=True)
    except Exception as e: await interaction.response.send_message(MSG_ERR_GENERIC.replace("{error}", str(e)), ephemeral=True)

@bot.tree.command(name="startquiz", description="Manuel quiz başlatır.")
@app_commands.checks.has_permissions(administrator=True)
async def start_quiz(interaction: discord.Interaction):
    global quiz_state
    await interaction.response.defer(ephemeral=True)
    if quiz_state["active"]:
        ch = bot.get_channel(QUIZ_CHANNEL_ID)
        if ch: await ch.send(MSG_QUIZ_FORCE_NEW.replace("{title}", quiz_state['vn_title']))
    await start_quiz_question()
    await interaction.followup.send(MSG_STARTED, ephemeral=True)

@bot.tree.command(name="setwelcome", description="Hoşgeldin mesajı değiştir.")
@app_commands.checks.has_permissions(administrator=True)
async def set_welcome(interaction: discord.Interaction, message: str):
    global MSG_WELCOME
    MSG_WELCOME = message
    await interaction.response.send_message(MSG_UPDATED, ephemeral=True)

@bot.tree.command(name="setbump", description="Bump mesajı değiştir.")
@app_commands.checks.has_permissions(administrator=True)
async def set_bump(interaction: discord.Interaction, message: str):
    global MSG_BUMP
    MSG_BUMP = message
    await interaction.response.send_message(MSG_UPDATED, ephemeral=True)

@bot.tree.command(name="startmedia", description="Medya döngüsünü başlat.")
@app_commands.checks.has_permissions(administrator=True)
async def start_media(interaction: discord.Interaction):
    global media_loop_running, media_loop_task
    if media_loop_running: return await interaction.response.send_message(MSG_ALREADY_RUNNING, ephemeral=True)
    media_loop_running = True
    media_loop_task = asyncio.ensure_future(run_media_loop())
    await interaction.response.send_message(MSG_STARTED, ephemeral=True)

@bot.tree.command(name="stopmedia", description="Medya döngüsünü durdur.")
@app_commands.checks.has_permissions(administrator=True)
async def stop_media(interaction: discord.Interaction):
    global media_loop_running, media_loop_task
    if not media_loop_running: return await interaction.response.send_message(MSG_ALREADY_STOPPED, ephemeral=True)
    media_loop_running = False
    if media_loop_task: media_loop_task.cancel()
    await interaction.response.send_message(MSG_STOPPED, ephemeral=True)

# 🛑 YENİ: AKTİFİM DOĞRULAMA KOMUTU
@bot.tree.command(name="aktifim", description="İnaktif durumundan çıkıp sunucuya tekrar katılmanızı sağlar.")
async def aktifim(interaction: discord.Interaction):
    inactive_role = interaction.guild.get_role(INACTIVE_ROLE_ID)
    
    if inactive_role and inactive_role in interaction.user.roles:
        try:
            await interaction.user.remove_roles(inactive_role, reason="/aktifim komutu ile kendini doğruladı.")
            await interaction.response.send_message("✅ **Harika!** İnaktif durumdan başarıyla çıktın.", ephemeral=True)
            
            # erikafur listesine kaydetme işlemi
            if interaction.user.id not in erikafur_listesi:
                erikafur_listesi.append(interaction.user.id)
                log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
                if log_channel:
                    zaman = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S")
                    await log_channel.send(f"**erikafur** | Yeni Doğrulama: `{interaction.user} (ID: {interaction.user.id})` — Zaman: `{zaman} UTC`")
        except Exception as e:
            await interaction.response.send_message(f"❌ Bir hata oluştu: {e}", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ Zaten inaktif listesinde değilsin veya rol bulunamadı!", ephemeral=True)

@bot.tree.command(name="inaktif_taramasi", description="2 aydır sunucuda olup level rolü olmayanlara inaktif rolü verir.")
@app_commands.checks.has_permissions(administrator=True)
async def inaktif_taramasi(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    INACTIVE_ROLE_ID = 1535807591207407627
    LEVEL_ROLE_IDS = [
        1489964270518141058, 
        1489963890505679088, 
        1503004591585759344, 
        1489963940732735649, 
        1503007942142722108, 
        1489963981404770416, 
        1489964031719772272
    ]
    
    guild = interaction.guild
    inactive_role = guild.get_role(INACTIVE_ROLE_ID)
    
    if not inactive_role:
        return await interaction.followup.send("❌ **Hata:** İnaktif rolü sunucuda bulunamadı. Lütfen ID'yi kontrol edin.", ephemeral=True)
        
    iki_ay_once = discord.utils.utcnow() - timedelta(days=60)
    
    etkilenen_kisi_sayisi = 0
    
    for member in guild.members:
        if member.bot:
            continue
            
        if member.joined_at and member.joined_at < iki_ay_once:
            has_level_role = any(role.id in LEVEL_ROLE_IDS for role in member.roles)
            
            if not has_level_role and inactive_role not in member.roles:
                try:
                    await member.add_roles(inactive_role, reason="Sistem: 2 aydır sunucuda ve level rolü yok.")
                    etkilenen_kisi_sayisi += 1
                    
                    await asyncio.sleep(0.5) 
                except Exception as e:
                    print(f"[{member.name}] kişisine rol verilirken hata oluştu: {e}")
                    
    await interaction.followup.send(f"✅ **Tarama Tamamlandı!**\nBelirtilen kriterlere uyan toplam **{etkilenen_kisi_sayisi}** üyeye İnaktif rolü verildi.", ephemeral=True)

if __name__ == "__main__":
    if TOKEN: bot.run(TOKEN)
