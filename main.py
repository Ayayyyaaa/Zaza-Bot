"""Bot Discord : message "sticky" qui reste toujours en bas du salon.

Principe : à chaque nouveau message posté par un membre dans un salon où un
sticky est actif, on incrémente un compteur. Une fois le seuil atteint, on
supprime l'ancien message sticky et on en renvoie un nouveau (donc toujours
tout en bas de la conversation), puis on remet le compteur à 0.
"""
import asyncio
import logging
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from core.db import Database

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("sticky-bot")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID") 
DATA_DIR = os.getenv("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "sticky.db")
DEFAULT_THRESHOLD = int(os.getenv("DEFAULT_THRESHOLD", "1"))  

INTENTS = discord.Intents.default()


class StickyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)
        self.db: Optional[Database] = None

    async def setup_hook(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.db = Database(DB_PATH)
        await self.db.connect()
        log.info("Base de données prête (%s)", DB_PATH)

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Commandes synchronisées sur le serveur de test %s", GUILD_ID)
        else:
            await self.tree.sync()
            log.info("Commandes synchronisées globalement (jusqu'à 1h pour apparaître partout)")

    async def close(self):
        if self.db:
            await self.db.close()
        await super().close()

    async def on_ready(self):
        log.info("Connecté en tant que %s (id: %s)", self.user, self.user.id)


bot = StickyBot()


# ---------------------------------------------------------------------------
# Écoute de tous les messages pour déclencher le repost du sticky
# ---------------------------------------------------------------------------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return

    cfg = await bot.db.get_sticky(message.channel.id)
    if not cfg:
        return

    counter = await bot.db.increment_counter(message.channel.id)
    if counter < cfg["threshold"]:
        return

    # Seuil atteint : on supprime l'ancien sticky et on en renvoie un nouveau
    if cfg["last_message_id"]:
        try:
            old = await message.channel.fetch_message(cfg["last_message_id"])
            await old.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    try:
        new_msg = await message.channel.send(cfg["text"])
        await bot.db.reset_counter_and_message(message.channel.id, new_msg.id)
    except discord.Forbidden:
        log.warning("Missing permissions in %s", message.channel.id)


# ---------------------------------------------------------------------------
# Commandes slash
# ---------------------------------------------------------------------------
@bot.tree.command(name="stick", description="Stick a message for this channel")
@app_commands.describe(
    texte="Message content",
    seuil="Number of messages before repost (default 1)",
)
@app_commands.default_permissions(manage_messages=True)
async def stick(interaction: discord.Interaction, texte: str, seuil: app_commands.Range[int, 1, 50] = DEFAULT_THRESHOLD):
    perms = interaction.channel.permissions_for(interaction.guild.me)
    if not (perms.send_messages and perms.manage_messages):
        await interaction.response.send_message(
            "❌ Missing permissions : **Send messages** and **Manage messages** in this channel.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    msg = await interaction.channel.send(texte)
    await bot.db.set_sticky(interaction.channel.id, interaction.guild_id, texte, seuil, msg.id)
    await interaction.followup.send(
        f"📌 Sticky enabled in  {interaction.channel.mention} (repost every {seuil} messages).",
        ephemeral=True,
    )


@bot.tree.command(name="stickstop", description="Disable the sticky post in this channel")
@app_commands.default_permissions(manage_messages=True)
async def stickstop(interaction: discord.Interaction):
    cfg = await bot.db.remove_sticky(interaction.channel.id)
    if not cfg:
        await interaction.response.send_message("There are no active sticky posts in this channel", ephemeral=True)
        return

    if cfg["last_message_id"]:
        try:
            old = await interaction.channel.fetch_message(cfg["last_message_id"])
            await old.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    await interaction.response.send_message("🛑 Sticky disabled for this channel", ephemeral=True)


@bot.tree.command(name="stickstatus", description="View the sticky post settings for this channel")
async def stickstatus(interaction: discord.Interaction):
    cfg = await bot.db.get_sticky(interaction.channel.id)
    if not cfg:
        await interaction.response.send_message("There are no active sticky posts in this channel", ephemeral=True)
        return

    embed = discord.Embed(title="📌 Active Sticky", color=discord.Color.blurple())
    embed.add_field(name="Text", value=cfg["text"][:1000], inline=False)
    embed.add_field(name="Repost Threshold", value=f"{cfg['threshold']} messages", inline=True)
    embed.add_field(name="Current counter", value=f"{cfg['counter']}/{cfg['threshold']}", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def main():
    if not TOKEN:
        raise SystemExit("❌ La variable d'environnement DISCORD_TOKEN est manquante (voir .env.example).")
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
