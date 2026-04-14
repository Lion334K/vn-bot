import discord
from discord.ext import commands
from discord import app_commands
import asyncio

# ───────────────────────────────────────────────
#  CONFIGURATION
# ───────────────────────────────────────────────

TOKEN = "MTQ3ODg0MjI0NzY2NjU5Nzk4MA.Ggg4u3.9Zqy8vw7Vky8wFjnXURoOTsdPU17KbAJFXpac4"

WELCOME_CHANNEL_ID = 1488662459009994965
BUMP_CHANNEL_ID    = 1381771230964748370
GUILD_ID           = 1381768080610426930
IMAGE_LOG_CHANNEL_ID = 1381770621054091306  # images from welcome channel get logged here

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

    # ── Image logger ──
    if message.channel.id == WELCOME_CHANNEL_ID and not message.author.bot:
        image_extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp")
        images = [a for a in message.attachments if a.filename.lower().endswith(image_extensions)]
        if images:
            log_channel = bot.get_channel(IMAGE_LOG_CHANNEL_ID)
            if log_channel:
                for image in images:
                    await log_channel.send(file=await image.to_file())
                print(f"[image_log] Logged {len(images)} image(s) from {message.author}.")

    # ── Cross-server mirror ──
    if message.channel.id == MIRROR_SOURCE_CHANNEL_ID:
        if not (message.author == bot.user):
            target = bot.get_channel(MIRROR_TARGET_CHANNEL_ID)
            if target:
                # Send the message text if there is one
                if message.content:
                    await target.send(message.content)
                # Send any attachments
                for attachment in message.attachments:
                    await target.send(file=await attachment.to_file())
                print(f"[mirror] Mirrored message from {message.author} ({len(message.attachments)} attachments)")
            else:
                print(f"[mirror] ERROR: Target channel {MIRROR_TARGET_CHANNEL_ID} not found.")

    # ── Bump reminder ──
    if message.channel.id == BUMP_CHANNEL_ID:
        if message.author == bot.user and message.content == BUMP_MESSAGE:
            return
        if bump_task and not bump_task.done():
            bump_task.cancel()
            print("[bump] Timer reset due to new message.")
        bump_task = asyncio.ensure_future(schedule_bump())

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
#  RUN
# ───────────────────────────────────────────────

bot.run(TOKEN)
