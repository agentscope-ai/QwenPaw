"""长期 SMS 记忆的 SQLite 向量表。工作记忆仍在会话消息里。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from airport_sms.memory.embedder import Embedder


class SourceType(str, Enum):
    """记忆来源。closed_case 为派生记忆。"""

    MANUAL = "manual"
    CLOSED_CASE = "closed_case"


@dataclass(frozen=True)
class MemoryDoc:
    """一条可检索文档。主键是 (org_id, doc_id)。"""

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
    """创建记忆表。向量与文档同行，删除即去向量。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_docs (
          org_id TEXT NOT NULL,
          doc_id TEXT NOT NULL,
          source_type TEXT NOT NULL,
          source_id TEXT NOT NULL,
          text TEXT NOT NULL,
          embedding TEXT NOT NULL,
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

    @property
    def embedder(self) -> Embedder:
        """本库使用的嵌入器。"""
        return self._embedder

    def index(self, doc: MemoryDoc) -> None:
        """写入或覆盖一条文档及其向量。"""
        embedding = self._embedder.embed([doc.text])[0]
        self._conn.execute(
            "INSERT OR REPLACE INTO memory_docs("
            "org_id, doc_id, source_type, source_id, text, embedding)"
            " VALUES(?,?,?,?,?,?)",
            (
                doc.org_id,
                doc.doc_id,
                doc.source_type.value,
                doc.source_id,
                doc.text,
                json.dumps(embedding),
            ),
        )
        self._conn.commit()

    def index_manual(self, org_id: str, clause_id: str, text: str) -> MemoryDoc:
        """把手册条款写入本组织索引。"""
        doc = MemoryDoc(
            doc_id=f"manual:{clause_id}",
            org_id=org_id,
            source_type=SourceType.MANUAL,
            source_id=clause_id,
            text=text,
        )
        self.index(doc)
        return doc

    def index_manuals(self, org_id: str, clauses: Mapping[str, str]) -> int:
        """批量写入手册条款。"""
        for clause_id, text in clauses.items():
            self.index_manual(org_id, clause_id, text)
        return len(clauses)

    def index_closed_case(self, org_id: str, case_id: str, text: str) -> MemoryDoc:
        """把结案写入本组织索引，来源固定为 closed_case。"""
        doc = MemoryDoc(
            doc_id=f"closed:{case_id}",
            org_id=org_id,
            source_type=SourceType.CLOSED_CASE,
            source_id=case_id,
            text=text,
        )
        self.index(doc)
        return doc

    def delete(self, org_id: str, doc_id: str) -> None:
        """删除文档及其向量。缺行也是成功。"""
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

    def load(self, org_id: str) -> list[tuple[MemoryDoc, list[float]]]:
        """读取本组织文档与向量。不改 row_factory，避免污染共用连接。"""
        cur = self._conn.execute(
            "SELECT org_id, doc_id, source_type, source_id, text, embedding"
            " FROM memory_docs WHERE org_id=?",
            (org_id,),
        )
        out: list[tuple[MemoryDoc, list[float]]] = []
        for org, doc_id, source_type, source_id, text, embedding in cur.fetchall():
            out.append(
                (
                    MemoryDoc(
                        doc_id=doc_id,
                        org_id=org,
                        source_type=SourceType(source_type),
                        source_id=source_id,
                        text=text,
                    ),
                    json.loads(embedding),
                )
            )
        return out


__all__ = [
    "MemoryDoc",
    "MemoryStore",
    "SourceType",
    "init_memory_schema",
]
