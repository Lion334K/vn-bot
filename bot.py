import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import random
import json
import os
from datetime import datetime, timezone, timedelta

# ───────────────────────────────────────────────
#  CONFIGURATION
# ───────────────────────────────────────────────

TOKEN = "MTQ3ODg0MjI0NzY2NjU5Nzk4MA.G41wtj.yYeUafzcZP6S95CMFXHhSB8Jtcc_IX7R_Mhnkk"

WELCOME_CHANNEL_ID         = 1488662459009994965
BUMP_CHANNEL_ID            = 1381771230964748370
GUILD_ID                   = 1381768080610426930
BUMP_BOT_ID                = 302050872383242240
IMAGE_LOG_CHANNEL_ID       = 1381770621054091306
ANNOUNCE_SOURCE_CHANNEL_ID = 1489993668126572545
EMBED_POOL_CHANNEL_ID      = 1501344668242280559
MIRROR_SOURCE_CHANNEL_ID   = 1489996127347413114
MIRROR_TARGET_CHANNEL_ID   = 1488485721877643314

WELCOME_MESSAGE = "Aramıza yeni biri katıldı! Hoşgeldin {member} 🥹"
BUMP_MESSAGE    = "Buuuuuump"

# ───────────────────────────────────────────────
#  BOT SETUP
# ───────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

bump_task        = None
media_loop_running = False
media_loop_task  = None
media_queue      = []

# ───────────────────────────────────────────────
#  POINTS SYSTEM
# ───────────────────────────────────────────────

POINTS_FILE = "points.json"

def load_points() -> dict:
    if os.path.exists(POINTS_FILE):
        with open(POINTS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_points(data: dict):
    with open(POINTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

points_data: dict = {}

# ───────────────────────────────────────────────
#  EVENTS
# ───────────────────────────────────────────────

@bot.event
async def on_ready():
    global points_data
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    points_data = load_points()
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.clear_commands(guild=guild)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced)} slash command(s) to guild.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


@bot.event
async def on_member_join(member: discord.Member):
    print(f"[welcome] {member} joined.")
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if channel is None:
        print(f"[welcome] ERROR: Channel {WELCOME_CHANNEL_ID} not found.")
        return
    msg = WELCOME_MESSAGE.replace("{member}", member.mention)
    await channel.send(msg)
    print(f"[welcome] Message sent for {member}.")


@bot.event
async def on_message(message: discord.Message):
    global bump_task

    print(f"[on_message] Channel: {message.channel.id} | Author: {message.author} | Content: {message.content[:50]}")

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
                print(f"[log] Logged {len(message.attachments)} attachment(s) from {message.author} in #{message.channel.name}.")

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

    # ── Cross-server mirror ──
    if message.channel.id == MIRROR_SOURCE_CHANNEL_ID:
        if not (message.author == bot.user):
            target = bot.get_channel(MIRROR_TARGET_CHANNEL_ID)
            if target:
                if message.content:
                    await target.send(message.content)
                for attachment in message.attachments:
                    await target.send(file=await attachment.to_file())
                print(f"[mirror] Mirrored message from {message.author} ({len(message.attachments)} attachments)")
            else:
                print(f"[mirror] ERROR: Target channel {MIRROR_TARGET_CHANNEL_ID} not found.")

    # ── Bump reminder (only resets on bump bot messages) ──
    if message.channel.id == BUMP_CHANNEL_ID:
        if message.author == bot.user and message.content == BUMP_MESSAGE:
            return
        if message.author.id == BUMP_BOT_ID:
            if bump_task and not bump_task.done():
                bump_task.cancel()
            bump_task = asyncio.ensure_future(schedule_bump())
            print("[bump] Timer reset by bump bot.")

    await bot.process_commands(message)


async def schedule_bump():
    try:
        await asyncio.sleep(2 * 60 * 60)
        channel = bot.get_channel(BUMP_CHANNEL_ID)
        if channel:
            await channel.send(BUMP_MESSAGE)
            print("[bump] Reminder sent.")
    except asyncio.CancelledError:
        pass


# ───────────────────────────────────────────────
#  SLASH COMMANDS  –  Welcome & Mirror
# ───────────────────────────────────────────────

@bot.tree.command(name="setwelcome", description="Hoşgeldin mesajını değiştir. {member} yeni üyeyi etiketler.")
@app_commands.checks.has_permissions(administrator=True)
async def set_welcome(interaction: discord.Interaction, message: str):
    global WELCOME_MESSAGE
    WELCOME_MESSAGE = message
    await interaction.response.send_message(f"✅ Hoşgeldin mesajı güncellendi:\n> {WELCOME_MESSAGE}", ephemeral=True)


@bot.tree.command(name="testwelcome", description="Mevcut hoşgeldin mesajını önizle.")
@app_commands.checks.has_permissions(administrator=True)
async def test_welcome(interaction: discord.Interaction):
    msg = WELCOME_MESSAGE.replace("{member}", interaction.user.mention)
    await interaction.response.send_message(f"**Önizleme:**\n{msg}", ephemeral=True)


@bot.tree.command(name="testmirror", description="Copies the last message from the source channel to the target channel.")
@app_commands.checks.has_permissions(administrator=True)
async def test_mirror(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    source = bot.get_channel(MIRROR_SOURCE_CHANNEL_ID)
    if source is None:
        await interaction.followup.send(f"❌ Source channel not found.", ephemeral=True)
        return
    target = bot.get_channel(MIRROR_TARGET_CHANNEL_ID)
    if target is None:
        await interaction.followup.send(f"❌ Target channel not found.", ephemeral=True)
        return
    messages = [msg async for msg in source.history(limit=1)]
    if not messages:
        await interaction.followup.send("❌ No messages found in the source channel.", ephemeral=True)
        return
    last = messages[0]
    if last.content:
        await target.send(last.content)
    for attachment in last.attachments:
        await target.send(file=await attachment.to_file())
    await interaction.followup.send(f"✅ Last message mirrored to <#{MIRROR_TARGET_CHANNEL_ID}>.", ephemeral=True)


@bot.tree.command(name="setbump", description="Bump hatırlatma mesajını değiştir.")
@app_commands.checks.has_permissions(administrator=True)
async def set_bump(interaction: discord.Interaction, message: str):
    global BUMP_MESSAGE
    BUMP_MESSAGE = message
    await interaction.response.send_message(f"✅ Bump mesajı güncellendi:\n> {BUMP_MESSAGE}", ephemeral=True)


# ───────────────────────────────────────────────
#  SLASH COMMANDS  –  Points
# ───────────────────────────────────────────────

@bot.tree.command(name="addpoints", description="Give points to a user.")
@app_commands.checks.has_permissions(administrator=True)
async def add_points(interaction: discord.Interaction, user: discord.Member, points: int):
    uid = str(user.id)
    points_data[uid] = points_data.get(uid, 0) + points
    save_points(points_data)
    await interaction.response.send_message(
        f"✅ **{user.display_name}** now has **{points_data[uid]}** points.",
        ephemeral=True
    )


@bot.tree.command(name="removepoints", description="Remove points from a user.")
@app_commands.checks.has_permissions(administrator=True)
async def remove_points(interaction: discord.Interaction, user: discord.Member, points: int):
    uid = str(user.id)
    points_data[uid] = max(0, points_data.get(uid, 0) - points)
    save_points(points_data)
    await interaction.response.send_message(
        f"✅ **{user.display_name}** now has **{points_data[uid]}** points.",
        ephemeral=True
    )


@bot.tree.command(name="points", description="Check how many points a user has.")
async def check_points(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    uid = str(target.id)
    total = points_data.get(uid, 0)
    await interaction.response.send_message(
        f"**{target.display_name}** has **{total}** points.",
        ephemeral=True
    )


@bot.tree.command(name="leaderboard", description="Show the points leaderboard.")
async def leaderboard(interaction: discord.Interaction):
    if not points_data:
        await interaction.response.send_message("No points have been given yet.", ephemeral=False)
        return

    sorted_users = sorted(points_data.items(), key=lambda x: x[1], reverse=True)

    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, pts) in enumerate(sorted_users[:10]):
        try:
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
        except Exception:
            name = f"User {uid}"
        prefix = medals[i] if i < 3 else f"**{i+1}.**"
        lines.append(f"{prefix} {name} — **{pts}** points")

    embed = discord.Embed(
        title="🏆 Leaderboard",
        description="\n".join(lines),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)


# ───────────────────────────────────────────────
#  RANDOM MEDIA (ACTIVITY BASED)
# ───────────────────────────────────────────────

async def get_media_queue() -> list:
    pool_channel = bot.get_channel(EMBED_POOL_CHANNEL_ID)
    if pool_channel is None:
        return []
    image_extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    valid = []
    async for msg in pool_channel.history(limit=200):
        media = [a for a in msg.attachments if a.filename.lower().endswith(image_extensions)]
        if media:
            valid.append((msg, media))
    random.shuffle(valid)
    print(f"[random_media] Built new queue with {len(valid)} items.")
    return valid


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
            print("[random_media] No images/gifs found in pool channel.")
            return
        chosen_msg, chosen_media = media_queue.pop(0)
        attachment = random.choice(chosen_media)
        await welcome_channel.send(file=await attachment.to_file())
        print(f"[random_media] Sent image/gif. {len(media_queue)} remaining in queue.")
    except Exception as e:
        print(f"[random_media] ERROR: {e}")


async def get_active_user_count() -> int:
    welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
    if welcome_channel is None:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    users = set()
    async for msg in welcome_channel.history(limit=100, after=cutoff):
        if not msg.author.bot:
            users.add(msg.author.id)
    return len(users)


async def run_media_loop():
    while media_loop_running:
        active_users = await get_active_user_count()
        print(f"[random_media] Active users in last 30min: {active_users}")
        if active_users >= 5:
            interval = 30 * 60
        elif active_users >= 3:
            interval = 1 * 60 * 60
        else:
            interval = 3 * 60 * 60
        await post_random_media()
        await asyncio.sleep(interval)


@bot.tree.command(name="startmedia", description="Start posting random images/gifs based on chat activity.")
@app_commands.checks.has_permissions(administrator=True)
async def start_media(interaction: discord.Interaction):
    global media_loop_running, media_loop_task
    if media_loop_running:
        await interaction.response.send_message("⚠️ Random media is already running!", ephemeral=True)
        return
    media_loop_running = True
    media_loop_task = asyncio.ensure_future(run_media_loop())
    await interaction.response.send_message("✅ Started.", ephemeral=True)


@bot.tree.command(name="stopmedia", description="Stop posting random images/gifs.")
@app_commands.checks.has_permissions(administrator=True)
async def stop_media(interaction: discord.Interaction):
    global media_loop_running, media_loop_task
    if not media_loop_running:
        await interaction.response.send_message("⚠️ Random media isn't running.", ephemeral=True)
        return
    media_loop_running = False
    if media_loop_task and not media_loop_task.done():
        media_loop_task.cancel()
    await interaction.response.send_message("🛑 Stopped.", ephemeral=True)


# ───────────────────────────────────────────────
#  RUN
# ───────────────────────────────────────────────

bot.run(TOKEN)
