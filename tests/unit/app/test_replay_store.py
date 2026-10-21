# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.replay_store.ReplayStore``.

Covers the acceptance criteria that are properties of the store itself
rather than of a whole reconnect:

- control frames and unparseable lines survive a fold byte for byte and in
  order (criterion 5, spec C7)
- the ``clear_history`` latch rides the last snapshot and survives
  (criterion 5)
- classification reads a bounded window, never the payload, at 10 MiB and
  in both serialization styles (criterion 6, spec section 3.2)
- the unanchored classifier the original spec described misreads a message
  as content, which is why the shipped one anchors on the leading key
  (criterion 7, spec revision M-1)
- a folded slot sits at its key's last occurrence: the response snapshot
  ends up last and every content slot before its host message
  (criterion 8, spec revision M-2)
- content snapshots with a null ``msg_id`` are dropped from the replay copy
  and never become a fold key (criterion 10, spec section 3.4 iii)
"""
# pylint: disable=protected-access
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

import pytest

from qwenpaw.app import replay_store as rs
from qwenpaw.app.replay_store import ReplayStore
from qwenpaw.schemas import (
    AgentResponse,
    ContentType,
    DataContent,
    Event,
    Message,
    MessageType,
    Role,
    RunStatus,
    TextContent,
)
from tests.unit.app import replay_corpus as corpus

_MIB = 1024 * 1024
_BIG = "x" * (10 * _MIB)

_OBJECT_RE = re.compile(r'"object":\s*"(\w+)"')


def _payload(sse: str) -> str:
    """Return the JSON payload of a framed SSE line."""
    return sse[len(corpus.SSE_PREFIX) : -len(corpus.SSE_SUFFIX)]


def _decode(sse: str) -> object:
    """Parse a framed SSE line, or None when it is not a JSON object."""
    try:
        return json.loads(_payload(sse))
    except ValueError:
        return None


def _fold(stream: list[str]) -> list[str]:
    """Return ``stream`` as the store hands it to a reconnect."""
    store = ReplayStore()
    for sse in stream:
        store.append(sse)
    return list(store.replay())


# ---------------------------------------------------------------------------
# Criterion 5: control frames and the clear_history latch
# ---------------------------------------------------------------------------


_FRAMES = corpus.CONTROL_SSES + corpus.UNPARSEABLE_SSES


@pytest.mark.parametrize("frame", _FRAMES)
def test_control_and_unparseable_frames_survive_verbatim(frame: str) -> None:
    """One control frame between two deltas comes back byte for byte."""
    before = corpus.compact(_text_delta("msg_a", "hello "))
    after = corpus.compact(_text_delta("msg_a", "world"))
    folded = _fold([before, frame, after])
    assert frame in folded
    assert folded.count(frame) == 1
    assert len(folded) == 2


async def test_mixed_stream_keeps_every_control_frame_in_order() -> None:
    """The mixed corpus loses no control frame and does not reorder them."""
    stream = await corpus.mixed_stream(corpus.compact)
    folded = _fold(stream)
    frames = (
        list(corpus.CONTROL_SSES)
        + list(corpus.UNPARSEABLE_SSES)
        + [
            'data: {"object": "event", "type": "session.created"}\n\n',
            'data: {"type": "replay_end"}\n\n',
        ]
    )
    for frame in frames:
        assert stream.count(frame) == folded.count(frame), frame
    kept_original = [sse for sse in stream if sse in frames]
    kept_folded = [sse for sse in folded if sse in frames]
    assert kept_original == kept_folded


async def test_clear_history_latch_survives_the_fold() -> None:
    """The latch is written after the stub, so only last-wins keeps it.

    ``Envelope.from_msg`` yields the completed message twice: first empty,
    then with ``metadata`` from the command's ``Msg``. A fold that kept the
    first snapshot would silently drop ``clear_history`` and leave the
    console showing a session it was told to reset.
    """
    stream = await corpus.command_stream(
        corpus.compact,
        metadata={"clear_history": True, "clear_plan": True},
    )
    latched_originals = [sse for sse in stream if "clear_history" in sse]
    assert len(latched_originals) == 2, "message and response both carry it"

    latched_folded = [sse for sse in _fold(stream) if "clear_history" in sse]
    assert latched_folded == latched_originals


async def test_clear_history_absent_when_command_sets_none() -> None:
    """A command without metadata must not gain a latch from the fold."""
    stream = await corpus.command_stream(corpus.compact)
    assert not any("clear_history" in sse for sse in stream)
    assert not any("clear_history" in sse for sse in _fold(stream))


# ---------------------------------------------------------------------------
# Criterion 6: bounded-window classification, 5 shapes x 2 styles x 10 MiB
# ---------------------------------------------------------------------------


def _text_delta(msg_id: str, text: str) -> TextContent:
    content = TextContent(
        type=ContentType.TEXT,
        text=text,
        delta=True,
        index=0,
        msg_id=msg_id,
    )
    return content


def _data_snapshot(msg_id: str, output: str) -> DataContent:
    return DataContent(
        type=ContentType.DATA,
        data={"call_id": "call_1", "name": "shell", "output": output},
        delta=False,
        index=0,
        msg_id=msg_id,
    )


def _shapes() -> list[tuple[str, Callable[[], Any], rs._Class]]:
    """Return ``(name, object, expected classification)`` for the 5 shapes.

    ``object`` is a zero-argument factory so the 10 MiB payloads are built
    one at a time rather than all at once.
    """

    def text_delta() -> TextContent:
        return _text_delta("msg_big", _BIG)

    def data_snapshot() -> DataContent:
        return _data_snapshot("msg_big", _BIG)

    def message() -> Message:
        envelope = Message(
            id="msg_big",
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[_text_delta("msg_big", _BIG)],
            status=RunStatus.Completed,
        )
        envelope.object = "message"
        return envelope

    def response() -> AgentResponse:
        payload = Message(
            id="msg_big",
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[_text_delta("msg_big", _BIG)],
            status=RunStatus.Completed,
        )
        payload.object = "message"
        snapshot = AgentResponse(
            id="response_big",
            output=[payload],
            status=RunStatus.Completed,
        )
        snapshot.object = "response"
        return snapshot

    def heartbeat() -> Event:
        # ``Event`` declares ``object`` first, so its leading key is neither
        # ``type`` nor ``id`` and it is retained verbatim whatever it carries.
        return Event(
            object="message",
            type="heartbeat",
            data={"blob": _BIG},
        )

    return [
        (
            "content text delta",
            text_delta,
            rs._Class(
                rs._MERGE,
                (
                    "content",
                    "msg_big",
                    "0",
                    "text",
                ),
            ),
        ),
        (
            "content data snapshot",
            data_snapshot,
            rs._Class(
                rs._REPLACE,
                (
                    "content",
                    "msg_big",
                    "0",
                    "data",
                ),
            ),
        ),
        ("message", message, rs._Class(rs._REPLACE, ("id", "msg_big"))),
        ("response", response, rs._Class(rs._REPLACE, ("id", "response_big"))),
        ("heartbeat event", heartbeat, rs._Class(rs._PASSTHROUGH)),
    ]


@pytest.mark.parametrize("style", [corpus.compact, corpus.spaced])
@pytest.mark.parametrize("name,factory,expected", _shapes())
def test_ten_mib_payload_classifies_from_the_window(
    name: str,
    factory: Callable[[], Any],
    expected: rs._Class,
    style: corpus.Serialize,
) -> None:
    """A 10 MiB event classifies identically to a small one.

    Every field the fold keys on is a declared pydantic field ahead of the
    unbounded ``text`` / ``data`` / ``output`` payload, so it sits inside
    ``head[:256]`` whatever the event grows to. If pydantic ever reorders
    them this fails loudly instead of silently dropping the ratio to 1x.
    """
    sse = style(factory())
    assert len(sse) > 10 * _MIB, name

    head = rs._head(sse)
    assert head is not None
    assert len(head) <= rs._HEAD_WINDOW
    assert rs._classify(head) == expected, name

    # Widening the window to the whole 10 MiB payload does not change the
    # answer, so nothing beyond the window was needed to reach it.
    assert rs._classify(_payload(sse)) == expected, name


@pytest.mark.parametrize("name,factory,_expected", _shapes())
def test_both_styles_classify_identically(
    name: str,
    factory: Callable[[], Any],
    _expected: rs._Class,
) -> None:
    """Compact and spaced JSON must never take different branches."""
    compact_head = rs._head(corpus.compact(factory()))
    spaced_head = rs._head(corpus.spaced(factory()))
    assert compact_head is not None and spaced_head is not None
    assert rs._classify(compact_head) == rs._classify(spaced_head), name


@pytest.mark.parametrize("style", [corpus.compact, corpus.spaced])
def test_append_never_parses_a_ten_mib_payload(
    style: corpus.Serialize,
) -> None:
    """Classification and retention are both parse-free at 10 MiB.

    Appending happens inside the tracker lock, so parsing a multi-megabyte
    snapshot there would stall every concurrent reconnect. The merge path is
    the only one that parses and it is capped at 1 MiB, so at 10 MiB nothing
    parses at all — asserted by counting calls rather than by timing.
    """
    calls: list[str] = []
    real_loads = rs.json.loads

    def counting_loads(text: str) -> object:
        calls.append(text[:32])
        return real_loads(text)

    lines = [style(factory()) for _name, factory, _exp in _shapes()]
    store = ReplayStore()
    original = rs.json.loads
    rs.json.loads = counting_loads  # type: ignore[assignment]
    try:
        started = time.monotonic()
        for _ in range(4):
            for sse in lines:
                store.append(sse)
        elapsed = time.monotonic() - started
    finally:
        rs.json.loads = original  # type: ignore[assignment]

    assert not calls, "a 10 MiB payload must never be parsed"
    assert elapsed < 5.0, f"20 appends of 10 MiB events took {elapsed:.2f}s"


def test_small_deltas_do_merge() -> None:
    """The parse-free guarantee above is not vacuous: small deltas merge."""
    calls: list[str] = []
    real_loads = rs.json.loads

    def counting_loads(text: str) -> object:
        calls.append(text)
        return real_loads(text)

    store = ReplayStore()
    original = rs.json.loads
    rs.json.loads = counting_loads  # type: ignore[assignment]
    try:
        store.append(corpus.compact(_text_delta("msg_a", "hello ")))
        store.append(corpus.compact(_text_delta("msg_a", "world")))
    finally:
        rs.json.loads = original  # type: ignore[assignment]

    assert len(calls) == 2
    folded = list(store.replay())
    assert len(folded) == 1
    decoded = _decode(folded[0])
    assert isinstance(decoded, dict)
    assert decoded["text"] == "hello world"


def test_head_window_is_bounded() -> None:
    """``_head`` slices at most the window, and never the whole payload."""
    sse = corpus.compact(_text_delta("msg_a", _BIG))
    head = rs._head(sse)
    assert head is not None
    assert len(head) == rs._HEAD_WINDOW
    # An empty payload still yields an empty window rather than None.
    assert rs._head("data: \n\n") == ""
    # Anything the channels would not have framed is left for verbatim
    # retention: no space after the colon, no framing at all, empty line.
    assert rs._head("data:\n\n") is None
    assert rs._head("not sse\n\n") is None
    assert rs._head("") is None


# ---------------------------------------------------------------------------
# Criterion 7: the unanchored classifier the original spec described
# ---------------------------------------------------------------------------


def _unanchored_classify(head: str) -> str:
    """The spec section 3.2 classifier: scan the window for ``object``.

    Kept here as a negative control. It reads plausible and passes every
    test that uses hand-written payloads, because those lead with
    ``"object"``. Real message snapshots do not.
    """
    found = _OBJECT_RE.search(head)
    return found.group(1) if found else "unknown"


async def test_unanchored_classifier_misreads_a_message_as_content() -> None:
    """Why M-1 anchors on the leading key.

    ``Message`` declares ``id, type, role, content, status, metadata`` and
    carries ``object`` as an extra, so it is serialized last. The first
    ``"object"`` inside the window is therefore the *nested*
    ``"object": "content"`` of ``content[0]``, and an unanchored scan routes
    the whole message into the content branch — where it would be folded
    against a content key and its snapshot lost.
    """
    stream = await corpus.synthetic_stream(1, corpus.compact)
    messages = [
        sse
        for sse in stream
        if (rs._head(sse) or "").startswith('{"id"')
        and '"object":"content"' in (rs._head(sse) or "")
    ]
    assert messages, "expected a message snapshot with content in the window"

    for sse in messages:
        head = rs._head(sse)
        assert head is not None
        assert _unanchored_classify(head) == "content"
        assert rs._classify(head).key[0] == "id"

    assert any(
        rs._classify(head) != rs._Class(rs._PASSTHROUGH)
        for head in (rs._head(sse) for sse in messages)
        if head is not None
    )


# ---------------------------------------------------------------------------
# Criterion 8: last-occurrence ordering
# ---------------------------------------------------------------------------


async def test_fold_orders_slots_by_last_occurrence() -> None:
    """A slot sits at its key's *last* event, not its first.

    ``handleContent`` assigns a snapshot onto ``msg.content[-1]``, so
    replaying a content slot after its own message snapshot overwrites
    finished output with a stale one; and ``handleResponse`` copies
    ``output`` wholesale, so a response snapshot replayed early is
    overwritten by nothing and the run appears stuck in progress.
    """
    for style in (corpus.compact, corpus.spaced):
        stream = await corpus.synthetic_stream(3, style)
        folded = _fold(stream)

        positions = []
        for position, sse in enumerate(folded):
            decoded = _decode(sse)
            if isinstance(decoded, dict):
                positions.append((position, decoded))

        responses = [p for p, d in positions if d.get("object") == "response"]
        assert responses, "no response snapshot in the fold"
        assert responses[-1] == len(folded) - 1
        assert len(responses) == 1

        messages = {
            d["id"]: p for p, d in positions if d.get("object") == "message"
        }
        contents = [
            (p, d) for p, d in positions if d.get("object") == "content"
        ]
        assert contents
        for position, decoded in contents:
            host = messages.get(decoded.get("msg_id"))
            assert host is not None, decoded.get("msg_id")
            assert position < host, (
                f"content slot {position} replayed after its host message "
                f"{host} for {decoded.get('msg_id')}"
            )


def test_reordering_moves_a_touched_slot_to_the_end() -> None:
    """The move is observable on three lines, without a whole run."""
    store = ReplayStore()
    store.append('data: {"id":"a","object":"message","content":[]}\n\n')
    store.append('data: {"id":"b","object":"message","content":[]}\n\n')
    store.append('data: {"id":"a","object":"message","content":[1]}\n\n')
    folded = list(store.replay())
    assert [json.loads(_payload(s))["id"] for s in folded] == ["b", "a"]
    assert json.loads(_payload(folded[1]))["content"] == [1]


# ---------------------------------------------------------------------------
# Criterion 10: null msg_id content snapshots
# ---------------------------------------------------------------------------


def _null_msg_id_contents(stream: list[str]) -> list[str]:
    """Return the content lines of ``stream`` whose ``msg_id`` is null."""
    found = []
    for sse in stream:
        decoded = _decode(sse)
        if not isinstance(decoded, dict):
            continue
        if decoded.get("object") != "content":
            continue
        if "msg_id" in decoded and decoded["msg_id"] is None:
            found.append(sse)
    return found


async def test_null_msg_id_snapshots_are_dropped_and_never_a_key() -> None:
    """Spec section 3.4 (iii), on the two sites that produce them.

    ``envelope.py:458`` (TOOL_CALL_END) and ``:600`` (TOOL_RESULT_END) each
    yield a terminal ``DataContent`` whose ``msg_id`` was never set, because
    ``schemas.py:add_content`` does not back-fill it. ``handleContent``
    resolves the host message by ``msg_id`` and warns-and-drops when there is
    none, so these are not applied on the live path either. Keying on null
    would additionally let concurrent tool calls evict each other.
    """
    stream = await corpus.synthetic_stream(3, corpus.compact)
    dropped = _null_msg_id_contents(stream)
    assert len(dropped) == 6, "expected two per round from :458 and :600"

    folded = _fold(stream)
    for sse in dropped:
        assert sse not in folded
    assert not _null_msg_id_contents(folded)

    # Both terminal shapes are represented: the tool-call one carries no
    # index at all, the tool-result one carries index 0.
    shapes = {json.loads(_payload(s)).get("index") for s in dropped}
    assert shapes == {None, 0}


def test_null_msg_id_snapshot_cannot_evict_a_real_slot() -> None:
    """A dropped event must not take the key of the content around it."""
    first = corpus.compact(_text_delta("msg_a", "hello "))
    null_snapshot = corpus.compact(
        DataContent(
            type=ContentType.DATA,
            data={"output": "stale"},
            delta=False,
        ),
    )
    assert '"msg_id":null' in null_snapshot
    second = corpus.compact(_text_delta("msg_a", "world"))

    folded = _fold([first, null_snapshot, second])
    assert len(folded) == 1
    decoded = _decode(folded[0])
    assert isinstance(decoded, dict)
    assert decoded["text"] == "hello world"


async def test_two_tool_outputs_do_not_collide() -> None:
    """Two tool calls in one run keep two separate output slots."""
    from qwenpaw.runtime.envelope import Envelope

    envelope = Envelope(session_id="test-two-tools")
    out: list[str] = []
    for suffix in ("a", "b"):
        for event in corpus.tool_events(
            0,
            call_suffix=suffix,
            output_chars=512,
            output_deltas=4,
        ):
            async for obj in envelope.translate_event(event):
                out.append(corpus.compact(obj))

    folded = _fold(out)
    outputs = []
    for sse in folded:
        decoded = _decode(sse)
        if not isinstance(decoded, dict) or decoded.get("object") != "message":
            continue
        if decoded.get("type") != "plugin_call_output":
            continue
        data = decoded["content"][0].get("data") or {}
        outputs.append((data.get("call_id"), len(data.get("output") or "")))
    assert len(outputs) == 2
    assert len({call_id for call_id, _ in outputs}) == 2
    assert all(length == 512 for _, length in outputs)


# ---------------------------------------------------------------------------
# Fold mechanics that are not tied to one acceptance criterion
# ---------------------------------------------------------------------------


def test_delta_after_snapshot_keeps_both_events() -> None:
    """The builder pushes a new item there; one slot cannot express it.

    ``Builder.js:132`` guards the merge on ``lastContent.delta``, so a delta
    arriving after a snapshot becomes a second content item rather than
    extending the first. Merging them would render one item where the client
    shows two.
    """
    snapshot = corpus.compact(
        DataContent(
            type=ContentType.DATA,
            data={"output": "first"},
            delta=False,
            index=0,
            msg_id="msg_a",
        ),
    )
    delta = corpus.compact(
        DataContent(
            type=ContentType.DATA,
            data={"arguments": "tail"},
            delta=True,
            index=0,
            msg_id="msg_a",
        ),
    )
    folded = _fold([snapshot, delta])
    assert len(folded) == 2
    assert folded[0] == snapshot
    assert folded[1] == delta


def test_snapshot_supersedes_deltas_and_later_deltas_reopen() -> None:
    """A snapshot overwrites the accumulated deltas; the next delta pushes.

    ``Builder.js:161-166`` assigns a ``delta=false`` event onto
    ``msg.content[-1]`` wholesale, so the text the preceding deltas
    accumulated is gone on the live path too — retaining it in the fold
    would add content the client never showed. ``Builder.js:132`` then fails
    its ``lastContent.delta`` guard, so the delta after the snapshot becomes
    a second content item and folds separately from the first run.
    """
    key = "msg_a"
    lines = [
        corpus.compact(_text_delta(key, "a")),
        corpus.compact(_text_delta(key, "b")),
        corpus.compact(
            TextContent(
                type=ContentType.TEXT,
                text="snapshot",
                delta=False,
                index=0,
                msg_id=key,
            ),
        ),
        corpus.compact(_text_delta(key, "c")),
        corpus.compact(_text_delta(key, "d")),
    ]
    snapshot = lines[2]
    folded = _fold(lines)
    assert folded[0] == snapshot
    rendered = []
    for sse in folded:
        payload = _decode(sse)
        assert isinstance(payload, dict)
        rendered.append((payload["text"], payload["delta"]))
    assert rendered == [("snapshot", False), ("cd", True)]


def test_merge_takes_the_merge_base_from_the_first_fragment() -> None:
    """A later TOOL_CALL_DELTA carries only ``arguments`` (spec M-8, F6).

    ``envelope.py:429-431`` deliberately omits ``call_id`` and ``name`` from
    argument deltas so the builder does not concatenate those too, so basing
    the merged event on the last fragment would drop them.
    """
    first = DataContent(
        type=ContentType.DATA,
        data={"call_id": "call_1", "name": "shell", "arguments": '{"a":'},
        delta=True,
        index=0,
        msg_id="msg_a",
    )
    second = DataContent(
        type=ContentType.DATA,
        data={"arguments": " 1}"},
        delta=True,
        index=0,
        msg_id="msg_a",
    )
    folded = _fold([corpus.compact(first), corpus.compact(second)])
    assert len(folded) == 1
    decoded = _decode(folded[0])
    assert isinstance(decoded, dict)
    assert decoded["data"] == {
        "call_id": "call_1",
        "name": "shell",
        "arguments": '{"a": 1}',
    }


def test_merge_carries_status_and_sequence_from_the_last_fragment() -> None:
    """The client should see the final status, not the opening one."""
    lines = []
    for text, seq in (("a", 7), ("b", 8), ("c", 9)):
        content = _text_delta("msg_a", text)
        content.status = RunStatus.InProgress
        content.sequence_number = seq
        lines.append(corpus.compact(content))
    folded = _fold(lines)
    assert len(folded) == 1
    decoded = _decode(folded[0])
    assert isinstance(decoded, dict)
    assert decoded["text"] == "abc"
    assert decoded["sequence_number"] == 9
    assert decoded["status"] == "in_progress"


def test_non_contiguous_sequence_numbers_are_not_a_reason_to_split() -> None:
    """C8: the fixture jumps 57 -> 192 and the fold must not care."""
    lines = []
    for text, seq in (("a", 57), ("b", 192)):
        content = _text_delta("msg_a", text)
        content.sequence_number = seq
        lines.append(corpus.spaced(content))
    folded = _fold(lines)
    assert len(folded) == 1
    decoded = _decode(folded[0])
    assert isinstance(decoded, dict)
    assert decoded["text"] == "ab"


def test_oversized_delta_is_retained_verbatim_instead_of_parsed() -> None:
    """Above the merge cap the event is kept, never dropped (spec C7)."""
    big = corpus.compact(_text_delta("msg_a", "y" * (2 * _MIB)))
    folded = _fold([big, corpus.compact(_text_delta("msg_a", "z"))])
    assert folded[0] == big
    assert len(folded) == 2


def test_unparseable_merge_fragment_falls_back_to_verbatim() -> None:
    """A delta whose payload will not parse is retained, not lost."""
    good = corpus.compact(_text_delta("msg_a", "hello "))
    broken = (
        'data: {"type":"text","delta":true,"index":0,"object":"content",'
        '"msg_id":"msg_a","text": ???\n\n'
    )
    folded = _fold([good, broken])
    assert broken in folded
    assert folded[0] == good


def test_empty_store_and_approx_bytes() -> None:
    """``approx_bytes`` is an estimate, for measurement only."""
    store = ReplayStore()
    assert not list(store.replay())
    assert store.approx_bytes() == 0

    raw = 'data: {"id":"a","object":"message"}\n\n'
    store.append(raw)
    assert store.approx_bytes() == len(raw)

    cjk = ReplayStore()
    cjk.append(corpus.compact(_text_delta("msg_a", "中文")))
    rendered = list(cjk.replay())[0]
    assert cjk.approx_bytes() == len(rendered)
    assert cjk.approx_bytes() < len(rendered.encode("utf-8"))


async def test_approx_bytes_tracks_rendered_size() -> None:
    """The estimate stays within a fraction of a percent of the truth.

    On a compact stream it is a lower bound as well: ``approx_len`` counts
    the fragments as they arrived, while ``render`` re-escapes the joined
    ``arguments``, and escaping only ever adds characters. A spaced stream
    goes the other way by a couple of bytes per merged slot.
    """
    stream = await corpus.synthetic_stream(
        8,
        corpus.compact,
        round_kwargs={"output_chars": 4096, "output_deltas": 24},
    )
    store = ReplayStore()
    for sse in stream:
        store.append(sse)
    rendered = sum(len(sse) for sse in store.replay())
    assert store.approx_bytes() <= rendered
    assert store.approx_bytes() > rendered * 0.99


def test_replay_is_lazy_and_repeatable() -> None:
    """Two iterations of ``replay()`` agree; the store is not consumed."""
    store = ReplayStore()
    for sse in ("data: first\n\n", corpus.compact(_text_delta("m", "a"))):
        store.append(sse)
    first = list(store.replay())
    second = list(store.replay())
    assert first == second
    assert len(first) == 2
