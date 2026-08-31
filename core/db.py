"""Accès à la base de données SQLite (persistante, montée en volume Docker)."""
from __future__ import annotations

import aiosqlite
from typing import Optional, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS sticky_config (
    channel_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    threshold INTEGER NOT NULL DEFAULT 5,
    last_message_id INTEGER,
    counter INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    # ------------------------------------------------------------------
    async def set_sticky(self, channel_id: int, guild_id: int, text: str, threshold: int, message_id: int):
        await self._conn.execute(
            "INSERT INTO sticky_config (channel_id, guild_id, text, threshold, last_message_id, counter) "
            "VALUES (?, ?, ?, ?, ?, 0) "
            "ON CONFLICT(channel_id) DO UPDATE SET "
            "guild_id=excluded.guild_id, text=excluded.text, threshold=excluded.threshold, "
            "last_message_id=excluded.last_message_id, counter=0",
            (channel_id, guild_id, text, threshold, message_id),
        )
        await self._conn.commit()

    async def get_sticky(self, channel_id: int) -> Optional[aiosqlite.Row]:
        cur = await self._conn.execute("SELECT * FROM sticky_config WHERE channel_id = ?", (channel_id,))
        return await cur.fetchone()

    async def remove_sticky(self, channel_id: int) -> Optional[aiosqlite.Row]:
        row = await self.get_sticky(channel_id)
        await self._conn.execute("DELETE FROM sticky_config WHERE channel_id = ?", (channel_id,))
        await self._conn.commit()
        return row

    async def increment_counter(self, channel_id: int) -> int:
        await self._conn.execute(
            "UPDATE sticky_config SET counter = counter + 1 WHERE channel_id = ?", (channel_id,)
        )
        await self._conn.commit()
        row = await self.get_sticky(channel_id)
        return row["counter"] if row else 0

    async def reset_counter_and_message(self, channel_id: int, new_message_id: int):
        await self._conn.execute(
            "UPDATE sticky_config SET counter = 0, last_message_id = ? WHERE channel_id = ?",
            (new_message_id, channel_id),
        )
        await self._conn.commit()

    async def get_all_sticky(self) -> Sequence[aiosqlite.Row]:
        cur = await self._conn.execute("SELECT * FROM sticky_config")
        return await cur.fetchall()
