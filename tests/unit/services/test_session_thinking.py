# -*- coding: utf-8 -*-
"""Session reasoning persists independently from agent and workspace state."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.app.chats.api import (
    get_chat_thinking,
    set_chat_model,
    set_chat_thinking,
)
from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.app.routers.console import (
    _extract_session_and_payload,
    _persist_pending_project_dirs,
)

from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.providers.thinking import ThinkingControl, ThinkingPreference
from qwenpaw.schemas import AgentRequest
from qwenpaw.services.session_thinking import (
    apply_session_thinking,
    session_preference,
    thinking_view,
)


@pytest.mark.parametrize("request_form", ["direct", "context", "mapping"])
@pytest.mark.parametrize("slot_form", ["object", "dict", "string"])
async def test_request_model_selects_its_own_thinking(
    request_form,
    slot_form,
):
    """An explicit override must not inherit another model's preference."""
    default = ModelSlotConfig(provider_id="p", model="default")
    selected = ModelSlotConfig(provider_id="p", model="session")
    override = ModelSlotConfig(provider_id="other", model="request:tag")
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=default,
        thinking_level="budget",
        thinking_budget=4096,
    )
    chat = SimpleNamespace(
        meta={
            "runtime_context": {
                "model": selected.model_dump(),
                "thinking": {
                    "p:session": {"level": "high"},
                    "other:request:tag": {"level": "low"},
                },
            },
        },
    )
    manager = SimpleNamespace(
        get_chat_id_by_session=AsyncMock(return_value="chat"),
        get_chat=AsyncMock(return_value=chat),
    )
    slot = {
        "object": override,
        "dict": override.model_dump(),
        "string": "other:request:tag",
    }[slot_form]
    values = {
        "channel": "feishu",
        "user_id": "u",
        "request_context": {"model_slot_override": slot},
    }
    if request_form == "direct":
        values["model_slot_override"] = slot
        values["request_context"]["model_slot_override"] = "ignored:model"
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(chat_manager=manager),
        session_id="s",
    )
    if request_form == "mapping":
        ctx.payload = values
    else:
        ctx.request = SimpleNamespace(**values)
    snapshot = await apply_session_thinking(ctx, config)
    assert snapshot.active_model == override
    assert snapshot.thinking_level == "low"
    assert snapshot.thinking_budget is None
    assert config.active_model == default
    assert config.thinking_budget == 4096
    manager.get_chat_id_by_session.assert_awaited_once_with("s", "feishu", "u")


async def test_request_override_works_without_a_registered_chat():
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        thinking_level="high",
    )
    selected = ModelSlotConfig(provider_id="p", model="m")
    ctx = SimpleNamespace(
        request=SimpleNamespace(model_slot_override=selected),
    )
    with patch(
        "qwenpaw.services.session_thinking.ProviderManager.get_instance",
    ) as factory:
        factory.return_value.active_model = None
        snapshot = await apply_session_thinking(ctx, config)
    assert snapshot.active_model == selected
    assert snapshot.thinking_level == "inherit"
    assert config.active_model is None


async def test_subagent_resolves_parent_conversation_thinking():
    config = AgentProfileConfig(id="agent", name="Agent")
    manager = SimpleNamespace(
        get_chat_id_by_session=AsyncMock(return_value=None),
    )
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(chat_manager=manager),
        session_id="child",
        request=SimpleNamespace(
            channel="console",
            user_id="u",
            request_context={
                "_spawn_subagent": True,
                "parent_session_id": "parent",
            },
        ),
    )
    assert await apply_session_thinking(ctx, config) is config
    manager.get_chat_id_by_session.assert_awaited_once_with(
        "parent",
        "console",
        "u",
    )


async def test_normal_request_keeps_its_own_conversation_identity():
    config = AgentProfileConfig(id="agent", name="Agent")
    manager = SimpleNamespace(
        get_chat_id_by_session=AsyncMock(return_value=None),
    )
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(chat_manager=manager),
        session_id="current",
        request=AgentRequest(
            channel="console",
            user_id="u",
            request_context={
                "parent_session_id": "other",
                "channel": "feishu",
                "user_id": "other-user",
            },
        ),
    )
    assert await apply_session_thinking(ctx, config) is config
    manager.get_chat_id_by_session.assert_awaited_once_with(
        "current",
        "console",
        "u",
    )


@pytest.mark.parametrize("parent_channel", ["console", "feishu"])
@pytest.mark.parametrize("model_override", [None, "p:subagent"])
async def test_console_subagent_inherits_parent_model_and_thinking(
    tmp_path,
    parent_channel,
    model_override,
):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    parent = await manager.create_chat(
        ChatSpec(
            session_id="parent",
            user_id="alice",
            channel=parent_channel,
        ),
    )
    selected = ModelSlotConfig(provider_id="p", model="selected")
    await manager.set_session_model(parent.id, selected.model_dump())
    expected = (
        ModelSlotConfig(provider_id="p", model="subagent")
        if model_override
        else selected
    )
    await manager.set_session_thinking(
        parent.id,
        ThinkingPreference(level="low"),
        f"{expected.provider_id}:{expected.model}",
    )
    # A more recent chat with the same session must not cross user boundaries.
    other = await manager.create_chat(
        ChatSpec(
            session_id="parent",
            user_id="default",
            channel=parent_channel,
        ),
    )
    await manager.set_session_model(
        other.id,
        {"provider_id": "p", "model": "other-user"},
    )
    request_context = {
        "_spawn_subagent": True,
        "parent_session_id": "parent",
        "channel": parent_channel,
        "user_id": "alice",
    }
    if model_override:
        request_context["model_slot_override"] = model_override
    native = _extract_session_and_payload(
        AgentRequest(session_id="child", request_context=request_context),
    )
    channel = ConsoleChannel(process=AsyncMock(), enabled=True, bot_prefix="")
    request = channel.build_agent_request_from_native(native)
    assert request.channel == "console"
    assert request.user_id == "default"
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=ModelSlotConfig(provider_id="p", model="default"),
        thinking_level="high",
    )
    snapshot = await apply_session_thinking(
        SimpleNamespace(
            workspace=SimpleNamespace(chat_manager=manager),
            session_id=request.session_id,
            request=request,
        ),
        config,
    )
    assert snapshot.active_model == expected
    assert snapshot.thinking_level == "low"
    assert config.active_model.model == "default"
    assert config.thinking_level == "high"


@pytest.mark.asyncio
async def test_session_isolation_reload_and_reset(tmp_path):
    path = tmp_path / f"chats.json"
    manager = ChatManager(repo=JsonChatRepository(path))
    first = await manager.create_chat(
        ChatSpec(
            session_id=f"one",
            user_id=f"u",
            channel=f"console",
        ),
    )
    second = await manager.create_chat(
        ChatSpec(
            session_id=f"two",
            user_id=f"u",
            channel=f"console",
        ),
    )
    preference = ThinkingPreference(level=f"budget", budget_tokens=2345)
    await asyncio.gather(
        manager.set_session_thinking(first.id, preference, f"p:m"),
        manager.set_session_project_dirs(
            first.id,
            [
                {f"path": str(tmp_path), f"label": f"Project"},
            ],
        ),
    )
    loaded = await manager.get_chat(first.id)
    assert session_preference(loaded.meta, f"p:m") == preference
    assert loaded.meta[f"runtime_context"][f"project_dirs"]
    manager = ChatManager(repo=JsonChatRepository(path))
    config = AgentProfileConfig(
        id=f"agent",
        name=f"Agent",
        active_model=ModelSlotConfig(provider_id=f"p", model=f"m"),
    )
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(chat_manager=manager),
        session_id=f"one",
        request=SimpleNamespace(channel=f"console", user_id=f"u"),
    )
    snapshot = await apply_session_thinking(ctx, config)
    assert snapshot.thinking_budget == 2345
    assert config.thinking_level == f"inherit"
    ctx.session_id = f"two"
    assert await apply_session_thinking(ctx, config) is config
    assert session_preference((await manager.get_chat(second.id)).meta) is None
    await manager.set_session_thinking(first.id, ThinkingPreference(), f"p:m")
    loaded = await manager.get_chat(first.id)
    assert session_preference(loaded.meta, f"p:m") is None
    assert loaded.meta[f"runtime_context"][f"project_dirs"]


@pytest.mark.asyncio
async def test_inherit_uses_agent_preference():
    config = AgentProfileConfig(
        id=f"agent",
        name=f"Agent",
        thinking_level=f"high",
    )
    with (
        patch(
            f"qwenpaw.services.session_thinking.load_agent_config",
            return_value=config,
        ),
        patch(
            f"qwenpaw.services.session_thinking.ProviderManager.get_instance",
        ) as factory,
    ):
        manager = factory.return_value
        manager.get_active_model.return_value = SimpleNamespace(
            provider_id=f"p",
            model=f"m",
        )
        manager.get_provider.return_value.thinking_control.return_value = (
            ThinkingControl(kind=f"effort", efforts=[f"low", f"high"])
        )
        view = await thinking_view(
            SimpleNamespace(agent_id=f"agent"),
            ThinkingPreference(),
        )
    assert view[f"effective"][f"level"] == f"high"
    assert view[f"source"] == f"agent"


@pytest.mark.asyncio
async def test_first_message_persists_thinking_without_project_dirs(tmp_path):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / f"chats.json"))
    chat = await manager.create_chat(ChatSpec(session_id=f"new", user_id=f"u"))
    workspace = SimpleNamespace(chat_manager=manager)
    body = {
        f"meta": {
            f"request_context": {
                f"session_thinking": {f"level": f"high"},
            },
        },
    }
    with patch(
        f"qwenpaw.app.routers.console.thinking_view",
        return_value={f"reason": None, f"model_key": f"p:m"},
    ):
        updated = await _persist_pending_project_dirs(workspace, chat, body)
    assert session_preference(updated.meta, f"p:m").level == f"high"
    assert f"session_thinking" not in body[f"meta"][f"request_context"]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_console_decision_approval_requires_enabled_model(enabled):
    runtime = {"decision_enabled": enabled}
    chat = SimpleNamespace(meta={"runtime_context": runtime})
    workspace = SimpleNamespace(agent_id="agent")
    body = {"meta": {"request_context": {"approval_level": "JEV"}}}
    with (
        patch("qwenpaw.app.routers.console.load_agent_config") as load,
        patch("qwenpaw.app.routers.console.decision_settings") as settings,
    ):
        settings.return_value = {"enabled": enabled}
        await _persist_pending_project_dirs(workspace, chat, body)
    assert load.called
    assert settings.call_args.args == (load.return_value, enabled)
    assert body["meta"]["request_context"]["approval_level"] == (
        "JEV" if enabled else "STRICT"
    )


@pytest.mark.asyncio
async def test_invalid_setting_is_not_persisted():
    manager = SimpleNamespace(
        set_session_thinking=AsyncMock(),
        get_chat=AsyncMock(return_value=SimpleNamespace(meta={})),
    )
    with patch(
        f"qwenpaw.app.chats.api.thinking_view",
        return_value={f"reason": f"cannot_disable"},
    ):
        with pytest.raises(HTTPException) as raised:
            await set_chat_thinking(
                f"id",
                ThinkingPreference(level=f"off"),
                manager,
                None,
            )
    assert raised.value.status_code == 422
    manager.set_session_thinking.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_preferences_restore_independently(tmp_path):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / f"chats.json"))
    chat = await manager.create_chat(
        ChatSpec(session_id=f"one", user_id=f"u", channel=f"console"),
    )
    config = AgentProfileConfig(
        id=f"agent",
        name=f"Agent",
        active_model=ModelSlotConfig(provider_id=f"p", model=f"default"),
    )
    workspace = SimpleNamespace(chat_manager=manager, agent_id=f"agent")
    ctx = SimpleNamespace(
        workspace=workspace,
        session_id=f"one",
        request=SimpleNamespace(channel=f"console", user_id=f"u"),
    )
    await manager.set_session_thinking(
        chat.id,
        ThinkingPreference(level=f"high"),
        f"p:a",
    )
    await manager.set_session_thinking(
        chat.id,
        ThinkingPreference(level=f"low"),
        f"p:b",
    )
    for model, level in [(f"a", f"high"), (f"b", f"low"), (f"a", f"high")]:
        await manager.set_session_model(
            chat.id,
            {f"provider_id": f"p", f"model": model},
        )
        snapshot = await apply_session_thinking(ctx, config)
        assert snapshot.active_model.model == model
        assert snapshot.thinking_level == level
        assert config.active_model.model == f"default"
        assert config.thinking_level == f"inherit"
    await manager.set_session_thinking(
        chat.id,
        ThinkingPreference(),
        f"p:a",
    )
    loaded = await manager.get_chat(chat.id)
    assert session_preference(loaded.meta, f"p:a") is None
    assert session_preference(loaded.meta, f"p:b").level == f"low"


@pytest.mark.asyncio
async def test_first_message_persists_model_before_thinking(tmp_path):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / f"chats.json"))
    chat = await manager.create_chat(ChatSpec(session_id=f"new", user_id=f"u"))
    selected = {f"provider_id": f"p", f"model": f"b"}
    body = {
        f"meta": {
            f"request_context": {
                f"session_model": selected,
                f"session_thinking": {f"level": f"low"},
            },
        },
    }
    with patch(
        f"qwenpaw.app.routers.console.thinking_view",
        return_value={f"model": f"b", f"model_key": f"p:b", f"reason": None},
    ) as view:
        updated = await _persist_pending_project_dirs(
            SimpleNamespace(chat_manager=manager),
            chat,
            body,
        )
    assert updated.meta[f"runtime_context"][f"model"] == selected
    assert session_preference(updated.meta, f"p:b").level == f"low"
    assert view.call_args.args[2].model == f"b"
    assert body[f"meta"][f"request_context"] == {}


@pytest.mark.asyncio
async def test_session_routes_use_selected_model_constraints(tmp_path):
    manager = ChatManager(repo=JsonChatRepository(tmp_path / f"chats.json"))
    chat = await manager.create_chat(
        ChatSpec(
            session_id=f"one",
            user_id=f"u",
            meta={f"draft": f"keep"},
        ),
    )
    config = AgentProfileConfig(
        id=f"agent",
        name=f"Agent",
        thinking_level=f"high",
        active_model=ModelSlotConfig(provider_id=f"p", model=f"a"),
    )
    workspace = SimpleNamespace(chat_manager=manager, agent_id=f"agent")
    with (
        patch(
            f"qwenpaw.services.session_thinking.load_agent_config",
            return_value=config,
        ),
        patch(
            f"qwenpaw.services.session_thinking.ProviderManager.get_instance",
        ) as factory,
    ):
        provider = factory.return_value.get_provider.return_value
        provider.thinking_control.return_value = ThinkingControl(
            kind=f"effort",
            efforts=[f"low", f"high"],
        )
        provider.get_context_size.side_effect = lambda model: (
            32000 if model == f"a" else 128000
        )
        view = await set_chat_model(
            chat.id,
            ModelSlotConfig(provider_id=f"p", model=f"b"),
            manager,
            workspace,
        )
        assert view[f"model"] == f"b"
        assert view[f"effective_max_input_length"] == 128000
        assert view[f"source"] == f"model"
        await set_chat_thinking(
            chat.id,
            ThinkingPreference(level=f"low"),
            manager,
            workspace,
            model_key=f"p:b",
        )
        view = await get_chat_thinking(chat.id, manager, workspace)
        assert view[f"value"][f"level"] == f"low"
        await set_chat_model(
            chat.id,
            ModelSlotConfig(provider_id=f"p", model=f"a"),
            manager,
            workspace,
        )
        with pytest.raises(HTTPException) as raised:
            await set_chat_thinking(
                chat.id,
                ThinkingPreference(level=f"low"),
                manager,
                workspace,
                model_key=f"p:b",
            )
        assert raised.value.status_code == 409
        view = await get_chat_thinking(chat.id, manager, workspace)
        assert view[f"source"] == f"agent"
        assert view[f"effective"][f"level"] == f"high"
        assert config.active_model.model == f"a"
        await set_chat_thinking(
            chat.id,
            ThinkingPreference(level=f"low"),
            manager,
            workspace,
            model_key=f"p:a",
        )
        view = await set_chat_model(chat.id, None, manager, workspace)
        assert view[f"model_source"] == f"agent"
        assert view[f"model"] == f"a"
        assert view[f"value"][f"level"] == f"inherit"
        assert view[f"effective"][f"level"] == f"high"
        persisted = await manager.get_chat(chat.id)
        assert f"thinking" not in persisted.meta[f"runtime_context"]
        assert persisted.meta[f"draft"] == f"keep"
        assert config.thinking_level == f"high"


@pytest.mark.asyncio
async def test_hub_view_separates_display_name_from_routing_id(monkeypatch):
    model_id = f"ddfc504d910c40d5afb25250933df0000"
    monkeypatch.setenv(f"QWENPAW_HUB_MODEL_URL", f"https://hub.example")
    monkeypatch.setenv(f"QWENPAW_HUB_MODEL_TOKEN", f"test-token")
    catalog = {
        f"default_model_id": model_id,
        f"models": [
            {
                f"id": model_id,
                f"name": f"Organization Qwen",
                f"supports_image": False,
                f"supports_agent_thinking": False,
                f"input_token_limit": 32000,
                f"output_token_limit": None,
            },
        ],
    }
    config = AgentProfileConfig(
        id=f"agent",
        name=f"Agent",
        active_model=ModelSlotConfig(
            provider_id=f"hub-managed",
            model=model_id,
        ),
    )
    with (
        patch(
            f"qwenpaw.services.session_thinking.load_agent_config",
            return_value=config,
        ),
        patch(
            f"qwenpaw.providers.hub_managed.directory",
            return_value=catalog,
        ),
    ):
        view = await thinking_view(SimpleNamespace(agent_id=f"agent"))
    assert view[f"model_name"] == f"Organization Qwen"
    assert view[f"model"] == model_id
    assert view[f"model_key"] == f"hub-managed:{model_id}"


@pytest.mark.asyncio
async def test_hub_personal_session_selection_and_reasoning(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(f"QWENPAW_HUB_MODEL_TOKEN", f"test-token")
    config = AgentProfileConfig(
        id=f"agent",
        name=f"Agent",
        active_model=ModelSlotConfig(provider_id=f"hub-managed", model=f"org"),
    )
    manager = ChatManager(repo=JsonChatRepository(tmp_path / f"chats.json"))
    chat = await manager.create_chat(
        ChatSpec(session_id=f"personal", user_id=f"u", channel=f"console"),
    )
    workspace = SimpleNamespace(agent_id=f"agent", chat_manager=manager)
    selected = ModelSlotConfig(provider_id=f"kilo", model=f"qwen")
    with (
        patch(
            f"qwenpaw.services.session_thinking.load_agent_config",
            return_value=config,
        ),
        patch(
            f"qwenpaw.services.session_thinking.ProviderManager.get_instance",
        ) as factory,
        patch(f"qwenpaw.services.session_thinking.managed_slot") as hub,
    ):
        provider = factory.return_value.get_provider.return_value
        provider.get_model_info.return_value = SimpleNamespace(name=f"Qwen")
        provider.thinking_control.return_value = ThinkingControl()
        provider.get_context_size.return_value = 128000
        view = await set_chat_model(chat.id, selected, manager, workspace)
        assert view[f"provider_id"] == f"kilo"
        assert view[f"model_name"] == f"Qwen"
        assert view[f"effective_max_input_length"] == 128000
        reread = await get_chat_thinking(chat.id, manager, workspace)
        assert reread[f"model"] == f"qwen"
        ctx = SimpleNamespace(
            workspace=workspace,
            session_id=f"personal",
            request=SimpleNamespace(channel=f"console", user_id=f"u"),
        )
        snapshot = await apply_session_thinking(ctx, config)
        assert snapshot.active_model == selected
        hub.assert_not_called()
        factory.return_value.get_provider.assert_called_with(f"kilo")
        hub.return_value = (config.active_model, {f"models": []})
        with patch(
            f"qwenpaw.services.session_thinking.managed_provider",
            return_value=provider,
        ):
            org = await set_chat_model(
                chat.id,
                config.active_model,
                manager,
                workspace,
            )
            assert org[f"provider_id"] == f"hub-managed"
            assert org[f"model"] == f"org"
        calls = hub.call_count
        personal = await set_chat_model(chat.id, selected, manager, workspace)
        assert personal[f"provider_id"] == f"kilo"
        assert hub.call_count == calls


@pytest.mark.asyncio
async def test_invalid_personal_selection_is_not_persisted(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(f"QWENPAW_HUB_MODEL_TOKEN", f"token")
    config = AgentProfileConfig(id=f"agent", name=f"Agent")
    manager = ChatManager(repo=JsonChatRepository(tmp_path / f"chats.json"))
    chat = await manager.create_chat(ChatSpec(session_id=f"s", user_id=f"u"))
    with (
        patch(
            f"qwenpaw.services.session_thinking.load_agent_config",
            return_value=config,
        ),
        patch(
            f"qwenpaw.services.session_thinking.ProviderManager.get_instance",
        ) as factory,
        patch(f"qwenpaw.services.session_thinking.managed_slot") as hub,
    ):
        provider = factory.return_value.get_provider.return_value
        provider.get_model_info.return_value = None
        with pytest.raises(HTTPException) as failure:
            await set_chat_model(
                chat.id,
                ModelSlotConfig(provider_id=f"kilo", model=f"missing"),
                manager,
                SimpleNamespace(agent_id=f"agent"),
            )
        assert failure.value.status_code == 422
        hub.assert_not_called()
        assert not (await manager.get_chat(chat.id)).meta.get(
            f"runtime_context",
        )
