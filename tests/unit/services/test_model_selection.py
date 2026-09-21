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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    ["deleted", "missing-model", "missing-provider", "valid"],
)
async def test_deleted_agent_default_falls_back_without_rewriting(
    monkeypatch,
    kind,
):
    from qwenpaw.providers.openai_provider import OpenAIProvider
    from qwenpaw.providers.provider import ModelInfo

    provider = OpenAIProvider(
        id="provider",
        name="Provider",
        models=[]
        if kind == "missing-model"
        else [ModelInfo(id="agent", name="Agent")],
        removed_model_ids=["agent"] if kind == "deleted" else [],
    )
    manager = SimpleNamespace(
        get_provider=lambda _id: None
        if kind == "missing-provider"
        else provider,
        get_active_model=lambda: _slot("global"),
    )
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: manager,
    )
    config = SimpleNamespace(active_model=_slot("agent"))
    workspace = SimpleNamespace(
        config=config,
        chat_manager=SimpleNamespace(find_chat=AsyncMock(return_value=None)),
    )
    context = await prepare_model_context(
        workspace=workspace,
        session_id="new-session",
        user_id="user",
        channel="console",
        request_override=None,
    )
    expected = "agent" if kind == "valid" else "global"
    assert context.slot == _slot(expected)
    assert context.source == expected
    assert config.active_model == _slot("agent")
    clear_current_model_context()
    assert get_current_model_slot(agent_model=config.active_model) == (
        _slot(expected),
        expected,
    )
    assert get_current_model_slot(
        agent_model=config.active_model,
        request_override=_slot("explicit"),
    ) == (_slot("explicit"), "request")


@pytest.mark.asyncio
async def test_effective_api_ignores_deleted_agent_model(monkeypatch):
    from qwenpaw.app.routers import providers

    slot = _slot("global")
    manager = SimpleNamespace(
        get_provider=lambda _id: SimpleNamespace(
            get_model_info=lambda _model: None,
            get_context_size=lambda _model: 8192,
        ),
        get_active_model=lambda: slot,
    )
    monkeypatch.setattr(
        providers,
        "_load_agent_model",
        AsyncMock(return_value=_slot("deleted")),
    )
    monkeypatch.setattr(providers, "hub_mode", lambda: False)
    result = await providers.get_active_models(
        None,
        manager,
        "effective",
        "agent",
    )
    assert result.active_llm == slot
    raw = await providers.get_active_models(None, manager, "agent", "agent")
    assert raw.active_llm == _slot("deleted")


def test_parse_model_slot_accepts_slot_like_objects() -> None:
    value = SimpleNamespace(provider_id="provider", model="compatible")

    assert parse_model_slot(value) == _slot("compatible")


def test_explicit_absent_agent_model_does_not_reload_config(monkeypatch):
    from unittest.mock import MagicMock

    load = MagicMock(return_value=SimpleNamespace(active_model=_slot("agent")))
    monkeypatch.setattr("qwenpaw.config.config.load_agent_config", load)
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: SimpleNamespace(
            get_active_model=lambda: _slot("global"),
            get_provider=lambda _id: SimpleNamespace(
                get_model_info=lambda _model: object(),
            ),
        ),
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
    import threading

    request_thread = threading.get_ident()

    def global_model():
        assert threading.get_ident() != request_thread
        return _slot("global")

    manager = SimpleNamespace(find_chat=AsyncMock())
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: SimpleNamespace(get_active_model=global_model),
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
        lambda: SimpleNamespace(
            get_active_model=lambda: _slot("global"),
            get_provider=lambda _id: SimpleNamespace(
                get_model_info=lambda _model: object(),
            ),
        ),
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
        lambda: SimpleNamespace(
            get_active_model=lambda: _slot("global"),
            get_provider=lambda _id: SimpleNamespace(
                get_model_info=lambda _model: object(),
            ),
        ),
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
        lambda: SimpleNamespace(
            get_active_model=lambda: _slot("global"),
            get_provider=lambda _id: SimpleNamespace(
                get_model_info=lambda _model: object(),
            ),
        ),
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
