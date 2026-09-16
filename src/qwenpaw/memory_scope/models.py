# -*- coding: utf-8 -*-
"""记忆作用域的领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class MemoryScope(StrEnum):
    """记忆数据的逻辑作用域。"""

    PUBLIC = "public"
    PRIVATE = "private"


class MemoryWorkspaceStatus(StrEnum):
    """用户运行空间的生命周期状态。"""

    ACTIVE = "active"
    ACCESS_REVOKED = "access_revoked"
    CLEANUP_PENDING = "cleanup_pending"


class MemoryIndexState(StrEnum):
    """作用域索引的可重建状态。"""

    READY = "ready"
    NEEDS_REINDEX = "needs_reindex"
    REINDEXING = "reindexing"
    REINDEX_FAILED = "reindex_failed"


class MemoryScopeDenied(RuntimeError):
    """请求无法安全解析为可信记忆作用域。"""


@dataclass(frozen=True, slots=True)
class MemoryScopeContext:
    """服务端认证后形成的记忆作用域上下文。"""

    actor_user_id: UUID | None
    agent_id: str
    scope: MemoryScope
    session_id: str | None = None
    run_id: str | None = None
    governance: bool = False
