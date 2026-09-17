# -*- coding: utf-8 -*-
"""Tests for persisting the Agent model-mode governance summary."""

from contextlib import asynccontextmanager

import pytest

from qwenpaw.access.agent_repository import (
    PostgresAgentRepository,
    agent_database_id,
)


class _Session:
    def __init__(self, rowcount: int = 1) -> None:
        self.calls = []
        self.rowcount = rowcount

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return type("Result", (), {"rowcount": self.rowcount})()


@pytest.mark.asyncio
async def test_update_model_mode_writes_only_governance_summary() -> None:
    session = _Session()

    @asynccontextmanager
    async def session_factory():
        yield session

    repository = PostgresAgentRepository(
        schema="qwenpaw_test",
        session_factory=session_factory,
    )

    changed = await repository.update_model_mode("agent-1", "explicit")

    assert changed is True
    assert len(session.calls) == 1
    sql, params = session.calls[0]
    assert "default_model_mode = :mode" in sql
    assert "default_model_mode IS DISTINCT FROM :mode" in sql
    assert params == {
        "id": agent_database_id("agent-1"),
        "mode": "explicit",
    }


@pytest.mark.asyncio
async def test_update_model_mode_reports_unchanged_summary() -> None:
    session = _Session(rowcount=0)

    @asynccontextmanager
    async def session_factory():
        yield session

    repository = PostgresAgentRepository(
        schema="qwenpaw_test",
        session_factory=session_factory,
    )

    changed = await repository.update_model_mode("agent-1", "inherited")

    assert changed is False
