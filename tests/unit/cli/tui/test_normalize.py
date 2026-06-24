# -*- coding: utf-8 -*-
"""Unit tests for the ACP-update → TuiEvent normalizer."""

from __future__ import annotations

# ``assert normalize_update(...) == []`` reads clearer than ``not ...`` here.
# pylint: disable=use-implicit-booleaness-not-comparison

import pytest

from acp import (
    start_tool_call,
    text_block,
    tool_content,
    update_agent_message,
    update_agent_thought,
    update_tool_call,
)
from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AvailableCommand,
    AvailableCommandsUpdate,
    PlanEntry,
    ResourceContentBlock,
    UsageUpdate,
)

from qwenpaw.cli.tui import events as E
from qwenpaw.cli.tui.normalize import normalize_update

pytestmark = [pytest.mark.unit, pytest.mark.p1]


def test_message_chunk_is_text_delta():
    out = normalize_update(update_agent_message(text_block("hi")))
    assert out == [E.TextDelta("hi")]


def test_empty_message_chunk_is_dropped():
    assert normalize_update(update_agent_message(text_block(""))) == []


def test_message_chunk_with_error_meta_is_transport_error():
    chunk = AgentMessageChunk(
        sessionUpdate="agent_message_chunk",
        content=text_block("Error: bad key"),
        field_meta={"qwenpaw.error": True},
    )
    assert normalize_update(chunk) == [E.TransportError("Error: bad key")]


def test_message_chunk_with_unrelated_meta_is_text():
    chunk = AgentMessageChunk(
        sessionUpdate="agent_message_chunk",
        content=text_block("hello"),
        field_meta={"other": 42},
    )
    assert normalize_update(chunk) == [E.TextDelta("hello")]


def test_usage_meta_chunk_is_token_usage():
    chunk = AgentMessageChunk(
        sessionUpdate="agent_message_chunk",
        content=text_block(""),
        field_meta={
            "usage": {
                "inputTokens": 1200,
                "outputTokens": 340,
                "totalTokens": 1540,
                "model": "qwen3.6-plus",
            },
        },
    )
    assert normalize_update(chunk) == [
        E.TokenUsage(
            input_tokens=1200,
            output_tokens=340,
            total_tokens=1540,
            model="qwen3.6-plus",
        ),
    ]


def test_thought_chunk():
    out = normalize_update(update_agent_thought(text_block("ponder")))
    assert out == [E.ThoughtDelta("ponder")]


def test_tool_call_start_and_update():
    start = normalize_update(
        start_tool_call("t1", "grep", kind="search", status="in_progress"),
    )
    assert start == [
        E.ToolCall(
            tool_call_id="t1",
            title="grep",
            kind="search",
            status="in_progress",
        ),
    ]

    done = normalize_update(
        update_tool_call(
            "t1",
            status="completed",
            content=[tool_content(text_block("3 hits"))],
        ),
    )
    assert len(done) == 1
    ev = done[0]
    assert ev.tool_call_id == "t1"
    assert ev.status == "completed"
    assert ev.output == "3 hits"


def test_tool_call_extracts_resource_link():
    # send_file_to_user → a text block + a resource_link content block.
    [ev] = normalize_update(
        update_tool_call(
            "t9",
            status="completed",
            content=[
                tool_content(text_block("File sent successfully.")),
                tool_content(
                    ResourceContentBlock(
                        type="resource_link",
                        uri="file:///tmp/report.pdf",
                        name="report.pdf",
                        mime_type="application/pdf",
                    ),
                ),
            ],
        ),
    )
    assert ev.output == "File sent successfully."
    assert ev.links == (
        E.FileLink(
            uri="file:///tmp/report.pdf",
            name="report.pdf",
            mime_type="application/pdf",
        ),
    )


def test_tool_call_without_links_has_empty_tuple():
    [ev] = normalize_update(
        update_tool_call(
            "t10",
            status="completed",
            content=[tool_content(text_block("plain output"))],
        ),
    )
    assert ev.links == ()


def test_tool_call_drops_non_local_link_schemes():
    # A buggy/hostile agent emitting an http(s) resource_link must not become a
    # one-click-openable FileLink; only file:// / local paths are surfaced.
    [ev] = normalize_update(
        update_tool_call(
            "t11",
            status="completed",
            content=[
                tool_content(
                    ResourceContentBlock(
                        type="resource_link",
                        uri="https://evil.example/login",
                        name="totally-a-file",
                    ),
                ),
            ],
        ),
    )
    assert ev.links == ()


def test_tool_call_renders_raw_input_params():
    [ev] = normalize_update(
        start_tool_call(
            "t2",
            "execute_shell_command",
            kind="execute",
            status="in_progress",
            raw_input={"command": "ls -la /tmp"},
        ),
    )
    assert ev.params == "command: ls -la /tmp"

    # Multi-key input renders one ``key: value`` line each; non-string
    # values are JSON-encoded.
    [multi] = normalize_update(
        start_tool_call(
            "t3",
            "grep",
            raw_input={"pattern": "TODO", "max": 5},
        ),
    )
    assert multi.params == "pattern: TODO\nmax: 5"


def test_plan_update():
    upd = AgentPlanUpdate(
        session_update="plan",
        entries=[
            PlanEntry(content="step 1", status="completed", priority="high"),
            PlanEntry(content="step 2", status="pending", priority="low"),
        ],
    )
    out = normalize_update(upd)
    assert len(out) == 1
    plan = out[0]
    assert isinstance(plan, E.PlanUpdate)
    assert [e.content for e in plan.entries] == ["step 1", "step 2"]
    assert plan.entries[0].status == "completed"


def test_usage_update():
    out = normalize_update(
        UsageUpdate(session_update="usage_update", used=1200, size=8000),
    )
    assert out == [E.Usage(used=1200, size=8000)]


def test_available_commands_update():
    upd = AvailableCommandsUpdate(
        session_update="available_commands_update",
        available_commands=[
            AvailableCommand(name="model", description="switch model"),
            AvailableCommand(name="agent", description=""),
        ],
    )
    out = normalize_update(upd)
    assert out == [
        E.AvailableCommands(
            commands=[
                E.SlashCommand(name="model", description="switch model"),
                E.SlashCommand(name="agent", description=""),
            ],
        ),
    ]


def test_session_info_update_is_session_title():
    from acp.schema import SessionInfoUpdate

    upd = SessionInfoUpdate(
        sessionUpdate="session_info_update",
        title="Fix the parser",
    )
    assert normalize_update(upd) == [E.SessionTitle("Fix the parser")]

    # No title → nothing surfaced.
    cleared = SessionInfoUpdate(sessionUpdate="session_info_update")
    assert normalize_update(cleared) == []


def test_unknown_update_is_empty():
    class Weird:
        session_update = "something_new"

    assert normalize_update(Weird()) == []
