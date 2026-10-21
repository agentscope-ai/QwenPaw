import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.formatter import DashScopeChatFormatter, OpenAIChatFormatter
from agentscope.message import (
    HintBlock,
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from agentscope.state import AgentState

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.runtime.conversation_context import project_conversation_context
from qwenpaw.runtime.message_convert import _request_input_to_msgs
from qwenpaw.schemas import Message, TextContent


def row(identity="spoken", text="BANANA_REFERENCE.txt", **extra):
    return dict(id=identity, source="voice", role="user", text=text) | extra


def handoff(rows, text="create it", *, target="", **flags):
    return _request_input_to_msgs(
        [Message(role="user", content=[TextContent(text=text)])],
        conversation_context=json.dumps(
            dict(available=True, omitted=False, messages=rows) | flags,
            ensure_ascii=False,
        ),
        input_target=target,
    )


def text_of(messages):
    return "\n".join(
        block.hint if block.type == "hint" else block.text
        for message in messages
        for block in message.content
        if block.type in {"hint", "text"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "formatter", [DashScopeChatFormatter, OpenAIChatFormatter]
)
async def test_agent_boundary_preserves_tool_result_and_only_missing_voice(
    formatter,
):
    original = Msg(
        id="original",
        name="user",
        role="user",
        content=[TextBlock(text="ORIGINAL_WORK")],
    )
    tool = Msg(
        name="assistant",
        role="assistant",
        content=[
            ToolCallBlock(
                id="tool-1",
                name="execute_shell_command",
                input='{"command":"synthetic"}',
            ),
            ToolResultBlock(
                id="tool-1",
                name="execute_shell_command",
                state="success",
                output=[TextBlock(text="TOOL_SUCCEEDED")],
            ),
        ],
    )
    rows = [
        row(),
        dict(id="original", source="user", role="user", text="ORIGINAL_WORK"),
        dict(
            id="progress",
            source="agent",
            role="assistant",
            text="STALE_PROGRESS",
        ),
    ]
    history = [
        original,
        tool,
        *handoff(rows, "FIRST_CORRECTION"),
        *handoff(rows, "SECOND_CORRECTION"),
    ]
    before = [m.model_dump() for m in history]
    agent = object.__new__(QwenPawAgent)
    agent.state = AgentState(context=history)
    agent.context_config = SimpleNamespace(compression_tool_enabled=False)
    agent._get_system_prompt = AsyncMock(return_value="Test")
    agent.toolkit = SimpleNamespace(
        get_tool_schemas=AsyncMock(return_value=[])
    )
    agent._run_input_mailbox = None
    prepared = await agent._prepare_model_input()
    wire = await formatter().format(prepared["messages"])
    encoded = json.dumps(wire)
    assert encoded.count("BANANA_REFERENCE.txt") == 1
    assert encoded.count("ORIGINAL_WORK") == 1
    assert "STALE_PROGRESS" not in encoded
    assert encoded.count("TOOL_SUCCEEDED") == 1
    assert encoded.count("FIRST_CORRECTION") == 1
    assert encoded.count("SECOND_CORRECTION") == 1
    assert next(i for i, m in enumerate(wire) if m["role"] == "tool") < next(
        i for i, m in enumerate(wire) if "SECOND_CORRECTION" in str(m)
    )
    assert [m.model_dump() for m in history] == before


def test_loaded_voice_covers_snapshots_but_compaction_recomputes_coverage():
    voice = Msg(
        id="spoken",
        name="user",
        role="user",
        content=[TextBlock(text="BANANA_REFERENCE.txt")],
    )
    snapshots = handoff([row()]) + handoff([row()], "repeat it explicitly")
    restored = [
        Msg.model_validate(m.model_dump()) for m in [voice, *snapshots]
    ]
    projected = project_conversation_context(restored)
    assert text_of(projected).count("BANANA_REFERENCE.txt") == 1
    assert not any(b.type == "hint" for m in projected for b in m.content)
    # No permanent consumed-ID set: a snapshot is still available after the
    # original message is removed from the next actual model context.
    after_compaction = project_conversation_context(restored[1:])
    assert text_of(after_compaction).count("BANANA_REFERENCE.txt") == 1
    assert any(b.type == "hint" for m in after_compaction for b in m.content)


def test_latest_revision_wins_and_explicit_repeats_remain():
    messages = handoff([row(text="OLD_NAME")], "repeat the work") + handoff(
        [row(text="NEW_NAME")], "repeat the work"
    )
    projected = project_conversation_context(messages)
    assert "OLD_NAME" not in text_of(projected)
    assert text_of(projected).count("NEW_NAME") == 1
    assert text_of(projected).count("repeat the work") == 2


@pytest.mark.parametrize("complete_first", [True, False])
def test_truncated_copy_cannot_replace_complete_reference(complete_first):
    complete = row(text="LONG_COMPLETE_FILENAME.txt", truncated=False)
    short = row(text="LONG_", truncated=True)
    versions = [complete, short] if complete_first else [short, complete]
    projected = project_conversation_context(
        sum((handoff([v]) for v in versions), [])
    )
    assert text_of(projected).count("LONG_COMPLETE_FILENAME.txt") == 1
    assert text_of(projected).count('"id":"spoken"') == 1


def test_input_target_and_unavailable_warning_survive_empty_projection():
    messages = handoff(
        [dict(id="old", source="agent", role="assistant", text="STALE")],
        target="TARGET_REFERENCE",
    )
    text = text_of(project_conversation_context(messages))
    assert "TARGET_REFERENCE" in text and "STALE" not in text
    unavailable = handoff([], available=False, omitted=True)
    assert '"available":false' in text_of(
        project_conversation_context(unavailable)
    )


def test_unknown_legacy_hint_shape_is_preserved():
    messages = [
        Msg(
            name="context",
            role="assistant",
            content=[
                HintBlock(source="chat_context", hint="Legacy reference")
            ],
        )
    ]
    assert project_conversation_context(messages) == messages


@pytest.mark.parametrize(
    "rows", [[{"text": "legacy"}], [row(source=[])], [row(role={})]]
)
def test_malformed_snapshot_is_not_silently_discarded(rows):
    messages = handoff(rows)
    assert project_conversation_context(messages) == messages
