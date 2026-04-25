# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Unit tests for the async chat-title generator."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.app.runner import title_generator
from qwenpaw.app.runner.manager import ChatManager
from qwenpaw.app.runner.models import ChatSpec, ChatUpdate
from qwenpaw.app.runner.repo.json_repo import JsonChatRepository
from qwenpaw.app.runner.title_generator import (
    MAX_TITLE_CHARS,
    _clean_title,
    _extract_text,
    generate_and_update_title,
)


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


class TestCleanTitle:
    """Normalization of model output into a single-line title."""

    def test_strips_surrounding_whitespace(self) -> None:
        assert _clean_title("  Meeting Notes  ") == "Meeting Notes"

    def test_strips_double_quotes(self) -> None:
        assert _clean_title('"Quoted Title"') == "Quoted Title"

    def test_strips_smart_quotes(self) -> None:
        assert _clean_title("“smart quotes”") == "smart quotes"

    def test_strips_single_quotes_and_backticks(self) -> None:
        assert _clean_title("'apostrophe'") == "apostrophe"
        assert _clean_title("`backtick`") == "backtick"

    def test_keeps_only_first_line(self) -> None:
        assert _clean_title("Line one\nLine two\nLine three") == "Line one"

    def test_strips_trailing_punctuation(self) -> None:
        assert _clean_title("Hello.") == "Hello"
        assert _clean_title("What now?") == "What now"
        assert _clean_title("Wow!!!") == "Wow"
        assert _clean_title("End: ") == "End"

    def test_truncates_to_max_length(self) -> None:
        long_input = "a" * (MAX_TITLE_CHARS * 2)
        result = _clean_title(long_input)
        assert len(result) == MAX_TITLE_CHARS
        assert result == "a" * MAX_TITLE_CHARS

    def test_empty_input_returns_empty_string(self) -> None:
        assert _clean_title("") == ""
        assert _clean_title("   ") == ""

    def test_only_punctuation_returns_empty(self) -> None:
        assert _clean_title("...") == ""

    def test_does_not_strip_internal_punctuation(self) -> None:
        assert _clean_title("hello, world!") == "hello, world"


class TestExtractText:
    """Best-effort extraction of plain text from model responses."""

    def test_extracts_from_plain_string(self) -> None:
        assert _extract_text("hello world") == "hello world"

    def test_extracts_from_text_attribute(self) -> None:
        response = MagicMock()
        response.text = "from .text"
        # Don't let .content shadow .text
        response.content = None
        assert _extract_text(response) == "from .text"

    def test_extracts_from_string_content(self) -> None:
        response = MagicMock()
        response.text = None
        response.content = "from .content"
        assert _extract_text(response) == "from .content"

    def test_extracts_from_list_of_dicts(self) -> None:
        response = MagicMock()
        response.text = None
        response.content = [
            {"text": "first"},
            {"text": " second"},
            {"type": "image"},  # ignored
        ]
        assert _extract_text(response) == "first second"

    def test_extracts_from_list_of_objects(self) -> None:
        class Item:
            def __init__(self, t: str) -> None:
                self.text = t

        response = MagicMock()
        response.text = None
        response.content = [Item("a"), Item("b")]
        assert _extract_text(response) == "ab"

    def test_handles_none(self) -> None:
        assert _extract_text(None) == ""

    def test_handles_unknown_shape(self) -> None:
        response = MagicMock()
        response.text = None
        response.content = 12345  # unsupported type
        assert _extract_text(response) == ""


# ---------------------------------------------------------------------------
# generate_and_update_title behavior tests
# ---------------------------------------------------------------------------


@pytest.fixture
def chat_manager(tmp_path: Path) -> ChatManager:
    """Create a chat manager backed by a temporary chats.json file."""
    return ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))


@pytest.fixture
def workspace(chat_manager: ChatManager) -> MagicMock:
    """Lightweight workspace stub exposing only what the generator uses."""
    ws = MagicMock()
    ws.agent_id = "test-agent"
    ws.chat_manager = chat_manager
    return ws


def _make_response(text: str) -> MagicMock:
    """Construct a fake ChatResponse-like object with a .text attribute."""
    response = MagicMock()
    response.text = text
    response.content = None
    return response


async def _seed_chat(
    chat_manager: ChatManager,
    name: str = "Hello, wor",
) -> ChatSpec:
    """Create a chat row that mirrors the placeholder produced by the
    console handler."""
    spec = ChatSpec(
        id="chat-1",
        name=name,
        session_id="console:default",
        user_id="default",
        channel="console",
    )
    return await chat_manager.create_chat(spec)


def _patch_model_factory(model: AsyncMock | MagicMock | None = None):
    """Patch ``create_model_and_formatter`` at the source module level so the
    function-local import inside :mod:`title_generator` picks up the mock."""
    if model is None:
        return patch(
            "qwenpaw.agents.model_factory.create_model_and_formatter",
            side_effect=RuntimeError("no model"),
        )
    return patch(
        "qwenpaw.agents.model_factory.create_model_and_formatter",
        return_value=(model, MagicMock()),
    )


async def test_updates_chat_name_with_cleaned_title(
    chat_manager: ChatManager,
    workspace: MagicMock,
) -> None:
    """Happy path: model output is cleaned and persisted."""
    chat = await _seed_chat(chat_manager)
    placeholder = chat.name

    model = AsyncMock(
        return_value=_make_response('"Trip Planning Assistant."'),
    )
    with _patch_model_factory(model):
        await generate_and_update_title(
            workspace=workspace,
            chat_id=chat.id,
            user_message="Help me plan a trip to Tokyo next week.",
            placeholder_name=placeholder,
        )

    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.name == "Trip Planning Assistant"
    model.assert_awaited_once()


async def test_passes_concise_title_prompt_to_model(
    chat_manager: ChatManager,
    workspace: MagicMock,
) -> None:
    """Model receives the system prompt and (truncated) user message."""
    chat = await _seed_chat(chat_manager)

    model = AsyncMock(return_value=_make_response("Title"))
    with _patch_model_factory(model):
        await generate_and_update_title(
            workspace=workspace,
            chat_id=chat.id,
            user_message="x" * (title_generator.MAX_INPUT_CHARS + 50),
            placeholder_name=chat.name,
        )

    args, _ = model.call_args
    messages = args[0]
    assert messages[0]["role"] == "system"
    assert "title" in messages[0]["content"].lower()
    assert messages[1]["role"] == "user"
    # Long user message is truncated before being sent to the model.
    assert len(messages[1]["content"]) == title_generator.MAX_INPUT_CHARS


async def test_skips_when_user_message_blank(
    chat_manager: ChatManager,
    workspace: MagicMock,
) -> None:
    """No model call and no chat update for an empty user message."""
    chat = await _seed_chat(chat_manager)

    model = AsyncMock(return_value=_make_response("anything"))
    with _patch_model_factory(model):
        await generate_and_update_title(
            workspace=workspace,
            chat_id=chat.id,
            user_message="   ",
            placeholder_name=chat.name,
        )

    model.assert_not_called()
    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.name == chat.name


async def test_skips_when_chat_was_renamed(
    chat_manager: ChatManager,
    workspace: MagicMock,
) -> None:
    """Concurrent rename must not be clobbered by the generated title."""
    chat = await _seed_chat(chat_manager)

    # Simulate a user rename happening while the model call is in flight.
    await chat_manager.patch_chat(chat.id, ChatUpdate(name="User Pick"))

    model = AsyncMock(return_value=_make_response("Auto Title"))
    with _patch_model_factory(model):
        await generate_and_update_title(
            workspace=workspace,
            chat_id=chat.id,
            user_message="What is the weather today?",
            placeholder_name=chat.name,  # original placeholder is stale
        )

    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.name == "User Pick"


async def test_skips_when_chat_missing(
    chat_manager: ChatManager,
    workspace: MagicMock,
) -> None:
    """Deleted chat must not raise, just no-op."""
    model = AsyncMock(return_value=_make_response("Whatever"))
    with _patch_model_factory(model):
        await generate_and_update_title(
            workspace=workspace,
            chat_id="does-not-exist",
            user_message="hello",
            placeholder_name="hello",
        )

    # No exception, and nothing got created.
    assert await chat_manager.get_chat("does-not-exist") is None


async def test_skips_when_model_returns_empty(
    chat_manager: ChatManager,
    workspace: MagicMock,
) -> None:
    """Empty/whitespace model output must not overwrite the placeholder."""
    chat = await _seed_chat(chat_manager)

    model = AsyncMock(return_value=_make_response("   \n   "))
    with _patch_model_factory(model):
        await generate_and_update_title(
            workspace=workspace,
            chat_id=chat.id,
            user_message="hello",
            placeholder_name=chat.name,
        )

    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.name == chat.name


async def test_skips_when_model_unavailable(
    chat_manager: ChatManager,
    workspace: MagicMock,
) -> None:
    """No active model configured must not raise — just skip the update."""
    chat = await _seed_chat(chat_manager)

    with _patch_model_factory(None):  # raises RuntimeError("no model")
        await generate_and_update_title(
            workspace=workspace,
            chat_id=chat.id,
            user_message="hello",
            placeholder_name=chat.name,
        )

    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.name == chat.name


async def test_swallows_model_exceptions(
    chat_manager: ChatManager,
    workspace: MagicMock,
) -> None:
    """Errors from the model invocation must not bubble up."""
    chat = await _seed_chat(chat_manager)

    model = AsyncMock(side_effect=RuntimeError("network blew up"))
    with _patch_model_factory(model):
        await generate_and_update_title(
            workspace=workspace,
            chat_id=chat.id,
            user_message="hello",
            placeholder_name=chat.name,
        )

    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.name == chat.name


async def test_swallows_model_timeout(
    chat_manager: ChatManager,
    workspace: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slow models hit the timeout and are swallowed cleanly."""
    chat = await _seed_chat(chat_manager)

    # Force the timeout to fire immediately.
    monkeypatch.setattr(title_generator, "TITLE_TIMEOUT_SECONDS", 0.01)

    async def _slow(_messages):
        await asyncio.sleep(1.0)
        return _make_response("late")

    model = AsyncMock(side_effect=_slow)
    with _patch_model_factory(model):
        await generate_and_update_title(
            workspace=workspace,
            chat_id=chat.id,
            user_message="hello",
            placeholder_name=chat.name,
        )

    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.name == chat.name


async def test_cancellation_propagates(
    chat_manager: ChatManager,
    workspace: MagicMock,
) -> None:
    """asyncio.CancelledError must propagate so task cancellation works."""
    chat = await _seed_chat(chat_manager)

    async def _cancel(_messages):
        raise asyncio.CancelledError()

    model = AsyncMock(side_effect=_cancel)
    with _patch_model_factory(model):
        with pytest.raises(asyncio.CancelledError):
            await generate_and_update_title(
                workspace=workspace,
                chat_id=chat.id,
                user_message="hello",
                placeholder_name=chat.name,
            )
