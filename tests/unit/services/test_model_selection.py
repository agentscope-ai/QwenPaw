# -*- coding: utf-8 -*-
"""Tests for canonical request-to-global model resolution."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.services.model_selection import (
    clear_current_model_context,
    get_current_model_context,
    get_current_model_info,
    get_current_model_slot,
    parse_model_slot,
    prepare_model_context,
    resolve_effective_model_slot,
    session_model_slot,
)


@pytest.fixture(autouse=True)
def _clear_model_context():
    clear_current_model_context()
    yield
    clear_current_model_context()


def _slot(name: str) -> ModelSlotConfig:
    return ModelSlotConfig(provider_id="provider", model=name)


def test_parse_model_slot_accepts_slot_like_objects() -> None:
    value = SimpleNamespace(provider_id="provider", model="compatible")

    assert parse_model_slot(value) == _slot("compatible")


def test_explicit_absent_agent_model_does_not_reload_config(monkeypatch):
    from unittest.mock import MagicMock

    load = MagicMock(return_value=SimpleNamespace(active_model=_slot("agent")))
    monkeypatch.setattr("qwenpaw.config.config.load_agent_config", load)
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: SimpleNamespace(get_active_model=lambda: _slot("global")),
    )
    assert get_current_model_slot(agent_id="agent", agent_model=None) == (
        _slot("global"),
        "global",
    )
    load.assert_not_called()
    assert get_current_model_slot(agent_id="agent") == (
        _slot("agent"),
        "agent",
    )
    load.assert_called_once_with("agent")


@pytest.mark.asyncio
async def test_unknown_channel_does_not_register_console_chat(monkeypatch):
    manager = SimpleNamespace(find_chat=AsyncMock())
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: SimpleNamespace(get_active_model=lambda: _slot("global")),
    )
    context = await prepare_model_context(
        workspace=SimpleNamespace(
            config=SimpleNamespace(active_model=None),
            chat_manager=manager,
        ),
        session_id="acp-session",
        user_id="user",
        channel="",
        request_override=_slot("request"),
    )
    assert context.chat_id is None
    assert context.slot == _slot("request")
    manager.find_chat.assert_not_awaited()


def test_model_resolution_follows_canonical_priority() -> None:
    chat_meta = {
        "runtime_context": {
            "model_slot_override": _slot("session").model_dump(),
        },
    }
    slot, source = resolve_effective_model_slot(
        request_override=_slot("request"),
        chat_meta=chat_meta,
        agent_model=_slot("agent"),
        global_model=_slot("global"),
    )
    assert slot == _slot("request")
    assert source == "request"


def test_model_resolution_falls_back_through_session_agent_and_global() -> (
    None
):
    chat_meta = {
        "runtime_context": {
            "model_slot_override": _slot("session").model_dump(),
        },
    }
    assert resolve_effective_model_slot(
        chat_meta=chat_meta,
        agent_model=_slot("agent"),
        global_model=_slot("global"),
    ) == (_slot("session"), "session")
    assert resolve_effective_model_slot(
        agent_model=_slot("agent"),
        global_model=_slot("global"),
    ) == (_slot("agent"), "agent")
    assert resolve_effective_model_slot(
        global_model=_slot("global"),
    ) == (_slot("global"), "global")


def test_session_model_slot_ignores_unrelated_or_invalid_metadata() -> None:
    assert (
        session_model_slot({"runtime_context": {"project_dir": "/tmp"}})
        is None
    )


@pytest.mark.parametrize("removed", [False, True])
def test_current_model_info_returns_info_and_resolved_slot(
    monkeypatch,
    removed,
) -> None:
    model_info = SimpleNamespace(id="session")
    provider = SimpleNamespace(
        models=[model_info],
        extra_models=[],
        all_models=lambda: [] if removed else [model_info],
    )
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: SimpleNamespace(get_provider=lambda _provider_id: provider),
    )
    from qwenpaw.services.model_selection import (
        ModelSelectionContext,
        set_current_model_context,
    )

    slot = _slot("session")
    set_current_model_context(
        ModelSelectionContext(slot=slot, source="session"),
    )

    assert get_current_model_info() == (None if removed else model_info, slot)


@pytest.mark.asyncio
@pytest.mark.parametrize("override", ["invalid", {}, 42, {"model": "missing"}])
async def test_invalid_request_override_falls_back(monkeypatch, override):
    from qwenpaw.services.model_selection import (
        ModelSelectionContext,
        set_current_model_context,
    )

    set_current_model_context(
        ModelSelectionContext(slot=_slot("old"), source="session"),
    )

    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: SimpleNamespace(get_active_model=lambda: _slot("global")),
    )
    context = await prepare_model_context(
        workspace=SimpleNamespace(
            config=SimpleNamespace(active_model=_slot("agent")),
            chat_manager=SimpleNamespace(
                find_chat=AsyncMock(return_value=None),
            ),
        ),
        session_id="session-1",
        user_id="user-1",
        channel="console",
        request_override=override,
    )
    assert context.slot == _slot("agent")
    assert context.source == "agent"
    assert get_current_model_context() == context


@pytest.mark.asyncio
async def test_temporary_override_does_not_persist(monkeypatch):
    request_slot = _slot("request")
    updated_chat = SimpleNamespace(
        id="chat-1",
        meta={
            "runtime_context": {
                "model_slot_override": request_slot.model_dump(),
            },
        },
    )
    chat_manager = SimpleNamespace(
        find_chat=AsyncMock(
            return_value=SimpleNamespace(id="chat-1", meta={}),
        ),
        set_model_slot_override=AsyncMock(return_value=updated_chat),
    )
    workspace = SimpleNamespace(
        config=SimpleNamespace(active_model=_slot("agent")),
        chat_manager=chat_manager,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: SimpleNamespace(get_active_model=lambda: _slot("global")),
    )

    context = await prepare_model_context(
        workspace=workspace,
        session_id="session-1",
        user_id="user-1",
        channel="console",
        request_override=request_slot.model_dump(),
    )

    assert context.slot == request_slot
    assert context.source == "request"
    assert context.chat_id == "chat-1"
    assert get_current_model_context() == context
    assert get_current_model_slot() == (request_slot, "request")
    chat_manager.set_model_slot_override.assert_not_awaited()
    next_context = await prepare_model_context(
        workspace=workspace,
        session_id="session-1",
        user_id="user-1",
        channel="console",
        request_override=None,
    )
    assert next_context.slot == _slot("agent")
    assert next_context.source == "agent"


@pytest.mark.asyncio
async def test_prepare_context_reads_session_without_rewriting_request(
    monkeypatch,
):
    session_slot = _slot("session")
    request = SimpleNamespace(model_slot_override=None)
    chat_manager = SimpleNamespace(
        find_chat=AsyncMock(
            return_value=SimpleNamespace(
                id="chat-1",
                meta={
                    "runtime_context": {
                        "model_slot_override": session_slot.model_dump(),
                    },
                },
            ),
        ),
        set_model_slot_override=AsyncMock(),
    )
    workspace = SimpleNamespace(
        config=SimpleNamespace(active_model=_slot("agent")),
        chat_manager=chat_manager,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: SimpleNamespace(get_active_model=lambda: _slot("global")),
    )

    context = await prepare_model_context(
        workspace=workspace,
        session_id="session-1",
        user_id="user-1",
        channel="console",
        request_override=request.model_slot_override,
    )

    assert context.slot == session_slot
    assert context.source == "session"
    assert request.model_slot_override is None
    chat_manager.set_model_slot_override.assert_not_awaited()
    assert (
        session_model_slot(
            {"runtime_context": {"model_slot_override": {"model": "missing"}}},
        )
        is None
    )
