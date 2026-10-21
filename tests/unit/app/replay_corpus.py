# -*- coding: utf-8 -*-
"""Stream corpora shared by the ``ReplayStore`` tests.

Every corpus is produced by the real :class:`~qwenpaw.runtime.envelope.
Envelope`, so the event shapes under test are the ones the console channel
actually puts on the wire rather than hand-written approximations. Each can
be serialized in either of the two styles that reach a client:

``compact``
    ``model_dump_json()``, the default path in
    ``channels/base.py:_serialize_event_for_sse``.
``spaced``
    ``json.dumps(..., ensure_ascii=False)``, what the same method falls back
    to through ``_strip_event_headlines`` for tracked content deltas. Real
    console content deltas take this path, so a fold verified only on
    compact JSON is not yet verified (spec revision M-7).

The four corpora the equivalence acceptance criterion requires are
:func:`fixture_stream`, :func:`synthetic_stream`, :func:`mixed_stream` and
:func:`partial_stream`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, List, Optional

from agentscope.event import (
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
    ThinkingBlockDeltaEvent,
    ThinkingBlockEndEvent,
    ThinkingBlockStartEvent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
)
from agentscope.message import ToolResultState

from qwenpaw.runtime.envelope import Envelope

SSE_PREFIX = "data: "
SSE_SUFFIX = "\n\n"

Serialize = Callable[[Any], str]

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The reconnect replay fixture the console's own tests use. Spaced JSON,
#: non-contiguous ``sequence_number`` (57 -> 192) and a ``replay_end``
#: marker in the middle of the stream.
FIXTURE_PATH = (
    _REPO_ROOT
    / "console"
    / "src"
    / "pages"
    / "Chat"
    / "tests"
    / "fixtures"
    / "reconnectReplayStream.txt"
)

_TOOL_NAME = "execute_shell_command"

# Control frames the console channel emits with plain ``json.dumps``, i.e.
# with no ``object`` field. They must survive a fold byte for byte and in
# order (spec C7), and they must never be mistaken for content just
# because they also lead with ``"type"``.
TURN_USAGE_SSE = (
    "data: "
    + json.dumps(
        {
            "type": "turn_usage",
            "session_id": "sess-1",
            "usage": {"last_prompt_tokens": 1200, "context_size": 8000},
            "context_usage": {
                "estimated_tokens": 1200,
                "max_input_length": 8000,
                "context_usage_ratio": 15.0,
            },
        },
    )
    + "\n\n"
)
RATE_LIMITED_SSE = (
    "data: "
    + json.dumps(
        {
            "type": "rate_limited",
            "error": "quota exceeded",
            "alternatives": ["qwen-flash"],
        },
    )
    + "\n\n"
)
ERROR_SSE = 'data: {"error": "internal server error"}\n\n'

CONTROL_SSES = (TURN_USAGE_SSE, RATE_LIMITED_SSE, ERROR_SSE)

# Not framed as SSE at all, or not JSON, or a JSON array. Retention must be
# verbatim: a fold that guesses here changes what a reconnecting client
# sees (spec C7).
UNPARSEABLE_SSES = (
    "data: first\n\n",
    "data: \n\n",
    "data: {not json}\n\n",
    "data: [1, 2, 3]\n\n",
    "",
)


def compact(obj: Any) -> str:
    """Serialize one envelope object the way the default channel path does."""
    return f"{SSE_PREFIX}{obj.model_dump_json()}{SSE_SUFFIX}"


def spaced(obj: Any) -> str:
    """Serialize one envelope object the headline-stripping way."""
    payload = json.dumps(
        obj.model_dump(mode="json"),
        ensure_ascii=False,
        default=str,
    )
    return f"{SSE_PREFIX}{payload}{SSE_SUFFIX}"


def _split(text: str, parts: int) -> List[str]:
    """Split ``text`` into ``parts`` deterministic near-equal chunks."""
    if parts <= 1:
        return [text]
    size, remainder = divmod(len(text), parts)
    chunks: List[str] = []
    start = 0
    for position in range(parts):
        end = start + size + (1 if position < remainder else 0)
        chunks.append(text[start:end])
        start = end
    return chunks


def _filler(length: int, seed: int) -> str:
    """Return deterministic pseudo-text of exactly ``length`` characters."""
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    state = seed * 2654435761 % 4294967296
    out: List[str] = []
    produced = -1
    while produced < length:
        word = []
        for _ in range(3 + state % 7):
            state = (state * 1103515245 + 12345) % 4294967296
            word.append(alphabet[state % len(alphabet)])
        chunk = "".join(word)
        out.append(chunk)
        produced += len(chunk) + 1
    return " ".join(out)[:length]


def tool_events(
    index: int,
    *,
    output_chars: int = 1024,
    output_deltas: int = 12,
    arg_deltas: int = 4,
    call_suffix: str = "",
) -> List[Any]:
    """Build the agentscope events of one tool call and its result."""
    reply_id = f"reply_{index}"
    call_id = f"call_{index}{call_suffix}"
    events: List[Any] = [
        ToolCallStartEvent(
            reply_id=reply_id,
            tool_call_id=call_id,
            tool_call_name=_TOOL_NAME,
        ),
    ]
    arguments = json.dumps(
        {"command": _filler(48 + 8 * index, index + 3)},
    )
    for delta in _split(arguments, arg_deltas):
        events.append(
            ToolCallDeltaEvent(
                reply_id=reply_id,
                tool_call_id=call_id,
                delta=delta,
            ),
        )
    events.append(
        ToolCallEndEvent(reply_id=reply_id, tool_call_id=call_id),
    )
    events.append(
        ToolResultStartEvent(
            reply_id=reply_id,
            tool_call_id=call_id,
            tool_call_name=_TOOL_NAME,
        ),
    )
    output = _filler(output_chars, index * 11 + 4)
    for delta in _split(output, output_deltas):
        events.append(
            ToolResultTextDeltaEvent(
                reply_id=reply_id,
                tool_call_id=call_id,
                delta=delta,
            ),
        )
    events.append(
        ToolResultEndEvent(
            reply_id=reply_id,
            tool_call_id=call_id,
            state=ToolResultState.SUCCESS,
        ),
    )
    return events


def round_events(
    index: int,
    *,
    think_chars: int = 240,
    think_deltas: int = 8,
    text_chars: int = 160,
    text_deltas: int = 6,
    **tool_kwargs: Any,
) -> List[Any]:
    """Build the agentscope events of one ReAct round.

    The defaults are deliberately light so a unit test can build a
    multi-round run in milliseconds. Pass the shape
    ``scripts/bench_replay_buffer.py:145-152`` uses to reproduce the T0
    baseline corpus a compression ratio is measured against.
    """
    reply_id = f"reply_{index}"
    events: List[Any] = [
        ThinkingBlockStartEvent(reply_id=reply_id, block_id=f"think_{index}"),
    ]
    for delta in _split(_filler(think_chars, index * 11 + 1), think_deltas):
        events.append(
            ThinkingBlockDeltaEvent(
                reply_id=reply_id,
                block_id=f"think_{index}",
                delta=delta,
            ),
        )
    events.append(
        ThinkingBlockEndEvent(reply_id=reply_id, block_id=f"think_{index}"),
    )
    events.append(
        TextBlockStartEvent(reply_id=reply_id, block_id=f"text_{index}"),
    )
    for delta in _split(_filler(text_chars, index * 11 + 2), text_deltas):
        events.append(
            TextBlockDeltaEvent(
                reply_id=reply_id,
                block_id=f"text_{index}",
                delta=delta,
            ),
        )
    events.append(
        TextBlockEndEvent(reply_id=reply_id, block_id=f"text_{index}"),
    )
    events.extend(tool_events(index, **tool_kwargs))
    return events


async def _drain(
    envelope: Envelope,
    events: List[Any],
    out: List[str],
    serialize: Serialize,
) -> None:
    """Translate agentscope events into SSE lines appended to ``out``."""
    for event in events:
        async for obj in envelope.translate_event(event):
            out.append(serialize(obj))


async def _open(
    envelope: Envelope,
    out: List[str],
    serialize: Serialize,
) -> None:
    """Emit the two response snapshots ``runtime.py:126`` opens a run with.

    Serialized at yield time, not after: ``emit_response_created`` yields the
    same mutable response object twice and only the status differs.
    """
    async for obj in envelope.emit_response_created():
        out.append(serialize(obj))


async def synthetic_stream(
    rounds: int = 4,
    serialize: Serialize = compact,
    *,
    session_id: str = "test-session",
    round_kwargs: Optional[dict] = None,
) -> List[str]:
    """Corpus 2: a complete run of ``rounds`` ReAct rounds plus finalize.

    ``round_kwargs`` is forwarded to :func:`round_events`, so a caller can
    widen the per-round shape without this helper knowing about it.
    """
    envelope = Envelope(session_id=session_id)
    out: List[str] = []
    await _open(envelope, out, serialize)
    kwargs = dict(round_kwargs or {})
    for index in range(rounds):
        await _drain(envelope, round_events(index, **kwargs), out, serialize)
    async for obj in envelope.finalize():
        out.append(serialize(obj))
    return out


async def command_stream(
    serialize: Serialize = compact,
    *,
    metadata: Optional[dict] = None,
) -> List[str]:
    """A slash-command run, the path that carries the ``clear_history`` latch.

    ``Envelope.from_msg`` yields ``self._completed_message`` twice — once as
    an empty in-progress stub and once completed with ``metadata`` set from
    the command's ``Msg`` (``agents/command_handler.py:726`` passes
    ``{"clear_history": True, "clear_plan": True}`` for ``/clear``) — and
    then the response once. The latch therefore only reaches a reconnecting
    client if the fold keeps the *last* snapshot for each id verbatim.
    """
    from agentscope.message import Msg, TextBlock

    envelope = Envelope(session_id="test-command")
    out: List[str] = []
    await _open(envelope, out, serialize)
    cmd_msg = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text="**History Cleared!**")],
        metadata=metadata or {},
    )
    async for obj in envelope.from_msg(cmd_msg):
        out.append(serialize(obj))
    return out


async def partial_stream(
    serialize: Serialize = compact,
    *,
    complete_rounds: int = 1,
    output_deltas: int = 6,
) -> List[str]:
    """Corpus 4: a run cut off mid tool output, with no END and no finalize.

    This is the only corpus that can prove a ``delta=true`` content slot
    must not be dropped: there is no terminal message snapshot carrying the
    accumulated text, so the folded deltas are the entire record of the
    tool output (spec revision M-2).
    """
    envelope = Envelope(session_id="test-partial")
    out: List[str] = []
    await _open(envelope, out, serialize)
    for index in range(complete_rounds):
        await _drain(envelope, round_events(index), out, serialize)

    reply_id = "reply_cut"
    call_id = "call_cut"
    cut = [
        ToolCallStartEvent(
            reply_id=reply_id,
            tool_call_id=call_id,
            tool_call_name=_TOOL_NAME,
        ),
        ToolCallDeltaEvent(
            reply_id=reply_id,
            tool_call_id=call_id,
            delta=json.dumps({"command": "sleep 30"}),
        ),
        ToolCallEndEvent(reply_id=reply_id, tool_call_id=call_id),
        ToolResultStartEvent(
            reply_id=reply_id,
            tool_call_id=call_id,
            tool_call_name=_TOOL_NAME,
        ),
    ]
    await _drain(envelope, cut, out, serialize)
    for delta in _split(_filler(2048, 77), output_deltas):
        await _drain(
            envelope,
            [
                ToolResultTextDeltaEvent(
                    reply_id=reply_id,
                    tool_call_id=call_id,
                    delta=delta,
                ),
            ],
            out,
            serialize,
        )
    return out


async def mixed_stream(serialize: Serialize = compact) -> List[str]:
    """Corpus 3: a run interleaved with the fixture and the control frames.

    Carries ``turn_usage``, ``rate_limited``, the tracker's error SSE,
    ``replay_end``, an ``Event`` envelope and unparseable lines, none of
    which the synthetic run produces on its own.
    """
    out = await synthetic_stream(2, serialize)
    middle = len(out) // 2
    injected = [
        TURN_USAGE_SSE,
        RATE_LIMITED_SSE,
        ERROR_SSE,
        'data: {"object": "event", "type": "session.created"}\n\n',
        'data: {"type": "replay_end"}\n\n',
        *UNPARSEABLE_SSES,
    ]
    return out[:middle] + injected + out[middle:] + fixture_stream()


def fixture_stream() -> List[str]:
    """Corpus 1: the real console reconnect fixture, spaced JSON."""
    raw = FIXTURE_PATH.read_text(encoding="utf-8")
    return [f"{chunk}\n\n" for chunk in raw.split("\n\n") if chunk.strip()]
