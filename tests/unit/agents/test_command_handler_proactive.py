# -*- coding: utf-8 -*-
"""``/proactive`` presents ReMe's agenda instead of running a side agent."""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.agents.command_handler import (
    _PROACTIVE_DEFAULT_IDLE_MINUTES,
    CommandHandler,
)
from qwenpaw.agents.memory.proactive.proactive_responder import (
    ProactiveSettings,
)


@pytest.fixture(autouse=True)
def agent_config(monkeypatch):
    """Pin the agent language so the bilingual copy is predictable."""

    def _load(_agent_id: str):
        return SimpleNamespace(language="en")

    monkeypatch.setattr(
        "qwenpaw.agents.command_handler.load_agent_config",
        _load,
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "agent-1",
    )


@pytest.fixture
def calls(monkeypatch):
    """Record every proactive side effect the command handler triggers."""
    record: dict[str, object] = {
        "enabled": [],
        "disabled": 0,
        "receipt": "**Proactive agenda** (2026-10-11, 1 item(s))",
        "queued": True,
    }

    def _enable(session_id, minutes, workspace=None):
        record["enabled"].append((session_id, minutes, workspace))
        return f"watching after {minutes} idle minutes"

    async def _disable(_session_id):
        record["disabled"] += 1
        return "disabled"

    async def _receipt(**kwargs):
        record["receipt_kwargs"] = kwargs
        return record["receipt"]

    def _rebuild(**kwargs):
        record["rebuild_kwargs"] = kwargs
        return bool(record["queued"])

    monkeypatch.setattr(
        "qwenpaw.agents.memory.enable_proactive_for_session",
        _enable,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.memory.disable_proactive_for_session",
        _disable,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.memory.present_agenda_receipt",
        _receipt,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.memory.start_agenda_rebuild",
        _rebuild,
    )
    return record


def _settings(**overrides) -> ProactiveSettings:
    base = {
        "language": "en",
        "enabled": True,
        "inbox_enabled": True,
        "max_items": 3,
        "cron_max_items": 0,
        "cooldown_days": 3,
        "refresh_min_interval_minutes": 0,
        "metadata_dir": "mem_metadata",
    }
    base.update(overrides)
    return ProactiveSettings(**base)


@pytest.fixture
def settings(monkeypatch):
    resolved = _settings()

    async def _load(_agent_id: str) -> ProactiveSettings:
        return resolved

    monkeypatch.setattr(
        "qwenpaw.agents.memory.load_proactive_settings",
        _load,
    )
    return resolved


def _handler(workspace: SimpleNamespace | None = None) -> CommandHandler:
    return CommandHandler(
        agent_name="QwenPaw",
        state=SimpleNamespace(context=[], session_id="chat-1"),
        agent_id="agent-1",
        session_id="chat-1",
        prompt_context=SimpleNamespace(workspace=workspace),
        workspace_dir="/ws/agent-1",
    )


def _workspace() -> SimpleNamespace:
    return SimpleNamespace(
        agent_id="agent-1",
        workspace_dir="/ws/agent-1",
        memory_manager=SimpleNamespace(),
    )


def _text(msg) -> str:
    blocks = msg.content
    if isinstance(blocks, list):
        return "\n".join(
            str(getattr(block, "text", "") or "") for block in blocks
        )
    return str(blocks)


@pytest.mark.asyncio
async def test_master_switch_off_explains_how_to_enable(
    monkeypatch,
    calls,
):
    async def _load(_agent_id: str) -> ProactiveSettings:
        return _settings(enabled=False)

    monkeypatch.setattr(
        "qwenpaw.agents.memory.load_proactive_settings",
        _load,
    )

    msg = await _handler(_workspace()).handle_command("/proactive")

    assert "Proactive agenda is disabled" in _text(msg)
    assert calls["enabled"] == []


@pytest.mark.asyncio
async def test_master_switch_off_still_allows_off(
    monkeypatch,
    calls,
):
    async def _load(_agent_id: str) -> ProactiveSettings:
        return _settings(enabled=False)

    monkeypatch.setattr(
        "qwenpaw.agents.memory.load_proactive_settings",
        _load,
    )

    msg = await _handler(_workspace()).handle_command("/proactive off")

    assert "Proactive Mode Disabled" in _text(msg)
    assert calls["disabled"] == 1


@pytest.mark.asyncio
async def test_bare_command_arms_the_loop_and_returns_the_agenda(
    calls,
    settings,
):
    del settings
    workspace = _workspace()

    msg = await _handler(workspace).handle_command("/proactive")

    text = _text(msg)
    assert "Proactive Mode Enabled" in text
    assert f"{_PROACTIVE_DEFAULT_IDLE_MINUTES} minute" in text
    assert "ReMe proactive agenda" in text
    assert "Proactive agenda** (2026-10-11" in text
    # The bypass/screenshot warning is gone with the side agent.
    assert "bypasses tool" not in text
    assert calls["enabled"] == [
        ("QwenPaw", _PROACTIVE_DEFAULT_IDLE_MINUTES, workspace),
    ]
    assert calls["receipt_kwargs"]["agent_id"] == "agent-1"
    assert calls["receipt_kwargs"]["workspace_dir"] == "/ws/agent-1"
    assert calls["receipt_kwargs"]["session_id"] == "chat-1"


@pytest.mark.asyncio
async def test_numeric_argument_sets_the_idle_threshold(calls, settings):
    del settings

    msg = await _handler(_workspace()).handle_command("/proactive 45")

    assert "45 minute" in _text(msg)
    assert calls["enabled"][0][1] == 45


@pytest.mark.asyncio
@pytest.mark.parametrize("args", ["abc", "0", "-5"])
async def test_invalid_arguments_return_the_usage(args, calls, settings):
    del settings

    msg = await _handler(_workspace()).handle_command(f"/proactive {args}")

    assert "Invalid Proactive Arguments" in _text(msg)
    assert "/proactive now" in _text(msg)
    assert calls["enabled"] == []


@pytest.mark.asyncio
async def test_missing_workspace_is_reported(calls, settings):
    del settings

    msg = await _handler(None).handle_command("/proactive")

    text = _text(msg)
    assert "Error Enabling Proactive Mode" in text
    assert "No workspace is bound" in text
    assert calls["enabled"] == []


@pytest.mark.asyncio
async def test_now_queues_a_rebuild_and_answers_at_once(calls, settings):
    """``/proactive now`` never waits for ReMe's minutes-long chain."""
    del settings

    msg = await _handler(_workspace()).handle_command("/proactive now")

    text = _text(msg)
    assert "background" in text
    assert "separate message" in text
    # The inbox switch is on, so the copy says where the durable copy lands.
    assert "inbox" in text
    assert calls["rebuild_kwargs"]["agent_id"] == "agent-1"
    assert calls["rebuild_kwargs"]["workspace_dir"] == "/ws/agent-1"
    assert calls["rebuild_kwargs"]["session_id"] == "chat-1"


@pytest.mark.asyncio
async def test_now_reports_a_rebuild_that_is_already_running(
    calls,
    settings,
):
    del settings
    calls["queued"] = False

    msg = await _handler(_workspace()).handle_command("/proactive now")

    assert "already being rebuilt" in _text(msg)
