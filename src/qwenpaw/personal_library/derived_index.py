# -*- coding: utf-8 -*-
"""可重建的资料倒排索引；不承担资料归属或访问授权。"""

from __future__ import annotations

import json
import sqlite3
import threading
import unicodedata
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from ..utils.path_safety import is_link_or_junction
from .paths import PersonalLibraryPathDenied
from .search_index import PersonalLibrarySearchIndex

# 固定数量的锁避免用户/智能体数量增长导致常驻锁表无限增长。
_LOCKS = tuple(threading.RLock() for _ in range(64))


def search_grams(text: str) -> set[str]:
    """字符及双字片段支持中英文子串召回；最终相关性由服务层验证。"""
    text = unicodedata.normalize("NFKC", text).casefold()
    return {char for char in text if not char.isspace()} | {
        text[i : i + 2] for i in range(len(text) - 1) if not text[i : i + 2].isspace()
    }


class LibraryIndexStore:
    def __init__(self, working_dir: Path, owner_id: UUID, agent_id: UUID):
        # 索引放在上传根目录之外，用户上传文件名不能覆盖索引数据库。
        root = Path(working_dir).resolve()
        current = root
        for component in ("personal_library_indexes", str(owner_id), str(agent_id)):
            current /= component
            if is_link_or_junction(current):
                raise PersonalLibraryPathDenied("library_index_symlink_denied")
            current.mkdir(exist_ok=True)
        self.path = current / "search.sqlite3"
        if any(
            is_link_or_junction(Path(str(self.path) + suffix))
            for suffix in ("", "-journal", "-wal", "-shm")
        ):
            raise PersonalLibraryPathDenied("library_index_symlink_denied")
        self.lock = _LOCKS[hash(str(self.path)) % len(_LOCKS)]

    @contextmanager
    def connection(self):
        with self.lock, closing(sqlite3.connect(self.path, timeout=15)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, relative_path TEXT NOT NULL,
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                    status TEXT NOT NULL, indexed_characters INTEGER NOT NULL,
                    updated_at TEXT NOT NULL, payload TEXT
                )""")
                conn.execute("""CREATE TABLE IF NOT EXISTS postings (
                    token TEXT NOT NULL, document_id TEXT NOT NULL,
                    PRIMARY KEY (token, document_id)
                ) WITHOUT ROWID""")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS postings_document ON postings(document_id)"
                )
                yield conn

    def metadata(self) -> dict[str, dict]:
        with self.connection() as conn:
            return {
                row["id"]: dict(row)
                for row in conn.execute(
                    "SELECT id, version, sha256, relative_path, size, mtime_ns, status, indexed_characters, updated_at FROM documents"
                )
            }

    def save(
        self,
        document,
        *,
        version: int,
        size: int,
        mtime_ns: int,
        status: str,
        index: PersonalLibrarySearchIndex | None,
    ):
        payload = (
            json.dumps(index.to_json_dict(), ensure_ascii=False) if index else None
        )
        tokens = search_grams(index.content) if index else set()
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM postings WHERE document_id = ?", (str(document.id),)
            )
            conn.execute(
                """INSERT OR REPLACE INTO documents
                (id, version, sha256, relative_path, size, mtime_ns, status, indexed_characters, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(document.id),
                    version,
                    document.sha256,
                    document.relative_path,
                    size,
                    mtime_ns,
                    status,
                    len(index.content) if index else 0,
                    datetime.now(UTC).isoformat(),
                    payload,
                ),
            )
            conn.executemany(
                "INSERT INTO postings (token, document_id) VALUES (?, ?)",
                ((token, str(document.id)) for token in tokens),
            )

    def load(self, document_id: str) -> PersonalLibrarySearchIndex | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT payload FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            return (
                PersonalLibrarySearchIndex.from_json_dict(json.loads(row[0]))
                if row and row[0]
                else None
            )

    def candidates(self, terms: list[str]) -> set[str]:
        tokens: set[str] = set()
        for term in terms:
            grams = search_grams(term)
            # 长词仅使用双字片段，避免单个常见汉字召回整个资料库。
            tokens.update(token for token in grams if len(token) == 2 or len(term) == 1)
        if not tokens:
            return set()
        with self.connection() as conn:
            placeholders = ",".join("?" for _ in tokens)
            return {
                row[0]
                for row in conn.execute(
                    f"SELECT DISTINCT document_id FROM postings WHERE token IN ({placeholders})",
                    tuple(tokens),
                )
            }

    def delete(self, document_id: str):
        with self.connection() as conn:
            conn.execute("DELETE FROM postings WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    def repair(self):
        """显式重建时隔离损坏的派生数据库，保留诊断副本及所有原文件。"""
        with self.lock:
            try:
                with self.connection() as conn:
                    result = conn.execute("PRAGMA quick_check").fetchone()[0]
                    if result != "ok":
                        raise sqlite3.DatabaseError("index_corrupt")
            except sqlite3.DatabaseError:
                self.path.replace(
                    self.path.with_name(f"search.broken-{uuid4().hex}.sqlite3")
                )
                with self.connection():
                    pass
