# -*- coding: utf-8 -*-
"""Tests for ``GET /chats/{chat_id}/messages`` (the scroll-back read path).

Exercises the endpoint through a real FastAPI ``TestClient`` + a real
``HistoryStore`` on a temp dir, with everything else (chat manager, session
store, task tracker) mocked — the same "mock the workspace, mount just the
router" pattern as ``tests/unit/app/routers/test_messages_router.py``. This
lets the acceptance scenario (200 messages, most evicted from the live
session JSON, scroll back to message 1) run fast and deterministically
without a live LLM/subprocess.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentscope.message import Msg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.serialize import msg_to_entries
from qwenpaw.app.chats.api import (
    get_chat_manager,
    get_session,
    get_workspace,
    router as chats_router,
)
from qwenpaw.app.chats.models import ChatSpec


def _persist_msg(store: HistoryStore, session_id: str, msg: Msg) -> None:
    for entry in msg_to_entries(msg):
        dedup_key = (
            entry.tool_call_id if entry.kind == "tool_result" else msg.id
        )
        store.append(session_id=session_id, dedup_key=dedup_key, entry=entry)


def _turn(i: int) -> tuple[Msg, Msg]:
    user = Msg(
        name="user",
        role="user",
        content=[{"type": "text", "text": f"question {i}"}],
    )
    assistant = Msg(
        name="assistant",
        role="assistant",
        content=[{"type": "text", "text": f"answer {i}"}],
    )
    return user, assistant


def _agent_state_dict(msgs: list[Msg], session_id: str) -> dict:
    return {
        "session_id": session_id,
        "summary": "",
        "context": [m.model_dump(mode="json") for m in msgs],
    }


@pytest.fixture
def workspace_mock(tmp_path: Path) -> Any:
    workspace = MagicMock(name="Workspace")
    workspace.workspace_dir = tmp_path
    workspace.config.backend = "qwenpaw"
    # Real AgentProfileConfig nests this under `.running`, not directly on
    # `.config` (unlike `backend`/`backend_settings`) — matches
    # `agents/context/scroll/sync.py`'s `agent_config.running.
    # light_context_config`. Mocking the wrong path here previously let a
    # `.running` typo in api.py ship undetected; only a live server caught it.
    workspace.config.running.light_context_config.strategy = "scroll"
    workspace.config.running.light_context_config.scroll_config.db_filename = (
        "history.db"
    )
    scroll_cfg = workspace.config.running.light_context_config.scroll_config
    scroll_cfg.history_retention_days = 30
    workspace.task_tracker.get_status = AsyncMock(return_value="idle")
    return workspace


@pytest.fixture
def app(workspace_mock) -> FastAPI:
    """Mount just the chats router, with its three workspace-resolving
    dependencies overridden straight to ``workspace_mock`` — bypasses the
    real ``get_agent_for_request``/config-profile lookup entirely, so no
    on-disk agent profile is needed for these tests."""
    application = FastAPI()
    application.include_router(chats_router, prefix="/api")
    application.dependency_overrides[get_workspace] = lambda: workspace_mock
    application.dependency_overrides[
        get_chat_manager
    ] = lambda: workspace_mock.chat_manager
    application.dependency_overrides[
        get_session
    ] = lambda: workspace_mock.session
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _wire_chat(
    workspace_mock,
    *,
    chat_id: str,
    session_id: str,
    live_msgs: list[Msg],
    scroll_extra: dict | None = None,
) -> None:
    chat_spec = ChatSpec(
        id=chat_id,
        session_id=session_id,
        user_id="u1",
        channel="console",
    )
    workspace_mock.chat_manager.get_chat = AsyncMock(return_value=chat_spec)
    agent_raw: dict = {"state": _agent_state_dict(live_msgs, session_id)}
    if scroll_extra is not None:
        agent_raw["scroll"] = scroll_extra
    workspace_mock.session.get_session_state_dict = AsyncMock(
        return_value={"agent": agent_raw},
    )


@pytest.mark.p0
def test_scroll_back_reaches_first_message_after_eviction(
    client,
    workspace_mock,
    tmp_path: Path,
):
    """The acceptance scenario: 200 turns persisted to history.db, only the
    last few survive in the live session JSON (simulating compaction) —
    scrolling back page by page must reach turn 0 with no gaps, no
    duplicates, and end in history_status="complete"."""
    session_id = "console:u1"
    store = HistoryStore(tmp_path / "history.db")
    try:
        all_msgs: list[Msg] = []
        for i in range(200):
            user, assistant = _turn(i)
            _persist_msg(store, session_id, user)
            _persist_msg(store, session_id, assistant)
            all_msgs.extend([user, assistant])
    finally:
        store.close()

    # Only the last 3 turns are still in the live session JSON — everything
    # older was evicted by compaction (but is still durable in history.db).
    live_msgs = all_msgs[-6:]
    _wire_chat(
        workspace_mock,
        chat_id="c1",
        session_id=session_id,
        live_msgs=live_msgs,
    )

    first = client.get(
        "/api/chats/c1/messages",
        params={"limit": 10},
        headers={"X-Agent-Id": "a1"},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["history_status"] == "available"
    assert body["has_more"] is True
    assert body["status"] == "idle"

    collected_texts: list[str] = []
    seen_ids: set[str] = set()
    for message in body["messages"]:
        seen_ids.add(message["id"])
        for content in message["content"]:
            if content.get("text"):
                collected_texts.append(content["text"])

    cursor = body["next_cursor"]
    history_status = body["history_status"]
    pages = 0
    while history_status == "available":
        pages += 1
        assert pages < 100, "pagination did not terminate"
        page = client.get(
            "/api/chats/c1/messages",
            params={"limit": 10, "before_seq": cursor},
            headers={"X-Agent-Id": "a1"},
        )
        assert page.status_code == 200, page.text
        page_body = page.json()
        for message in page_body["messages"]:
            assert message["id"] not in seen_ids, "duplicate message id"
            seen_ids.add(message["id"])
            for content in message["content"]:
                if content.get("text"):
                    collected_texts.append(content["text"])
        history_status = page_body["history_status"]
        cursor = page_body["next_cursor"]

    assert history_status == "complete"
    # The very first thing ever sent must be reachable, and pages come back
    # oldest-last (we paginate backward) but each page internally ascending.
    assert "question 0" in collected_texts
    assert collected_texts.index("question 0") < collected_texts.index(
        "answer 0",
    )
    assert "answer 199" in collected_texts[:6]
    assert len(collected_texts) == 400


def test_non_scroll_mode_reports_unavailable(client, workspace_mock):
    workspace_mock.config.running.light_context_config.strategy = "native"
    user, assistant = _turn(0)
    _wire_chat(
        workspace_mock,
        chat_id="c1",
        session_id="console:u1",
        live_msgs=[user, assistant],
    )

    resp = client.get(
        "/api/chats/c1/messages",
        headers={"X-Agent-Id": "a1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["history_status"] == "unavailable"
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    # Fallback safety window still renders the live messages — the user
    # doesn't lose what's already in the session JSON.
    assert len(body["messages"]) == 2


def test_missing_history_db_reports_degraded_not_complete(
    client,
    workspace_mock,
):
    """Scroll mode expects a history db; if it's simply not there (never
    created, or wiped), that must never masquerade as "reached the end"."""
    user, assistant = _turn(0)
    _wire_chat(
        workspace_mock,
        chat_id="c1",
        session_id="console:u1",
        live_msgs=[user, assistant],
    )
    # workspace_mock.workspace_dir points at an empty tmp_path — no
    # history.db file exists there.

    resp = client.get(
        "/api/chats/c1/messages",
        headers={"X-Agent-Id": "a1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["history_status"] == "degraded"
    assert body["fallback_limited"] is True
    assert body["has_more"] is False


def test_running_status_is_passed_through(client, workspace_mock):
    workspace_mock.task_tracker.get_status = AsyncMock(return_value="running")
    user, assistant = _turn(0)
    _wire_chat(
        workspace_mock,
        chat_id="c1",
        session_id="console:u1",
        live_msgs=[user, assistant],
    )

    resp = client.get(
        "/api/chats/c1/messages",
        headers={"X-Agent-Id": "a1"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_expired_when_index_claims_more_than_db_has(
    client,
    workspace_mock,
    tmp_path: Path,
):
    """An eviction index claiming archived content older than anything left
    in history.db means an old retention policy purged real conversation
    turns — the page-level status must say so, not "complete"."""
    session_id = "console:u1"
    user0, assistant0 = _turn(0)
    user1, assistant1 = _turn(1)
    store = HistoryStore(tmp_path / "history.db")
    try:
        _persist_msg(store, session_id, user0)  # seq 1
        _persist_msg(store, session_id, assistant0)  # seq 2
        _persist_msg(store, session_id, user1)  # seq 3
        _persist_msg(store, session_id, assistant1)  # seq 4
        # Simulate an old retention policy that already purged turn 0's
        # rows — the eviction index still remembers archiving them.
        with store._lock, store._conn:  # pylint: disable=protected-access
            store._conn.execute(
                "DELETE FROM conversation_history WHERE seq IN (1, 2)",
            )
    finally:
        store.close()

    _wire_chat(
        workspace_mock,
        chat_id="c1",
        session_id=session_id,
        live_msgs=[user1, assistant1],
        scroll_extra={
            "index": {
                "session_id": session_id,
                "agent_id": None,
                "tiers": [
                    [
                        {
                            "seq_lo": 1,
                            "seq_hi": 2,
                            "lines": [[1, 2, "old turn", "old turn"]],
                        },
                    ],
                ],
            },
        },
    )

    resp = client.get(
        "/api/chats/c1/messages",
        headers={"X-Agent-Id": "a1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["history_status"] == "expired"
    assert body["has_more"] is False
