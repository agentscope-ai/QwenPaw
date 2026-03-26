# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from copaw.app.runner.session import (
    SafeJSONSession,
    normalize_in_memory_memory_state,
    restore_in_memory_memory,
)


async def test_get_session_state_dict_returns_empty_for_blank_file(
    tmp_path,
) -> None:
    session = SafeJSONSession(save_dir=str(tmp_path))
    session_path = Path(session._get_save_path("session-1", user_id="user-1"))
    session_path.write_text("", encoding="utf-8")

    state = await session.get_session_state_dict("session-1", user_id="user-1")

    assert state == {}


async def test_get_session_state_dict_returns_empty_for_invalid_json(
    tmp_path,
) -> None:
    session = SafeJSONSession(save_dir=str(tmp_path))
    session_path = Path(session._get_save_path("session-2", user_id="user-2"))
    session_path.write_text("{invalid", encoding="utf-8")

    state = await session.get_session_state_dict("session-2", user_id="user-2")

    assert state == {}


async def test_update_session_state_recovers_invalid_json_file(tmp_path) -> None:
    session = SafeJSONSession(save_dir=str(tmp_path))
    session_path = Path(session._get_save_path("session-3", user_id="user-3"))
    session_path.write_text("{invalid", encoding="utf-8")

    await session.update_session_state(
        session_id="session-3",
        user_id="user-3",
        key="agent.memory",
        value=[{"role": "assistant", "content": "ok"}],
    )

    persisted = json.loads(session_path.read_text(encoding="utf-8"))

    assert persisted == {
        "agent": {
            "memory": [{"role": "assistant", "content": "ok"}],
        },
    }


def test_normalize_in_memory_memory_state_accepts_legacy_list() -> None:
    normalized = normalize_in_memory_memory_state(
        [{"role": "assistant", "content": "ok"}],
    )

    assert normalized["_compressed_summary"] == ""
    assert len(normalized["content"]) == 1
    assert normalized["content"][0]["role"] == "assistant"
    assert normalized["content"][0]["content"] == "ok"
    assert normalized["content"][0]["name"] == "assistant"


def test_normalize_in_memory_memory_state_filters_invalid_items() -> None:
    normalized = normalize_in_memory_memory_state(
        {
            "_compressed_summary": "summary",
            "content": [
                [{"role": "assistant", "content": "ok"}, ["keep"]],
                {"role": "assistant"},
                "bad-item",
            ],
        },
    )

    assert normalized["_compressed_summary"] == "summary"
    assert len(normalized["content"]) == 1
    assert normalized["content"][0][0]["role"] == "assistant"
    assert normalized["content"][0][0]["content"] == "ok"
    assert normalized["content"][0][0]["name"] == "assistant"
    assert normalized["content"][0][1] == ["keep"]


async def test_restore_in_memory_memory_reads_legacy_list(tmp_path) -> None:
    session = SafeJSONSession(save_dir=str(tmp_path))
    session_path = Path(session._get_save_path("session-4", user_id="user-4"))
    session_path.write_text(
        json.dumps(
            {
                "agent": {
                    "memory": [{"role": "assistant", "content": "ok"}],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    state = await session.get_session_state_dict("session-4", user_id="user-4")
    memory = restore_in_memory_memory(state["agent"]["memory"])
    messages = await memory.get_memory()

    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].content == "ok"
