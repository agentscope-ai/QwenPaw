# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from copaw.app.runner.session import SafeJSONSession


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
