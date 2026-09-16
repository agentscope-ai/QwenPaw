# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for asynchronous chat-title generation."""

from types import SimpleNamespace

import pytest

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
