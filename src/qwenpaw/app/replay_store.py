# -*- coding: utf-8 -*-
"""Folded reconnect replay storage for ``TaskTracker``.

``TaskTracker`` retains every SSE event of a run so a reconnecting
console can replay what it missed. Retaining them verbatim keeps every
full tool result snapshot the envelope re-emits, so one long run holds
hundreds of near-identical copies of the same bytes.

:class:`ReplayStore` retains only what survives the reduction the
frontend already performs, keyed the way the SDK response builder keys
it. The folded replay reduces to the same state as the unfolded stream.
Anything that cannot be classified with certainty is retained verbatim:
a misclassification may cost compression, it must never change the end
state (spec C7).

Two rules come from reading the real builder shipped in
``@agentscope-ai/chat`` (``Response/Builder.js``) rather than from an
idealized protocol:

*   A content snapshot whose ``msg_id`` is null is dropped from the
    replay copy. ``handleContent`` resolves the host message by
    ``msg_id`` and silently discards the event when there is none, so
    those snapshots are not applied on the live path either (spec
    section 3.4, option iii). The live broadcast still carries every
    event (spec C1).
*   A folded slot sits at the position of its key's *last* event, not
    its first. ``handleContent`` assigns a snapshot onto
    ``msg.content[-1]`` and pushes a fresh item when a delta follows a
    non-delta, so replaying a content slot after its own message
    snapshot overwrites finished output with a stale one and duplicates
    the tool card (spec revision M-2).
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterator, Optional, Union

_SSE_PREFIX = "data: "
_SSE_SUFFIX = "\n\n"

# Classification reads a bounded prefix, never the whole payload.
# ``_ContentBase`` declares ``type, delta, index, status, object,
# msg_id`` ahead of the unbounded ``text`` / ``data`` fields, and both
# ``Message`` and ``AgentResponse`` declare ``id`` first, so every field
# the fold keys on sits inside this window whatever the payload grows to
# (spec section 3.2). ``test_replay_store.py`` fails loudly if pydantic
# ever reorders them, instead of silently dropping the ratio to 1x.
_HEAD_WINDOW = 256

# Merging is the only path that parses, so it is the only one that needs
# a bound. The largest events of a run are the multi-megabyte
# ``response`` snapshots, and parsing one inside the tracker lock would
# stall every concurrent reconnect; a delta above the cap is retained
# verbatim instead, which is always safe (spec C7).
_MERGE_PAYLOAD_LIMIT = 1 << 20

# Taken from the last fragment of a merged key rather than the first: the
# final status and sequence number are the ones a client should see.
_CARRIED_FIELDS = ("status", "sequence_number")

_MERGE = "merge"
_REPLACE = "replace"
_DROP = "drop"
_PASSTHROUGH = "passthrough"

# pydantic v2 serializes declared fields in declaration order and puts
# ``extra="allow"`` fields after them, which is what makes the leading
# key a reliable discriminator. Searching the window for the first
# ``"object"`` instead matches the *nested* ``"object": "content"`` of
# ``Message.content[0]`` and routes every message into the content
# branch (spec revision M-1).
_FIRST_KEY_RE = re.compile(r'^\{\s*"(\w+)"\s*:')
_LEADING_ID_RE = re.compile(r'^\{\s*"id":\s*"([^"]+)"')
_OBJECT_CONTENT_RE = re.compile(r'"object":\s*"content"')
_MSG_ID_RE = re.compile(r'"msg_id":\s*(?:"([^"]+)"|null)')
_INDEX_RE = re.compile(r'"index":\s*(-?\d+|null)')
_TYPE_RE = re.compile(r'"type":\s*"(\w+)"')
_DELTA_RE = re.compile(r'"delta":\s*(true|false)')


@dataclass(frozen=True)
class _Class:
    """What the fold does with one SSE line, from bounded windows only."""

    kind: str
    key: Any = None


_PASSTHROUGH_CLASS = _Class(_PASSTHROUGH)
_DROP_CLASS = _Class(_DROP)


@dataclass
class _RawSlot:
    """One SSE line retained byte for byte."""

    sse: str

    def render(self) -> str:
        """Return the retained line unchanged."""
        return self.sse

    def approx_len(self) -> int:
        """Return the retained length in characters."""
        return len(self.sse)


@dataclass
class _MergeSlot:
    """Accumulated ``delta=true`` fragments of one content key.

    The first fragment is the merge base. A later ``TOOL_CALL_DELTA``
    carries only ``{"arguments": ...}`` while the first also carries
    ``call_id`` and ``name``, so basing the merged event on the last
    fragment would drop them (spec revision M-8, ruling F6).
    """

    base: dict[str, Any]
    path: tuple[str, ...]
    fragments: list[str]
    carried: dict[str, Any]
    base_len: int

    def render(self) -> str:
        """Serialize the accumulated fragments into one SSE line."""
        merged = dict(self.base)
        node = merged
        for part in self.path[:-1]:
            node[part] = dict(node[part])
            node = node[part]
        node[self.path[-1]] = "".join(self.fragments)
        merged.update(self.carried)
        payload = json.dumps(
            merged,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return f"{_SSE_PREFIX}{payload}{_SSE_SUFFIX}"

    def approx_len(self) -> int:
        """Estimate the rendered length in characters."""
        extra = sum(map(len, self.fragments)) - len(self.fragments[0])
        return self.base_len + extra


_Slot = Union[_RawSlot, _MergeSlot]


def _head(sse: str) -> Optional[str]:
    """Return the classification window of an SSE line, or None.

    None means the line is not framed the way the channels frame SSE, so
    there is nothing to classify and it must be retained verbatim. The
    window is a bounded slice: taking the whole payload first would copy
    the multi-megabyte ``response`` snapshots this module exists to stop
    the tracker from re-reading.
    """
    if not sse.startswith(_SSE_PREFIX) or not sse.endswith(_SSE_SUFFIX):
        return None
    start = len(_SSE_PREFIX)
    stop = min(len(sse) - len(_SSE_SUFFIX), start + _HEAD_WINDOW)
    return sse[start : max(start, stop)]


def _payload(sse: str) -> str:
    """Return the JSON payload of a framed SSE line."""
    return sse[len(_SSE_PREFIX) : len(sse) - len(_SSE_SUFFIX)]


def _classify_content(head: str) -> _Class:
    """Classify a window whose leading key is ``type``.

    ``_ContentBase`` leads with ``type``, but so do the control events
    ``channels/console/channel.py`` emits with plain ``json.dumps``
    (``turn_usage``, ``rate_limited``) and ``REPLAY_END_SSE``. Those
    carry no ``object`` field at all, which is what separates them from
    real content and lets them fall through to verbatim retention with no
    special case anywhere.
    """
    if _OBJECT_CONTENT_RE.search(head) is None:
        return _PASSTHROUGH_CLASS
    msg_id = _MSG_ID_RE.search(head)
    if msg_id is None:
        return _PASSTHROUGH_CLASS
    if msg_id.group(1) is None:
        # Spec section 3.4 (iii). Keying on null would let concurrent
        # tool calls evict each other's output, and the builder drops
        # these anyway because it cannot find their host message.
        return _DROP_CLASS
    index = _INDEX_RE.search(head)
    content_type = _TYPE_RE.search(head)
    delta = _DELTA_RE.search(head)
    if index is None or content_type is None or delta is None:
        return _PASSTHROUGH_CLASS
    key = (
        "content",
        msg_id.group(1),
        index.group(1),
        content_type.group(1),
    )
    kind = _MERGE if delta.group(1) == "true" else _REPLACE
    return _Class(kind, key)


def _classify(head: str) -> _Class:
    """Classify one SSE line from its leading key and a bounded window."""
    first = _FIRST_KEY_RE.match(head)
    if first is None:
        return _PASSTHROUGH_CLASS
    marker = first.group(1)
    if marker == "type":
        return _classify_content(head)
    if marker == "id":
        # ``AgentResponse.id`` is optional. Anchoring on the leading key
        # keeps a null id from picking up the ``"id"`` of the first
        # message in ``output`` and colliding with that message's slot.
        leading = _LEADING_ID_RE.match(head)
        if leading is None:
            return _PASSTHROUGH_CLASS
        return _Class(_REPLACE, ("id", leading.group(1)))
    return _PASSTHROUGH_CLASS


def _merge_payload(sse: str) -> Optional[dict[str, Any]]:
    """Parse a delta line, or None when it is oversized or not an object.

    Only the merge path parses, and only below ``_MERGE_PAYLOAD_LIMIT``;
    every other classification is decided from the window alone.
    """
    if len(sse) > _MERGE_PAYLOAD_LIMIT:
        return None
    try:
        decoded = json.loads(_payload(sse))
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _append_path(decoded: dict[str, Any]) -> Optional[tuple[str, ...]]:
    """Return the field a content delta accumulates into, if any.

    ``handleContent`` appends ``text`` for a TEXT delta and, for a DATA
    delta whose host message is a streaming tool input, concatenates each
    string field of ``data``. Only ``arguments`` ever reaches the buffer
    that way: the envelope emits tool result snapshots as ``delta=false``
    and deliberately leaves ``call_id`` and ``name`` out of argument
    deltas so those are not concatenated too.
    """
    if isinstance(decoded.get("text"), str):
        return ("text",)
    data = decoded.get("data")
    if isinstance(data, dict) and isinstance(data.get("arguments"), str):
        return ("data", "arguments")
    return None


def _read(decoded: dict[str, Any], path: tuple[str, ...]) -> str:
    """Return the string ``path`` selects from ``decoded``."""
    node: Any = decoded
    for part in path:
        node = node[part]
    return node


def _carried(decoded: dict[str, Any]) -> dict[str, Any]:
    """Return the fields a merged event takes from its last fragment."""
    return {name: decoded[name] for name in _CARRIED_FIELDS if name in decoded}


def _create_merge(sse: str) -> Optional[_MergeSlot]:
    """Open a merge slot from the first fragment of a content key."""
    decoded = _merge_payload(sse)
    if decoded is None:
        return None
    path = _append_path(decoded)
    if path is None:
        return None
    return _MergeSlot(
        base=decoded,
        path=path,
        fragments=[_read(decoded, path)],
        carried=_carried(decoded),
        base_len=len(sse),
    )


def _extend(slot: _MergeSlot, sse: str) -> bool:
    """Add one fragment to ``slot``; False when that would be unsafe."""
    decoded = _merge_payload(sse)
    if decoded is None:
        return False
    path = _append_path(decoded)
    if path != slot.path:
        return False
    slot.fragments.append(_read(decoded, path))
    slot.carried = _carried(decoded)
    return True


class ReplayStore:
    """Reconnect replay buffer folded by the frontend's reduction.

    Every method must be called under the tracker lock. ``replay()`` is
    lazy, so appending while a caller iterates would mutate the slots it
    is still rendering.
    """

    def __init__(self) -> None:
        self._slots: OrderedDict[int, _Slot] = OrderedDict()
        self._owners: dict[Any, int] = {}
        self._next_slot = 0

    def append(self, sse: str) -> None:
        """Fold one SSE line into the replay copy."""
        head = _head(sse)
        if head is None:
            self._push(_RawSlot(sse))
            return
        found = _classify(head)
        if found.kind == _MERGE:
            self._merge(found.key, sse)
        elif found.kind == _REPLACE:
            self._replace(found.key, sse)
        elif found.kind == _PASSTHROUGH:
            self._push(_RawSlot(sse))
        # _DROP retains nothing: the builder cannot apply these events on
        # the live path either, so the replay copy simply omits them.

    def replay(self) -> Iterator[str]:
        """Yield the folded SSE lines in last-occurrence order."""
        for slot in self._slots.values():
            yield slot.render()

    def approx_bytes(self) -> int:
        """Estimate the retained replay size, for measurement only.

        Nothing is ever evicted on this figure, and it is not a bound in
        either direction. ``len`` counts code points, so UTF-8 CJK makes it
        under-count the real byte cost (spec N6); a merged slot renders
        compact while its base may have arrived spaced, which makes it
        over-count the rendered characters by a couple of bytes per slot
        (spec revision F7). Both errors are well under a percent.
        """
        return sum(slot.approx_len() for slot in self._slots.values())

    def _push(self, slot: _Slot) -> int:
        """Append ``slot`` at the end and return its id."""
        slot_id = self._next_slot
        self._next_slot += 1
        self._slots[slot_id] = slot
        return slot_id

    def _replace(self, key: Any, sse: str) -> None:
        """Keep only this event for ``key``, at this event's position."""
        slot_id = self._owners.get(key)
        if slot_id is None:
            self._owners[key] = self._push(_RawSlot(sse))
            return
        self._slots[slot_id] = _RawSlot(sse)
        self._slots.move_to_end(slot_id)

    def _merge(self, key: Any, sse: str) -> None:
        """Accumulate a content delta into the slot owning ``key``."""
        slot_id = self._owners.get(key)
        if slot_id is not None:
            slot = self._slots[slot_id]
            if isinstance(slot, _MergeSlot):
                if _extend(slot, sse):
                    self._slots.move_to_end(slot_id)
                    return
                del self._owners[key]
                self._push(_RawSlot(sse))
                return
            # A snapshot owns the slot. The builder pushes a new content
            # item when a delta follows a non-delta, which one slot
            # cannot express, so both events stay verbatim and later
            # deltas for this key open a slot of their own (spec M-5).
            del self._owners[key]
        created = _create_merge(sse)
        if created is None:
            self._push(_RawSlot(sse))
            return
        self._owners[key] = self._push(created)
