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
    _extract_text_from_response,
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


class TestExtractTextFromResponse:
    """Same shape as skills_stream._extract_text_from_response: prefer .text,
    fall back to .content (string or list-of-text-blocks), else empty."""

    def test_plain_string(self) -> None:
        assert _extract_text_from_response("plain") == "plain"

    def test_none(self) -> None:
        assert _extract_text_from_response(None) == ""

    def test_text_attribute_wins(self) -> None:
        response = MagicMock()
        response.text = "from text"
        response.content = "from content"
        assert _extract_text_from_response(response) == "from text"

    def test_falls_back_to_string_content(self) -> None:
        response = MagicMock()
        response.text = None
        response.content = "from content"
        assert _extract_text_from_response(response) == "from content"

    def test_returns_first_text_dict_in_list(self) -> None:
        response = MagicMock()
        response.text = None
        response.content = [
            {"type": "image"},  # skipped
            {"text": "first"},
            {"text": "second"},  # not concatenated, matches skills_stream
        ]
        assert _extract_text_from_response(response) == "first"

    def test_returns_first_text_object_in_list(self) -> None:
        class Item:
            def __init__(self, t: str) -> None:
                self.text = t

        response = MagicMock()
        response.text = None
        response.content = [Item("alpha"), Item("beta")]
        assert _extract_text_from_response(response) == "alpha"

    def test_unknown_shape_returns_empty(self) -> None:
        response = MagicMock()
        response.text = None
        response.content = 12345
        assert _extract_text_from_response(response) == ""


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


class _FakeResponse:
    """Plain non-streaming ``ChatResponse`` stub.

    Deliberately not a ``MagicMock``: ``MagicMock`` auto-implements
    ``__aiter__`` and would trip the streaming branch in
    :func:`_consume_model_response`, which checks ``hasattr(response,
    "__aiter__")`` to detect async-generator responses.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.content = None


def _make_response(text: str) -> _FakeResponse:
    """Construct a fake non-streaming ChatResponse with a ``.text``
    attribute."""
    return _FakeResponse(text)


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


def _patch_model_factory(
    model: AsyncMock | MagicMock | None = None,
    factory_error: BaseException | None = None,
):
    """Patch ``create_model_and_formatter`` at the source module level so the
    function-local import inside :mod:`title_generator` picks up the mock."""
    if factory_error is not None:
        return patch(
            "qwenpaw.agents.model_factory.create_model_and_formatter",
            side_effect=factory_error,
        )
    return patch(
        "qwenpaw.agents.model_factory.create_model_and_formatter",
        return_value=(model, MagicMock()),
    )


def _stub_agent_config(
    *,
    enabled: bool = True,
    timeout_seconds: float = 30.0,
) -> MagicMock:
    """Return a stub agent config exposing ``running.auto_title_config``."""
    cfg = MagicMock()
    cfg.running.auto_title_config.enabled = enabled
    cfg.running.auto_title_config.timeout_seconds = timeout_seconds
    return cfg


@pytest.fixture(autouse=True)
def _stub_load_agent_config():
    """Replace :func:`load_agent_config` with a stub returning a default
    enabled ``AutoTitleConfig`` so tests do not have to set up a real
    workspace on disk."""
    with patch(
        "qwenpaw.config.config.load_agent_config",
        return_value=_stub_agent_config(),
    ) as mocked:
        yield mocked


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
    """No active model configured must not raise — just skip the update.

    Mirrors the ``(ValueError, AppBaseException)`` shape that
    ``skills_stream.get_model`` swallows when the provider is missing.
    """
    chat = await _seed_chat(chat_manager)

    with _patch_model_factory(factory_error=ValueError("no provider")):
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
    _stub_load_agent_config,
) -> None:
    """Slow models hit the configured timeout and are swallowed cleanly."""
    chat = await _seed_chat(chat_manager)

    # Force the timeout from config to fire immediately.
    _stub_load_agent_config.return_value = _stub_agent_config(
        timeout_seconds=0.01,
    )

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


async def test_skips_when_auto_title_disabled_by_config(
    chat_manager: ChatManager,
    workspace: MagicMock,
    _stub_load_agent_config,
) -> None:
    """``auto_title_config.enabled = False`` short-circuits before any LLM
    call so users can opt out of the per-chat token cost."""
    chat = await _seed_chat(chat_manager)
    _stub_load_agent_config.return_value = _stub_agent_config(enabled=False)

    model = AsyncMock(return_value=_make_response("Should Not Run"))
    with _patch_model_factory(model):
        await generate_and_update_title(
            workspace=workspace,
            chat_id=chat.id,
            user_message="hello",
            placeholder_name=chat.name,
        )

    model.assert_not_called()
    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.name == chat.name


async def test_skips_when_agent_config_unavailable(
    chat_manager: ChatManager,
    workspace: MagicMock,
    _stub_load_agent_config,
) -> None:
    """A misconfigured / missing agent must not raise, just no-op."""
    chat = await _seed_chat(chat_manager)
    _stub_load_agent_config.side_effect = ValueError("agent not found")

    model = AsyncMock(return_value=_make_response("Anything"))
    with _patch_model_factory(model):
        await generate_and_update_title(
            workspace=workspace,
            chat_id=chat.id,
            user_message="hello",
            placeholder_name=chat.name,
        )

    model.assert_not_called()
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


def test_cancelled_error_does_not_inherit_from_exception() -> None:
    """Pin the language-level invariant the cancellation handling relies on.

    ``except Exception`` in :func:`generate_and_update_title` deliberately
    does not catch ``asyncio.CancelledError``; this only works because
    ``CancelledError`` has inherited from ``BaseException`` since
    Python 3.8 (the project requires Python >= 3.10). If a future Python
    version reverts that, this test fails loudly so the cancellation
    handling can be revisited.
    """
    assert not issubclass(asyncio.CancelledError, Exception)
    assert issubclass(asyncio.CancelledError, BaseException)


async def test_does_not_overwrite_concurrent_rename(
    chat_manager: ChatManager,
    workspace: MagicMock,
) -> None:
    """A rename that lands while the model call is in flight must win.

    Regression test for the TOCTOU window between reading the chat name
    and writing the generated title. The fake model patches the chat
    name *during* its own ``await``, mimicking a user rename that arrives
    before the patch step but after the read step.
    """
    chat = await _seed_chat(chat_manager)

    async def _model_then_rename(_messages):
        await chat_manager.patch_chat(
            chat.id,
            ChatUpdate(name="User Pick"),
        )
        return _make_response("Auto Title")

    model = AsyncMock(side_effect=_model_then_rename)
    with _patch_model_factory(model):
        await generate_and_update_title(
            workspace=workspace,
            chat_id=chat.id,
            user_message="What is the weather?",
            placeholder_name=chat.name,
        )

    saved = await chat_manager.get_chat(chat.id)
    assert saved is not None
    assert saved.name == "User Pick"
