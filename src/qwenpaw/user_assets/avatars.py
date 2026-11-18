# -*- coding: utf-8 -*-
"""Bounded, user-scoped avatar persistence with original GIF bytes."""

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import sqlite3

from PIL import Image, UnidentifiedImageError

MAX_BYTES = 2 * 1024 * 1024
HISTORY_LIMIT = 12
FORMATS = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


class AvatarStore:
    """Keep identity selection and bounded history in one transaction."""

    def __init__(self, database: Path):
        self.database = database
        database.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            with conn:
                conn.executescript(
                    "CREATE TABLE IF NOT EXISTS avatar_images ("
                    "owner TEXT NOT NULL, id TEXT NOT NULL,"
                    "mime TEXT NOT NULL,"
                    "data BLOB NOT NULL, created_at TEXT NOT NULL,"
                    "PRIMARY KEY(owner, id));"
                    "CREATE TABLE IF NOT EXISTS avatar_selection ("
                    "owner TEXT PRIMARY KEY, image_id TEXT);",
                )

    def _connect(self):
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def profile(self, owner: str) -> dict:
        with closing(self._connect()) as conn:
            selected = conn.execute(
                "SELECT image_id FROM avatar_selection WHERE owner = ?",
                (owner,),
            ).fetchone()
            history = conn.execute(
                "SELECT id, mime, created_at FROM avatar_images "
                "WHERE owner = ? ORDER BY created_at DESC, id",
                (owner,),
            ).fetchall()
        return {
            "selected": selected[0] if selected else None,
            "history": [dict(row) for row in history],
        }

    def upload(self, owner: str, data: bytes) -> dict:
        if not data or len(data) > MAX_BYTES:
            raise ValueError(f"Image must be between 1 byte and {MAX_BYTES}")
        try:
            with Image.open(BytesIO(data)) as image:
                mime = FORMATS.get(image.format)
                if not mime or image.width * image.height > 16_777_216:
                    raise ValueError("Unsupported image format or size")
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValueError("Invalid image") from None
        identifier = sha256(data).hexdigest()
        created = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO avatar_images "
                    "VALUES (?, ?, ?, ?, ?)",
                    (owner, identifier, mime, data, created),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO avatar_selection VALUES (?, ?)",
                    (owner, identifier),
                )
                conn.execute(
                    "DELETE FROM avatar_images WHERE owner = ? AND id NOT IN "
                    "(SELECT id FROM avatar_images WHERE owner = ? "
                    "ORDER BY created_at DESC, id LIMIT ?)",
                    (owner, owner, HISTORY_LIMIT),
                )
        return self.profile(owner)

    def select(self, owner: str, identifier: str | None) -> dict:
        with closing(self._connect()) as conn:
            with conn:
                if (
                    identifier
                    and not conn.execute(
                        "SELECT 1 FROM avatar_images "
                        "WHERE owner = ? AND id = ?",
                        (owner, identifier),
                    ).fetchone()
                ):
                    raise KeyError(identifier)
                conn.execute(
                    "INSERT OR REPLACE INTO avatar_selection VALUES (?, ?)",
                    (owner, identifier),
                )
        return self.profile(owner)

    def image(self, owner: str, identifier: str) -> tuple[bytes, str]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT data, mime FROM avatar_images "
                "WHERE owner = ? AND id = ?",
                (owner, identifier),
            ).fetchone()
        if row is None:
            raise KeyError(identifier)
        return row[0], row[1]
