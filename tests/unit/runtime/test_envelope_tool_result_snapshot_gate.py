# -*- coding: utf-8 -*-
"""Tests for geometric byte-interval gating of tool result snapshots.

Every ``TOOL_RESULT_*_DELTA`` snapshot re-serializes everything the tool
has produced so far, so emitting one per delta makes the bytes retained
for reconnect replay quadratic in the delta count.  The gate emits a
snapshot only once the accumulated output reaches a geometric threshold,
which pins the amplification at roughly 2x regardless of output size or
tool duration.  Accumulation itself is never gated: the cancel-save path
and the terminal ``TOOL_RESULT_END`` snapshot both read accumulated
state, so a suppressed emission must not drop any content.
"""
# pylint: disable=protected-access
from __future__ import annotations

import json
from typing import Any

import pytest
from agentscope.event import (
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultDataDeltaEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from agentscope.message import ToolResultState

import qwenpaw.runtime.envelope as envelope_module
from qwenpaw.runtime.envelope import Envelope
from qwenpaw.schemas import RunStatus

CALL_ID = "call_gate"
TOOL_NAME = "execute_shell_command"
REPLY_ID = "reply_gate"
BLOCK_ID = "block_gate"
KIB = 1024


def _split(text: str, parts: int) -> list[str]:
    """Split ``text`` into ``parts`` near-equal deterministic chunks."""
    if parts <= 1:
        return [text]
    size, remainder = divmod(len(text), parts)
    chunks: list[str] = []
    start = 0
    for position in range(parts):
        end = start + size + (1 if position < remainder else 0)
        chunks.append(text[start:end])
        start = end
    return chunks


async def _drain(envelope: Envelope, event: Any) -> list[Any]:
    """Translate one agentscope event and collect what it emits."""
    return [obj async for obj in envelope.translate_event(event)]


async def _start_tool(envelope: Envelope) -> None:
    """Feed ``TOOL_CALL_START`` so argument deltas have a host message."""
    await _drain(
        envelope,
        ToolCallStartEvent(
            reply_id=REPLY_ID,
            tool_call_id=CALL_ID,
            tool_call_name=TOOL_NAME,
        ),
    )


async def _start_result(envelope: Envelope) -> None:
    """Feed ``TOOL_RESULT_START`` to open the tool output message."""
    await _drain(
        envelope,
        ToolResultStartEvent(
            reply_id=REPLY_ID,
            tool_call_id=CALL_ID,
            tool_call_name=TOOL_NAME,
        ),
    )


async def _feed_text_deltas(
    envelope: Envelope,
    deltas: list[str],
) -> list[list[Any]]:
    """Feed text deltas; return the objects emitted per delta."""
    emitted: list[list[Any]] = []
    for delta in deltas:
        emitted.append(
            await _drain(
                envelope,
                ToolResultTextDeltaEvent(
                    reply_id=REPLY_ID,
                    tool_call_id=CALL_ID,
                    delta=delta,
                ),
            ),
        )
    return emitted


async def _feed_data_deltas(
    envelope: Envelope,
    chunks: list[str],
) -> list[list[Any]]:
    """Feed base64 data deltas on one block; objects emitted per delta."""
    emitted: list[list[Any]] = []
    for chunk in chunks:
        emitted.append(
            await _drain(
                envelope,
                ToolResultDataDeltaEvent(
                    reply_id=REPLY_ID,
                    tool_call_id=CALL_ID,
                    block_id=BLOCK_ID,
                    media_type="image/png",
                    data=chunk,
                ),
            ),
        )
    return emitted


async def _end_result(envelope: Envelope) -> list[Any]:
    """Feed ``TOOL_RESULT_END`` and return what it emits."""
    return await _drain(
        envelope,
        ToolResultEndEvent(
            reply_id=REPLY_ID,
            tool_call_id=CALL_ID,
            state=ToolResultState.SUCCESS,
        ),
    )


def _emits(per_delta: list[list[Any]]) -> int:
    """Total object count emitted across all deltas."""
    return sum(len(objects) for objects in per_delta)


def _last_snapshot(per_delta: list[list[Any]]) -> Any:
    """The last in-progress snapshot emitted by a delta."""
    for objects in reversed(per_delta):
        if objects:
            return objects[-1]
    raise AssertionError("no snapshot was emitted")


def _payload(obj: Any) -> str:
    """Serialize ``obj`` ignoring per-run identity and ordering fields."""
    clone = obj.model_copy(deep=True)
    clone.sequence_number = 0
    clone.msg_id = "msg_reference"
    return clone.model_dump_json()


# ---------------------------------------------------------------------------
# Acceptance 1: emission count is logarithmic, payload shape is unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_64kib_over_1024_deltas_emits_at_most_eight_snapshots() -> None:
    envelope = Envelope(session_id="gate")
    await _start_result(envelope)

    output = ("line-0000 payload\n" * 4096)[: 64 * KIB]
    assert len(output) == 64 * KIB
    per_delta = await _feed_text_deltas(envelope, _split(output, 1024))

    assert _emits(per_delta) <= 8
    assert len(per_delta[0]) == 1, "the first delta must emit immediately"
    assert _last_snapshot(per_delta).data["output"] == output


@pytest.mark.asyncio
async def test_last_snapshot_is_byte_identical_to_the_ungated_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gated stream must end on exactly the snapshot it used to send."""
    output = "x" * (64 * KIB)
    deltas = _split(output, 1024)

    # floor=1 / growth=1 makes every delta cross the threshold, which
    # reproduces the pre-change emission schedule exactly.
    monkeypatch.setattr(envelope_module, "TOOL_RESULT_SNAPSHOT_MIN_BYTES", 1)
    monkeypatch.setattr(envelope_module, "TOOL_RESULT_SNAPSHOT_GROWTH", 1)
    ungated = Envelope(session_id="gate")
    await _start_result(ungated)
    ungated_per_delta = await _feed_text_deltas(ungated, deltas)
    monkeypatch.undo()

    gated = Envelope(session_id="gate")
    await _start_result(gated)
    gated_per_delta = await _feed_text_deltas(gated, deltas)

    assert _emits(ungated_per_delta) == 1024
    assert _emits(gated_per_delta) <= 8
    assert _payload(_last_snapshot(gated_per_delta)) == _payload(
        _last_snapshot(ungated_per_delta),
    )
    # The host message id is still the run's own, not a normalized value.
    gated_last = _last_snapshot(gated_per_delta)
    host = gated._tool_calls[CALL_ID]["output_message"]
    assert gated_last.msg_id == host.id


# ---------------------------------------------------------------------------
# Acceptance 2: accumulation is never gated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_after_suppressed_deltas_keeps_the_full_output() -> None:
    envelope = Envelope(session_id="gate")
    await _start_result(envelope)
    output = "y" * (64 * KIB)

    per_delta = await _feed_text_deltas(envelope, _split(output, 1024))
    # No TOOL_RESULT_END: the run was cancelled mid-tool.
    assert _emits(per_delta) < 1024

    saved = envelope.collect_tool_output()

    assert saved[CALL_ID] == output
    assert len(saved[CALL_ID]) == 64 * KIB


@pytest.mark.asyncio
async def test_suppressed_data_deltas_still_merge_into_the_block() -> None:
    envelope = Envelope(session_id="gate")
    await _start_result(envelope)
    chunk = "A" * 512

    per_delta = await _feed_data_deltas(envelope, [chunk] * 64)
    terminal = await _end_result(envelope)

    assert _emits(per_delta) <= 8
    blocks = json.loads(terminal[0].data["output"])
    assert blocks == [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "data": chunk * 64,
                "media_type": "image/png",
            },
        },
    ]


@pytest.mark.asyncio
async def test_text_and_data_deltas_share_one_emission_gate() -> None:
    envelope = Envelope(session_id="gate")
    await _start_result(envelope)
    text = "t" * (32 * KIB)
    chunk = "B" * 512

    text_emits = await _feed_text_deltas(envelope, _split(text, 64))
    data_emits = await _feed_data_deltas(envelope, [chunk] * 64)
    terminal = await _end_result(envelope)

    # Both streams are gated, and the data phase inherits the threshold
    # the text phase already reached instead of restarting at the floor.
    assert _emits(text_emits) <= 8
    assert _emits(data_emits) <= 8
    blocks = json.loads(terminal[0].data["output"])
    assert blocks[0]["source"]["data"] == chunk * 64
    assert blocks[-1] == {"type": "text", "text": text}


# ---------------------------------------------------------------------------
# Acceptance 3: amplification does not grow with output volume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_1mib_output_emits_at_most_twelve_snapshots() -> None:
    envelope = Envelope(session_id="gate")
    await _start_result(envelope)
    output = "z" * (1024 * KIB)

    per_delta = await _feed_text_deltas(envelope, _split(output, 1024))

    assert _emits(per_delta) <= 12
    assert _last_snapshot(per_delta).data["output"] == output


# ---------------------------------------------------------------------------
# Acceptance 5 (M-6): an output below the floor still shows up immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_output_below_the_floor_emits_its_first_delta() -> None:
    envelope = Envelope(session_id="gate")
    await _start_result(envelope)

    per_delta = await _feed_text_deltas(envelope, _split("42", 2))

    assert _emits(per_delta) == 1
    assert _last_snapshot(per_delta).data["output"] == "4"


@pytest.mark.asyncio
async def test_single_delta_output_emits_exactly_one_snapshot() -> None:
    envelope = Envelope(session_id="gate")
    await _start_result(envelope)

    per_delta = await _feed_text_deltas(envelope, ["short answer"])

    assert _emits(per_delta) == 1


@pytest.mark.asyncio
async def test_small_output_terminal_snapshot_is_complete() -> None:
    envelope = Envelope(session_id="gate")
    await _start_result(envelope)

    await _feed_text_deltas(envelope, _split("tiny output", 4))
    terminal = await _end_result(envelope)

    assert terminal[0].data["output"] == "tiny output"
    assert terminal[0].status == RunStatus.Completed


# ---------------------------------------------------------------------------
# Acceptance 7 (M-4): the gate never touches tool call arguments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_argument_deltas_are_not_gated() -> None:
    envelope = Envelope(session_id="gate")
    await _start_tool(envelope)
    arguments = json.dumps(
        {"command": " ".join(f"echo {index:03d};" for index in range(40))},
    )

    emitted: list[Any] = []
    for delta in _split(arguments, 40):
        emitted.extend(
            await _drain(
                envelope,
                ToolCallDeltaEvent(
                    reply_id=REPLY_ID,
                    tool_call_id=CALL_ID,
                    delta=delta,
                ),
            ),
        )

    assert len(emitted) == 40
    assert "".join(obj.data["arguments"] for obj in emitted) == arguments

    terminal = await _drain(
        envelope,
        ToolCallEndEvent(reply_id=REPLY_ID, tool_call_id=CALL_ID),
    )
    assert len(terminal) == 2
    assert terminal[0].data["arguments"] == arguments


# ---------------------------------------------------------------------------
# Acceptance 6 (M-3/M-4): option (iii) is frozen, so no msg_id is injected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminal_snapshots_carry_no_msg_id() -> None:
    """Freeze option (iii): the replay copy drops them, live shape stays."""
    envelope = Envelope(session_id="gate")
    await _start_tool(envelope)
    call_terminal = await _drain(
        envelope,
        ToolCallEndEvent(reply_id=REPLY_ID, tool_call_id=CALL_ID),
    )

    await _start_result(envelope)
    await _feed_text_deltas(envelope, ["final output"])
    result_terminal = await _end_result(envelope)

    assert call_terminal[0].msg_id is None
    assert result_terminal[0].msg_id is None
    assert result_terminal[-1].object == "message"
