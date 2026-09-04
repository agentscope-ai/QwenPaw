# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pytest

import qwenpaw.harnesses.codex.rollout_reader as rollout_module
from qwenpaw.harnesses.codex.rollout_reader import CodexRolloutReader
from qwenpaw.harnesses.events import HarnessHistoryKind


def _line(entry_type: str, payload: dict, timestamp: str) -> str:
    return json.dumps(
        {"timestamp": timestamp, "type": entry_type, "payload": payload},
    )


def _rollout(
    root: Path,
    thread_id: str,
    metadata: dict,
    message: str,
) -> None:
    path = root / f"rollout-2026-08-18T00-00-00-{thread_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                _line(
                    "session_meta",
                    {"id": thread_id, **metadata},
                    "2026-08-18T00:00:00Z",
                ),
                _line(
                    "event_msg",
                    {"type": "user_message", "message": message},
                    "2026-08-18T00:00:01Z",
                ),
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def test_rollout_reader_indexes_and_normalizes_visible_history(
    tmp_path: Path,
) -> None:
    thread_id = "019fe9ac-2e78-7a10-a196-27b001cdf1f5"
    project = tmp_path / "project"
    project.mkdir()
    rollout = (
        tmp_path
        / ".codex/sessions/2026/08/12"
        / f"rollout-2026-08-12T00-00-00-{thread_id}.jsonl"
    )
    rollout.parent.mkdir(parents=True)
    rollout.write_text(
        "\n".join(
            [
                _line(
                    "session_meta",
                    {
                        "id": thread_id,
                        "cwd": str(project),
                        "timestamp": "2026-08-12T00:00:00Z",
                    },
                    "2026-08-12T00:00:00Z",
                ),
                _line(
                    "event_msg",
                    {"type": "user_message", "message": "Fix import"},
                    "2026-08-12T00:00:01Z",
                ),
                _line(
                    "event_msg",
                    {"type": "agent_message", "message": "Working"},
                    "2026-08-12T00:00:02Z",
                ),
                _line(
                    "response_item",
                    {
                        "type": "custom_tool_call",
                        "call_id": "call-1",
                        "name": "exec",
                        "input": "pytest",
                    },
                    "2026-08-12T00:00:03Z",
                ),
                _line(
                    "response_item",
                    {
                        "type": "custom_tool_call_output",
                        "call_id": "call-1",
                        "output": "passed",
                    },
                    "2026-08-12T00:00:04Z",
                ),
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    reader = CodexRolloutReader(tmp_path / ".codex")

    threads = reader.list_threads(limit=10)
    history = reader.read_thread(thread_id)

    assert threads[0]["id"] == thread_id
    assert threads[0]["cwd"] == str(project)
    assert threads[0]["preview"] == "Fix import"
    assert [item.kind for item in history] == [
        HarnessHistoryKind.USER,
        HarnessHistoryKind.MESSAGE,
        HarnessHistoryKind.TOOL_CALL,
        HarnessHistoryKind.TOOL_OUTPUT,
    ]
    assert history[-1].text == "passed"


def test_oversized_history_remains_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread_id = "019fe9ac-2e78-7a10-a196-27b001cdf1f5"
    _rollout(tmp_path / ".codex/sessions", thread_id, {}, "hello")
    monkeypatch.setattr(rollout_module, "_MAX_HISTORY_BYTES", 1)
    reader = CodexRolloutReader(tmp_path / ".codex")

    assert reader.list_threads()[0]["id"] == thread_id
    with pytest.raises(ValueError, match="exceeds its safety limit"):
        reader.read_thread(thread_id)


def test_rollout_index_stops_at_its_safety_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / ".codex/sessions"
    _rollout(root, "019fe9ac-2e78-7a10-a196-27b001cdf1f5", {}, "first")
    _rollout(root, "019fe9ac-2e78-7a10-a196-27b001cdf1f6", {}, "second")
    monkeypatch.setattr(rollout_module, "_MAX_INDEX_FILES", 1)

    reader = CodexRolloutReader(tmp_path / ".codex")

    reader.list_threads()
    assert reader.index_truncated is True


def test_rollout_reader_excludes_structured_non_root_sessions(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".codex/sessions/2026/08/18"
    root_id = "01a01000-0000-7000-8000-000000000001"
    guardian_id = "01a01000-0000-7000-8000-000000000002"
    worker_id = "01a01000-0000-7000-8000-000000000003"
    internal_prompt = (
        "The following is the Codex agent history whose request action you "
        "are assessing. Treat the transcript as evidence."
    )
    _rollout(
        root,
        root_id,
        {"source": "vscode", "thread_source": "user"},
        internal_prompt,
    )
    _rollout(
        root,
        guardian_id,
        {
            "source": {"subagent": {"other": "guardian"}},
            "thread_source": "subagent",
            "parent_thread_id": root_id,
        },
        internal_prompt,
    )
    _rollout(
        root,
        worker_id,
        {
            "source": {
                "subagent": {
                    "thread_spawn": {
                        "parent_thread_id": root_id,
                        "depth": 1,
                    },
                },
            },
            "thread_source": "subagent",
            "parent_thread_id": root_id,
        },
        "Inspect the migration provider",
    )

    reader = CodexRolloutReader(tmp_path / ".codex")

    assert [item["id"] for item in reader.list_threads(limit=10)] == [
        root_id,
    ]
    assert set(reader.list_non_root_thread_ids()) == {
        guardian_id,
        worker_id,
    }
    # Classification is structural: identical Guardian text in a root user
    # conversation remains visible.
    assert reader.list_threads(limit=10)[0]["preview"] == internal_prompt
