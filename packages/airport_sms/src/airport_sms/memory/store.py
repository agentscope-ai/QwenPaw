"""长期 SMS 记忆的 SQLite 向量表。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import Enum

from airport_sms.memory.embedder import Embedder


class SourceType(str, Enum):
    """记忆来源。closed_case 为派生记忆。"""

    MANUAL = "manual"
    CLOSED_CASE = "closed_case"


@dataclass(frozen=True)
class MemoryDoc:
    """一条可检索文档。"""

    doc_id: str
    org_id: str
    source_type: SourceType
    source_id: str
    text: str

    @property
    def derived(self) -> bool:
        """结案记忆是派生的，手册不是。"""
        return self.source_type is SourceType.CLOSED_CASE


def init_memory_schema(conn: sqlite3.Connection) -> None:
    """创建记忆表。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_docs (
          org_id TEXT NOT NULL,
          doc_id TEXT NOT NULL,
          source_type TEXT NOT NULL,
          source_id TEXT NOT NULL,
          text TEXT NOT NULL,
          embedding TEXT NOT NULL,
          derived INTEGER NOT NULL,
          PRIMARY KEY (org_id, doc_id)
        )
        """
    )
    conn.commit()


class MemoryStore:
    """按组织隔离的向量存储。接口可替换为 faiss。"""

    def __init__(self, conn: sqlite3.Connection, embedder: Embedder) -> None:
        self._conn = conn
        self._embedder = embedder
        init_memory_schema(conn)

    def index(self, doc: MemoryDoc) -> None:
        """写入或覆盖一条文档及其向量。"""
        embedding = self._embedder.embed([doc.text])[0]
        self._conn.execute(
            "INSERT OR REPLACE INTO memory_docs("
            "org_id, doc_id, source_type, source_id, text, embedding, derived)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                doc.org_id,
                doc.doc_id,
                doc.source_type.value,
                doc.source_id,
                doc.text,
                json.dumps(embedding),
                1 if doc.derived else 0,
            ),
        )
        self._conn.commit()

    def delete(self, org_id: str, doc_id: str) -> None:
        """删除文档及其向量。"""
        self._conn.execute(
            "DELETE FROM memory_docs WHERE org_id=? AND doc_id=?",
            (org_id, doc_id),
        )
        self._conn.commit()

    def count(self, org_id: str) -> int:
        """组织内文档数。"""
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM memory_docs WHERE org_id=?",
            (org_id,),
        ).fetchone()
        return int(row[0])

    def rows(self, org_id: str) -> list[sqlite3.Row]:
        """读取组织内全部文档行，供检索。"""
        self._conn.row_factory = sqlite3.Row
        return list(
            self._conn.execute(
                "SELECT * FROM memory_docs WHERE org_id=?",
                (org_id,),
            ).fetchall()
        )


__all__ = [
    "MemoryDoc",
    "MemoryStore",
    "SourceType",
    "init_memory_schema",
]
