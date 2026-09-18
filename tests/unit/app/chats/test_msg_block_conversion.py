# -*- coding: utf-8 -*-
"""Cover the block-conversion paths of agentscope_msg_to_message.

``tests/unit/app/chats/test_utils.py`` drives the transcript-filtering
rules (scroll placeholders, synthetic user stubs, headline stripping) and
the timestamp/finished_at metadata.  What stayed uncovered is the
*content-block* conversion: the ``data`` block media-type dispatch added
for AgentScope 2.0, the image/audio/video/file source shapes, the
tool_call/tool_result argument serialisation, the message segmentation
that flushes a pending message whenever the block kind changes, and the
small url helpers they depend on.

Two reachability notes, both verified against agentscope 2.0.7.post1:

* ``Msg.content`` is validated as ``list[ContentBlock]``, so a bare
  ``{"type": "image"}`` dict cannot be constructed through ``Msg(...)``.
  The supported production shape is the ``data`` block, whose
  ``source.media_type`` selects image/audio/video/file — that is the path
  exercised here for all four media kinds.
* A few defensive branches can only be reached when validation is
  bypassed (``content`` as ``str``, a non-dict entry, an unknown block
  type, ``tool_call`` input as dict/list).  Those use
  ``Msg.model_construct`` and each test says so explicitly, because the
  guard exists for callers that hand over unvalidated payloads rather
  than for messages built through the public constructor.
"""
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

import json
from enum import Enum
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from agentscope.message import Msg

from qwenpaw.app.chats import utils as chats_utils
from qwenpaw.app.chats.utils import (
    _abspath_from_url,
    _is_local_file_url,
    _resolve_content_url,
    agentscope_msg_to_message,
    build_env_context,
)
from qwenpaw.constant import QWENPAW_USER_CONTENT_KEY
from qwenpaw.exceptions import AgentRuntimeErrorException
from qwenpaw.schemas import ContentType, MessageType


def _convert(msg, tz: str | None = "UTC"):
    """Convert with a stubbed config so the user timezone is fixed.

    ``tz`` is widened to ``None`` because one test deliberately stubs a
    config whose ``user_timezone`` is missing, to exercise the UTC
    fallback in the timestamp rendering.
    """
    with patch.object(
        chats_utils,
        "load_config",
        return_value=SimpleNamespace(user_timezone=tz),
    ):
        return agentscope_msg_to_message(msg)


def _msg(content, role: str = "assistant", **kw) -> Msg:
    return Msg(name=role, role=role, content=content, **kw)


def _unvalidated(content, role: str = "assistant") -> Msg:
    """Build a Msg without pydantic validation (defensive-branch only)."""
    return Msg.model_construct(
        name=role,
        role=role,
        content=content,
        metadata=None,
        id="probe-id",
        timestamp=None,
    )


def _data_block(media_type: str, **source) -> dict:
    src = {"media_type": media_type}
    src.update(source)
    return {"type": "data", "source": src}


def _contents(message) -> list[dict]:
    return [c.model_dump() for c in message.content]


# ---------------------------------------------------------------------------
# top-level input validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["a string", 123, None, {"role": "user"}])
def test_invalid_input_type_raises(bad) -> None:
    with pytest.raises(AgentRuntimeErrorException) as excinfo:
        _convert(bad)
    assert excinfo.value.code == "INVALID_MESSAGE_TYPE"
    assert type(bad).__name__ in str(excinfo.value)


def test_list_of_messages_converts_each() -> None:
    out = _convert(
        [
            _msg([{"type": "text", "text": "a"}]),
            _msg([{"type": "text", "text": "b"}]),
        ],
    )
    assert len(out) == 2


def test_empty_list_returns_empty() -> None:
    assert _convert([]) == []


def test_invalid_user_timezone_falls_back_to_utc() -> None:
    out = _convert(
        _msg([{"type": "text", "text": "t"}]),
        tz="Mars/Olympus",
    )
    assert len(out) == 1
    assert out[0].metadata["timestamp"].endswith("+00:00")


def test_none_user_timezone_falls_back_to_utc() -> None:
    out = _convert(_msg([{"type": "text", "text": "t"}]), tz=None)
    assert out[0].metadata["timestamp"].endswith("+00:00")


# ---------------------------------------------------------------------------
# content as str — defensive branch (validated Msg rejects a str content)
# ---------------------------------------------------------------------------
def test_string_content_becomes_single_text_message() -> None:
    with pytest.raises(Exception):
        # proves the public constructor validates content as a list
        _msg("plain string")

    out = _convert(_unvalidated("plain string"))
    assert len(out) == 1
    assert out[0].type == MessageType.MESSAGE
    assert _contents(out[0])[0]["text"] == "plain string"


def test_string_content_is_cleaned_for_display() -> None:
    out = _convert(_unvalidated("all set\n<!-- ⟦ headline ⟧ -->"))
    text = _contents(out[0])[0]["text"]
    assert "all set" in text
    assert "⟦" not in text


# ---------------------------------------------------------------------------
# data block -> concrete media type (AgentScope 2.0 shape)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("media_type", "expected_kind", "expected_message_type"),
    [
        ("image/png", "ImageContent", MessageType.MESSAGE),
        ("audio/wav", "AudioContent", MessageType.MESSAGE),
        ("video/mp4", "VideoContent", MessageType.MESSAGE),
        ("application/pdf", "FileContent", MessageType.MESSAGE),
        ("text/csv", "FileContent", MessageType.MESSAGE),
    ],
)
def test_data_block_dispatches_on_media_type(
    media_type: str,
    expected_kind: str,
    expected_message_type,
) -> None:
    out = _convert(
        [_msg([_data_block(media_type, type="base64", data="X")])][0],
    )
    assert len(out) == 1
    assert out[0].type == expected_message_type
    assert type(out[0].content[0]).__name__ == expected_kind


def test_data_block_image_base64_builds_data_url() -> None:
    out = _convert(
        _msg([_data_block("image/png", type="base64", data="AAA")]),
    )
    content = _contents(out[0])[0]
    assert content["type"] == ContentType.IMAGE
    assert content["image_url"] == "data:image/png;base64,AAA"


def test_data_block_image_url_is_passed_through() -> None:
    out = _convert(
        _msg([_data_block("image/png", type="url", url="https://x/y.png")]),
    )
    assert _contents(out[0])[0]["image_url"] == "https://x/y.png"


def test_data_block_image_local_url_is_reduced_to_path() -> None:
    out = _convert(
        _msg([_data_block("image/png", type="url", url="file:///tmp/a.png")]),
    )
    assert _contents(out[0])[0]["image_url"] == "/tmp/a.png"


def test_data_block_audio_url_extracts_format_from_extension() -> None:
    out = _convert(
        _msg([_data_block("audio/wav", type="url", url="https://x/y.wav")]),
    )
    content = _contents(out[0])[0]
    assert content["type"] == ContentType.AUDIO
    assert content["data"] == "https://x/y.wav"
    assert content["format"] == "wav"


def test_data_block_audio_base64_keeps_media_type_as_format() -> None:
    out = _convert(
        _msg([_data_block("audio/wav", type="base64", data="BBB")]),
    )
    content = _contents(out[0])[0]
    assert content["data"] == "data:audio/wav;base64,BBB"
    assert content["format"] == "audio/wav"


def test_data_block_video_base64_and_url() -> None:
    b64 = _convert(
        _msg([_data_block("video/mp4", type="base64", data="CCC")]),
    )
    assert _contents(b64[0])[0]["video_url"] == "data:video/mp4;base64,CCC"

    url = _convert(
        _msg([_data_block("video/mp4", type="url", url="https://x/y.mp4")]),
    )
    assert _contents(url[0])[0]["video_url"] == "https://x/y.mp4"


def test_data_block_file_base64_and_url() -> None:
    b64 = _convert(
        _msg([_data_block("application/pdf", type="base64", data="DDD")]),
    )
    assert (
        _contents(b64[0])[0]["file_url"] == "data:application/pdf;base64,DDD"
    )

    url = _convert(
        _msg(
            [
                _data_block(
                    "application/pdf",
                    type="url",
                    url="https://x/f.pdf",
                ),
            ],
        ),
    )
    assert _contents(url[0])[0]["file_url"] == "https://x/f.pdf"


def test_data_block_without_source_type_yields_empty_media_fields() -> None:
    # source.type is neither "url" nor "base64" -> no kwargs are added.
    # DataBlock.source is a discriminated union whose type literal is only
    # "base64" or "url" (verified against agentscope 2.0.7.post1: any other
    # value raises ValidationError through Msg(...)), so this defensive
    # branch is only reachable from an unvalidated caller.
    out = _convert(
        _unvalidated(
            [
                {
                    "type": "data",
                    "source": {
                        "type": "inline",
                        "media_type": "image/png",
                        "data": "Z",
                    },
                },
            ],
        ),
    )
    content = _contents(out[0])[0]
    assert content["type"] == ContentType.IMAGE
    assert content.get("image_url") is None


# ---------------------------------------------------------------------------
# text / thinking / hint segmentation
# ---------------------------------------------------------------------------
def test_consecutive_texts_share_one_message() -> None:
    out = _convert(
        _msg([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]),
    )
    assert len(out) == 1
    assert [c["text"] for c in _contents(out[0])] == ["a", "b"]


def test_thinking_starts_a_reasoning_message() -> None:
    out = _convert(
        _msg(
            [
                {"type": "thinking", "thinking": "reason"},
                {"type": "text", "text": "answer"},
            ],
        ),
    )
    assert [m.type for m in out] == [
        MessageType.REASONING,
        MessageType.MESSAGE,
    ]
    assert _contents(out[0])[0]["text"] == "reason"
    assert _contents(out[1])[0]["text"] == "answer"


def test_text_after_thinking_flushes_pending_message() -> None:
    out = _convert(
        _msg(
            [
                {"type": "text", "text": "a"},
                {"type": "thinking", "thinking": "r"},
                {"type": "text", "text": "b"},
            ],
        ),
    )
    assert [m.type for m in out] == [
        MessageType.MESSAGE,
        MessageType.REASONING,
        MessageType.MESSAGE,
    ]


def test_consecutive_thinkings_share_one_reasoning_message() -> None:
    out = _convert(
        _msg(
            [
                {"type": "thinking", "thinking": "r1"},
                {"type": "thinking", "thinking": "r2"},
            ],
        ),
    )
    assert len(out) == 1
    assert out[0].type == MessageType.REASONING
    assert [c["text"] for c in _contents(out[0])] == ["r1", "r2"]


def test_hint_block_is_dropped_from_transcript() -> None:
    out = _convert(
        _msg(
            [
                {
                    "type": "hint",
                    "hint": "private runtime state",
                    "source": "s",
                },
                {"type": "text", "text": "visible"},
            ],
        ),
    )
    assert len(out) == 1
    assert [c["text"] for c in _contents(out[0])] == ["visible"]


def test_block_without_type_defaults_to_text() -> None:
    out = _convert(_unvalidated([{"text": "no type key"}]))
    assert len(out) == 1
    assert _contents(out[0])[0]["text"] == "no type key"


def test_non_dict_block_is_skipped() -> None:
    out = _convert(_unvalidated(["raw-string", {"type": "text", "text": "t"}]))
    assert len(out) == 1
    assert [c["text"] for c in _contents(out[0])] == ["t"]


def test_unknown_block_type_is_stringified_into_text() -> None:
    out = _convert(_unvalidated([{"type": "mystery", "x": 1}]))
    assert len(out) == 1
    assert out[0].type == MessageType.MESSAGE
    assert _contents(out[0])[0]["text"] == str({"type": "mystery", "x": 1})


def test_empty_content_list_yields_no_message() -> None:
    assert _convert(_msg([])) == []


# ---------------------------------------------------------------------------
# tool_call / tool_result
# ---------------------------------------------------------------------------
def test_tool_call_string_input_is_passed_through() -> None:
    out = _convert(
        _msg([{"type": "tool_call", "id": "c1", "name": "f", "input": "raw"}]),
    )
    assert len(out) == 1
    assert out[0].type == MessageType.PLUGIN_CALL
    data = _contents(out[0])[0]["data"]
    assert data == {"call_id": "c1", "name": "f", "arguments": "raw"}


def test_tool_call_dict_input_is_json_serialised() -> None:
    # ToolCallBlock.input is typed str, so a dict only arrives from an
    # unvalidated caller; the converter must still serialise it.
    out = _convert(
        _unvalidated(
            [
                {
                    "type": "tool_call",
                    "id": "c2",
                    "name": "f",
                    "input": {"a": 1},
                },
            ],
        ),
    )
    assert _contents(out[0])[0]["data"]["arguments"] == json.dumps({"a": 1})


def test_tool_call_list_input_is_json_serialised() -> None:
    out = _convert(
        _unvalidated(
            [{"type": "tool_call", "id": "c3", "name": "f", "input": [1, 2]}],
        ),
    )
    assert _contents(out[0])[0]["data"]["arguments"] == json.dumps([1, 2])


def test_tool_call_unicode_input_keeps_characters() -> None:
    out = _convert(
        _unvalidated(
            [
                {
                    "type": "tool_call",
                    "id": "c4",
                    "name": "f",
                    "input": {"t": "中文"},
                },
            ],
        ),
    )
    assert "中文" in _contents(out[0])[0]["data"]["arguments"]


def test_tool_call_flushes_preceding_text_message() -> None:
    out = _convert(
        _msg(
            [
                {"type": "text", "text": "before"},
                {"type": "tool_call", "id": "c", "name": "f", "input": "i"},
            ],
        ),
    )
    assert [m.type for m in out] == [
        MessageType.MESSAGE,
        MessageType.PLUGIN_CALL,
    ]


def test_tool_result_string_output() -> None:
    out = _convert(
        _msg(
            [
                {
                    "type": "tool_result",
                    "id": "c",
                    "name": "f",
                    "output": "ok",
                },
            ],
        ),
    )
    assert out[0].type == MessageType.PLUGIN_CALL_OUTPUT
    data = _contents(out[0])[0]["data"]
    assert data["call_id"] == "c"
    assert data["output"] == "ok"
    # ToolResultBlock defaults state to "running"
    assert data["state"] == "running"


def test_tool_result_structured_output_is_json_serialised() -> None:
    out = _convert(
        _msg(
            [
                {
                    "type": "tool_result",
                    "id": "c",
                    "name": "f",
                    "output": [{"type": "text", "text": "hi"}],
                },
            ],
        ),
    )
    output = _contents(out[0])[0]["data"]["output"]
    assert isinstance(output, str)
    assert json.loads(output)[0]["text"] == "hi"


@pytest.mark.parametrize("state", ["success", "error", "running"])
def test_tool_result_state_is_exposed(state: str) -> None:
    out = _convert(
        _msg(
            [
                {
                    "type": "tool_result",
                    "id": "c",
                    "name": "f",
                    "output": "o",
                    "state": state,
                },
            ],
        ),
    )
    assert _contents(out[0])[0]["data"]["state"] == state


def test_tool_result_state_enum_is_unwrapped() -> None:
    class _State(Enum):
        SUCCESS = "success"

    out = _convert(
        _unvalidated(
            [
                {
                    "type": "tool_result",
                    "id": "c",
                    "name": "f",
                    "output": "o",
                    "state": _State.SUCCESS,
                },
            ],
        ),
    )
    assert _contents(out[0])[0]["data"]["state"] == "success"


def test_tool_result_flushes_preceding_message() -> None:
    out = _convert(
        _msg(
            [
                {"type": "text", "text": "before"},
                {"type": "tool_result", "id": "c", "name": "f", "output": "o"},
            ],
        ),
    )
    assert [m.type for m in out] == [
        MessageType.MESSAGE,
        MessageType.PLUGIN_CALL_OUTPUT,
    ]


def test_media_block_after_thinking_flushes_reasoning() -> None:
    out = _convert(
        _msg(
            [
                {"type": "thinking", "thinking": "r"},
                _data_block("image/png", type="base64", data="A"),
            ],
        ),
    )
    assert [m.type for m in out] == [
        MessageType.REASONING,
        MessageType.MESSAGE,
    ]


# ---------------------------------------------------------------------------
# original user content restoration
# ---------------------------------------------------------------------------
def test_original_user_content_replaces_rendered_text() -> None:
    msg = _msg(
        [{"type": "text", "text": "rendered"}],
        role="user",
        metadata={
            QWENPAW_USER_CONTENT_KEY: [{"type": "text", "text": "orig"}],
        },
    )
    out = _convert(msg)
    assert len(out) == 1
    assert [c["text"] for c in _contents(out[0])] == ["orig"]


def test_original_user_content_drops_empty_text_parts() -> None:
    msg = _msg(
        [{"type": "text", "text": "rendered"}],
        role="user",
        metadata={QWENPAW_USER_CONTENT_KEY: [{"type": "text", "text": ""}]},
    )
    out = _convert(msg)
    assert _contents(out[0]) == []


def test_invalid_original_user_content_falls_back_to_normal_path() -> None:
    msg = _msg(
        [{"type": "text", "text": "kept"}],
        role="user",
        metadata={QWENPAW_USER_CONTENT_KEY: [{"type": "not_a_real_type"}]},
    )
    out = _convert(msg)
    # ValidationError is swallowed -> the ordinary text block is rendered
    assert [c["text"] for c in _contents(out[0])] == ["kept"]


@pytest.mark.parametrize("content", ["not-a-list", [], None, 42])
def test_non_list_original_user_content_is_ignored(content) -> None:
    msg = _msg(
        [{"type": "text", "text": "kept"}],
        role="user",
        metadata={QWENPAW_USER_CONTENT_KEY: content},
    )
    out = _convert(msg)
    assert [c["text"] for c in _contents(out[0])] == ["kept"]


def test_original_user_content_ignored_for_assistant() -> None:
    msg = _msg(
        [{"type": "text", "text": "rendered"}],
        metadata={
            QWENPAW_USER_CONTENT_KEY: [{"type": "text", "text": "orig"}],
        },
    )
    out = _convert(msg)
    assert [c["text"] for c in _contents(out[0])] == ["rendered"]


def test_user_content_key_is_hidden_from_metadata() -> None:
    msg = _msg(
        [{"type": "text", "text": "t"}],
        role="user",
        metadata={
            QWENPAW_USER_CONTENT_KEY: [{"type": "text", "text": "o"}],
            "keep": 1,
        },
    )
    out = _convert(msg)
    meta = out[0].metadata["metadata"]
    assert QWENPAW_USER_CONTENT_KEY not in meta
    assert meta["keep"] == 1


def test_metadata_carries_original_identity() -> None:
    msg = _msg([{"type": "text", "text": "t"}], role="assistant")
    out = _convert(msg)
    meta = out[0].metadata
    assert meta["original_name"] == "assistant"
    assert meta["original_id"] == msg.id
    assert meta["finished_at"] is None


# ---------------------------------------------------------------------------
# _is_local_file_url
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("", False),
        ("   ", False),
        (None, False),
        (123, False),
        ("http://x/y", False),
        ("HTTPS://x/y", False),
        ("data:image/png;base64,A", False),
        ("//host/share", False),
        ("file:///tmp/a", True),
        ("/tmp/a", True),
        ("C:/temp/a", True),
        ("c|/temp/a", False),  # second char is not ":"
        ("relative/path", False),
    ],
)
def test_is_local_file_url(url, expected: bool) -> None:
    assert _is_local_file_url(url) is expected


# ---------------------------------------------------------------------------
# _abspath_from_url
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("file:///tmp/a", "/tmp/a"),
        ("file://localhost/tmp/a", "/tmp/a"),
        # non-empty netloc that is not localhost keeps the UNC shape
        ("file://host/tmp/a", "//host/tmp/a"),
        # two-char netloc ending with ":" is a Windows drive -> drop "//"
        ("file://C:/tmp/a", "C:/tmp/a"),
        ("file://c|/tmp/a", "//c|/tmp/a"),
        # non file: urls are only percent-decoded
        ("/tmp/a", "/tmp/a"),
        ("file://%2Ftmp%2Fa", "///tmp/a"),
    ],
)
def test_abspath_from_url(url: str, expected: str) -> None:
    assert _abspath_from_url(url) == expected


def test_abspath_from_url_strips_windows_drive_uri_prefix() -> None:
    assert _abspath_from_url("file:///C:/temp/a") == "C:/temp/a"


def test_abspath_from_url_percent_decodes_spaces() -> None:
    assert _abspath_from_url("file:///tmp/a%20b.md") == "/tmp/a b.md"


# ---------------------------------------------------------------------------
# _resolve_content_url
# ---------------------------------------------------------------------------
def test_resolve_content_url_passes_remote_through() -> None:
    assert _resolve_content_url("https://x/y.png") == "https://x/y.png"


def test_resolve_content_url_reduces_local_file_url() -> None:
    assert _resolve_content_url("file:///tmp/a.png") == "/tmp/a.png"


def test_resolve_content_url_reduces_absolute_path() -> None:
    assert _resolve_content_url("/tmp/a.png") == "/tmp/a.png"


@pytest.mark.parametrize("value", [None, 123, ["a"]])
def test_resolve_content_url_non_string_is_returned_as_is(value) -> None:
    assert _resolve_content_url(value) is value


# ---------------------------------------------------------------------------
# build_env_context
# ---------------------------------------------------------------------------
def _env_context(tz: str = "UTC", **kw) -> str:
    with patch(
        "qwenpaw.app.chats.utils.load_config",
        return_value=SimpleNamespace(user_timezone=tz),
    ):
        return build_env_context(**kw)


def test_env_context_always_has_identity_and_date_lines() -> None:
    out = _env_context()
    assert out.startswith("====================\n")
    assert out.endswith("\n====================")
    assert "- GitHub: https://github.com/agentscope-ai/QwenPaw" in out
    assert "- Current date: " in out


def test_env_context_working_dir_without_project_dir() -> None:
    out = _env_context(working_dir="/work")
    assert "- Working directory: /work" in out
    assert "- Project directory" not in out
    assert "Agent workspace" not in out


def test_env_context_project_dir_with_different_working_dir() -> None:
    out = _env_context(project_dir="/proj", working_dir="/work")
    assert "here): /proj" in out
    assert "- Agent workspace (internal" in out
    assert "/work" in out
    # the plain working-directory line is replaced, not duplicated
    assert "- Working directory:" not in out


def test_env_context_project_dir_equal_to_working_dir() -> None:
    out = _env_context(project_dir="/same", working_dir="/same")
    assert "here): /same" in out
    assert "Agent workspace" not in out


def test_env_context_omits_working_dir_when_none() -> None:
    out = _env_context()
    assert "- Working directory:" not in out


def test_env_context_includes_shell_and_model_identity() -> None:
    out = _env_context(default_shell="/bin/sh", active_model_name="qwen-max")
    assert "- Default Shell: /bin/sh" in out
    assert "powered by qwen-max" in out


def test_env_context_includes_agent_identity_quoted() -> None:
    out = _env_context(agent_id="qpqat-beunit")
    assert '"qpqat-beunit"' in out
    assert "- Agent Identity:" in out


def test_env_context_request_specific_lines() -> None:
    out = _env_context(
        channel="console",
        user_name="Alice",
        user_id="u1",
        session_id="s1",
    )
    assert "- Channel: console" in out
    assert "- User Name: Alice" in out
    assert "- User ID: u1" in out
    assert "- Session ID: s1" in out


def test_env_context_omits_optional_request_lines() -> None:
    out = _env_context()
    assert "- Channel:" not in out
    assert "- User Name:" not in out
    assert "- User ID:" not in out
    assert "- Session ID:" not in out


def test_env_context_invalid_timezone_falls_back_to_utc() -> None:
    out = _env_context(tz="Mars/Olympus")
    assert "- Current date: " in out
    assert " UTC (" in out
    assert "Mars/Olympus" not in out
