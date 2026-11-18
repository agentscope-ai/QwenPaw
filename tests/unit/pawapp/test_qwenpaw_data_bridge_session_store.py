# -*- coding: utf-8 -*-
"""Bridge session store and slash command tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _store(bridge_session_store, tmp_path):
    return bridge_session_store.BridgeSessionStore(
        path=tmp_path / "bridge_sessions.json",
    )


def test_store_roundtrip_and_defaults(
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)

    state = store.get("console:alice")
    assert state.active is False
    assert state.engine_session_id == ""

    store.update(
        "console:alice",
        active=True,
        engine_session_id="ses_1",
        datasource_id="ds_a",
    )

    # Fresh instance reads from disk
    reloaded = _store(bridge_session_store, tmp_path).get("console:alice")
    assert reloaded.active is True
    assert reloaded.engine_session_id == "ses_1"
    assert reloaded.datasource_id == "ds_a"


def test_store_survives_corrupt_file(
    bridge_session_store,
    tmp_path,
) -> None:
    path = tmp_path / "bridge_sessions.json"
    path.write_text("{not json", encoding="utf-8")
    store = bridge_session_store.BridgeSessionStore(path=path)

    assert store.get("console:alice").active is False
    store.update("console:alice", active=True)
    assert store.get("console:alice").active is True


def test_store_isolates_sessions(bridge_session_store, tmp_path) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update("console:alice", active=True)
    assert store.get("dingtalk:bob").active is False


def test_failed_write_keeps_cache_and_disk_at_prior_state(
    bridge_session_store,
    monkeypatch,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update("console:alice", active=True)
    path_type = type(store.path)
    original_replace = path_type.replace

    def fail_temp_replace(path, target):
        if path == store.path.with_suffix(".tmp"):
            raise OSError("simulated replacement failure")
        return original_replace(path, target)

    monkeypatch.setattr(path_type, "replace", fail_temp_replace)

    result = store.update("console:alice", active=False)

    assert result.active is True
    assert store.get("console:alice").active is True
    reloaded = _store(bridge_session_store, tmp_path)
    assert reloaded.get("console:alice").active is True


# ---------------------------------------------------------------- commands


def _ctx(session_id: str = "console:alice") -> SimpleNamespace:
    return SimpleNamespace(session_id=session_id)


def _text(msg) -> str:
    return msg.get_text_content() or ""


@pytest.mark.asyncio
async def test_data_command_on_off_status(
    bridge_commands,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    command = bridge_commands.make_data_command(store)

    on_reply = await command(_ctx(), "on")
    assert "已开启" in _text(on_reply)
    assert store.get("console:alice").active is True

    status_reply = await command(_ctx(), "status")
    assert "已开启" in _text(status_reply)

    off_reply = await command(_ctx(), "off")
    assert "退出" in _text(off_reply)
    assert store.get("console:alice").active is False


@pytest.mark.asyncio
async def test_data_off_clears_pending_state(
    bridge_commands,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update(
        "console:alice",
        active=True,
        pending_clarification={"chat_id": "c1"},
        pending_datasource_choice=[{"id": "ds", "name": "DS"}],
    )
    command = bridge_commands.make_data_command(store)

    await command(_ctx(), "off")

    state = store.get("console:alice")
    assert state.pending_clarification is None
    assert state.pending_datasource_choice is None


@pytest.mark.asyncio
async def test_datasource_command_lists_options(
    bridge_commands,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update("console:alice", active=True)

    class Client:
        async def list_datasources(self):
            return [
                {"id": "ds_a", "name": "Demo PG"},
                {"id": "ds_b", "name": "DuckDB"},
            ]

    command = bridge_commands.make_datasource_command(store, Client())
    reply = await command(_ctx(), "")

    text = _text(reply)
    assert "1. Demo PG" in text
    assert "2. DuckDB" in text
    assert store.get("console:alice").pending_datasource_choice == [
        {"id": "ds_a", "name": "Demo PG"},
        {"id": "ds_b", "name": "DuckDB"},
    ]


@pytest.mark.asyncio
async def test_datasource_command_requires_data_mode(
    bridge_commands,
    bridge_session_store,
    tmp_path,
) -> None:
    store = _store(bridge_session_store, tmp_path)

    class Client:
        async def list_datasources(self):
            raise AssertionError("must not be called")

    command = bridge_commands.make_datasource_command(store, Client())
    reply = await command(_ctx(), "")
    assert "/data on" in _text(reply)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(400, "稍后重试"), (500, "不可用")],
)
async def test_datasource_command_handles_normalized_http_errors(
    bridge_commands,
    bridge_session_store,
    bridge,
    tmp_path,
    status_code: int,
    expected: str,
) -> None:
    store = _store(bridge_session_store, tmp_path)
    store.update("console:alice", active=True)

    class Client:
        async def list_datasources(self):
            raise bridge.EngineResponseError(status_code, "secret response")

    command = bridge_commands.make_datasource_command(store, Client())
    reply = await command(_ctx(), "")

    assert expected in _text(reply)
    assert "secret" not in _text(reply)
