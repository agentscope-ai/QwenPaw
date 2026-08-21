# -*- coding: utf-8 -*-
"""Tests for asynchronous chat-title generation."""

from types import SimpleNamespace

from qwenpaw.app.chats import title_generator


class _ChatManager:
    def __init__(self) -> None:
        self.updated_title: str | None = None

    async def patch_chat_if_name_matches(
        self,
        chat_id,
        _placeholder_name,
        patch,
    ):
        self.updated_title = patch.name
        return SimpleNamespace(id=chat_id, name=patch.name)


async def test_title_generation_disables_thinking(monkeypatch):
    """Utility title calls should not ask reasoning models to think."""
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
        return "Deploying QwenPaw"

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

    assert seen_kwargs == {"disable_thinking": True}
    assert chat_manager.updated_title == "Deploying QwenPaw"
