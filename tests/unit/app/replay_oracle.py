# -*- coding: utf-8 -*-
"""Reference reducer for the ``ReplayStore`` equivalence tests.

A fold is acceptable exactly when a client that replays it renders the same
conversation as a client that watched the run live. The client is the SDK
response builder shipped in ``@agentscope-ai/chat`` at
``lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder.js``,
behind the ``responseParser`` the console installs at
``console/src/pages/Chat/index.tsx``. This module transcribes both, so the
comparison runs against the reducer that actually ships rather than an
idealized protocol (spec revision M-5).

Three of the shipped behaviours are non-obvious and are the reason an
idealized oracle judges a correct fold as broken, or a broken fold as
correct:

*   ``handleContent`` assigns a snapshot onto ``msg.content[-1]`` — the
    *last* item, with no lookup by ``index`` or ``type``
    (``Builder.js:161-166``).
*   ``handleContent`` concatenates DATA deltas per key only when the host
    message is a streaming tool input, and only when both the existing and
    the incoming value are strings (``Builder.js:137-156``).
*   An unknown payload does not raise. It falls through to ``handleError``,
    which marks the response failed and injects an error message
    (``Builder.js:187-200``). Silent state corruption, not an exception.

The parser in front of the builder swallows three control frames before the
builder can see them (``index.tsx:4333-4356``): ``turn_usage`` and
``rate_limited`` return ``null``, and ``replay_end`` is rewritten to a
heartbeat, which ``handle`` skips. Feeding those to ``handleError`` instead
would fabricate error messages no client ever renders.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SSE_PREFIX = "data: "
SSE_SUFFIX = "\n\n"

OBJECT_RESPONSE = "response"
OBJECT_MESSAGE = "message"
OBJECT_CONTENT = "content"

MESSAGE_HEARTBEAT = "heartbeat"
MESSAGE_ERROR = "error"
MESSAGE_PLUGIN_CALL = "plugin_call"
MESSAGE_TOOL_CALL = "tool_call"
MESSAGE_MCP_CALL = "mcp_call"

CONTENT_TEXT = "text"
CONTENT_IMAGE = "image"
CONTENT_DATA = "data"

STATUS_CREATED = "created"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_CANCELED = "canceled"

#: ``Builder.js:138`` — DATA deltas are concatenated per key only for these.
STREAMING_TOOL_INPUT = frozenset(
    {MESSAGE_PLUGIN_CALL, MESSAGE_TOOL_CALL, MESSAGE_MCP_CALL},
)

#: ``index.tsx:4256-4276`` — the wire says ``cancelled``, the SDK says
#: ``canceled``, and the parser rewrites one to the other.
_GENERATING = frozenset({STATUS_CREATED, STATUS_IN_PROGRESS, STATUS_CANCELLED})

#: Fields the comparison deliberately ignores. ``sequence_number`` because
#: C8 forbids a client from depending on it — a merged delta legitimately
#: carries its last fragment's number where the live client kept the first
#: — and ``created_at`` because the builder defaults it to the wall clock.
_IGNORED_FIELDS = frozenset({"sequence_number", "created_at", "object"})


@dataclass
class Reduction:
    """Everything one pass through the client produces."""

    state: Dict[str, Any]
    #: Lines ``JSON.parse`` rejects; the builder never sees them, and a fold
    #: must hand them back byte for byte (spec C7).
    verbatim: List[str] = field(default_factory=list)
    #: Control frames the responseParser swallows or rewrites. Recorded so a
    #: test can assert the fold neither lost nor duplicated one.
    intercepted: List[str] = field(default_factory=list)
    #: ``handleContent`` warnings for a content event with no host message.
    #: Excluded from the comparison: a fold legitimately changes this count
    #: (spec revision M-2 measured 2 -> 5 on the real corpus).
    dropped: int = 0


#: Outcome of running one SSE line through the console's responseParser.
_SWALLOW = "swallow"
_UNPARSEABLE = "unparseable"


def _normalize_cancellation(payload: Dict[str, Any]) -> None:
    """Rewrite ``cancelled`` to ``canceled`` (``index.tsx:4256-4276``)."""
    if (
        payload.get("object") != OBJECT_RESPONSE
        or payload.get("status") != STATUS_CANCELLED
    ):
        return
    payload["status"] = STATUS_CANCELED
    outputs = payload.get("output")
    for message in outputs if isinstance(outputs, list) else []:
        if not isinstance(message, dict):
            continue
        if message.get("status") in _GENERATING:
            message["status"] = STATUS_CANCELED
        contents = message.get("content")
        for content in contents if isinstance(contents, list) else []:
            if isinstance(content, dict) and content.get("status") in (
                _GENERATING
            ):
                content["status"] = STATUS_CANCELED


def parse_response(chunk: str) -> Any:
    """Apply the console's ``responseParser`` to one SSE line.

    Returns the payload dict to hand to the builder, ``_SWALLOW`` when the
    parser consumes the frame itself, or ``_UNPARSEABLE`` when
    ``JSON.parse`` would reject it.
    """
    if not chunk.startswith(SSE_PREFIX) or not chunk.endswith(SSE_SUFFIX):
        return _UNPARSEABLE
    body = chunk[len(SSE_PREFIX) : -len(SSE_SUFFIX)]
    try:
        payload = json.loads(body)
    except ValueError:
        return _UNPARSEABLE
    if not isinstance(payload, dict):
        return _UNPARSEABLE
    _normalize_cancellation(payload)
    kind = payload.get("type")
    if kind in ("turn_usage", "rate_limited"):
        return _SWALLOW
    if kind == "replay_end":
        return {"object": OBJECT_MESSAGE, "type": MESSAGE_HEARTBEAT}
    return payload


def _handle_response(state: Dict[str, Any], data: Dict[str, Any]) -> None:
    """Transcribe ``Builder.js:41-92``."""
    existing = state.get("output") or []
    incoming = data.get("output")
    state.update(data)
    if not incoming:
        state["output"] = existing
        return
    if not existing:
        return
    by_id = {m.get("id"): m for m in existing if isinstance(m, dict)}
    incoming_ids = {m.get("id") for m in incoming if isinstance(m, dict)}
    merged: List[Any] = []
    for increment in incoming:
        if not isinstance(increment, dict):
            merged.append(increment)
            continue
        previous = by_id.get(increment.get("id"))
        if previous is None:
            merged.append(increment)
            continue
        # "Prefer the message with content already populated" (Bug 2 of
        # issue #4644): a partial-update response must not wipe out the
        # tool-call data streaming already collected.
        incoming_has = bool(increment.get("content"))
        existing_has = bool(previous.get("content"))
        if existing_has and not incoming_has:
            merged.append({**increment, "content": previous["content"]})
        else:
            merged.append(increment)
    for message in existing:
        if isinstance(message, dict) and message.get("id") not in incoming_ids:
            merged.append(message)
    state["output"] = merged


def _handle_message(state: Dict[str, Any], data: Dict[str, Any]) -> None:
    """Transcribe ``Builder.js:96-115``."""
    if state.get("output") is None:
        state["output"] = []
    output: List[Any] = state["output"]
    wanted = data.get("id")
    index = next(
        (
            position
            for position, message in enumerate(output)
            if isinstance(message, dict) and message.get("id") == wanted
        ),
        -1,
    )
    if index < 0:
        output.append(data)
        return
    previous_content = output[index].get("content")
    output[index].update(data)
    if not data.get("content"):
        # ``Object.assign`` replaced content wholesale; roll back so an
        # empty snapshot cannot erase accumulated streaming content.
        output[index]["content"] = previous_content


def _merge_data(
    message: Dict[str, Any],
    last: Dict[str, Any],
    data: Dict[str, Any],
) -> Any:
    """Transcribe ``Builder.js:151-158``.

    A DATA delta concatenates per key only when the host message is a
    streaming tool input, and then only for values that are strings on both
    sides. Every other shape replaces the field wholesale.
    """
    if message.get("type") not in STREAMING_TOOL_INPUT:
        return data.get("data")
    merged = dict(last.get("data") or {})
    for key, value in (data.get("data") or {}).items():
        if isinstance(value, str) and isinstance(merged.get(key), str):
            merged[key] = merged[key] + value
        else:
            merged[key] = value
    return merged


def _merge_delta(
    message: Dict[str, Any],
    last: Dict[str, Any],
    data: Dict[str, Any],
) -> None:
    """Transcribe ``Builder.js:137-157``, the ``delta=true`` merge."""
    kind = data.get("type")
    if kind == CONTENT_TEXT and last.get("type") == CONTENT_TEXT:
        last["text"] = (last.get("text") or "") + (data.get("text") or "")
    elif kind == CONTENT_IMAGE:
        last["image_url"] = data.get("image_url")
    elif kind == CONTENT_DATA:
        last["data"] = _merge_data(message, last, data)


def _handle_content(
    state: Dict[str, Any],
    data: Dict[str, Any],
    reduction: Reduction,
) -> None:
    """Transcribe ``Builder.js:118-168``."""
    message = next(
        (
            candidate
            for candidate in state.get("output") or []
            if isinstance(candidate, dict)
            and candidate.get("id") == data.get("msg_id")
        ),
        None,
    )
    if message is None:
        reduction.dropped += 1
        return
    if message.get("content") is None:
        message["content"] = []
    contents: List[Any] = message["content"]
    if not data.get("delta"):
        if contents:
            contents[-1].update(data)
        else:
            contents.append(data)
        return

    last = contents[-1] if contents else None
    if not (isinstance(last, dict) and last.get("delta")):
        # A delta after a snapshot pushes a *new* item; it does not merge
        # into the snapshot. One folded slot cannot express that sequence,
        # which is why the store keeps both events verbatim.
        contents.append(data)
        return

    _merge_delta(message, last, data)


def _handle_error(state: Dict[str, Any], data: Dict[str, Any]) -> None:
    """Transcribe ``Builder.js:170-186``.

    ``uuid()`` becomes a positional placeholder: the id is random, so it can
    never compare equal across two reductions, and nothing downstream keys
    on it.
    """
    state["status"] = STATUS_FAILED
    raw = data.get("message")
    if raw is None:
        rendered: Optional[str] = None
    elif isinstance(raw, str):
        rendered = raw
    else:
        rendered = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    errors = sum(
        1
        for message in state.get("output") or []
        if isinstance(message, dict) and message.get("type") == MESSAGE_ERROR
    )
    if state.get("output") is None:
        state["output"] = []
    state["output"].append(
        {
            "status": STATUS_FAILED,
            "type": MESSAGE_ERROR,
            "content": [],
            "id": f"__error_{errors}__",
            "role": "assistant",
            "code": data.get("code"),
            "message": rendered,
        },
    )


def reduce(events: List[str]) -> Reduction:  # noqa: A001 - spec name
    """Reduce an SSE stream to the state a client renders."""
    reduction = Reduction(
        state={
            "id": None,
            "output": [],
            "object": OBJECT_RESPONSE,
            "status": STATUS_CREATED,
            "created_at": 0,
        },
    )
    for chunk in events:
        payload = parse_response(chunk)
        if payload == _UNPARSEABLE:
            reduction.verbatim.append(chunk)
        elif payload == _SWALLOW:
            reduction.intercepted.append(chunk)
        else:
            _dispatch(reduction, payload)
    return reduction


def _dispatch(reduction: Reduction, data: Dict[str, Any]) -> None:
    """Transcribe ``Builder.js:187-200``."""
    state = reduction.state
    payload = copy.deepcopy(data)
    kind = payload.get("object")
    if kind == OBJECT_RESPONSE:
        _handle_response(state, payload)
    elif kind == OBJECT_MESSAGE:
        if payload.get("type") == MESSAGE_HEARTBEAT:
            return
        _handle_message(state, payload)
    elif kind == OBJECT_CONTENT:
        _handle_content(state, payload, reduction)
    else:
        _handle_error(state, payload)


def _summarize_content(content: Any) -> Any:
    """Comparison value for one content item."""
    if not isinstance(content, dict):
        return content
    return {
        key: value
        for key, value in content.items()
        if key not in _IGNORED_FIELDS
    }


def _summarize_message(message: Any) -> Any:
    """Comparison value for one output message."""
    if not isinstance(message, dict):
        return message
    summary = {
        key: value
        for key, value in message.items()
        if key not in _IGNORED_FIELDS and key != "content"
    }
    summary["content"] = [
        _summarize_content(item) for item in message.get("content") or []
    ]
    return summary


def summarize(reduction: Reduction) -> Dict[str, Any]:
    """Return the field-by-field comparison value of a reduction.

    ``output`` is compared as an ordered list, not as a set keyed by id:
    the console renders it in order and pairs tool inputs with outputs by
    walking it, so a fold that reorders messages is user-visible even when
    every message is individually intact.
    """
    state = reduction.state
    return {
        "status": state.get("status"),
        "id": state.get("id"),
        "output": [_summarize_message(m) for m in state.get("output") or []],
        "verbatim": list(reduction.verbatim),
        "intercepted": list(reduction.intercepted),
    }
