# -*- coding: utf-8 -*-
"""Tests for explicit Scroll-history transcript migration."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner
from agentscope.message import Msg

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.serialize import msg_to_entries
from qwenpaw.agents.context.types import LogEntry
from qwenpaw.app.chats.models import ChatSpec, ChatsFile
from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_migration import (
    migrate_history_transcript,
)
from qwenpaw.cli import history_cmd
from qwenpaw.utils.io_utils import write_json_atomic


def _write_history(workspace: Path) -> None:
    store = HistoryStore(workspace / "history.db")
    store.append(
        session_id="session-1",
        agent_id="agent-1",
        dedup_key="user-1",
        entry=LogEntry(
            kind="model_turn",
            role="user",
            content="hello",
            created_at="2026-09-20T01:00:00+00:00",
        ),
    )
    store.append(
        session_id="session-1",
        agent_id="agent-1",
        dedup_key="assistant-1",
        entry=LogEntry(
            kind="model_turn",
            role="assistant",
            content="world",
            created_at="2026-09-20T01:01:00+00:00",
        ),
    )
    store.close()


def _write_chats(workspace: Path, *, copies: int = 1) -> None:
    chats = [
        ChatSpec(
            id=f"chat-{index}",
            session_id="session-1",
            user_id="user-1",
            channel="console",
        )
        for index in range(copies)
    ]
    write_json_atomic(
        workspace / "chats.json",
        ChatsFile(chats=chats).model_dump(mode="json"),
    )


def _persist_message(store: HistoryStore, message: Msg) -> None:
    for index, entry in enumerate(msg_to_entries(message)):
        dedup_key = (
            entry.tool_call_id if entry.kind == "tool_result" else message.id
        )
        store.append(
            session_id="session-1",
            agent_id="agent-1",
            dedup_key=dedup_key or f"{message.id}-{index}",
            entry=entry,
        )


def test_dry_run_does_not_create_transcript_database(tmp_path: Path) -> None:
    _write_history(tmp_path)
    _write_chats(tmp_path)

    result = migrate_history_transcript(
        tmp_path,
        agent_id="agent-1",
        dry_run=True,
    )

    assert result.eligible_sessions == 1
    assert result.imported_sessions == 0
    assert not (tmp_path / "transcript.db").exists()


def test_migration_is_partial_and_idempotent(tmp_path: Path) -> None:
    _write_history(tmp_path)
    _write_chats(tmp_path)

    first = migrate_history_transcript(
        tmp_path,
        agent_id="agent-1",
        dry_run=False,
    )
    second = migrate_history_transcript(
        tmp_path,
        agent_id="agent-1",
        dry_run=False,
    )
    store = TranscriptStore(tmp_path / "transcript.db", retention_days=0)
    page = store.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert first.imported_sessions == 1
    assert first.imported_turns == 1
    assert first.imported_messages == 2
    assert second.already_imported is True
    assert page is not None
    assert page.completeness == "partial"
    assert [item.content[0].text for item in page.messages] == [
        "hello",
        "world",
    ]
    store.close()


def test_migration_skips_ambiguous_session_mapping(tmp_path: Path) -> None:
    _write_history(tmp_path)
    _write_chats(tmp_path, copies=2)

    result = migrate_history_transcript(
        tmp_path,
        agent_id="agent-1",
        dry_run=False,
    )

    assert result.skipped_ambiguous == 1
    assert result.imported_sessions == 0


def test_migration_preserves_tool_result_order(tmp_path: Path) -> None:
    history = HistoryStore(tmp_path / "history.db")
    _persist_message(
        history,
        Msg(
            name="assistant",
            role="assistant",
            content=[
                {"type": "text", "text": "before"},
                {
                    "type": "tool_call",
                    "id": "call-1",
                    "name": "lookup",
                    "input": '{"query": "value"}',
                },
                {
                    "type": "tool_result",
                    "id": "call-1",
                    "name": "lookup",
                    "output": "result",
                },
                {"type": "text", "text": "after"},
            ],
        ),
    )
    history.close()
    _write_chats(tmp_path)

    migrate_history_transcript(
        tmp_path,
        agent_id="agent-1",
        dry_run=False,
    )
    transcript = TranscriptStore(
        tmp_path / "transcript.db",
        retention_days=0,
    )
    page = transcript.get_page(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )

    assert page is not None
    assert [message.type.value for message in page.messages] == [
        "message",
        "plugin_call",
        "plugin_call_output",
        "message",
    ]
    transcript.close()


def test_cli_resolves_agent_workspace_and_prints_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_history(tmp_path)
    _write_chats(tmp_path)
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "agent-1": SimpleNamespace(workspace_dir=str(tmp_path)),
            },
        ),
    )
    monkeypatch.setattr(history_cmd, "load_config", lambda: config)

    result = CliRunner().invoke(
        history_cmd.history_group,
        ["migrate-transcript", "--agent", "agent-1", "--dry-run"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["eligible_sessions"] == 1
    assert not (tmp_path / "transcript.db").exists()
