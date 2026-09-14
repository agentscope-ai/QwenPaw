# -*- coding: utf-8 -*-
"""Assistant text streaming for delegated ACP runners.

Two defects these tests pin, both reported from live kimi-cli / codex runs:

* Runners differ wildly in how they chunk assistant text.  kimi-cli streams a
  few words per ``session/update`` notification, and each delta used to become
  its own stream item rendered as ``[assistant]\\n<fragment>``, so a single
  answer arrived as dozens of ``[assistant]`` markers interleaved with the
  sentence it was breaking up.
* The same text is delivered twice per turn: incrementally as deltas, and
  again in full by ``ACPHostedClient.finish_prompt`` (returned as
  ``run_result["event"]`` from ``service.py``).  The closing block used to
  render that text a second time, so codex/qwen answers appeared verbatim
  twice, separated only by the ``runner: ... working directory: ...`` header.
"""
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Package ``tools.__init__`` re-exports the tool function under the same name
# as the module, so use importlib to get the real module object.
dea = importlib.import_module("qwenpaw.agents.tools.delegate_external_agent")

ANSWER = "你好！我是 **Kimi Code CLI**，一个运行在你终端里的 AI 编程助手。"


def _chunk_text(chunk: object) -> str:
    content = getattr(chunk, "content", None) or []
    return "".join(
        text
        for text in (getattr(block, "text", None) for block in content)
        if text
    )


def _text_event(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text, "is_chunk": False}


def _tool_event(detail: str) -> dict[str, Any]:
    return {"type": "tool_start", "kind": "edit", "detail": detail}


def _fragments(text: str, size: int = 4) -> list[dict[str, Any]]:
    """Split *text* into small deltas, the way kimi-cli streams them."""
    return [
        _text_event(text[index : index + size])
        for index in range(0, len(text), size)
    ]


def _fake_run_action(
    events: list[dict[str, Any]],
    result: dict[str, Any],
) -> Any:
    async def _run(**kwargs: Any) -> dict[str, Any]:
        on_message = kwargs["on_message"]
        for event in events:
            await on_message(event, False)
        return result

    return _run


async def _collect(
    tmp_path: Path,
    events: list[dict[str, Any]],
    result: dict[str, Any],
) -> list[object]:
    """Drive one delegated turn and return every chunk it yields."""
    chunks: list[object] = []
    with patch.object(dea, "_run_action", _fake_run_action(events, result)):
        stream = dea._stream_action_responses(
            service=MagicMock(),
            chat_id="chat-1",
            action_name="message",
            runner_name="kimi",
            message_text="hi",
            execution_cwd=tmp_path,
        )
        async for chunk in stream:
            chunks.append(chunk)
    return chunks


@pytest.mark.asyncio
async def test_fragmented_deltas_become_one_assistant_item(
    tmp_path: Path,
) -> None:
    """kimi-cli's few-words-per-notification streaming stays readable."""
    events = _fragments(ANSWER)
    assert len(events) > 5, "test needs a fragmented answer"

    chunks = await _collect(tmp_path, events, {"event": _text_event(ANSWER)})
    joined = "".join(_chunk_text(chunk) for chunk in chunks)

    assert joined.count("[assistant]") == 1
    assert ANSWER in joined


@pytest.mark.asyncio
async def test_answer_is_delivered_exactly_once(tmp_path: Path) -> None:
    """The closing block must not repeat text the stream already carried."""
    events = _fragments(ANSWER)

    chunks = await _collect(tmp_path, events, {"event": _text_event(ANSWER)})
    joined = "".join(_chunk_text(chunk) for chunk in chunks)

    assert joined.count(ANSWER) == 1
    # The header still closes the turn, so the caller keeps runner context.
    assert "runner: kimi" in joined
    assert f"working directory: {tmp_path}" in joined


@pytest.mark.asyncio
async def test_single_chunk_runner_is_not_duplicated(tmp_path: Path) -> None:
    """codex/qwen send the whole answer at once; it used to appear twice."""
    events = [_text_event(ANSWER)]

    chunks = await _collect(tmp_path, events, {"event": _text_event(ANSWER)})
    joined = "".join(_chunk_text(chunk) for chunk in chunks)

    assert joined.count(ANSWER) == 1
    assert joined.count("[assistant]") == 1


@pytest.mark.asyncio
async def test_tool_event_does_not_reorder_surrounding_text(
    tmp_path: Path,
) -> None:
    """A non-text event ends the current message, so text drains first."""
    events = [
        *_fragments("before", 2),
        _tool_event("WriteFile: notes.md"),
        *_fragments("after", 2),
    ]

    chunks = await _collect(tmp_path, events, {"event": None})
    items = [
        item
        for chunk in chunks
        for item in (getattr(block, "text", "") for block in chunk.content)
        if item
    ]
    flat = "\n".join(items)

    assert flat.index("before") < flat.index("[tool_call]")
    assert flat.index("[tool_call]") < flat.index("after")
    assert flat.count("[assistant]") == 2


@pytest.mark.asyncio
async def test_text_is_kept_when_nothing_was_streamed(tmp_path: Path) -> None:
    """No deltas emitted -> the closing block must still carry the answer."""
    chunks = await _collect(tmp_path, [], {"event": _text_event(ANSWER)})
    joined = "".join(_chunk_text(chunk) for chunk in chunks)

    assert joined.count(ANSWER) == 1
    assert "[assistant]" in joined


@pytest.mark.asyncio
async def test_closing_block_prefers_complete_text_over_last_delta(
    tmp_path: Path,
) -> None:
    """A truncated stream must not end the turn on a sentence fragment."""
    partial = ANSWER[:12]
    events = _fragments(partial, 4)

    chunks = await _collect(tmp_path, events, {"event": _text_event(ANSWER)})

    # The stream carried only the prefix, so the complete answer is not a
    # duplicate: the closing block must render it rather than the last delta.
    closing = _chunk_text(chunks[-1])
    assert "runner: kimi" in closing
    assert ANSWER in closing
    joined = "".join(_chunk_text(chunk) for chunk in chunks)
    assert joined.count(ANSWER) == 1


@pytest.mark.asyncio
async def test_error_event_survives_when_no_text_arrived(
    tmp_path: Path,
) -> None:
    error = {"type": "error", "message": "runner exploded"}
    chunks = await _collect(tmp_path, [error], {"event": None})
    joined = "".join(_chunk_text(chunk) for chunk in chunks)

    assert "runner exploded" in joined


class TestTextAlreadyStreamed:
    """Unit coverage for the suppression predicate."""

    def test_full_text_in_stream_suppresses(self) -> None:
        event = _text_event(ANSWER)
        assert dea._text_already_streamed(event, ["你好", ANSWER[2:]]) is True

    def test_partial_stream_does_not_suppress(self) -> None:
        event = _text_event(ANSWER)
        assert dea._text_already_streamed(event, [ANSWER[:8]]) is False

    def test_empty_stream_does_not_suppress(self) -> None:
        assert dea._text_already_streamed(_text_event(ANSWER), []) is False

    def test_non_text_event_does_not_suppress(self) -> None:
        error = {"type": "error", "message": ANSWER}
        assert dea._text_already_streamed(error, [ANSWER]) is False

    def test_blank_body_does_not_suppress(self) -> None:
        assert dea._text_already_streamed(_text_event("   "), [""]) is False

    def test_none_event_does_not_suppress(self) -> None:
        assert dea._text_already_streamed(None, [ANSWER]) is False


class TestRenderAssistantText:
    """The ``[assistant]`` marker is rendered in exactly one place."""

    def test_renders_single_marker(self) -> None:
        from qwenpaw.agents.acp import tool_adapter as ta

        assert ta.render_assistant_text(ANSWER) == f"[assistant]\n{ANSWER}"

    def test_blank_text_renders_nothing(self) -> None:
        from qwenpaw.agents.acp import tool_adapter as ta

        assert ta.render_assistant_text("   ") is None

    def test_text_event_renderer_shares_the_format(self) -> None:
        from qwenpaw.agents.acp import tool_adapter as ta

        assert ta._render_text_event(_text_event(ANSWER)) == (
            ta.render_assistant_text(ANSWER)
        )


class TestFinalResponseSuppression:
    """``format_final_assistant_response`` header-only mode."""

    def test_suppress_body_keeps_header_only(self) -> None:
        from qwenpaw.agents.acp import tool_adapter as ta

        chunk = ta.format_final_assistant_response(
            runner_name="kimi",
            execution_cwd=Path("/ws"),
            final_event=_text_event(ANSWER),
            suppress_body=True,
        )
        text = _chunk_text(chunk)
        assert "runner: kimi" in text
        assert ANSWER not in text

    def test_default_still_includes_body(self) -> None:
        from qwenpaw.agents.acp import tool_adapter as ta

        chunk = ta.format_final_assistant_response(
            runner_name="kimi",
            execution_cwd=Path("/ws"),
            final_event=_text_event(ANSWER),
        )
        assert ANSWER in _chunk_text(chunk)


@pytest.mark.asyncio
async def test_flush_task_is_settled_before_return(tmp_path: Path) -> None:
    """No dangling 1s flush task may outlive the turn."""
    before = len(_pending_tasks())
    await _collect(
        tmp_path, _fragments(ANSWER), {"event": _text_event(ANSWER)}
    )
    await asyncio.sleep(0)
    assert len(_pending_tasks()) <= before


def _pending_tasks() -> list[asyncio.Task[Any]]:
    return [task for task in asyncio.all_tasks() if not task.done()]
