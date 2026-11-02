# -*- coding: utf-8 -*-
"""Regression tests for context identity at completed turn boundaries."""

import asyncio
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest
from agentscope.state import AgentState

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.context_revisions import read_revision_state
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.app.chats.transcript_recorder import TranscriptRecorder
from qwenpaw.app.chats.session import DatabaseSession
from qwenpaw.hooks.session.session_hook import SessionSaveHook
from qwenpaw._session_signals import SESSION_SAVE_SUCCEEDED_KEY
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.runtime.builtin_commands import _save_agent_state
from qwenpaw.schemas import AgentRequest, AgentResponse

IDENTITY = {
    "session_id": "session",
    "user_id": "user",
    "channel": "console",
}


def _saved_context(path, turn_id) -> dict[str, Any] | None:
    store = TranscriptStore(path)
    try:
        snapshot = store.read_turn_context(**IDENTITY, turn_id=turn_id)
        return snapshot.state if snapshot else None
    finally:
        store.close()


def test_turn_context_survives_clear_and_later_saves(tmp_path):
    path = tmp_path / "session.db"
    store = TranscriptStore(path)
    try:
        store.start_turn(**IDENTITY, turn_id="first")
        store.write_runtime_state(
            **IDENTITY,
            turn_id="first",
            state={"agent": {"summary": "first context"}},
        )
        assert _saved_context(path, "first") is None
        store.finish_turn(
            session_id="session",
            turn_id="first",
            status="completed",
        )
        store.write_runtime_state(
            **IDENTITY,
            state={"agent": {}},
            reset_context=True,
        )
        store.start_turn(**IDENTITY, turn_id="second")
        store.write_runtime_state(
            **IDENTITY,
            turn_id="second",
            state={"agent": {"new": True}},
        )
        store.finish_turn(
            session_id="session",
            turn_id="second",
            status="completed",
        )
        assert _saved_context(path, "first") == {
            "agent": {"summary": "first context"},
        }
        assert _saved_context(path, "second") == {"agent": {"new": True}}
    finally:
        store.close()


def test_missing_turn_snapshot_does_not_reuse_current_context(tmp_path):
    path = tmp_path / "session.db"
    store = TranscriptStore(path)
    try:
        store.write_runtime_state(**IDENTITY, state={"agent": {"old": True}})
        store.start_turn(**IDENTITY, turn_id="unsaved")
        store.finish_turn(
            session_id="session",
            turn_id="unsaved",
            status="completed",
        )
        assert _saved_context(path, "unsaved") is None
        with pytest.raises(ValueError, match="running turn"):
            store.write_runtime_state(
                **IDENTITY,
                turn_id="unsaved",
                state={"agent": {}},
            )
        snapshot = store.read_runtime_state(**IDENTITY)
        assert snapshot.state == {"agent": {"old": True}}
    finally:
        store.close()


def test_context_prefixes_and_same_turn_revisions_are_append_only(tmp_path):
    path = tmp_path / "session.db"
    store = TranscriptStore(path)
    try:
        first = {"role": "user", "content": "first"}
        second = {"role": "assistant", "content": "second"}
        store.start_turn(**IDENTITY, turn_id="one")
        store.write_runtime_state(
            **IDENTITY,
            turn_id="one",
            state={"agent": {"state": {"context": [first]}}},
        )
        store.write_runtime_state(
            **IDENTITY,
            turn_id="one",
            state={"agent": {"state": {"context": [first, second]}}},
        )
        store.finish_turn(
            session_id="session",
            turn_id="one",
            status="completed",
        )
        with sqlite3.connect(path) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM context_revisions",
                ).fetchone()[0]
                == 2
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM context_nodes",
                ).fetchone()[0]
                == 2
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM content_objects "
                    "WHERE codec = 'context-item-v1'",
                ).fetchone()[0]
                == 2
            )
        assert _saved_context(path, "one") == {
            "agent": {"state": {"context": [first, second]}},
        }
    finally:
        store.close()


def test_runtime_revision_kinds_describe_the_actual_change(tmp_path):
    path = tmp_path / "session.db"
    store = TranscriptStore(path)
    try:
        store.write_runtime_state(**IDENTITY, state={"agent": {}})
        store.update_runtime_state(
            session_id="session",
            path=["agent", "mode"],
            value="coding",
        )
        store.set_current_usage(
            session_id="session",
            usage={"total_tokens": 1},
            context_usage={"estimated_tokens": 1},
        )
        with sqlite3.connect(path) as connection:
            usage_revision = connection.execute(
                "SELECT revision_id FROM context_revisions "
                "WHERE kind = 'usage_update'",
            ).fetchone()[0]
            assert read_revision_state(
                connection,
                session_id="session",
                revision_id=usage_revision,
            ) == {"agent": {"mode": "coding"}}
        store.write_runtime_state(
            **IDENTITY,
            state={"agent": {}},
            reset_context=True,
        )
        store.replace_runtime_state(
            **IDENTITY,
            state={"agent": {"restored": True}},
            context_generation=0,
            current_usage=None,
        )
        with sqlite3.connect(path) as connection:
            kinds = connection.execute(
                "SELECT kind FROM context_revisions ORDER BY rowid",
            ).fetchall()
        assert [row[0] for row in kinds] == [
            "snapshot",
            "state_update",
            "usage_update",
            "clear",
            "restore",
        ]
        # Later resets and restores must not change the usage-only snapshot.
        store.rebuild_projections()
        with sqlite3.connect(path) as connection:
            assert read_revision_state(
                connection,
                session_id="session",
                revision_id=usage_revision,
            ) == {"agent": {"mode": "coding"}}
        assert store.read_runtime_state(**IDENTITY).state == {
            "agent": {"restored": True},
        }
    finally:
        store.close()


def test_unsupported_development_schema_is_not_modified(tmp_path):
    path = tmp_path / "session.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE old_layout (value TEXT)")
        connection.execute("INSERT INTO old_layout VALUES ('preserve')")
    with pytest.raises(ValueError, match="unsupported conversation"):
        TranscriptStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM old_layout").fetchone() == (
            "preserve",
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'",
            ).fetchone()[0]
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    ["completed", "cancelled", "failed", "clear"],
)
async def test_real_session_hook_records_context_before_terminal(
    tmp_path,
    outcome,
):
    catalog = TranscriptCatalog(tmp_path)
    session = DatabaseSession(
        catalog=catalog,
        legacy_save_dir=str(tmp_path / "sessions"),
    )
    request = AgentRequest(**IDENTITY, input=[])
    recorder = TranscriptRecorder(store=catalog, request=request)
    ctx = SimpleNamespace(
        request=request,
        workspace=SimpleNamespace(session=session),
        agent=SimpleNamespace(state_dict=lambda: {"summary": "saved"}),
        session_id="session",
        mode_state={},
        extras={},
    )
    try:
        await recorder.start()
        if outcome == "clear":
            await _save_agent_state(ctx, AgentState(), reset_context=True)
        elif outcome in {"cancelled", "failed"}:
            ctx.error = (
                asyncio.CancelledError()
                if outcome == "cancelled"
                else RuntimeError("interrupted")
            )
            runtime = Runtime(workspace=ctx.workspace, app_services=None)
            # pylint: disable-next=protected-access
            await runtime._try_save_on_cancel(ctx)
        else:
            await SessionSaveHook().run(ctx)
            assert ctx.extras[SESSION_SAVE_SUCCEEDED_KEY]
        response = AgentResponse(
            status="completed" if outcome == "clear" else outcome,
        )
        await recorder.observe(response)
        path = next((tmp_path / "transcripts").rglob("*.db"))
        state = _saved_context(
            path,
            request.request_context["_qwenpaw_transcript_turn_id"],
        )
        assert isinstance(state, dict)
        agent = state.get("agent")
        assert isinstance(agent, dict)
        if outcome == "clear":
            agent_state = agent.get("state")
            assert isinstance(agent_state, dict)
            assert agent_state.get("context") == []
        else:
            assert agent.get("summary") == "saved"
        assert catalog.clone_session(
            source_session_id="session",
            source_user_id="user",
            source_channel="console",
            target_session_id="fork",
            target_user_id="user",
            target_channel="console",
        )
        target = {**IDENTITY, "session_id": "fork"}
        assert catalog.read_runtime_state(**target).state == state
    finally:
        catalog.close()
