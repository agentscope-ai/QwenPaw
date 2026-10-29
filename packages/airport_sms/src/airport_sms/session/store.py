"""SQLite 会话与消息表。"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from airport_sms.domain.case import CaseId
from airport_sms.domain.roles import Role
from airport_sms.session.principal import Principal, Session

Now = Callable[[], datetime]


def utcnow() -> datetime:
    """返回 UTC 当前时间。"""
    return datetime.now(timezone.utc)


def open_db(path: str = ":memory:") -> sqlite3.Connection:
    """打开 SQLite 连接并建表。"""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """创建会话、消息、案件、幂等键表。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
          session_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          org_id TEXT NOT NULL,
          role TEXT NOT NULL,
          site_id TEXT NOT NULL,
          channel TEXT NOT NULL,
          created_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          conversation_cursor TEXT NOT NULL DEFAULT '',
          bound_case_id TEXT,
          closed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS session_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cases (
          id TEXT PRIMARY KEY,
          org_id TEXT NOT NULL,
          site_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          state TEXT NOT NULL,
          payload TEXT NOT NULL,
          deleted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS idempotency (
          org_id TEXT NOT NULL,
          site_id TEXT NOT NULL,
          command TEXT NOT NULL,
          key TEXT NOT NULL,
          case_id TEXT NOT NULL,
          PRIMARY KEY (org_id, site_id, command, key)
        );
        """
    )
    conn.commit()


class SessionStore:
    """会话与聊天消息。写消息不改案件。"""

    def __init__(self, conn: sqlite3.Connection, *, now: Now = utcnow) -> None:
        self._conn = conn
        self._now = now
        init_schema(conn)

    def create(self, session: Session) -> Session:
        """持久化会话。"""
        p = session.principal
        self._conn.execute(
            "INSERT INTO sessions(session_id,user_id,org_id,role,site_id,channel,"
            "created_at,last_seen_at,conversation_cursor,bound_case_id,closed)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                session.session_id,
                p.user_id,
                p.org_id,
                p.role.value,
                p.site_id,
                session.channel,
                session.created_at.isoformat(),
                session.last_seen_at.isoformat(),
                session.conversation_cursor,
                session.bound_case_id,
                1 if session.closed else 0,
            ),
        )
        self._conn.commit()
        return session

    def get(self, session_id: str) -> Session | None:
        """按 id 读取会话。"""
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_session(row)

    def bind_case(self, session_id: str, case_id: CaseId) -> Session:
        """把案件 id 记在会话游标上，不改案件行。"""
        self._conn.execute(
            "UPDATE sessions SET bound_case_id=? WHERE session_id=?",
            (str(case_id), session_id),
        )
        self._conn.commit()
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def set_conversation_cursor(self, session_id: str, cursor: str) -> Session:
        """更新对话游标。"""
        self._conn.execute(
            "UPDATE sessions SET conversation_cursor=? WHERE session_id=?",
            (cursor, session_id),
        )
        self._conn.commit()
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def touch(self, session_id: str) -> None:
        """刷新 last_seen。"""
        self._conn.execute(
            "UPDATE sessions SET last_seen_at=? WHERE session_id=?",
            (self._now().isoformat(), session_id),
        )
        self._conn.commit()

    def expire_idle(self, *, ttl: timedelta) -> int:
        """将 last_seen 超过 TTL 的会话标为关闭。"""
        cutoff = (self._now() - ttl).isoformat()
        cur = self._conn.execute(
            "UPDATE sessions SET closed=1"
            " WHERE closed=0 AND last_seen_at <= ?",
            (cutoff,),
        )
        self._conn.commit()
        return cur.rowcount

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """追加聊天消息。"""
        self._conn.execute(
            "INSERT INTO session_messages(session_id, role, content, created_at)"
            " VALUES(?,?,?,?)",
            (session_id, role, content, self._now().isoformat()),
        )
        self._conn.commit()

    def message_count(self, session_id: str) -> int:
        """会话消息条数。"""
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM session_messages WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return int(row["c"])


def open_session(
    session_id: str,
    principal: Principal,
    channel: str,
    *,
    now: Now = utcnow,
) -> Session:
    """构造未关闭的新会话。"""
    ts = now()
    return Session(
        session_id=session_id,
        principal=principal,
        channel=channel,
        created_at=ts,
        last_seen_at=ts,
    )


def _row_to_session(row: sqlite3.Row) -> Session:
    """把会话行解析成领域类型。"""
    principal = Principal(
        user_id=row["user_id"],
        org_id=row["org_id"],
        role=Role(row["role"]),
        site_id=row["site_id"],
    )
    bound = row["bound_case_id"]
    return Session(
        session_id=row["session_id"],
        principal=principal,
        channel=row["channel"],
        created_at=datetime.fromisoformat(row["created_at"]),
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        conversation_cursor=row["conversation_cursor"] or "",
        bound_case_id=CaseId(bound) if bound else None,
        closed=bool(row["closed"]),
    )


__all__ = [
    "SessionStore",
    "init_schema",
    "open_db",
    "open_session",
    "utcnow",
]
