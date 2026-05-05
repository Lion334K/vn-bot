import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import random

# ───────────────────────────────────────────────
#  CONFIGURATION
# ───────────────────────────────────────────────

TOKEN = "MTQ3ODg0MjI0NzY2NjU5Nzk4MA.G41wtj.yYeUafzcZP6S95CMFXHhSB8Jtcc_IX7R_Mhnkk"

WELCOME_CHANNEL_ID = 1488662459009994965
BUMP_CHANNEL_ID    = 1381771230964748370
GUILD_ID           = 1381768080610426930
BUMP_BOT_ID        = 302050872383242240    # only this bot resets the bump timer
IMAGE_LOG_CHANNEL_ID = 1381770621054091306 # all images from all channels get logged here
ANNOUNCE_SOURCE_CHANNEL_ID = 1489993668126572545  # messages here get copied to welcome channel
EMBED_POOL_CHANNEL_ID      = 1501344668242280559  # random gif/image picked from here every 3 hours

# Cross-server mirroring
MIRROR_SOURCE_CHANNEL_ID = 1489996127347413114   # channel to watch (friend's server)
MIRROR_TARGET_CHANNEL_ID = 1488485721877643314   # channel to post into (your server)

# Default welcome message ({member} = new member's mention)
WELCOME_MESSAGE = "Aramıza yeni biri katıldı! Hoşgeldin {member} 🥹"

# Default bump reminder message
BUMP_MESSAGE = "Buuuuuump"

# ───────────────────────────────────────────────
#  BOT SETUP
# ───────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

bump_task = None  # holds the pending bump reminder task

# ───────────────────────────────────────────────
#  EVENTS
# ───────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        guild = discord.Object(id=GUILD_ID)
        # Clear all commands first, then re-sync only the current ones
        bot.tree.clear_commands(guild=guild)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced)} slash command(s) to guild.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    if not random_media.is_running():
        random_media.start()


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

    # ── Image logger (all channels) ──
    if not message.author.bot:
        image_extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp")
        images = [a for a in message.attachments if a.filename.lower().endswith(image_extensions)]
        if images:
            log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
            if log_channel and message.channel.id != IMAGE_LOG_CHANNEL_ID:
                for image in images:
                    await log_channel.send(
                        f"📸 **{message.author.display_name}** (#{message.channel.name})",
                        file=await image.to_file()
                    )
                print(f"[image_log] Logged {len(images)} image(s) from {message.author} in #{message.channel.name}.")

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
        await asyncio.sleep(2 * 60 * 60)  # 2 hours
        channel = bot.get_channel(BUMP_CHANNEL_ID)
        if channel:
            await channel.send(BUMP_MESSAGE)
            print("[bump] Reminder sent.")
    except asyncio.CancelledError:
        pass


# ───────────────────────────────────────────────
#  SLASH COMMANDS
# ───────────────────────────────────────────────

@bot.tree.command(name="setwelcome", description="Hoşgeldin mesajını değiştir. {member} yeni üyeyi etiketler.")
@app_commands.checks.has_permissions(administrator=True)
async def set_welcome(interaction: discord.Interaction, message: str):
    global WELCOME_MESSAGE
    WELCOME_MESSAGE = message
    await interaction.response.send_message(f"✅ Hoşgeldin mesajı güncellendi:\n> {WELCOME_MESSAGE}")


@bot.tree.command(name="testwelcome", description="Mevcut hoşgeldin mesajını önizle.")
@app_commands.checks.has_permissions(administrator=True)
async def test_welcome(interaction: discord.Interaction):
    msg = WELCOME_MESSAGE.replace("{member}", interaction.user.mention)
    await interaction.response.send_message(f"**Önizleme:**\n{msg}")


@bot.tree.command(name="testmirror", description="Copies the last message from the source channel to the target channel.")
@app_commands.checks.has_permissions(administrator=True)
async def test_mirror(interaction: discord.Interaction):
    await interaction.response.defer()
    source = bot.get_channel(MIRROR_SOURCE_CHANNEL_ID)
    if source is None:
        await interaction.followup.send(f"❌ Source channel {MIRROR_SOURCE_CHANNEL_ID} not found.")
        return
    target = bot.get_channel(MIRROR_TARGET_CHANNEL_ID)
    if target is None:
        await interaction.followup.send(f"❌ Target channel {MIRROR_TARGET_CHANNEL_ID} not found.")
        return
    # Fetch the last message in the source channel
    messages = [msg async for msg in source.history(limit=1)]
    if not messages:
        await interaction.followup.send("❌ No messages found in the source channel.")
        return
    last = messages[0]
    if last.content:
        await target.send(last.content)
    for attachment in last.attachments:
        await target.send(file=await attachment.to_file())
    await interaction.followup.send(f"✅ Last message mirrored to <#{MIRROR_TARGET_CHANNEL_ID}>.")


@bot.tree.command(name="setbump", description="Bump hatırlatma mesajını değiştir.")
@app_commands.checks.has_permissions(administrator=True)
async def set_bump(interaction: discord.Interaction, message: str):
    global BUMP_MESSAGE
    BUMP_MESSAGE = message
    await interaction.response.send_message(f"✅ Bump mesajı güncellendi:\n> {BUMP_MESSAGE}")


# ───────────────────────────────────────────────
#  RANDOM MEDIA EVERY 3 HOURS
# ───────────────────────────────────────────────

@tasks.loop(hours=3)
async def random_media():
    try:
        pool_channel = bot.get_channel(EMBED_POOL_CHANNEL_ID)
        welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
        if pool_channel is None or welcome_channel is None:
            print("[random_media] ERROR: Channel not found.")
            return

        image_extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp")
        valid_messages = []
        async for msg in pool_channel.history(limit=200):
            media = [a for a in msg.attachments if a.filename.lower().endswith(image_extensions)]
            if media:
                valid_messages.append((msg, media))

        if not valid_messages:
            print("[random_media] No images/gifs found in pool channel.")
            return

        chosen_msg, chosen_media = random.choice(valid_messages)
        attachment = random.choice(chosen_media)
        await welcome_channel.send(file=await attachment.to_file())
        print(f"[random_media] Sent a random image/gif to welcome channel.")
    except Exception as e:
        print(f"[random_media] ERROR: {e}")

@random_media.before_loop
async def before_random_media():
    await bot.wait_until_ready()


# ───────────────────────────────────────────────
#  RUN
# ───────────────────────────────────────────────

bot.run(TOKEN)
