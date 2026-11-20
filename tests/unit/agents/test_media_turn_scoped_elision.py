# -*- coding: utf-8 -*-
"""Turn-scoped media: the model is not re-sent pixels it has already consumed.

Two rules are pinned here:

* media produced by a *delivery* tool (`send_file_to_user`) is never model
  input — the channel ships the file, the model only needs a reference;
* media that precedes the last completed assistant turn has been consumed, so
  it is replaced by a path reference and only the current turn stays inline.

Both rules apply to the per-request copy; stored history must stay untouched.
"""

# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import (
    Base64Source,
    DataBlock,
    Msg,
    TextBlock,
)

from qwenpaw.agents import model_factory
from qwenpaw.agents.model_factory import (
    _elide_consumed_media,
    _is_final_assistant_turn,
    _media_slot,
    _normalize_messages_for_formatter,
)


def _image_block(name: str = "shot.png", size: int = 4000) -> dict:
    return {
        "type": "data",
        "name": name,
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "A" * size,
        },
    }


def _file_image_block(tmp_path, name: str = "shot.png") -> dict:
    target = tmp_path / name
    target.write_bytes(b"\x89PNG" + b"\x00" * 2048)
    return {
        "type": "data",
        "source": {
            "type": "url",
            "url": target.as_uri(),
            "media_type": "image/png",
        },
    }


def _tool_result(tool: str, block: dict) -> dict:
    return {"type": "tool_result", "name": tool, "output": [block]}


def _user(*blocks) -> SimpleNamespace:
    return SimpleNamespace(role="user", content=list(blocks))


def _assistant(*blocks) -> SimpleNamespace:
    return SimpleNamespace(role="assistant", content=list(blocks))


FINAL = {"type": "text", "text": "done"}
TOOL_CALL = {"type": "tool_call", "name": "view_image", "input": {}}


def test_delivery_tool_media_is_elided_even_in_current_turn() -> None:
    """A delivered file is an artefact, not something the model must read."""
    msgs = [
        _user({"type": "text", "text": "send the chart"}),
        _assistant(TOOL_CALL),
        _user(_tool_result("send_file_to_user", _image_block("chart.png"))),
        _assistant(FINAL),
    ]

    assert _elide_consumed_media(msgs) == 1
    text = msgs[2].content[0]["output"][0]["text"]
    assert "not re-sent to the model" in text
    assert "chart.png" in text


def test_current_turn_media_stays_inline() -> None:
    """No completed assistant turn yet: the model still needs the pixels."""
    msgs = [
        _user({"type": "text", "text": "what is on screen?"}),
        _assistant(TOOL_CALL),
        _user(_tool_result("view_image", _image_block())),
    ]

    assert _elide_consumed_media(msgs) == 0
    assert msgs[2].content[0]["output"][0]["type"] == "data"


def test_consumed_media_is_replaced_after_the_turn_completes(
    tmp_path,
) -> None:
    msgs = [
        _user({"type": "text", "text": "what is on screen?"}),
        _assistant(TOOL_CALL),
        _user(_tool_result("view_image", _file_image_block(tmp_path))),
        _assistant(FINAL),
        _user({"type": "text", "text": "thanks, next question"}),
    ]

    assert _elide_consumed_media(msgs) == 1
    placeholder = msgs[2].content[0]["output"][0]
    assert placeholder["type"] == "text"
    assert "shot.png" in placeholder["text"]
    assert "view_image again" in placeholder["text"]


def test_assistant_tool_call_does_not_close_the_turn() -> None:
    """A tool-calling assistant message is mid-turn, not a completion."""
    msgs = [
        _user({"type": "text", "text": "go"}),
        _assistant(TOOL_CALL),
        _user(_tool_result("view_image", _image_block())),
        _assistant({"type": "text", "text": "looking"}, TOOL_CALL),
    ]

    assert _is_final_assistant_turn(msgs[3]) is False
    assert _elide_consumed_media(msgs) == 0


def test_elision_is_deterministic() -> None:
    def build():
        return [
            _user({"type": "text", "text": "q"}),
            _assistant(TOOL_CALL),
            _user(_tool_result("view_image", _image_block("a.png"))),
            _assistant(FINAL),
        ]

    first, second = build(), build()
    _elide_consumed_media(first)
    _elide_consumed_media(second)
    assert (
        first[2].content[0]["output"][0] == second[2].content[0]["output"][0]
    )


def test_kill_switch_disables_elision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWENPAW_DISABLE_MEDIA_ELISION", "1")
    msgs = [
        _user({"type": "text", "text": "q"}),
        _assistant(TOOL_CALL),
        _user(_tool_result("send_file_to_user", _image_block())),
        _assistant(FINAL),
    ]

    assert _elide_consumed_media(msgs) == 0


def test_delivery_tool_list_is_extendable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_DELIVERY_ONLY_TOOL_RESULTS", "my_publisher")
    msgs = [
        _user({"type": "text", "text": "q"}),
        _assistant({"type": "tool_call", "name": "my_publisher", "input": {}}),
        _user(_tool_result("my_publisher", _image_block())),
    ]

    assert _elide_consumed_media(msgs) == 1


def test_slot_reports_local_file_size(tmp_path) -> None:
    target = tmp_path / "pic.png"
    target.write_bytes(b"\x89PNG" + b"\x00" * 2048)
    block = {
        "type": "data",
        "source": {
            "type": "url",
            "url": target.as_uri(),
            "media_type": "image/png",
        },
    }
    slot = _media_slot(block)
    assert slot is not None
    assert slot[0] == "image/png"
    assert slot[2] == 2052
    assert slot[3].endswith("pic.png")


def test_pydantic_blocks_are_replaced_with_text_blocks() -> None:
    """A Pydantic DataBlock becomes a TextBlock reference in the copy."""
    msgs = [
        Msg(
            name="user",
            role="user",
            content=[
                TextBlock(text="look at this"),
                DataBlock(
                    source=Base64Source(
                        media_type="image/png",
                        data="aGVsbG8=",
                    ),
                ),
            ],
        ),
        Msg(name="agent", role="assistant", content=[TextBlock(text="ok")]),
    ]

    assert _elide_consumed_media(msgs) == 1
    assert isinstance(msgs[0].content[1], TextBlock)


def test_stored_history_is_not_mutated_by_the_request_copy() -> None:
    """Normalization deep-copies, so elision never edits the session."""
    media = DataBlock(
        source=Base64Source(media_type="image/png", data="aGVsbG8="),
    )
    stored = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="q"), media],
        ),
        Msg(name="agent", role="assistant", content=[TextBlock(text="ok")]),
    ]

    (
        normalized,
        _is_anthropic,
        _is_gemini,
        _is_response,
    ) = _normalize_messages_for_formatter(
        stored,
        model_factory.OpenAIChatFormatter,
    )
    assert _elide_consumed_media(normalized) == 1

    assert isinstance(stored[0].content[1], DataBlock)
    assert isinstance(normalized[0].content[1], TextBlock)


def test_current_turn_assistant_media_stays_inline() -> None:
    """The newest message's media is still needed, even in an assistant msg.

    ``view_audio`` returns its DataBlock at the top level of an assistant
    message, so the highest index must stay inline.
    """
    msgs = [
        Msg(
            name="tool",
            role="assistant",
            content=[
                DataBlock(
                    source=Base64Source(
                        media_type="audio/wav",
                        data="UklGRg==",
                    ),
                ),
                TextBlock(text="Audio loaded in native mode"),
            ],
        ),
    ]

    assert _elide_consumed_media(msgs) == 0


def test_assistant_media_from_a_completed_turn_is_referenced() -> None:
    """Once the conversation moved on, assistant media is replayed as text."""
    msgs = [
        _user({"type": "text", "text": "make me a picture"}),
        _assistant({"type": "text", "text": "here"}, _image_block("out.png")),
        _user({"type": "text", "text": "next question"}),
    ]

    assert _elide_consumed_media(msgs) == 1
    assert msgs[1].content[1]["type"] == "text"
    assert "out.png" in msgs[1].content[1]["text"]
