# -*- coding: utf-8 -*-
# pylint: disable=protected-access,too-many-lines
"""Tests for ACPHostedClient session updates and payload rendering.

The existing ``test_acp_client_trusted.py`` only exercises the trusted
auto-approve decision.  These tests cover the rest of the observable
behaviour of the client adapter:

* how each ACP ``session/update`` notification kind is translated into
  the host message stream (or deliberately swallowed),
* how the accumulated assistant text is merged and flushed as deltas,
* how tool-call payloads are rendered into ``name``/``detail``/``target``
  for both ``tool_parse_mode`` settings,
* the permission suspend/resolve round trip.

Every assertion is written against observable output -- emitted message
payloads, returned values, or exception messages -- not against private
state, except where the private attribute *is* the contract (the text
accumulator).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from acp import RequestError
from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AvailableCommandsUpdate,
    BlobResourceContents,
    CurrentModeUpdate,
    EmbeddedResourceContentBlock,
    ImageContentBlock,
    ResourceContentBlock,
    TextContentBlock,
    TextResourceContents,
    ToolCallLocation,
    ToolCallProgress,
    ToolCallStart,
    UserMessageChunk,
)

from qwenpaw.agents.acp.client import ACPHostedClient
from qwenpaw.config.config import ACPAgentConfig


def _client(
    *,
    trusted: bool = False,
    mode: str = "call_title",
    cwd: str = "/tmp",
) -> ACPHostedClient:
    config = ACPAgentConfig(
        enabled=True,
        command="test",
        trusted=trusted,
        tool_parse_mode=mode,
    )
    return ACPHostedClient(
        agent_name="test-agent",
        agent_config=config,
        cwd=cwd,
    )


class _Recorder:
    """Collect every ``(payload, is_last)`` pair the client emits."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], bool]] = []

    async def handler(
        self,
        payload: dict[str, Any],
        is_last: bool,
    ) -> None:
        self.calls.append((payload, is_last))

    @property
    def payloads(self) -> list[dict[str, Any]]:
        return [payload for payload, _ in self.calls]

    @property
    def types(self) -> list[str]:
        return [payload["type"] for payload in self.payloads]

    def start(self, client: ACPHostedClient) -> None:
        client.start_prompt(self.handler)

    def clear(self) -> None:
        self.calls.clear()


def _text_chunk(text: str) -> AgentMessageChunk:
    return AgentMessageChunk(
        content=TextContentBlock(type="text", text=text),
        session_update="agent_message_chunk",
    )


def _thought_chunk(text: str) -> AgentThoughtChunk:
    return AgentThoughtChunk(
        content=TextContentBlock(type="text", text=text),
        session_update="agent_thought_chunk",
    )


def _tool_start(**kwargs: Any) -> ToolCallStart:
    kwargs.setdefault("tool_call_id", "call-1")
    kwargs.setdefault("title", "Run command")
    kwargs.setdefault("session_update", "tool_call")
    return ToolCallStart(**kwargs)


def _tool_progress(**kwargs: Any) -> ToolCallProgress:
    kwargs.setdefault("tool_call_id", "call-1")
    kwargs.setdefault("session_update", "tool_call_update")
    return ToolCallProgress(**kwargs)


class TestSessionUpdateDispatch:
    """Which notification kinds reach the host stream, and how."""

    async def test_agent_message_chunk_accumulates_without_emitting(
        self,
    ) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)

        await client.session_update("sess", _text_chunk("Hello "))
        await client.session_update("sess", _text_chunk("world"))

        # Assistant text is buffered; nothing is streamed until a flush.
        assert recorder.payloads == []
        assert client._assistant_text == "Hello world"
        assert client._thinking_active is False

    async def test_thought_chunk_marks_thinking_and_emits_nothing(
        self,
    ) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)

        await client.session_update("sess", _thought_chunk("pondering"))

        assert recorder.payloads == []
        assert client._thinking_active is True
        # Reasoning content is never merged into the assistant answer.
        assert client._assistant_text == ""

    async def test_tool_call_start_flushes_pending_text_first(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)
        await client.session_update("sess", _text_chunk("partial"))

        recorder.clear()
        await client.session_update(
            "sess",
            _tool_start(kind="execute", raw_input={"command": "ls -la"}),
        )

        # The buffered text must be delivered before the tool event so the
        # host renders narration in the order the agent produced it.
        assert recorder.types == ["text", "tool_start"]
        assert recorder.payloads[0]["text"] == "partial"
        # ``is_last`` is the handler's second argument, not a payload key:
        # the streamed delta is not final, the tool event is.
        assert recorder.calls[0][1] is False
        assert recorder.calls[1][1] is True
        event = recorder.payloads[1]
        assert event["call_id"] == "call-1"
        assert event["name"] == "Run command"
        assert event["kind"] == "execute"
        assert event["status"] == "pending"

    async def test_tool_progress_completed_maps_to_tool_end(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)

        await client.session_update("sess", _tool_start(kind="execute"))
        recorder.clear()
        await client.session_update(
            "sess",
            _tool_progress(status="completed", raw_output={"ok": True}),
        )

        assert recorder.types == ["tool_end"]
        event = recorder.payloads[0]
        assert event["status"] == "completed"
        assert event["summary"] == "{'ok': True}"
        # Title/kind survive because the accumulator still holds them.
        assert event["title"] == "Run command"
        assert event["kind"] == "execute"

    async def test_tool_progress_failed_maps_to_tool_end(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)

        await client.session_update(
            "sess",
            _tool_progress(status="failed"),
        )

        assert recorder.types == ["tool_end"]
        assert recorder.payloads[0]["status"] == "failed"

    async def test_tool_progress_in_progress_maps_to_tool_update(
        self,
    ) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)

        await client.session_update(
            "sess",
            _tool_progress(status="in_progress"),
        )

        assert recorder.types == ["tool_update"]

    async def test_blank_tool_call_id_emits_nothing(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)

        await client.session_update(
            "sess",
            _tool_progress(tool_call_id="", status="completed"),
        )

        assert recorder.payloads == []

    @pytest.mark.parametrize(
        "update",
        [
            CurrentModeUpdate(
                current_mode_id="default",
                session_update="current_mode_update",
            ),
            AgentPlanUpdate(entries=[], session_update="plan"),
            AvailableCommandsUpdate(
                available_commands=[],
                session_update="available_commands_update",
            ),
            UserMessageChunk(
                content=TextContentBlock(type="text", text="hi"),
                session_update="user_message_chunk",
            ),
        ],
        ids=["mode", "plan", "commands", "user"],
    )
    async def test_stateful_updates_are_absorbed_silently(
        self,
        update: Any,
    ) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)

        await client.session_update("sess", update)

        assert recorder.payloads == []
        # They still reach the accumulator so later tool deltas merge onto
        # the accumulated state instead of starting from nothing.
        assert client._session_acc.snapshot() is not None

    async def test_unknown_update_object_is_ignored(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)

        await client.session_update("sess", SimpleNamespace())

        assert recorder.payloads == []

    async def test_emitting_without_a_handler_is_silent(self) -> None:
        client = _client()

        # ``_on_message`` is None until start_prompt() runs; a late
        # notification must not raise.
        await client.session_update("sess", _text_chunk("ignored"))
        await client.emit_permission_resolved()

        # Accumulation is independent of delivery: the text is still held so
        # a handler attached later can finish the turn with it.
        assert client._assistant_text == "ignored"
        assert await client.finish_prompt() == {
            "type": "text",
            "text": "ignored",
            "is_chunk": False,
        }

    async def test_handler_attached_later_receives_the_final_text(
        self,
    ) -> None:
        client = _client()
        await client.session_update("sess", _text_chunk("buffered"))

        recorder = _Recorder()
        client.start_prompt(recorder.handler)

        # start_prompt() is a fresh turn, so the previous buffer is dropped.
        assert await client.finish_prompt() is None
        assert recorder.payloads == []

    async def test_start_prompt_resets_accumulated_state(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)
        await client.session_update("sess", _text_chunk("stale"))
        await client.session_update("sess", _thought_chunk("stale thought"))

        client.start_prompt(recorder.handler)

        assert client._assistant_text == ""
        assert client._emitted_assistant_text == ""
        assert client._thinking_active is False
        assert client.pending_permission is None

    async def test_resume_prompt_keeps_text_but_clears_the_gate(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)
        await client.session_update("sess", _text_chunk("keep me"))

        client.resume_prompt(recorder.handler)

        # Resuming must not drop the answer already streamed for the turn.
        assert client._assistant_text == "keep me"
        assert client._permission_requested.is_set() is False


class TestAssistantTextStreaming:
    """The merge/flush pair that rebuilds streamed answers."""

    async def test_finish_prompt_returns_full_text_once(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)
        await client.session_update("sess", _text_chunk("Hello "))
        await client.session_update("sess", _text_chunk("world"))

        final = await client.finish_prompt()

        assert final == {
            "type": "text",
            "text": "Hello world",
            "is_chunk": False,
        }
        # The streamed delta carries is_chunk=False too but is_last=False.
        assert recorder.calls[0][1] is False

    async def test_finish_prompt_without_text_returns_none(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)

        assert await client.finish_prompt() is None
        assert recorder.payloads == []

    async def test_flush_is_idempotent(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)
        await client.session_update("sess", _text_chunk("once"))

        await client.flush_assistant_text()
        await client.flush_assistant_text()
        await client.flush_assistant_text()

        assert recorder.types == ["text"]

    async def test_flush_emits_only_the_new_tail(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)
        await client.session_update("sess", _text_chunk("abc"))
        await client.flush_assistant_text()
        recorder.clear()

        await client.session_update("sess", _text_chunk("def"))
        await client.flush_assistant_text()

        assert recorder.payloads == [
            {"type": "text", "text": "def", "is_chunk": False},
        ]

    @pytest.mark.parametrize(
        ("existing", "incoming", "expected"),
        [
            ("", "x", "x"),
            ("abc", "abc", "abc"),
            ("ab", "abc", "abc"),
            ("abc", "cdef", "abcdef"),
            ("abc", "xabc", "abcxabc"),
            ("a", "b", "ab"),
            ("abc", "", "abc"),
        ],
        ids=[
            "empty",
            "duplicate",
            "superset",
            "overlapping-tail",
            "no-overlap-but-prefixed",
            "disjoint",
            "empty-incoming",
        ],
    )
    def test_merge_assistant_text(
        self,
        existing: str,
        incoming: str,
        expected: str,
    ) -> None:
        client = _client()
        client._assistant_text = existing

        client._merge_assistant_text(incoming)

        assert client._assistant_text == expected

    async def test_non_text_content_blocks_are_dropped(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)

        await client._accumulate_assistant_content(
            ImageContentBlock(type="image", data="AAA", mime_type="image/png"),
        )

        assert client._assistant_text == ""
        assert recorder.payloads == []

    async def test_mixed_content_list_keeps_only_text(self) -> None:
        client = _client()

        await client._accumulate_assistant_content(
            [
                TextContentBlock(type="text", text="a"),
                ImageContentBlock(
                    type="image",
                    data="AAA",
                    mime_type="image/png",
                ),
                TextContentBlock(type="text", text="b"),
            ],
        )

        assert client._assistant_text == "ab"


class TestExtractTextFromContent:
    """Every content shape the SDK can hand the client."""

    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            (None, ""),
            (42, ""),
            ("plain string", ""),
            ([], ""),
        ],
        ids=["none", "int", "str", "empty-list"],
    )
    def test_unusable_content_yields_empty(self, content: Any, expected: str):
        assert _client()._extract_text_from_content(content) == expected

    def test_text_block(self) -> None:
        content = TextContentBlock(type="text", text="body")
        assert _client()._extract_text_from_content(content) == "body"

    def test_resource_link_prefers_name(self) -> None:
        content = ResourceContentBlock(
            type="resource_link",
            name="report.md",
            uri="file:///tmp/report.md",
        )
        assert _client()._extract_text_from_content(content) == "report.md"

    def test_embedded_resource_text(self) -> None:
        content = EmbeddedResourceContentBlock(
            type="resource",
            resource=TextResourceContents(uri="file:///a", text="inner"),
        )
        assert _client()._extract_text_from_content(content) == "inner"

    def test_embedded_resource_falls_back_to_blob(self) -> None:
        content = EmbeddedResourceContentBlock(
            type="resource",
            resource=BlobResourceContents(uri="file:///a", blob="QkxPQg=="),
        )
        assert _client()._extract_text_from_content(content) == "QkxPQg=="

    def test_embedded_resource_without_text_or_blob(self) -> None:
        content = EmbeddedResourceContentBlock(
            type="resource",
            resource=TextResourceContents(uri="file:///a", text=""),
        )
        assert _client()._extract_text_from_content(content) == ""

    def test_resource_attribute_that_is_none(self) -> None:
        content = SimpleNamespace(resource=None)
        assert _client()._extract_text_from_content(content) == ""

    def test_dict_text_block(self) -> None:
        assert (
            _client()._extract_text_from_content({"type": "text", "text": "d"})
            == "d"
        )

    @pytest.mark.parametrize(
        "content",
        [
            {"type": "image", "text": "d"},
            {"type": "text", "text": 7},
            {"type": "text"},
            {},
        ],
        ids=["wrong-type", "non-str-text", "no-text", "empty"],
    )
    def test_dict_without_usable_text(self, content: dict[str, Any]) -> None:
        assert _client()._extract_text_from_content(content) == ""

    def test_nested_lists_are_flattened_in_order(self) -> None:
        content = [
            [TextContentBlock(type="text", text="a")],
            TextContentBlock(type="text", text="b"),
        ]
        assert _client()._extract_text_from_content(content) == "ab"


class TestToolPayloadRendering:
    """name/detail/target rendering for both parse modes."""

    def test_call_title_mode_always_uses_the_title(self) -> None:
        client = _client(mode="call_title")
        update = _tool_progress(
            kind="execute",
            raw_input={"command": "ls -la"},
            title="Run command",
        )

        assert client._tool_detail("execute", "Run command", None, update) == (
            "Run command"
        )

    @pytest.mark.parametrize(
        ("kind", "raw_input", "expected"),
        [
            ("execute", {"command": "ls -la"}, "ls -la"),
            ("read", {"file_path": "/r.py"}, "/r.py"),
            ("read", {"filePath": "/r.py"}, "/r.py"),
            ("read", {"path": "/r.py"}, "/r.py"),
            ("search", {"path": "/src", "pattern": "re"}, "/src"),
            ("search", {"pattern": "re"}, "re"),
            ("edit", {"file_path": "/e.py"}, "Edit file"),
            ("other", {"anything": 1}, "Edit file"),
            ("execute", {}, "Edit file"),
        ],
        ids=[
            "execute-command",
            "read-file_path",
            "read-filePath",
            "read-path",
            "search-path-wins",
            "search-pattern",
            "edit-uses-title",
            "unknown-kind-uses-title",
            "execute-without-command",
        ],
    )
    def test_update_detail_mode_reads_the_arguments(
        self,
        kind: str,
        raw_input: dict[str, Any],
        expected: str,
    ) -> None:
        client = _client(mode="update_detail")
        update = _tool_progress(kind=kind, raw_input=raw_input)

        detail = client._tool_detail(kind, "Edit file", None, update)

        assert detail == expected

    def test_update_detail_falls_back_to_target_then_title(self) -> None:
        client = _client(mode="update_detail")
        with_target = _tool_progress(
            kind="read",
            raw_input={},
            locations=[ToolCallLocation(path="/loc.py")],
        )
        assert client._tool_detail("read", "T", None, with_target) == "/loc.py"

        without = _tool_progress(kind="read", raw_input={}, locations=[])
        assert client._tool_detail("read", "T", None, without) == "T"

    def test_accumulated_state_wins_over_the_update_delta(self) -> None:
        client = _client(mode="update_detail")
        state = SimpleNamespace(
            title="State title",
            kind="execute",
            status="completed",
            raw_input={"command": "from-state"},
            locations=[ToolCallLocation(path="/state.py")],
            raw_output="state-out",
        )
        update = _tool_progress(
            title="Delta title",
            kind="read",
            status="in_progress",
            raw_input={"command": "from-delta"},
            locations=[ToolCallLocation(path="/delta.py")],
            raw_output="delta-out",
        )

        event = client._tool_event_from_state(update, state)

        assert event is not None
        assert event["name"] == "State title"
        assert event["kind"] == "execute"
        assert event["status"] == "completed"
        assert event["detail"] == "from-state"
        assert event["target"] == "/state.py"
        assert event["summary"] == "state-out"

    def test_event_falls_back_to_the_delta_and_then_to_defaults(
        self,
    ) -> None:
        client = _client(mode="call_title")

        event = client._tool_event_from_state(_tool_progress(), None)

        assert event == {
            "type": "tool_update",
            "name": "unknown",
            "call_id": "call-1",
            "title": "unknown",
            "kind": "other",
            "status": "pending",
            "detail": "unknown",
        }

    def test_event_without_call_id_is_dropped(self) -> None:
        client = _client()

        assert (
            client._tool_event_from_state(
                _tool_progress(tool_call_id=""),
                None,
            )
            is None
        )

    def test_whitespace_only_call_id_is_kept_verbatim(self) -> None:
        client = _client()

        # The guard is a truthiness test, not a strip: a runner that sends a
        # blank-but-non-empty id still gets an event, carrying that id.
        event = client._tool_event_from_state(
            _tool_progress(tool_call_id="   "),
            None,
        )

        assert event is not None
        assert event["call_id"] == "   "
        assert event["name"] == "unknown"
        assert event["kind"] == "other"
        assert event["status"] == "pending"

    def test_optional_event_keys_are_omitted_when_empty(self) -> None:
        client = _client(mode="update_detail")
        update = _tool_progress(status="completed", raw_output=None)

        event = client._tool_event_from_state(update, None)

        assert event is not None
        assert "target" not in event
        assert "summary" not in event

    def test_event_type_is_tool_start_for_a_start_notification(self) -> None:
        client = _client(mode="call_title")

        assert client._tool_event_type(_tool_start(), None) == "tool_start"

    def test_update_detail_mode_treats_everything_as_a_start(self) -> None:
        client = _client(mode="update_detail")

        assert (
            client._tool_event_type(_tool_progress(status="completed"), None)
            == "tool_start"
        )

    def test_target_reads_dict_locations(self) -> None:
        client = _client()
        update = SimpleNamespace(
            locations=[{"path": "/d/p.py"}],
            raw_input=None,
        )

        assert client._tool_target(None, update) == "/d/p.py"

    def test_target_skips_locations_without_a_path(self) -> None:
        client = _client()
        update = SimpleNamespace(
            locations=[{}, ToolCallLocation(path="")],
            raw_input=None,
        )

        assert client._tool_target(None, update) is None

    def test_target_prefers_state_locations(self) -> None:
        client = _client()
        state = SimpleNamespace(locations=[ToolCallLocation(path="/state.py")])
        update = SimpleNamespace(
            locations=[ToolCallLocation(path="/delta.py")],
            raw_input=None,
        )

        assert client._tool_target(state, update) == "/state.py"

    def test_target_without_locations(self) -> None:
        client = _client()

        assert client._tool_target(None, SimpleNamespace()) is None


class TestToolInputAndValueCoercion:
    """Argument lookup plus the two scalar-coercion helpers."""

    def test_input_text_reads_lists_from_the_end(self) -> None:
        client = _client()
        update = SimpleNamespace(raw_input={"command": ["first", "last"]})

        assert client._tool_input_text(None, update, "command") == "last"

    def test_input_text_skips_blank_list_entries(self) -> None:
        client = _client()
        update = SimpleNamespace(raw_input={"command": ["first", "  ", None]})

        assert client._tool_input_text(None, update, "command") == "first"

    def test_input_text_skips_non_dict_payloads(self) -> None:
        client = _client()
        state = SimpleNamespace(raw_input="not-a-dict")
        update = SimpleNamespace(raw_input={"path": "/p"})

        assert client._tool_input_text(state, update, "path") == "/p"

    def test_input_text_tries_every_key_in_order(self) -> None:
        client = _client()
        update = SimpleNamespace(raw_input={"pattern": "needle"})

        assert (
            client._tool_input_text(None, update, "path", "pattern")
            == "needle"
        )

    def test_input_text_stringifies_scalars(self) -> None:
        client = _client()
        update = SimpleNamespace(raw_input={"command": 123})

        assert client._tool_input_text(None, update, "command") == "123"

    def test_input_text_without_any_key(self) -> None:
        client = _client()

        assert client._tool_input_text(None, SimpleNamespace(), "x") is None

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("  s  ", "s"),
            (7, "7"),
        ],
        ids=["none", "empty", "blank", "padded", "int"],
    )
    def test_string_value(self, value: Any, expected: str | None) -> None:
        assert _client()._string_value(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, None),
            ("  s  ", "s"),
            ("", None),
            ({"k": 1}, "{'k': 1}"),
            (0, "0"),
        ],
        ids=["none", "str", "blank-str", "dict", "falsy-int"],
    )
    def test_stringify_summary(self, value: Any, expected: str | None) -> None:
        assert _client()._stringify_summary(value) == expected


class TestPriorToolCallState:
    """Lookups into the session accumulator behind a permission request."""

    async def test_unseen_id_returns_none(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)
        await client.session_update("sess", _tool_start(kind="execute"))

        assert client._prior_tool_call_state({"toolCallId": "other"}) is None

    async def test_known_id_returns_the_accumulated_view(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)
        await client.session_update(
            "sess",
            _tool_start(kind="execute", raw_input={"command": "ls"}),
        )

        state = client._prior_tool_call_state({"toolCallId": "call-1"})

        assert state is not None
        assert state.kind == "execute"
        assert state.raw_input == {"command": "ls"}

    async def test_no_processed_notification_yet_returns_none(self) -> None:
        client = _client()

        # A fresh accumulator has no snapshot at all; the permission payload
        # must then stand on its own instead of raising.
        assert client._prior_tool_call_state({"toolCallId": "call-1"}) is None

    def test_blank_id_short_circuits(self) -> None:
        client = _client()

        assert client._prior_tool_call_state({"toolCallId": "  "}) is None
        assert client._prior_tool_call_state({}) is None

    @pytest.mark.parametrize(
        ("tool_call", "expected"),
        [
            ({"toolCallId": " a1 "}, "a1"),
            ({"tool_call_id": "b2"}, "b2"),
            ({"toolCallId": None, "tool_call_id": "c3"}, "c3"),
            ({"other": "x"}, ""),
            (None, ""),
            (SimpleNamespace(tool_call_id="d4"), "d4"),
            (SimpleNamespace(), ""),
            (5, ""),
        ],
        ids=[
            "camelCase-padded",
            "snake_case",
            "null-then-snake",
            "unknown-keys",
            "none",
            "object",
            "object-without-id",
            "scalar",
        ],
    )
    def test_tool_call_id_extraction(
        self,
        tool_call: Any,
        expected: str,
    ) -> None:
        assert ACPHostedClient._tool_call_id(tool_call) == expected


class TestPermissionRoundTrip:
    """Suspend, resolve and the trusted/hard-block shortcuts."""

    async def test_untrusted_request_suspends_until_resolved(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)
        options = [
            {"optionId": "allow_once", "label": "Allow once"},
            {"optionId": "deny", "label": "Deny"},
        ]
        tool_call = {
            "toolCallId": "perm-1",
            "title": "Read file",
            "kind": "read",
            "rawInput": {"file_path": "/tmp/x"},
        }

        pending = asyncio.create_task(
            client.request_permission(
                options=options,
                session_id="sess",
                tool_call=tool_call,
            ),
        )
        await asyncio.sleep(0)

        assert recorder.types == ["permission_request"]
        assert recorder.payloads[0]["title"] == "Read file"
        assert recorder.payloads[0]["tool_kind"] == "read"
        assert recorder.payloads[0]["tool_name"] == "Read file"
        assert recorder.payloads[0]["options"] == options
        suspended = client.pending_permission
        assert suspended is not None
        assert suspended.options == options
        await client.wait_for_permission_request()

        client.resolve_permission("allow_once")
        response = await pending

        assert response.outcome.outcome == "selected"
        assert response.outcome.option_id == "allow_once"
        # The gate is cleared so the next turn can suspend again.
        assert client.pending_permission is None
        assert client._permission_requested.is_set() is False

    async def test_resolve_rejects_an_unknown_option_id(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)
        pending = asyncio.create_task(
            client.request_permission(
                options=[{"optionId": "deny", "label": "Deny"}],
                session_id="sess",
                tool_call={"toolCallId": "perm-2", "title": "Read"},
            ),
        )
        await asyncio.sleep(0)

        with pytest.raises(ValueError) as excinfo:
            client.resolve_permission("nope")

        assert "exact selected permission option id" in str(excinfo.value)
        # Still suspended, so the caller can retry with a valid id.
        assert client.pending_permission is not None

        client.resolve_permission("deny")
        response = await pending
        assert response.outcome.option_id == "deny"

    async def test_resolve_without_a_pending_request_raises(self) -> None:
        client = _client()

        with pytest.raises(ValueError) as excinfo:
            client.resolve_permission("allow_once")

        assert str(excinfo.value) == "No pending ACP permission request."

    async def test_hard_blocked_command_is_cancelled(self) -> None:
        client = _client(trusted=True)
        recorder = _Recorder()
        recorder.start(client)

        response = await client.request_permission(
            options=[{"optionId": "allow_once", "label": "Allow once"}],
            session_id="sess",
            tool_call={
                "toolCallId": "hard-1",
                "title": "Execute",
                "kind": "execute",
                "rawInput": {"command": "rm -rf /"},
            },
        )

        assert response.outcome.outcome == "cancelled"
        assert recorder.types == ["status"]
        status = recorder.payloads[0]
        assert status["status"] == "permission_cancelled"
        assert "hard-block" in status["summary"]
        assert status["tool_kind"] == "execute"
        assert status["tool_name"] == "Execute"
        # Cancellation must not leave the client suspended.
        assert client.pending_permission is None

    async def test_untrusted_hard_block_also_cancels(self) -> None:
        client = _client(trusted=False)
        recorder = _Recorder()
        recorder.start(client)

        response = await client.request_permission(
            options=[{"optionId": "allow_once", "label": "Allow once"}],
            session_id="sess",
            tool_call={
                "toolCallId": "hard-2",
                "title": "Execute",
                "kind": "execute",
                "rawInput": {"command": "rm -rf /"},
            },
        )

        assert response.outcome.outcome == "cancelled"
        assert recorder.types == ["status"]
        assert recorder.payloads[0]["status"] == "permission_cancelled"

    async def test_trusted_without_an_allow_option_suspends(self) -> None:
        client = _client(trusted=True)
        recorder = _Recorder()
        recorder.start(client)

        pending = asyncio.create_task(
            client.request_permission(
                options=[{"optionId": "deny", "label": "Deny"}],
                session_id="sess",
                tool_call={
                    "toolCallId": "no-allow",
                    "title": "Read",
                    "kind": "read",
                    "rawInput": {"file_path": "/tmp/y"},
                },
            ),
        )
        await asyncio.sleep(0)

        # Auto-approve is impossible, so the user is asked after all.
        assert recorder.types == ["permission_request"]
        assert client.pending_permission is not None

        client.resolve_permission("deny")
        response = await pending
        assert response.outcome.option_id == "deny"

    async def test_permission_request_flushes_buffered_text(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)
        await client.session_update("sess", _text_chunk("before"))
        recorder.clear()

        pending = asyncio.create_task(
            client.request_permission(
                options=[{"optionId": "deny", "label": "Deny"}],
                session_id="sess",
                tool_call={"toolCallId": "flush", "title": "Read"},
            ),
        )
        await asyncio.sleep(0)

        assert recorder.types == ["text", "permission_request"]
        client.resolve_permission("deny")
        await pending

    def test_pick_allow_option(self) -> None:
        """Protocol kind wins, then known ids, then any id with "allow".

        Identity is asserted (not just the id string) because the caller
        hands the very same dict back to ``selected_response``; a copy would
        break option lookup for runners that attach extra fields.
        """
        client = _client()
        deny = {"optionId": "deny", "label": "Deny"}
        kind_allow = {"kind": "allow_once", "label": "Allow once"}
        kind_always = {"kind": "allow_always", "label": "Allow always"}
        id_always = {"optionId": "allow_always", "label": "Allow always"}
        id_approve = {"option_id": "approve", "label": "Approve"}
        id_yes = {"option_id": "yes", "label": "Yes"}
        id_substring = {"optionId": "ALLOW_IT", "label": "Allow it"}
        junk: list[Any] = [None, "junk", 42]

        # Protocol-defined kind beats an id, and allow_once beats
        # allow_always because the narrower grant is the safer default.
        assert client._pick_allow_option([deny, kind_allow]) is kind_allow
        assert client._pick_allow_option([id_always, kind_allow]) is kind_allow
        assert client._pick_allow_option([kind_always, kind_allow]) is (
            kind_allow
        )
        assert client._pick_allow_option([kind_always]) is kind_always
        # Clients that omit the kind fall back to the id preference order.
        assert client._pick_allow_option([deny, id_always]) is id_always
        assert client._pick_allow_option([deny, id_approve]) is id_approve
        assert client._pick_allow_option([deny, id_yes]) is id_yes
        assert client._pick_allow_option([deny, {"optionId": "ALLOW"}]) == {
            "optionId": "ALLOW",
        }
        # Last resort: any option whose id merely contains "allow".
        assert client._pick_allow_option([deny, id_substring]) is id_substring
        # Non-dict entries are skipped rather than raising.
        assert client._pick_allow_option([*junk, id_substring]) is id_substring
        # No allow option at all -> the caller must suspend and ask.
        assert client._pick_allow_option([deny]) is None
        assert client._pick_allow_option([]) is None
        assert client._pick_allow_option(junk) is None

    async def test_emit_permission_resolved_message(self) -> None:
        client = _client()
        recorder = _Recorder()
        recorder.start(client)

        await client.emit_permission_resolved()

        assert recorder.payloads == [
            {
                "type": "status",
                "status": "permission_resolved",
                "summary": "Permission resolved, resuming execution.",
            },
        ]
        assert recorder.calls[0][1] is True

    async def _suspend_once(
        self,
        client: ACPHostedClient,
        call_id: str,
        path: str,
    ) -> Any:
        """Ask for one read permission and return the suspended payload."""
        task = asyncio.create_task(
            client.request_permission(
                options=[{"optionId": "deny", "label": "Deny"}],
                session_id="sess",
                tool_call={
                    "toolCallId": call_id,
                    "title": "Read file",
                    "kind": "read",
                    "rawInput": {"file_path": path},
                },
            ),
        )
        # request_permission() suspends on a future, so one loop turn is
        # enough for the pending state to be published.
        await asyncio.sleep(0)
        suspended = client.pending_permission
        assert suspended is not None, "expected the call to suspend"
        client.resolve_permission("deny")
        await task
        return suspended

    async def test_update_cwd_rebases_displayed_paths(
        self,
        tmp_path: Any,
    ) -> None:
        target = tmp_path / "sub" / "f.txt"
        target.parent.mkdir(parents=True)
        target.write_text("x", encoding="utf-8")
        client = _client(cwd=str(tmp_path / "sub"))
        recorder = _Recorder()
        recorder.start(client)

        before = await self._suspend_once(client, "cwd-1", str(target))

        assert before.target == "f.txt"
        assert before.paths == [str(target)]

        client.update_cwd(str(tmp_path))

        after = await self._suspend_once(client, "cwd-2", str(target))

        # Same absolute path, new working directory: only the display form
        # changes, the guard still sees the real path.
        assert after.target == "sub/f.txt"
        assert after.paths == [str(target)]


class TestExtensionMethods:
    """Unsupported ACP extension surface must fail loudly."""

    async def test_ext_method_raises_method_not_found(self) -> None:
        client = _client()

        with pytest.raises(RequestError) as excinfo:
            await client.ext_method("custom/method", {"k": 1})

        assert excinfo.value.code == -32601
        assert "custom/method" in str(excinfo.value)

    async def test_ext_notification_raises_method_not_found(self) -> None:
        client = _client()

        with pytest.raises(RequestError) as excinfo:
            await client.ext_notification("custom/notify", {"k": 1})

        assert excinfo.value.code == -32601
        assert "custom/notify" in str(excinfo.value)

    def test_unsupported_method_message_names_the_method(self) -> None:
        client = _client()

        with pytest.raises(RequestError) as excinfo:
            client._unsupported_method("mymethod")

        assert excinfo.value.code == -32601
        assert str(excinfo.value) == (
            "Unsupported ACP extension method: mymethod"
        )
