#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reproducible memory benchmark for the TaskTracker replay buffer.

Offline measurement harness for QWEN-4. It builds a synthetic agentscope
event stream, pushes it through the real
``qwenpaw.runtime.envelope.Envelope.translate_event()``, serializes every
emitted object exactly like the console channel does, and appends the
resulting SSE lines to a plain ``list`` standing in for
``_RunState.buffer``.

No production module is modified; this script only imports them.

How to run (repository root of the worktree under test)::

    PYTHONPATH=$(pwd)/src \
      /Users/mazhijian/miniconda3/envs/qwenpaw-dev/bin/python \
      scripts/bench_replay_buffer.py

The script aborts if ``qwenpaw`` resolves outside this repository, which
is what happens when ``PYTHONPATH`` is forgotten: the conda env is an
editable install of the *source checkout*, so omitting it silently
benchmarks somebody else's code.

Which command, which numbers
----------------------------
``scripts/bench_replay_buffer.py`` (no arguments) prints tables A, D, F,
G and V for one ~485k-event run. That single invocation is the acceptance
baseline for T1 and T2, and it exits non-zero if a V check fails.

A -- Quadratic amplification of one fixed 64 KiB tool output split into
    1 / 8 / 64 / 256 / 1024 deltas.
    **A1 gate**: in the ``deltas=1024`` row read ``delta_emits``, the
    number of SSE events emitted in response to
    ``TOOL_RESULT_TEXT_DELTA`` inputs. Baseline 1024, and after A1 it
    must be ``<= 8``. The ``buffer KiB`` column of that row is the
    matching memory figure: baseline 33201.1 KiB for a 64 KiB output,
    i.e. 518x amplification, which A1 must flatten to roughly 2x.

D -- Single long run: buffer event count, characters, exact
    ``sys.getsizeof`` bytes of the ``str`` objects, list pointer array,
    RSS and system swap before/after, average bytes per event, and the
    size of the one ``response`` snapshot that ``finalize()`` emits.

F -- Byte composition of the buffer, bucketed by event category. The
    ``content(delta=false,type=data)`` row is the pure-redundancy share
    that A1 removes at the source.

G -- Lossless fold prototype: event and byte compression at three
    scales (10%, 40%, 100% of the run).
    **A2 gate**: in the ``scale=1.00`` row read ``event_ratio`` and
    ``byte_ratio``. After A2 they must be ``>= 20`` and ``>= 6``.
    Rows tagged ``proto`` are this script's own prototype and stay
    available forever as the reference. Once
    ``qwenpaw.app.replay_store.ReplayStore`` exists (i.e. after T2) the
    same stream is also folded by the production store and reported on
    the ``prod`` rows; before T2 those rows read ``n/a``. The production
    numbers, not the prototype ones, are what A2 is accepted on.

V -- Correctness of the reference fold that G measures: spec C7
    (unparseable lines, the console control events and ``Event``
    envelopes pass through byte-identical and in order) and spec section
    3.3 (``reduce(folded) == reduce(original)``). The reduction check
    runs over three corpora -- the synthetic run, the real console
    fixture ``console/.../reconnectReplayStream.txt`` (spaced JSON, so
    it also covers spec N2), and a mixed stream interleaving both with
    the control events, because the synthetic run alone carries none and
    that is exactly the blind spot spec R2 warns about. If V does not
    read "fold is lossless" then the G ratios are meaningless, whatever
    they say.

Memory accounting
-----------------
``sys.getsizeof()`` summed over the buffer is the authoritative figure:
it is read from object headers, so it does not depend on VM state.
``psutil.Process().memory_info().rss`` is printed next to it, and
``resource.getrusage().ru_maxrss`` is deliberately not used -- on macOS
its unit and update behaviour are unreliable and produced a "+107 MB"
reading where the true cost was +564.6 MiB (analysis document, section
2.2).

RSS is only a lower bound, and under memory pressure a very loose one:
the ``resident_size`` behind it excludes pages the OS has compressed or
swapped out. Measured on this workstation with system swap already at
28 GiB, allocating 400 MiB of incompressible ``os.urandom`` raised RSS
by just +127.6 MiB. Table D therefore also samples
``psutil.swap_memory()`` and prints an explicit note whenever the RSS
delta is under half the exact byte count, so a depressed reading cannot
be mistaken for the buffer cost.

Serialization recipe
--------------------
``channels/base.py:1149-1183`` plus ``channels/console/channel.py:495-499``
reduce to ``model_dump_json()`` wrapped in ``f"data: {data}\\n\\n"``, and
that is what ``_to_sse`` reproduces. The console path can additionally
route content deltas through ``_strip_event_headlines``, whose
``json.dumps(..., ensure_ascii=False)`` emits *spaced* JSON; that makes
absolute byte counts a few percent higher than measured here but leaves
every ratio in this report unchanged. T1 and T2 must be compared against
a baseline produced by this same script, not against hand-computed
numbers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

import psutil
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

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MIB = 1024 * 1024
_SSE_PREFIX = "data: "
_SSE_SUFFIX = "\n\n"

# Synthetic ReAct round shape, matching the analysis document section 10:
# thinking ~490 chars / 120 deltas, text ~250 chars / 80 deltas,
# tool output ~10 KiB / 60 deltas.
_THINK_CHARS = 490
_THINK_DELTAS = 120
_TEXT_CHARS = 250
_TEXT_DELTAS = 80
_TOOL_ARG_CHARS = 48
_TOOL_ARG_DELTAS = 8
_TOOL_OUTPUT_CHARS = 10 * 1024
_TOOL_OUTPUT_DELTAS = 60
_TOOL_NAME = "execute_shell_command"

# Table A: fixed output volume, varying delta count (analysis document
# table A). The 1024 row is the A1 acceptance configuration.
_A1_OUTPUT_CHARS = 64 * 1024
_A1_LADDER = (1, 8, 64, 256, 1024)

# Table G scales, as fractions of the full run.
_G_SCALES = (0.1, 0.4, 1.0)

# Bounded classification window. The frozen implementation spec
# (section 3.2) requires that no payload is ever parsed in full: the
# largest single event is the ~18 MiB ``response`` snapshot, and parsing
# it inside the tracker lock would stall concurrent reconnects.
_WINDOW = 512

_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

_FIRST_KEY_RE = re.compile(r'^\{\s*"(\w+)"\s*:')
_OBJECT_RE = re.compile(r'"object":\s*"(\w+)"')
_ID_RE = re.compile(r'"id":\s*"([^"]+)"')
_MSG_ID_RE = re.compile(r'"msg_id":\s*"([^"]+)"')
_INDEX_RE = re.compile(r'"index":\s*(-?\d+|null)')
_TYPE_RE = re.compile(r'"type":\s*"(\w+)"')
_DELTA_RE = re.compile(r'"delta":\s*(true|false)')
_STATUS_RE = re.compile(r'"status":\s*"(\w+|null)"')


# ---------------------------------------------------------------------------
# Deterministic synthetic content
# ---------------------------------------------------------------------------


def _filler(length: int, seed: int) -> str:
    """Return deterministic pseudo-text of exactly ``length`` characters."""
    rng = random.Random(seed)
    words: list[str] = []
    produced = -1
    while produced < length:
        word = "".join(rng.choices(_ALPHABET, k=rng.randint(3, 9)))
        words.append(word)
        produced += len(word) + 1
    return " ".join(words)[:length]


def _split(text: str, parts: int) -> list[str]:
    """Split ``text`` into ``parts`` near-equal, deterministic chunks."""
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


def _to_sse(obj: Any) -> str:
    """Serialize one envelope object the way the console channel does."""
    return f"{_SSE_PREFIX}{obj.model_dump_json()}{_SSE_SUFFIX}"


def _round_events(index: int) -> list[Any]:
    """Build the synthetic agentscope events of one ReAct round."""
    reply_id = f"reply_{index}"
    think_id = f"think_{index}"
    text_id = f"text_{index}"
    call_id = f"call_{index}"
    events: list[Any] = [
        ThinkingBlockStartEvent(reply_id=reply_id, block_id=think_id),
    ]
    think_text = _filler(_THINK_CHARS, index * 11 + 1)
    for delta in _split(think_text, _THINK_DELTAS):
        events.append(
            ThinkingBlockDeltaEvent(
                reply_id=reply_id,
                block_id=think_id,
                delta=delta,
            ),
        )
    events.append(
        ThinkingBlockEndEvent(reply_id=reply_id, block_id=think_id),
    )
    events.append(TextBlockStartEvent(reply_id=reply_id, block_id=text_id))
    answer_text = _filler(_TEXT_CHARS, index * 11 + 2)
    for delta in _split(answer_text, _TEXT_DELTAS):
        events.append(
            TextBlockDeltaEvent(
                reply_id=reply_id,
                block_id=text_id,
                delta=delta,
            ),
        )
    events.append(TextBlockEndEvent(reply_id=reply_id, block_id=text_id))
    events.append(
        ToolCallStartEvent(
            reply_id=reply_id,
            tool_call_id=call_id,
            tool_call_name=_TOOL_NAME,
        ),
    )
    arguments = json.dumps({"command": _filler(_TOOL_ARG_CHARS, index + 3)})
    for delta in _split(arguments, _TOOL_ARG_DELTAS):
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
    tool_output = _filler(_TOOL_OUTPUT_CHARS, index * 11 + 4)
    for delta in _split(tool_output, _TOOL_OUTPUT_DELTAS):
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


# ---------------------------------------------------------------------------
# Bounded-window classifier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Class:
    """Classification of one SSE line, from bounded windows only."""

    bucket: str
    kind: str
    key: Any = None


def _last(pattern: re.Pattern, text: str) -> Optional[str]:
    """Return the last capture of ``pattern`` in ``text``, or None."""
    found = pattern.findall(text)
    return found[-1] if found else None


def _sse_payload(sse: str) -> Optional[str]:
    """Return the JSON payload of an SSE line, or None if not JSON."""
    if not sse.startswith(_SSE_PREFIX) or not sse.endswith(_SSE_SUFFIX):
        return None
    return sse[len(_SSE_PREFIX) : -len(_SSE_SUFFIX)]


def _decoded(sse: str) -> Any:
    """Return the decoded payload of an SSE line, or None.

    Only the verification table calls this. The fold itself must never
    parse a whole payload: the largest single event is the ~20 MiB
    ``response`` snapshot and A2 folds inside the tracker lock.
    """
    payload = _sse_payload(sse)
    if payload is None:
        return None
    try:
        return json.loads(payload)
    except ValueError:
        return None


def _classify_content(head: str) -> _Class:
    """Classify a payload whose first declared key is ``type``.

    ``_ContentBase`` starts with ``type``, but so do the control events
    that ``channels/console/channel.py`` emits with plain ``json.dumps``
    (``turn_usage``, ``rate_limited``) and ``REPLAY_END_SSE``. They have
    no ``object`` field at all, so requiring ``"object":"content"`` in
    the head window is what separates them from real content. For a
    ``_ContentBase`` payload that key sits at roughly byte 45 -- field
    order is ``type, delta, index, status, object, msg_id``, all of them
    ahead of the unbounded ``text`` / ``data`` fields.
    """
    if _last(_OBJECT_RE, head) != "content":
        name = _TYPE_RE.search(head)
        return _Class(
            f"control(type={name.group(1) if name else '?'})",
            "passthrough",
        )
    msg_id = _MSG_ID_RE.search(head)
    index = _INDEX_RE.search(head)
    content_type = _TYPE_RE.search(head)
    delta = _DELTA_RE.search(head)
    if not (msg_id and index and content_type and delta):
        # Spec 3.4: the terminal tool-result snapshot carries
        # ``msg_id=null``. Keying on null would let concurrent tool calls
        # evict each other's output, so it must pass through unfolded.
        return _Class("content(unkeyed)", "passthrough")
    is_delta = delta.group(1) == "true"
    bucket = (
        f"content(delta={'true' if is_delta else 'false'},"
        f"type={content_type.group(1)})"
    )
    key = (
        "content",
        msg_id.group(1),
        index.group(1),
        content_type.group(1),
    )
    return _Class(bucket, "merge" if is_delta else "replace", key)


def _classify_identified(head: str, tail: str) -> _Class:
    """Classify a ``Message`` or ``AgentResponse`` payload."""
    identity = _ID_RE.search(head)
    obj = _last(_OBJECT_RE, tail)
    if identity is None or obj not in ("message", "response"):
        return _Class(f"{obj or 'unknown'}(unkeyed)", "passthrough")
    message_type = _TYPE_RE.search(head)
    if obj == "message" and message_type:
        status = _last(_STATUS_RE, tail) or "?"
        bucket = f"message(type={message_type.group(1)},status={status})"
    else:
        bucket = obj
    return _Class(bucket, "replace", (obj, identity.group(1)))


def classify(sse: str) -> _Class:
    """Classify one SSE line without ever parsing the whole payload.

    The first declared key discriminates the schema class, because
    pydantic v2 serializes declared fields before ``extra="allow"``
    fields: ``_ContentBase`` starts with ``type``, ``Message`` and
    ``AgentResponse`` start with ``id``, ``Event`` starts with
    ``object``. Searching the head window for the first ``"object"``
    instead -- as the frozen spec's pseudocode in section 3.2 does --
    matches the *nested* ``"object":"content"`` of ``Message.content[0]``
    and routes every message into the content branch. A message's own
    ``"object"`` is likewise its *last* occurrence in the payload, so the
    tail lookup takes the final match rather than the first.
    """
    payload = _sse_payload(sse)
    if payload is None:
        return _Class("opaque", "passthrough")
    head = payload[:_WINDOW]
    first = _FIRST_KEY_RE.match(head)
    if first is None:
        return _Class("opaque", "passthrough")
    marker = first.group(1)
    if marker == "type":
        return _classify_content(head)
    if marker == "id":
        return _classify_identified(head, payload[-_WINDOW:])
    if marker == "object":
        name = _last(_OBJECT_RE, head)
        return _Class(f"event(object={name})", "passthrough")
    return _Class("opaque", "passthrough")


# ---------------------------------------------------------------------------
# Lossless fold prototype (analysis document G / spec section 3.3)
# ---------------------------------------------------------------------------


def _dumps(payload: Any) -> str:
    """Re-serialize byte-identically to pydantic ``model_dump_json()``."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class FoldPrototype:
    """Reference implementation of the A2 fold, for measurement only.

    Slots keep first-appearance order. ``replace`` overwrites a slot in
    place; ``merge`` accumulates the append-semantic string field of a
    content delta and serializes once at replay time, so the cost is
    O(total bytes) rather than the O(N^2) of the current buffer.

    A merged event keeps the *first* fragment as its shape and only
    overwrites the accumulated string field. Spec section 3.3 says to
    reuse the last fragment's shape, but the last ``TOOL_CALL_DELTA``
    carries only ``{"arguments": ...}`` while the first one carries
    ``call_id`` and ``name`` too, so a last-shape merge would drop them.
    First-shape is also the larger, i.e. conservative, byte estimate.
    """

    def __init__(self) -> None:
        self._slots: list[list[Any]] = []
        self._positions: dict[Any, int] = {}
        self.merged = 0
        self.superseded = 0
        self.passthrough = 0

    def append(self, sse: str) -> None:
        """Fold one SSE line into the replay slot list."""
        found = classify(sse)
        if found.kind == "passthrough":
            self.passthrough += 1
            self._slots.append(["raw", sse])
            return
        position = self._positions.get(found.key)
        if found.kind == "replace":
            if position is None:
                self._positions[found.key] = len(self._slots)
                self._slots.append(["raw", sse])
            else:
                self._slots[position] = ["raw", sse]
                self.superseded += 1
            return
        if not self._merge(sse, found.key, position):
            self.passthrough += 1
            self._slots.append(["raw", sse])

    def _merge(self, sse: str, key: Any, position: Optional[int]) -> bool:
        """Fold a content delta into its slot; False when unsafe."""
        payload = _sse_payload(sse)
        if payload is None:
            return False
        try:
            decoded = json.loads(payload)
        except ValueError:
            return False
        field = _append_field(decoded)
        if field is None:
            return False
        if position is None:
            self._positions[key] = len(self._slots)
            self._slots.append(
                [
                    "merge",
                    decoded,
                    [_read_field(decoded, field)],
                    field,
                    decoded,
                ],
            )
            return True
        slot = self._slots[position]
        if slot[0] != "merge" or slot[3] != field:
            return False
        slot[2].append(_read_field(decoded, field))
        slot[4] = decoded
        self.merged += 1
        return True

    def replay(self) -> Iterator[str]:
        """Yield the folded SSE lines in first-appearance order."""
        for slot in self._slots:
            if slot[0] == "raw":
                yield slot[1]
                continue
            _, base, fragments, field, last = slot
            merged = _with_field(base, field, "".join(fragments))
            for carried in ("status", "sequence_number"):
                if carried in last:
                    merged[carried] = last[carried]
            yield f"{_SSE_PREFIX}{_dumps(merged)}{_SSE_SUFFIX}"


def _append_field(decoded: Any) -> Optional[tuple[str, ...]]:
    """Return the append-semantic field of a content delta, if any."""
    if not isinstance(decoded, dict):
        return None
    if isinstance(decoded.get("text"), str):
        return ("text",)
    data = decoded.get("data")
    # ``envelope.py`` documents that the frontend appends the string
    # fields of a DATA delta, so tool-call argument fragments follow the
    # same append semantics as ``text``.
    if isinstance(data, dict) and isinstance(data.get("arguments"), str):
        return ("data", "arguments")
    return None


def _read_field(decoded: dict, field: tuple[str, ...]) -> str:
    node: Any = decoded
    for part in field:
        node = node[part]
    return node


def _with_field(
    base: dict,
    field: tuple[str, ...],
    value: str,
) -> dict:
    """Return ``base`` with ``field`` replaced by the joined ``value``."""
    result = dict(base)
    node = result
    for part in field[:-1]:
        node[part] = dict(node[part])
        node = node[part]
    node[field[-1]] = value
    return result


def _load_production_store() -> Optional[type]:
    """Return the production ReplayStore once T2 lands, else None."""
    try:
        from qwenpaw.app.replay_store import ReplayStore
    except ImportError:
        return None
    return ReplayStore


# ---------------------------------------------------------------------------
# Memory sampling
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MemSample:
    """Process RSS and system swap usage, both in MiB."""

    rss: float
    swap: float


def _mem_sample() -> _MemSample:
    """Snapshot the process and the system, for table D.

    Swap is sampled because RSS alone can silently under-report: the
    ``resident_size`` behind ``memory_info().rss`` excludes pages the
    OS has compressed or swapped out, so on a machine under memory
    pressure it stops tracking the Python heap. Table D compares the
    two and says so when they disagree.
    """
    return _MemSample(
        psutil.Process().memory_info().rss / _MIB,
        psutil.swap_memory().used / _MIB,
    )


# ---------------------------------------------------------------------------
# Stream construction
# ---------------------------------------------------------------------------


async def _drain(
    envelope: Envelope,
    event: Any,
    buffer: list[str],
    counter: Optional[list[int]] = None,
) -> None:
    """Translate one agentscope event into the simulated replay buffer."""
    async for obj in envelope.translate_event(event):
        buffer.append(_to_sse(obj))
        if counter is not None:
            counter[0] += 1


async def build_run_buffer(rounds: int) -> tuple[list[str], int]:
    """Build the replay buffer of a synthetic long run.

    Returns the buffer and the byte size of the single ``response``
    snapshot emitted by ``finalize()``.
    """
    envelope = Envelope(session_id="bench-session")
    buffer: list[str] = []
    for index in range(rounds):
        for event in _round_events(index):
            await _drain(envelope, event, buffer)
    response_bytes = 0
    async for obj in envelope.finalize():
        sse = _to_sse(obj)
        buffer.append(sse)
        if getattr(obj, "object", None) == "response":
            response_bytes = sys.getsizeof(sse)
    return buffer, response_bytes


async def build_a1_probe(delta_count: int) -> dict[str, Any]:
    """Measure one fixed 64 KiB tool output split into N deltas."""
    envelope = Envelope(session_id="bench-a1")
    buffer: list[str] = []
    call_id = "call_a1"
    await _drain(
        envelope,
        ToolResultStartEvent(
            reply_id="reply_a1",
            tool_call_id=call_id,
            tool_call_name=_TOOL_NAME,
        ),
        buffer,
    )
    delta_emits = 0
    counter = [0]
    output = _filler(_A1_OUTPUT_CHARS, 9091)
    for delta in _split(output, delta_count):
        counter[0] = 0
        await _drain(
            envelope,
            ToolResultTextDeltaEvent(
                reply_id="reply_a1",
                tool_call_id=call_id,
                delta=delta,
            ),
            buffer,
            counter,
        )
        delta_emits += counter[0]
    await _drain(
        envelope,
        ToolResultEndEvent(
            reply_id="reply_a1",
            tool_call_id=call_id,
            state=ToolResultState.SUCCESS,
        ),
        buffer,
    )
    chars = sum(len(line) for line in buffer)
    return {
        "deltas": delta_count,
        "events": len(buffer),
        "delta_emits": delta_emits,
        "chars": chars,
        "str_bytes": sum(sys.getsizeof(line) for line in buffer),
        "amplification": chars / _A1_OUTPUT_CHARS,
    }


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _print_header() -> None:
    import qwenpaw

    print("=" * 78)
    print("TaskTracker replay buffer benchmark")
    print("=" * 78)
    print(f"python        : {sys.version.split()[0]}")
    print(f"platform      : {platform.platform()}")
    print(f"machine       : {platform.machine()}")
    print(f"psutil        : {psutil.__version__}")
    print(f"qwenpaw       : {qwenpaw.__file__}")
    print(f"repo root     : {_REPO_ROOT}")
    print()


async def table_a() -> None:
    """Print table A: quadratic amplification and the A1 gate."""
    started = time.monotonic()
    rows = [await build_a1_probe(count) for count in _A1_LADDER]
    print("-" * 78)
    print("A. Fixed 64 KiB tool output, varying delta count")
    print("   A1 gate: deltas=1024 -> delta_emits must drop to <= 8")
    print("-" * 78)
    print(
        f"{'deltas':>7} {'events':>7} {'delta_emits':>12} "
        f"{'buffer KiB':>11} {'amplif':>8}",
    )
    for row in rows:
        print(
            f"{row['deltas']:>7} {row['events']:>7} "
            f"{row['delta_emits']:>12} "
            f"{row['str_bytes'] / 1024:>11.1f} "
            f"{row['amplification']:>7.1f}x",
        )
    print(f"   [{time.monotonic() - started:.1f}s]\n")


def table_d(
    buffer: list[str],
    response_bytes: int,
    samples: tuple[_MemSample, _MemSample],
) -> None:
    """Print table D: whole-run memory accounting."""
    chars = sum(len(line) for line in buffer)
    str_bytes = sum(sys.getsizeof(line) for line in buffer)
    list_bytes = sys.getsizeof(buffer)
    events = len(buffer)
    before, after = samples
    rss_delta = after.rss - before.rss
    exact_mib = str_bytes / _MIB
    print("-" * 78)
    print("D. Single long run")
    print("-" * 78)
    print(f"buffer events              : {events:,}")
    print(f"characters (sum of len)    : {chars:,}  ({chars / _MIB:.1f} MiB)")
    print(
        f"str object exact bytes     : {str_bytes:,}  "
        f"({exact_mib:.1f} MiB)  <- authoritative",
    )
    print(
        f"list pointer array         : {list_bytes:,} B  "
        f"({list_bytes / _MIB:.1f} MiB)",
    )
    print(
        f"RSS                        : {before.rss:.1f} MiB -> "
        f"{after.rss:.1f} MiB   (+{rss_delta:.1f} MiB)",
    )
    print(
        f"system swap used           : {before.swap / 1024:.1f} GiB -> "
        f"{after.swap / 1024:.1f} GiB",
    )
    if rss_delta < exact_mib * 0.5:
        print(
            "  NOTE: RSS is a lower bound on this machine, not the "
            "buffer cost.\n"
            f"  {exact_mib - rss_delta:.0f} MiB of live str objects are "
            "not resident: resident_size\n"
            "  excludes pages the OS compressed or swapped out. Quote "
            "'str object\n  exact bytes' as the memory figure.",
        )
    print(f"average per event          : {str_bytes // max(events, 1):,} B")
    print(
        f"finalize() response        : {response_bytes:,} B  "
        f"({response_bytes / _MIB:.2f} MiB)",
    )
    print()


def table_f(buffer: list[str]) -> None:
    """Print table F: byte composition by event category."""
    counts: dict[str, int] = {}
    sizes: dict[str, int] = {}
    for line in buffer:
        bucket = classify(line).bucket
        counts[bucket] = counts.get(bucket, 0) + 1
        sizes[bucket] = sizes.get(bucket, 0) + len(line)
    total_chars = sum(sizes.values())
    print("-" * 78)
    print("F. Buffer byte composition (characters)")
    print("-" * 78)
    print(f"{'events':>9} {'chars':>14} {'share':>7}  category")
    ordered = sorted(sizes.items(), key=lambda item: item[1], reverse=True)
    for bucket, chars in ordered:
        share = chars / total_chars * 100 if total_chars else 0.0
        print(
            f"{counts[bucket]:>9,} {chars:>14,} " f"{share:>6.1f}%  {bucket}",
        )
    print(f"{len(buffer):>9,} {total_chars:>14,} {100.0:>6.1f}%  TOTAL")
    print()


def _fold_row(
    label: str,
    scale: float,
    stream: list[str],
    replayed: list[str],
    stats: Optional[tuple[int, int, int]],
) -> None:
    """Print one G-table row comparing a stream with its folded form."""
    before_events = len(stream)
    after_events = len(replayed)
    before_bytes = sum(sys.getsizeof(line) for line in stream)
    after_bytes = sum(sys.getsizeof(line) for line in replayed)
    event_ratio = before_events / after_events if after_events else 0.0
    byte_ratio = before_bytes / after_bytes if after_bytes else 0.0
    tail = ""
    if stats is not None:
        tail = f"  {stats[0]:>8,}/{stats[1]:>8,}/{stats[2]:>7,}"
    print(
        f"{label:>6} {scale:>5.2f} {before_events:>9,} "
        f"{after_events:>9,} {event_ratio:>7.1f}x "
        f"{before_bytes / _MIB:>9.1f} {after_bytes / _MIB:>8.1f} "
        f"{byte_ratio:>7.1f}x{tail}",
    )


def _empty_row(label: str, scale: float) -> None:
    """Print a G-table placeholder row for an unavailable store."""
    na = "n/a"
    print(
        f"{label:>6} {scale:>5.2f} {na:>9} {na:>9} {na:>8} "
        f"{na:>9} {na:>8} {na:>8}",
    )


def table_g(buffer: list[str]) -> None:
    """Print table G: lossless fold compression at three scales."""
    started = time.monotonic()
    production = _load_production_store()
    print("-" * 78)
    print("G. Lossless fold compression")
    print("   A2 gate: scale=1.00 -> event_ratio >= 20, byte_ratio >= 6")
    print("   proto = this script's reference fold (always available)")
    print(
        "   prod  = qwenpaw.app.replay_store.ReplayStore "
        f"({'present' if production else 'absent, n/a until T2'})",
    )
    print("   proto rows end with merged/superseded/passthrough counts")
    print("-" * 78)
    print(
        f"{'store':>6} {'scale':>5} {'before':>9} {'after':>9} "
        f"{'ev ratio':>8} {'MiB in':>9} {'MiB out':>8} "
        f"{'B ratio':>8}  merged/supersd/pass",
    )
    for scale in _G_SCALES:
        cut = len(buffer) if scale >= 1.0 else int(len(buffer) * scale)
        stream = buffer[:cut]
        prototype = FoldPrototype()
        for line in stream:
            prototype.append(line)
        _fold_row(
            "proto",
            scale,
            stream,
            list(prototype.replay()),
            (prototype.merged, prototype.superseded, prototype.passthrough),
        )
        if production is None:
            _empty_row("prod", scale)
            continue
        store = production()
        for line in stream:
            store.append(line)
        _fold_row("prod", scale, stream, list(store.replay()), None)
    print(f"   [{time.monotonic() - started:.1f}s]\n")


# Lines that must survive the fold untouched: the two non-JSON payloads
# the characterization tests assert byte-for-byte, the console control
# events, an Event envelope, and the empty string.
_MALFORMED = (
    "data: first\n\n",
    "data: second\n\n",
    "data: \n\n",
    "data:\n\n",
    "data: {not json}\n\n",
    'data: {"type": "turn_usage", "input_tokens": 12}\n\n',
    'data: {"type": "rate_limited", "reason": "429"}\n\n',
    'data: {"type": "replay_end"}\n\n',
    'data: {"object": "event", "type": "session.created"}\n\n',
    "",
)

_FIXTURE = (
    _REPO_ROOT
    / "console"
    / "src"
    / "pages"
    / "Chat"
    / "tests"
    / "fixtures"
    / "reconnectReplayStream.txt"
)


def _reduce(events: list[str]) -> dict[str, Any]:
    """Reduce a stream to the state a client renders (spec section 3.3).

    Content deltas append their string field, content snapshots replace
    the accumulated state, messages and responses upsert by id, and
    anything else is kept verbatim in order. A fold is lossless exactly
    when it leaves this value unchanged. ``sequence_number`` and the
    ``status`` of intermediate deltas are deliberately not tracked: C8
    forbids clients from depending on either.
    """
    contents: dict[Any, dict[str, Any]] = {}
    messages: dict[Any, Any] = {}
    responses: dict[Any, Any] = {}
    verbatim: list[str] = []
    for sse in events:
        decoded = _decoded(sse)
        if not isinstance(decoded, dict):
            verbatim.append(sse)
            continue
        obj = decoded.get("object")
        if obj == "content":
            block = decoded.get("data")
            block = block if isinstance(block, dict) else {}
            key = (
                decoded.get("msg_id"),
                decoded.get("index"),
                decoded.get("type"),
            )
            slot = contents.setdefault(
                key,
                {"text": "", "arguments": "", "output": "", "snap": None},
            )
            if decoded.get("delta") is True:
                slot["text"] += decoded.get("text") or ""
                slot["arguments"] += block.get("arguments") or ""
            else:
                slot["text"] = decoded.get("text") or ""
                slot["arguments"] = block.get("arguments") or ""
                slot["output"] = block.get("output") or ""
                slot["snap"] = decoded
        elif obj == "message":
            messages[decoded.get("id")] = decoded
        elif obj == "response":
            responses[decoded.get("id")] = decoded
        else:
            verbatim.append(sse)
    return {
        "contents": contents,
        "messages": messages,
        "responses": responses,
        "verbatim": verbatim,
    }


def _fixture_lines() -> list[str]:
    """Return the real console replay fixture as buffered SSE lines.

    This is the only real production replay data in the repository, and
    it is serialized in the *spaced* style that
    ``channels/base.py:_strip_event_headlines`` produces, so it is what
    proves the classifier tolerates both spacing conventions (spec N2).
    """
    if not _FIXTURE.is_file():
        return []
    raw = _FIXTURE.read_text(encoding="utf-8")
    return [f"{chunk}\n\n" for chunk in raw.split("\n\n") if chunk.strip()]


def _interleave(base: list[str], extras: list[str]) -> list[str]:
    """Spread ``extras`` evenly through ``base``."""
    pending = list(extras)
    if not pending:
        return list(base)
    step = max(len(base) // len(pending), 1)
    mixed: list[str] = []
    for position, line in enumerate(base):
        mixed.append(line)
        if position % step == step - 1 and pending:
            mixed.append(pending.pop(0))
    mixed.extend(pending)
    return mixed


def _lossless(name: str, stream: list[str]) -> bool:
    """Fold ``stream`` and report whether its reduced state survived."""
    folded = FoldPrototype()
    for line in stream:
        folded.append(line)
    replayed = list(folded.replay())
    before = _reduce(stream)
    after = _reduce(replayed)
    equivalent = True
    print(f"  3.3  {name}")
    print(
        f"       {len(stream):,} events -> {len(replayed):,} "
        f"({len(stream) / max(len(replayed), 1):.1f}x)",
    )
    for key in ("contents", "messages", "responses", "verbatim"):
        ok = before[key] == after[key]
        equivalent = equivalent and ok
        print(
            f"       {key:<10} {len(before[key]):>8,} entries : "
            f"{'PASS' if ok else 'FAIL'}",
        )
    return equivalent


def table_v(buffer: list[str]) -> bool:
    """Print table V and report whether the reference fold is lossless.

    The G table only means something if the fold it measures preserves
    the end state, so these checks gate the whole report. The synthetic
    run alone carries no control events, which is precisely the blind
    spot spec R2 warns about, so a mixed corpus is checked as well.
    """
    started = time.monotonic()
    print("-" * 78)
    print("V. Reference fold correctness (spec C7 and section 3.3)")
    print("-" * 78)

    probe = FoldPrototype()
    for line in _MALFORMED:
        probe.append(line)
    kept = list(probe.replay())
    c7 = kept == list(_MALFORMED)
    print("  C7   unparseable / control / Event lines pass through")
    print(
        f"       {len(_MALFORMED)} in -> {len(kept)} out, byte-identical "
        f"and in order : {'PASS' if c7 else 'FAIL'}",
    )

    fixture = _fixture_lines()
    print(
        "       real console fixture: "
        f"{'loaded' if fixture else 'absent, skipped'}",
    )
    ok = c7
    ok = _lossless("synthetic run", buffer) and ok
    if fixture:
        ok = _lossless("real console fixture", fixture) and ok
    mixed = _interleave(buffer, [*fixture, *_MALFORMED])
    ok = _lossless("mixed: run + fixture + control events", mixed) and ok
    print(
        f"  verdict: {'fold is lossless' if ok else 'FOLD IS LOSSY'}"
        f"   [{time.monotonic() - started:.1f}s]\n",
    )
    return ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _guard_import() -> None:
    """Abort when qwenpaw resolved outside this repository."""
    import qwenpaw

    resolved = Path(qwenpaw.__file__).resolve()
    if _REPO_ROOT not in resolved.parents:
        raise SystemExit(
            "qwenpaw resolved outside this repository:\n"
            f"  imported: {resolved}\n"
            f"  expected under: {_REPO_ROOT}\n"
            "Re-run with PYTHONPATH=$(pwd)/src so the worktree under "
            "test is measured instead of the editable install.",
        )


async def _run(args: argparse.Namespace) -> bool:
    """Print the requested tables; False when a verification check failed."""
    wanted = set(args.table)
    _print_header()
    if "a" in wanted:
        await table_a()
    if not wanted & {"d", "f", "g", "v"}:
        return True
    print(f"Building a {args.rounds}-round synthetic run ...")
    started = time.monotonic()
    sample_before = _mem_sample()
    buffer, response_bytes = await build_run_buffer(args.rounds)
    sample_after = _mem_sample()
    print(
        f"Built {len(buffer):,} events in "
        f"{time.monotonic() - started:.1f}s\n",
    )
    if "d" in wanted:
        table_d(buffer, response_bytes, (sample_before, sample_after))
    if "f" in wanted:
        table_f(buffer)
    if "g" in wanted:
        table_g(buffer)
    return table_v(buffer) if "v" in wanted else True


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reproducible memory benchmark for the TaskTracker replay "
            "buffer (QWEN-4). Prints tables A, D, F, G and V; A carries "
            "the A1 acceptance gate, G the A2 gate, and V proves the "
            "reference fold G measures is lossless. Exits non-zero when "
            "a V check fails."
        ),
        epilog=(
            "default command (the acceptance baseline for T1/T2):\n"
            "  PYTHONPATH=$(pwd)/src <env>/bin/python "
            "scripts/bench_replay_buffer.py\n\n"
            "numbers to read:\n"
            "  A1 gate: table A, deltas=1024 row, delta_emits\n"
            "           baseline 1024, must become <= 8\n"
            "  A2 gate: table G, scale=1.00 prod row (proto row until\n"
            "           T2 lands), event_ratio >= 20 and byte_ratio >= 6\n"
            "  memory : table D, 'str object exact bytes' is the\n"
            "           authoritative figure; RSS is a lower bound\n"
            "  source : table F, content(delta=false,type=data) share\n"
            "  trust  : table V must read 'fold is lossless'; the G\n"
            "           ratios mean nothing if it does not\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--table",
        action="append",
        choices=("a", "d", "f", "g", "v"),
        help="table to print; repeatable; default is all five",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=1720,
        help=(
            "synthetic ReAct rounds for tables D/F/G/V; one round emits "
            "exactly 282 buffer events, so 1720 rounds yields about "
            "485k events (default: %(default)s)"
        ),
    )
    args = parser.parse_args(argv)
    if not args.table:
        args.table = ["a", "d", "f", "g", "v"]
    return args


def main(argv: Optional[list[str]] = None) -> int:
    """Run the benchmark; non-zero exit when a verification check fails."""
    _guard_import()
    args = _parse_args(argv)
    return 0 if asyncio.run(_run(args)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
