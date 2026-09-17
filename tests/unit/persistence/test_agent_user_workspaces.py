# -*- coding: utf-8 -*-
"""Agent 用户运行空间 PostgreSQL 仓储契约。"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qwenpaw.memory_scope.models import (
    MemoryIndexState,
    MemoryScope,
    MemoryWorkspaceStatus,
)
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.persistence.agent_user_workspaces import (
    AgentUserWorkspaceRepository,
)


class MappingResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def one(self):
        return self._row

    def one_or_none(self):
        return self._row


class RecordingSession:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return MappingResult(self.rows.pop(0))


def session_factory(session):
    @asynccontextmanager
    async def factory():
        yield session

    return factory


@pytest.mark.asyncio
async def test_ensure_private_workspace_is_idempotent_and_scoped() -> None:
    user_id = uuid4()
    now = datetime(2026, 8, 25, tzinfo=UTC)
    row = {
        "user_id": user_id,
        "agent_key": "agent-a",
        "scope": "private",
        "workspace_key": f"user_workspaces/{user_id}/agent-a",
        "status": "active",
        "index_state": "needs_reindex",
        "index_version": 0,
        "created_at": now,
        "updated_at": now,
        "last_accessed_at": now,
    }
    session = RecordingSession([row, row])
    repository = AgentUserWorkspaceRepository(
        schema="qwenpaw_test",
        session_factory=session_factory(session),
        clock=lambda: now,
    )

    first = await repository.ensure_private(
        user_id=user_id,
        agent_key="agent-a",
        workspace_key=row["workspace_key"],
    )
    second = await repository.ensure_private(
        user_id=user_id,
        agent_key="agent-a",
        workspace_key=row["workspace_key"],
    )

    assert first == second
    assert first.scope is MemoryScope.PRIVATE
    assert first.index_state is MemoryIndexState.NEEDS_REINDEX
    assert "ON CONFLICT" in session.calls[0][0]
    assert session.calls[0][1]["user_id"] == user_id


@pytest.mark.asyncio
async def test_get_private_never_queries_another_users_record() -> None:
    user_id = uuid4()
    session = RecordingSession([None])
    repository = AgentUserWorkspaceRepository(
        schema="qwenpaw_test",
        session_factory=session_factory(session),
    )

    result = await repository.get_private(
        user_id=user_id,
        agent_key="agent-a",
    )

    assert result is None
    sql, params = session.calls[0]
    assert "user_id = :user_id" in sql
    assert "agent_id = :agent_id" in sql
    assert params == {
        "user_id": user_id,
        "agent_id": agent_database_id("agent-a"),
        "agent_key": "agent-a",
    }


@pytest.mark.asyncio
async def test_update_index_state_returns_the_updated_private_record() -> None:
    user_id = uuid4()
    now = datetime(2026, 8, 25, tzinfo=UTC)
    row = {
        "user_id": user_id,
        "agent_key": "agent-a",
        "scope": "private",
        "workspace_key": f"user_workspaces/{user_id}/agent-a",
        "status": "active",
        "index_state": "ready",
        "index_version": 4,
        "created_at": now,
        "updated_at": now,
        "last_accessed_at": now,
    }
    session = RecordingSession([row])
    repository = AgentUserWorkspaceRepository(
        schema="qwenpaw_test",
        session_factory=session_factory(session),
        clock=lambda: now,
    )

    record = await repository.update_index_state(
        user_id=user_id,
        agent_key="agent-a",
        index_state=MemoryIndexState.READY,
        index_version=4,
    )

    assert record.index_state is MemoryIndexState.READY
    assert record.index_version == 4
    assert session.calls[0][1]["user_id"] == user_id


@pytest.mark.asyncio
async def test_update_status_preserves_user_and_agent_scope() -> None:
    user_id = uuid4()
    now = datetime(2026, 8, 25, tzinfo=UTC)
    row = {
        "user_id": user_id,
        "agent_key": "agent-a",
        "scope": "private",
        "workspace_key": f"user_workspaces/{user_id}/agent-a",
        "status": "access_revoked",
        "index_state": "ready",
        "index_version": 4,
        "created_at": now,
        "updated_at": now,
        "last_accessed_at": now,
    }
    session = RecordingSession([row])
    repository = AgentUserWorkspaceRepository(
        schema="qwenpaw_test",
        session_factory=session_factory(session),
        clock=lambda: now,
    )

    record = await repository.update_status(
        user_id=user_id,
        agent_key="agent-a",
        status=MemoryWorkspaceStatus.ACCESS_REVOKED,
    )

    assert record.status is MemoryWorkspaceStatus.ACCESS_REVOKED
    sql, params = session.calls[0]
    assert "user_id = :user_id" in sql
    assert "agent_id = :agent_id" in sql
    assert params["status"] == "access_revoked"
