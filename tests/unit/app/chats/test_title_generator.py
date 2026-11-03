# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for asynchronous chat-title generation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.chats import title_generator


class _ChatManager:
    def __init__(self) -> None:
        self.updated_title: str | None = None

    async def get_chat(self, chat_id):
        return SimpleNamespace(id=chat_id, meta={})

    async def patch_chat_if_name_matches(
        self,
        chat_id,
        _placeholder_name,
        patch,
    ):
        self.updated_title = patch.name
        return SimpleNamespace(id=chat_id, name=patch.name)


async def test_title_generation_keeps_thinking_out_of_persisted_title(
    monkeypatch,
):
    """Reasoning may run, but only the final answer becomes the title."""
    seen_kwargs = {}
    chat_manager = _ChatManager()
    workspace = SimpleNamespace(
        agent_id="agent-1",
        chat_manager=chat_manager,
    )
    config = SimpleNamespace(
        running=SimpleNamespace(
            auto_title_config=SimpleNamespace(
                enabled=True,
                timeout_seconds=5,
            ),
        ),
    )
    model = object()

    async def fake_run_sync_io(_func, *_args):
        return config

    async def fake_create_model_and_formatter_async(**_kwargs):
        return model, object()

    async def fake_consume_model_response(
        received_model,
        messages,
        **kwargs,
    ):
        assert received_model is model
        assert messages[-1].content[0].text == "How do I deploy QwenPaw?"
        seen_kwargs.update(kwargs)
        return (
            "<think>Here's a thinking process about the request.</think>\n"
            "Deploying QwenPaw"
        )

    monkeypatch.setattr(title_generator, "run_sync_io", fake_run_sync_io)
    monkeypatch.setattr(
        title_generator,
        "consume_model_response",
        fake_consume_model_response,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        fake_create_model_and_formatter_async,
    )

    await title_generator.generate_and_update_title(
        workspace=workspace,
        chat_id="chat-1",
        user_message="How do I deploy QwenPaw?",
        placeholder_name="How do I d",
    )

    assert not seen_kwargs
    assert chat_manager.updated_title == "Deploying QwenPaw"


def test_clean_title_rejects_unterminated_leading_reasoning():
    assert (
        title_generator._clean_title(
            "<think>Here's a thinking process without a final answer",
        )
        == ""
    )


def test_clean_title_keeps_answer_before_unterminated_reasoning():
    assert (
        title_generator._clean_title(
            "Deploying QwenPaw\n<think>truncated reasoning",
        )
        == "Deploying QwenPaw"
    )


def test_clean_title_keeps_complete_single_line_title():
    title = "A" * 120
    assert title_generator._clean_title(title) == title


@pytest.mark.parametrize(
    "raw",
    [
        "Understanding <think> Tags",
        "Meaning of <think>foo</think>",
        "Escaping <analysis> in XML",
        "Use <reasoning> safely",
    ],
)
def test_clean_title_preserves_reasoning_tags_in_answer(raw):
    assert title_generator._clean_title(raw) == raw


@pytest.mark.parametrize(
    "raw",
    [
        "<think>reasoning</think>\nDeploying QwenPaw",
        "<thinking>reasoning</thinking>\nDeploying QwenPaw",
        "<analysis>reasoning</analysis>\nDeploying QwenPaw",
        "<reasoning>reasoning</reasoning>\nDeploying QwenPaw",
        "<THINK mode='deep'>reasoning</THINK>\nDeploying QwenPaw",
    ],
)
def test_clean_title_strips_common_inline_reasoning_formats(raw):
    assert title_generator._clean_title(raw) == "Deploying QwenPaw"


@pytest.mark.parametrize("request_override", [None, "direct", "context"])
async def test_title_uses_conversation_model_and_its_thinking(
    monkeypatch,
    request_override,
):
    from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig

    default = ModelSlotConfig(provider_id="default", model="M1")
    selected = ModelSlotConfig(provider_id="session", model="M2")
    override = ModelSlotConfig(provider_id="request", model="M3")
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=default,
        thinking_level="high",
    )
    meta = {
        "runtime_context": {
            "model": selected.model_dump(),
            "thinking": {"session:M2": {"level": "low"}},
        },
    }
    chat_manager = _ChatManager()
    chat_manager.get_chat = AsyncMock(
        return_value=SimpleNamespace(meta=meta),
    )
    workspace = SimpleNamespace(agent_id="agent", chat_manager=chat_manager)
    factory = AsyncMock(return_value=(object(), None))
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _: config,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        factory,
    )
    monkeypatch.setattr(
        title_generator,
        "consume_model_response",
        AsyncMock(return_value="A title"),
    )
    request = None
    if request_override == "direct":
        request = {"model_slot_override": override.model_dump()}
    elif request_override == "context":
        request = {
            "meta": {
                "request_context": {
                    "model_slot_override": override.model_dump(),
                },
            },
        }
    await title_generator.generate_and_update_title(
        workspace,
        "chat",
        "First message",
        "First message",
        request=request,
    )
    used = factory.await_args.kwargs["agent_config"]
    assert used.active_model == (override if request_override else selected)
    assert used.thinking_level == ("inherit" if request_override else "low")
    assert config.active_model == default
    assert config.thinking_level == "high"
    assert chat_manager.updated_title == "A title"


@pytest.mark.parametrize(
    ("parent_channel", "parent_user"),
    [("console", "default"), ("console", "alice"), ("feishu", "alice")],
)
@pytest.mark.parametrize("model_override", [None, "subagent:M3"])
@pytest.mark.parametrize("spawned", [True, False])
async def test_title_and_execution_resolve_the_same_conversation_settings(
    monkeypatch,
    tmp_path,
    parent_channel,
    parent_user,
    model_override,
    spawned,
):
    from qwenpaw.app.channels.console.channel import ConsoleChannel
    from qwenpaw.app.chats.manager import ChatManager
    from qwenpaw.app.chats.models import ChatSpec
    from qwenpaw.app.chats.repo import JsonChatRepository
    from qwenpaw.app.routers.console import _extract_session_and_payload
    from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
    from qwenpaw.providers.thinking import ThinkingPreference
    from qwenpaw.schemas import AgentRequest
    from qwenpaw.services.session_thinking import apply_session_thinking

    manager = ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))
    parent = await manager.create_chat(
        ChatSpec(
            session_id="parent",
            user_id=parent_user,
            channel=parent_channel,
            name="Parent title",
        ),
    )
    selected = ModelSlotConfig(provider_id="parent", model="M2")
    override = ModelSlotConfig(provider_id="subagent", model="M3")
    await manager.set_session_model(parent.id, selected.model_dump())
    for slot in (selected, override):
        await manager.set_session_thinking(
            parent.id,
            ThinkingPreference(level="low"),
            f"{slot.provider_id}:{slot.model}",
        )
    # More recent, colliding sessions must not supply the parent's settings.
    for user, channel in (
        ("other-user", parent_channel),
        (parent_user, "other-channel"),
    ):
        other = await manager.create_chat(
            ChatSpec(session_id="parent", user_id=user, channel=channel),
        )
        await manager.set_session_model(
            other.id,
            {"provider_id": "wrong", "model": "other-conversation"},
        )

    context = {
        "parent_session_id": "parent",
        "channel": parent_channel,
        "user_id": parent_user,
    }
    if spawned:
        context["_spawn_subagent"] = True
    if model_override:
        context["model_slot_override"] = model_override
    native = _extract_session_and_payload(
        AgentRequest(session_id="child", request_context=context),
    )
    channel = ConsoleChannel(process=AsyncMock(), enabled=True, bot_prefix="")
    request = channel.build_agent_request_from_native(native)
    child = await manager.create_chat(
        ChatSpec(
            session_id=request.session_id,
            user_id=request.user_id,
            channel=request.channel,
            name="First message",
        ),
    )
    child_slot = ModelSlotConfig(provider_id="child", model="M4")
    await manager.set_session_model(child.id, child_slot.model_dump())
    for slot in (child_slot, override):
        await manager.set_session_thinking(
            child.id,
            ThinkingPreference(level="off"),
            f"{slot.provider_id}:{slot.model}",
        )
    default = ModelSlotConfig(provider_id="default", model="M1")
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=default,
        thinking_level="high",
    )
    workspace = SimpleNamespace(agent_id="agent", chat_manager=manager)
    execution = await apply_session_thinking(
        SimpleNamespace(
            workspace=workspace,
            session_id=request.session_id,
            request=request,
        ),
        config,
    )
    factory = AsyncMock(return_value=(object(), None))
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _: config,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        factory,
    )
    monkeypatch.setattr(
        title_generator,
        "consume_model_response",
        AsyncMock(return_value="Child title"),
    )

    await title_generator.generate_and_update_title(
        workspace,
        child.id,
        "First message",
        "First message",
        request=native,
    )

    expected = (
        override if model_override else selected if spawned else child_slot
    )
    title_config = factory.await_args.kwargs["agent_config"]
    assert title_config.active_model == execution.active_model == expected
    assert (
        title_config.thinking_level
        == execution.thinking_level
        == ("low" if spawned else "off")
    )
    assert (await manager.get_chat(child.id)).name == "Child title"
    assert (await manager.get_chat(parent.id)).name == "Parent title"
    assert config.active_model == default
    assert config.thinking_level == "high"


@pytest.mark.parametrize("model_override", [None, "subagent:M3"])
async def test_subagent_title_with_missing_parent_uses_execution_defaults(
    monkeypatch,
    model_override,
):
    from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig

    default = ModelSlotConfig(provider_id="default", model="M1")
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=default,
        thinking_level="high",
    )
    manager = _ChatManager()
    manager.get_chat = AsyncMock(
        return_value=SimpleNamespace(
            session_id="child",
            meta={
                "runtime_context": {
                    "model": {"provider_id": "child", "model": "M4"},
                },
            },
        ),
    )
    manager.get_chat_id_by_session = AsyncMock(return_value=None)
    factory = AsyncMock(return_value=(object(), None))
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _: config,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        factory,
    )
    monkeypatch.setattr(
        title_generator,
        "consume_model_response",
        AsyncMock(return_value="Child title"),
    )
    await title_generator.generate_and_update_title(
        SimpleNamespace(agent_id="agent", chat_manager=manager),
        "child-chat",
        "First message",
        "First message",
        request={
            "meta": {
                "request_context": {
                    "_spawn_subagent": True,
                    "parent_session_id": "missing",
                    "channel": "feishu",
                    "user_id": "alice",
                    "model_slot_override": model_override,
                },
            },
        },
    )
    used = factory.await_args.kwargs["agent_config"]
    assert used.active_model == (
        ModelSlotConfig(provider_id="subagent", model="M3")
        if model_override
        else default
    )
    assert used.thinking_level == ("inherit" if model_override else "high")
    manager.get_chat_id_by_session.assert_awaited_once_with(
        "missing",
        "feishu",
        "alice",
    )
    assert manager.updated_title == "Child title"


async def test_deleted_chat_does_not_generate_a_title(monkeypatch):
    from qwenpaw.config.config import AgentProfileConfig

    config = AgentProfileConfig(id="agent", name="Agent")
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _: config,
    )
    factory = AsyncMock()
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        factory,
    )
    workspace = SimpleNamespace(
        agent_id="agent",
        chat_manager=SimpleNamespace(get_chat=AsyncMock(return_value=None)),
    )
    await title_generator.generate_and_update_title(
        workspace,
        "deleted",
        "First message",
        "First message",
    )
    factory.assert_not_awaited()
