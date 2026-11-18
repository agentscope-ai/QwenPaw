# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for DoomLoopGate auto-recording from the agent context.

Every message written during one reply carries the same ``state.reply_id``,
so the gate must deduplicate on the tool-call block id instead of the
message id; otherwise it records at most one call per reply and can never
fill its window.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.config.config import DoomLoopStageConfig
from qwenpaw.loop.gates.base import StopAction
from qwenpaw.loop.gates.doom_loop import DoomLoopGate


def _stage(after, action="stop", prompt="stop"):
    return DoomLoopStageConfig(
        after=after,
        action=action,
        prompt=prompt,
    )


def _msg(msg_id, blocks):
    return SimpleNamespace(id=msg_id, role="assistant", content=list(blocks))


def _call(block_id, name="Bash", arguments='{"command": "python probe.py"}'):
    return SimpleNamespace(
        type="tool_call",
        id=block_id,
        name=name,
        input=arguments,
    )


def _result(block_id, name="Bash", output="exit code 15"):
    return SimpleNamespace(
        type="tool_result",
        id=block_id,
        name=name,
        output=output,
    )


class _Agent:
    def __init__(self, context):
        self.state = SimpleNamespace(context=context)


def _ctx(agent, has_tool_calls=True):
    return {
        "agent": agent,
        "final_msg": None,
        "iteration": 0,
        "has_tool_calls": has_tool_calls,
    }


@pytest.fixture(autouse=True)
def _force_session_id():
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="test-session",
    ):
        yield


@pytest.fixture()
def gate():
    g = DoomLoopGate(
        window_size=3,
        similarity_threshold=0.5,
        stages=[_stage(3, "stop", "doom stop")],
    )
    g.activate(None)
    g._ensure_state()
    return g


@pytest.mark.asyncio
async def test_repeated_calls_in_one_reply_reach_the_stage(gate):
    """Three iterations of one reply must fill the window and stop.

    All three messages share the id ``reply-1``; only the block ids differ.
    """
    context = [_msg("reply-1", [])]
    for index in range(3):
        context[-1].content.append(_call(f"call-{index}"))
        context[-1].content.append(_result(f"call-{index}"))
        result = await gate.check(_ctx(_Agent(context)))

    assert result.action == StopAction.TERMINATE
    assert len(gate._state().history) == 3


@pytest.mark.asyncio
async def test_same_block_is_recorded_once(gate):
    """Re-checking the same message does not grow the history."""
    context = [_msg("reply-1", [_call("call-0"), _result("call-0")])]
    for _ in range(4):
        result = await gate.check(_ctx(_Agent(context)))

    assert result.action == StopAction.BYPASS
    assert len(gate._state().history) == 1


@pytest.mark.asyncio
async def test_blocks_of_one_iteration_are_all_recorded(gate):
    """A parallel tool-call iteration records every block it contains."""
    context = [
        _msg(
            "reply-1",
            [
                _call("call-a"),
                _call("call-b"),
                _call("call-c", arguments='{"command": "other"}'),
            ],
        ),
    ]
    await gate.check(_ctx(_Agent(context)))

    # Calls wait in the id map until their result arrives, so the history
    # (completed calls only) stays empty here.
    assert len(gate._state().recorded_calls) == 3
    assert len(gate._state().history) == 0


@pytest.mark.asyncio
async def test_text_iteration_is_not_recorded(gate):
    """A text-only iteration carries no tool calls to record."""
    context = [_msg("reply-1", [_call("call-0")])]
    await gate.check(_ctx(_Agent(context), has_tool_calls=False))

    assert len(gate._state().history) == 0


@pytest.mark.asyncio
async def test_blocks_without_id_are_still_recorded(gate):
    """A dict block without an id is recorded once by the scan offset."""
    block = {"type": "tool_call", "name": "Bash", "input": "{}"}
    context = [_msg("reply-1", [block])]
    await gate.check(_ctx(_Agent(context)))
    await gate.check(_ctx(_Agent(context)))

    assert len(gate._state().recorded_calls) == 1


@pytest.mark.asyncio
async def test_distinct_calls_do_not_trip_the_gate(gate):
    """Three different calls are not a repetition."""
    context = [_msg("reply-1", [])]
    for index in range(3):
        context[-1].content.append(
            _call(f"call-{index}", arguments=f'{{"command": "cmd-{index}"}}'),
        )
        result = await gate.check(_ctx(_Agent(context)))

    assert result.action == StopAction.BYPASS


def test_reset_clears_recorded_calls(gate):
    """reset_turn() forgets which calls this turn already recorded."""
    state = gate._ensure_state()
    gate._record_call(state, "Bash", "deadbeef", "call-0")
    gate.reset_turn()

    state = gate._ensure_state()
    assert state.recorded_calls == {}


@pytest.mark.asyncio
async def test_a_new_message_with_the_same_reply_id_is_scanned(gate):
    """The scan offset belongs to one message, not to the whole reply.

    A warning inserts a user message, so the next reasoning step writes a
    fresh assistant message that still carries ``reply-1``. The previous
    message had four blocks, so four fresh calls in a five-block message
    were skipped: the offset said everything was already recorded.
    """
    context = [_msg("reply-1", [])]
    for index in range(4):
        context[-1].content.append(_call(f"first-{index}"))
    await gate.check(_ctx(_Agent(context)))
    assert len(gate._state().recorded_calls) == 4

    context.append(
        _msg("reply-1", [SimpleNamespace(type="text", text="thinking")]),
    )
    for index in range(4):
        context[-1].content.append(_call(f"second-{index}"))
    await gate.check(_ctx(_Agent(context)))

    assert len(gate._state().recorded_calls) == 8


@pytest.mark.asyncio
async def test_an_advancing_poll_is_not_a_doom_loop(gate):
    """Identical status checks whose output moves are progress.

    The default stop compares tool names and arguments, so a background task
    polled with the same command was terminated on the fourth check even
    though it kept reporting progress.
    """
    context = [_msg("reply-1", [])]
    result = None
    for index in range(4):
        context[-1].content.append(
            _call(f"poll-{index}", arguments='{"command": "status"}'),
        )
        context[-1].content.append(
            _result(f"poll-{index}", output=f"progress {index + 1}/8"),
        )
        result = await gate.check(_ctx(_Agent(context)))

    assert result is not None
    assert result.action == StopAction.BYPASS
    assert len(gate._state().history) == 4


@pytest.mark.asyncio
async def test_repeated_failures_still_stop(gate):
    """A poll that keeps failing on the same output is still a loop."""
    context = [_msg("reply-1", [])]
    result = None
    for index in range(4):
        context[-1].content.append(
            _call(f"poll-{index}", arguments='{"command": "status"}'),
        )
        context[-1].content.append(
            _result(f"poll-{index}", output="connection refused"),
        )
        result = await gate.check(_ctx(_Agent(context)))

    assert result is not None
    assert result.action == StopAction.TERMINATE


def _gate_with_defaults():
    """A gate configured like the shipped default stop."""
    gate = DoomLoopGate(
        window_size=3,
        similarity_threshold=1.0,
        stages=[_stage(4, "stop", "doom stop")],
    )
    gate.activate(None)
    gate._ensure_state()
    return gate


@pytest.mark.asyncio
async def test_stops_under_the_default_configuration_before_the_result_arrives():
    """The runner checks the gate before the pending call returns.

    With one call per iteration the newest record has no result yet, so the
    window is ``(H, H, None)``. Counting that ``None`` as a distinct signature
    caps the similarity at 0.5, and the repository default of 1.0 then never
    matches: the gate keeps running while the parent stopped on the fourth
    call.
    """
    gate = _gate_with_defaults()

    context = [_msg("reply-1", [])]
    result = None
    for index in range(5):
        # The call is appended before it runs; its result arrives afterwards.
        context[-1].content.append(_call(f"call-{index}"))
        result = await gate.check(_ctx(_Agent(context)))
        if index < 4:
            assert result.action == StopAction.BYPASS
            context[-1].content.append(_result(f"call-{index}"))

    assert result is not None
    assert result.action == StopAction.TERMINATE


@pytest.mark.asyncio
async def test_identical_sdk_text_blocks_share_one_signature():
    """A result is what the tool said, not the block that carried it.

    AgentScope normally supplies a list of content blocks. Serialising the
    block objects includes each one's generated id and timestamps, so identical
    error text hashed differently and the repetition was never seen.
    """
    from agentscope.message import TextBlock

    gate = _gate_with_defaults()

    context = [_msg("reply-1", [])]
    result = None
    for index in range(5):
        context[-1].content.append(_call(f"call-{index}"))
        result = await gate.check(_ctx(_Agent(context)))
        if index < 4:
            assert result.action == StopAction.BYPASS
            context[-1].content.append(
                _result(
                    f"call-{index}",
                    output=[TextBlock(text="connection refused")],
                ),
            )

    assert result is not None
    assert result.action == StopAction.TERMINATE


@pytest.mark.asyncio
async def test_progress_after_a_long_static_prefix_is_not_a_loop():
    """A long unchanged preamble must not hide a moving progress line.

    The digest used to hash only the first 2 KB, so a 3,000-character banner
    followed by ``progress n/5`` hashed identically every time and the gate
    stopped a poll that was still moving.
    """
    gate = _gate_with_defaults()
    banner = "x" * 3000

    context = [_msg("reply-1", [])]
    result = None
    for index in range(5):
        context[-1].content.append(_call(f"call-{index}"))
        result = await gate.check(_ctx(_Agent(context)))
        if index < 4:
            assert result.action == StopAction.BYPASS
            context[-1].content.append(
                _result(
                    f"call-{index}",
                    output=f"{banner}progress {index + 1}/5",
                ),
            )

    assert result is not None
    assert result.action == StopAction.BYPASS


@pytest.mark.asyncio
async def test_identical_long_results_still_stop():
    """The same long answer four times is still a loop."""
    gate = _gate_with_defaults()
    banner = "x" * 3000

    context = [_msg("reply-1", [])]
    result = None
    for index in range(5):
        context[-1].content.append(_call(f"call-{index}"))
        result = await gate.check(_ctx(_Agent(context)))
        if index < 4:
            assert result.action == StopAction.BYPASS
            context[-1].content.append(
                _result(
                    f"call-{index}",
                    output=f"{banner}connection refused",
                ),
            )

    assert result is not None
    assert result.action == StopAction.TERMINATE


@pytest.mark.asyncio
async def test_each_result_is_digested_once(monkeypatch):
    """A result that is already paired is not serialised again.

    The gate used to walk the whole context on every check and re-serialise
    every result it had already seen, including ones outside the window.
    """
    gate = _gate_with_defaults()
    calls = []
    original = gate._result_digest

    def counting(payload):
        calls.append(1)
        return original(payload)

    monkeypatch.setattr(gate, "_result_digest", counting)

    context = [_msg("reply-1", [])]
    for index in range(5):
        context[-1].content.append(_call(f"call-{index}"))
        await gate.check(_ctx(_Agent(context)))
        if index < 4:
            context[-1].content.append(
                _result(f"call-{index}", output=f"result-{index}"),
            )

    # Four results arrived; none of them was digested a second time.
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_repeated_resource_limit_failures_stop_despite_changing_measurements():
    """Shell reports the measured RSS in its error text.

    The command, the limit and the failure category are the same every run, so
    the gate must keep seeing a repeat even though the measured value moves.
    """
    gate = _gate_with_defaults()

    context = [_msg("reply-1", [])]
    result = None
    for index in range(5):
        context[-1].content.append(_call(f"call-{index}"))
        result = await gate.check(_ctx(_Agent(context)))
        if index < 4:
            assert result.action == StopAction.BYPASS
            context[-1].content.append(
                _result(
                    f"call-{index}",
                    output=(
                        "[resource protection] Shell memory limit exceeded "
                        f"(RSS {12345678 + index * 4096} bytes > 100663296 bytes)"
                    ),
                ),
            )

    assert result is not None
    assert result.action == StopAction.TERMINATE


@pytest.mark.asyncio
async def test_pending_calls_do_not_crowd_out_completed_results():
    """Pending calls must not consume the completed window's capacity.

    The runner checks before the batch runs, so four calls in flight used to
    fill four of the six deque slots and leave room for only two completed
    records: the three-wide window could never fill.
    """
    gate = _gate_with_defaults()

    context = [_msg("reply-1", [])]
    result = None

    def batch(tag):
        for index in range(4):
            context[-1].content.append(_call(f"{tag}-{index}"))

    def results(tag):
        for index in range(4):
            context[-1].content.append(
                _result(f"{tag}-{index}", output="same failure"),
            )

    batch("a")
    await gate.check(_ctx(_Agent(context)))
    results("a")

    batch("b")
    result = await gate.check(_ctx(_Agent(context)))
    assert result.action == StopAction.BYPASS
    results("b")

    batch("c")
    result = await gate.check(_ctx(_Agent(context)))

    assert result is not None
    assert result.action == StopAction.TERMINATE


@pytest.mark.asyncio
async def test_identical_media_references_share_one_signature():
    """Two blocks pointing at the same media are one result, not two.

    A fresh SDK block carries different generated fields, so serialising the
    object made the same image look like a new result on every call.
    """
    from agentscope.message import DataBlock

    gate = _gate_with_defaults()

    context = [_msg("reply-1", [])]
    result = None
    for index in range(5):
        context[-1].content.append(_call(f"call-{index}"))
        result = await gate.check(_ctx(_Agent(context)))
        if index < 4:
            assert result.action == StopAction.BYPASS
            context[-1].content.append(
                _result(
                    f"call-{index}",
                    output=[
                        DataBlock(
                            source={
                                "type": "url",
                                "url": "https://example.test/shot.png",
                                "media_type": "image/png",
                            },
                        ),
                    ],
                ),
            )

    assert result is not None
    assert result.action == StopAction.TERMINATE


def test_media_digest_stays_bounded():
    """An inline media payload must not be copied into the signature."""
    payload = [
        SimpleNamespace(
            type="data",
            source={"type": "base64", "data": "A" * 4_000_000},
        ),
    ]

    text = DoomLoopGate._visible_text(payload)

    assert len(text) < 200
