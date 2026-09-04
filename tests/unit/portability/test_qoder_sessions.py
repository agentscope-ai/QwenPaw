# -*- coding: utf-8 -*-
"""Regression tests for current Qoder IDE session discovery."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.portability.providers.qoder import QoderMigrationProvider
from qwenpaw.portability.providers.qoder_sessions import (
    QoderIndex,
    QoderTranscript,
    read_qoder_transcript,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _message(
    session_id: str,
    message_type: str,
    content,
    *,
    cwd: str,
    timestamp: str,
) -> dict:
    return {
        "type": message_type,
        "uuid": f"{message_type}-{timestamp}",
        "sessionId": session_id,
        "timestamp": timestamp,
        "cwd": cwd,
        "message": {"role": message_type, "content": content},
    }


def _create_index(user_data: Path, editor_id: str, quest_id: str) -> None:
    database = user_data / "globalStorage" / "state.vscdb"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, "
            "value BLOB)",
        )
        connection.executemany(
            "INSERT INTO ItemTable(key, value) VALUES (?, ?)",
            [
                (
                    "lingma.chat.localHistory.workspace-1",
                    json.dumps(
                        [
                            {
                                "sessionId": editor_id,
                                "title": "Editor history title",
                                "timestamp": 1_700_000_000_000,
                            },
                        ],
                    ),
                ),
                (
                    "lingma.chat.localHistory.agents.quest",
                    json.dumps(
                        [
                            {
                                "sessionId": quest_id,
                                "title": "Quest history title",
                                "timestamp": 1_700_000_100_000,
                            },
                        ],
                    ),
                ),
                (f"chat.chatMode.session.{editor_id}", "agent"),
                (f"chat.chatMode.session.{quest_id}", "plan"),
                (
                    "aicoding.questTaskListSnapshot",
                    json.dumps(
                        {
                            "folders": [
                                {
                                    "tasks": [
                                        {
                                            "id": "quest-task-1",
                                            "name": "Quest snapshot title",
                                            "status": "completed",
                                            "questType": "agent",
                                            "executionMode": "plan",
                                            "designSessionId": "design-1",
                                            "executionSessionId": quest_id,
                                            "filePath": "/projects/quest",
                                        },
                                    ],
                                },
                            ],
                        },
                    ),
                ),
            ],
        )


def test_transcript_reader_rejects_oversized_jsonl_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.portability.providers import qoder_sessions

    path = tmp_path / "session.jsonl"
    path.write_text('{"message":"too long"}\n', encoding="utf-8")
    monkeypatch.setattr(qoder_sessions, "_MAX_TRANSCRIPT_LINE_BYTES", 8)

    session, warnings, internal = read_qoder_transcript(
        QoderTranscript("session", path, "ide", datetime.now().astimezone()),
        QoderIndex(),
    )

    assert session is None
    assert internal is False
    assert "line 1 is too large" in warnings[0]


@pytest.mark.asyncio
async def test_provider_filters_internal_agent_tool_only_traces(
    tmp_path: Path,
) -> None:
    qoder_home = tmp_path / ".qoder"
    transcript = qoder_home / "projects" / "-project" / "transcript"
    worker_id = "22222222-2222-4222-8222-222222222222"
    visible_id = "33333333-3333-4333-8333-333333333333"
    _write_jsonl(
        transcript / f"{worker_id}.jsonl",
        [
            _message(
                worker_id,
                "assistant",
                [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Bash",
                        "input": {"command": "pwd"},
                    },
                ],
                cwd="/project",
                timestamp="2026-08-04T01:00:00Z",
            ),
            _message(
                worker_id,
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": "/project",
                    },
                ],
                cwd="/project",
                timestamp="2026-08-04T01:00:01Z",
            ),
        ],
    )
    _write_jsonl(
        transcript / f"{visible_id}.jsonl",
        [
            _message(
                visible_id,
                "user",
                "Visible conversation",
                cwd="/project",
                timestamp="2026-08-03T01:00:00Z",
            ),
        ],
    )

    inventory = await QoderMigrationProvider(
        SimpleNamespace(workspace_dir=tmp_path),
        qoder_home=qoder_home,
        qoder_user_data=tmp_path / "missing-user-data",
    ).inventory(limit=1)

    assert [item.source_id for item in inventory.sessions] == [visible_id]
    assert inventory.ignored_session_ids == [worker_id]
    assert any("internal Agent/Experts" in item for item in inventory.warnings)
