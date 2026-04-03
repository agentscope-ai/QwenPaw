# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from copaw.app.runner.session import SafeJSONSession


class _FakeStateful:
    def __init__(self, payload):
        self.payload = payload

    def state_dict(self):
        return self.payload


class _FakeLoader:
    def __init__(self):
        self.loaded = None

    def load_state_dict(self, state):
        self.loaded = state


@pytest.mark.asyncio
async def test_save_session_state_writes_valid_json_atomically(
    tmp_path: Path,
):
    session = SafeJSONSession(save_dir=str(tmp_path))
    agent = _FakeStateful({"memory": {"content": ["hello"]}})

    await session.save_session_state(
        "session-1",
        user_id="user-1",
        agent=agent,
    )

    saved = tmp_path / "user-1_session-1.json"
    assert saved.exists()
    assert '"content": ["hello"]' in saved.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
async def test_get_session_state_dict_returns_empty_dict_for_malformed_json(
    tmp_path: Path,
):
    session = SafeJSONSession(save_dir=str(tmp_path))
    broken = tmp_path / "user-1_session-1.json"
    broken.write_text("", encoding="utf-8")

    state = await session.get_session_state_dict(
        "session-1",
        user_id="user-1",
    )

    assert state == {}


@pytest.mark.asyncio
async def test_load_session_state_skips_malformed_json_when_allowed(
    tmp_path: Path,
):
    session = SafeJSONSession(save_dir=str(tmp_path))
    broken = tmp_path / "user-1_session-1.json"
    broken.write_text("{", encoding="utf-8")
    loader = _FakeLoader()

    await session.load_session_state(
        "session-1",
        user_id="user-1",
        allow_not_exist=True,
        agent=loader,
    )

    assert loader.loaded is None


@pytest.mark.asyncio
async def test_update_session_state_recovers_from_malformed_json_when_allowed(
    tmp_path: Path,
):
    session = SafeJSONSession(save_dir=str(tmp_path))
    broken = tmp_path / "user-1_session-1.json"
    broken.write_text("{", encoding="utf-8")

    await session.update_session_state(
        "session-1",
        key="agent.memory",
        value={"content": ["fixed"]},
        user_id="user-1",
        create_if_not_exist=True,
    )

    state = await session.get_session_state_dict(
        "session-1",
        user_id="user-1",
    )
    assert state == {"agent": {"memory": {"content": ["fixed"]}}}
