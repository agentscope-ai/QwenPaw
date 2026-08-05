# -*- coding: utf-8 -*-
"""The structured ``recall_history`` recall tool.

The parameterized front door to durable history: ``expand`` / ``search`` /
``recall_tool`` cover the overwhelming share of recall calls, and none of
them needs model-authored code — each is a bound, read-only SQL query over
:class:`.memoryspace.MemorySpace`, executed in-process. That is why this tool
needs no sandbox and no approval (it is registered as an ``internal``
governance type): unlike ``recall_history_python`` there is nothing here the
model controls beyond scalar parameters, so there is nothing to isolate.

``recall_history_python`` remains the escape hatch for everything else
(sessions listing, custom SQL aggregation, scratch tables) — but it executes
model-authored Python and therefore requires the sandbox. When no sandbox
backend is available, it fails closed unless the explicit unsafe fallback is
enabled.
Fold stubs and the eviction index point at THIS tool first so the common
re-read path works everywhere.
"""

# NOTE: no ``from __future__ import annotations`` here — FunctionTool builds
# the model-facing JSON schema from the wrapped function's runtime
# annotations, and stringified ones fail pydantic's resolution.
import base64
import binascii
import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ....runtime.tool_registry import ToolDescriptor
from ....utils.io_utils import run_sync_io
from ...tools.utils import DEFAULT_MAX_BYTES

logger = logging.getLogger(__name__)

_OPS = ("expand", "search", "recall_tool", "days_between")
RECALL_PAGE_METADATA_KEY = "qwenpaw_recall_page"
_RECALL_BLOCKED_NOTICE = (
    "RECALL LOOP BLOCKED — this exact recall page already completed in the "
    "current user turn. Do not repeat it. If the page returned next_cursor, "
    "continue with that cursor; otherwise narrow the range or change the "
    "search query."
)
_RECALL_IN_FLIGHT_NOTICE = (
    "RECALL LOOP BLOCKED — this exact recall page is already running in the "
    "current user turn. Wait for that result instead of issuing a duplicate "
    "concurrent recall."
)
_RECALL_OBSERVATION_TRUNCATED = (
    "\n[… recall observation truncated to byte limit]"
)


class RecallSnapshotChangedError(ValueError):
    """A continuation cursor no longer matches its result snapshot."""


def _normalize_seq_arg(value: int | str | None, name: str) -> int | None:
    """Normalize one model-facing seq argument to a positive integer.

    Some models serialize JSON integer tool arguments as strings. Accept an
    ASCII-decimal string for that compatibility case, but reject coercions
    that could silently change the requested span (booleans, floats, signs,
    whitespace, decimal points, or non-positive values).
    """
    if value is None:
        return None
    if type(value) is int:  # ``bool`` is an ``int`` subclass; reject it.
        normalized = value
    elif (
        isinstance(value, str)
        and value
        and value.isascii()
        and value.isdecimal()
    ):
        normalized = int(value)
    else:
        raise ValueError(
            f"{name} must be a positive JSON integer or an ASCII-decimal "
            "integer string",
        )
    if normalized <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return normalized


def _normalize_expand_args(
    op: str,
    lo: int | str | None,
    hi: int | str | None,
    max_bytes: int,
) -> tuple[int | None, int | None] | ToolChunk:
    """Canonicalize expand seqs or return a bounded validation failure."""
    if op != "expand":
        # These arguments belong only to ``expand``. Dropping them for other
        # operations also gives the execution layer one stable, integer-only
        # type regardless of the model-facing compatibility schema.
        return None, None
    try:
        return _normalize_seq_arg(lo, "lo"), _normalize_seq_arg(hi, "hi")
    except ValueError as exc:
        text = _bound_observation(
            f'RECALL FAILED — invalid op="expand" seq span '
            f"(ValueError: {exc}).",
            max_bytes,
        )
        return ToolChunk(
            content=[TextBlock(type="text", text=text)],
            state=ToolResultState.ERROR,
        )


def _canonical_request_payload(
    op: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return the parameters that determine one recall result set."""
    if op == "expand":
        return {
            key: payload.get(key)
            for key in ("lo", "hi")
            if payload.get(key) is not None
        }
    if op == "search":
        normalized = dict(payload)
        normalized.setdefault("k", 10)
        normalized.setdefault("all_agents", False)
        return {
            key: normalized.get(key)
            for key in (
                "query",
                "k",
                "kind",
                "all_agents",
                "session_id",
                "agent_id",
                "created_on",
                "created_from",
                "created_to",
            )
            if normalized.get(key) is not None
        }
    if op == "recall_tool":
        return {"tool_call_id": payload.get("tool_call_id")}
    if op == "days_between":
        normalized = dict(payload)
        normalized.setdefault("inclusive", False)
        return {
            key: normalized.get(key)
            for key in ("start", "end", "inclusive")
            if normalized.get(key) is not None
        }
    return {key: value for key, value in payload.items() if key != "cursor"}


def _request_fingerprint(op: str, payload: dict[str, Any]) -> str:
    canonical = {
        "op": op,
        "parameters": _canonical_request_payload(op, payload),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class RecallLoopGuard:
    """Atomically reject duplicate recall pages within one real user turn."""

    turn_id: str | None = None
    blocked: set[str] = field(default_factory=set)
    _generation: int = 0
    _in_flight: dict[str, int] = field(default_factory=dict)
    _lock: Any = field(
        default_factory=threading.Lock,
        repr=False,
        compare=False,
    )

    @staticmethod
    def key(op: str, payload: dict[str, Any]) -> str:
        relevant = _canonical_request_payload(op, payload)
        if payload.get("cursor") is not None:
            relevant["cursor"] = payload["cursor"]
        return f"{op}:" + json.dumps(
            relevant,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def begin_turn(self, turn_id: str | None) -> None:
        """Reset completed/in-flight pages when the real user turn changes."""
        with self._lock:
            if turn_id != self.turn_id:
                self.turn_id = turn_id
                self._generation += 1
                self.blocked.clear()
                self._in_flight.clear()

    def claim(
        self,
        op: str,
        payload: dict[str, Any],
    ) -> tuple[int | None, str | None]:
        key = self.key(op, payload)
        with self._lock:
            if key in self.blocked:
                return None, _RECALL_BLOCKED_NOTICE
            if key in self._in_flight:
                return None, _RECALL_IN_FLIGHT_NOTICE
            generation = self._generation
            self._in_flight[key] = generation
            return generation, None

    def finish(
        self,
        op: str,
        payload: dict[str, Any],
        generation: int,
        *,
        block: bool,
    ) -> None:
        key = self.key(op, payload)
        with self._lock:
            # A slow completion from an earlier turn must not mutate the new
            # turn's claim for the same request.
            if self._in_flight.get(key) != generation:
                return
            self._in_flight.pop(key, None)
            if block and generation == self._generation:
                self.blocked.add(key)

    def allow_restart(self, op: str, payload: dict[str, Any]) -> None:
        """Allow the documented no-cursor restart after snapshot drift."""
        base_payload = dict(payload)
        base_payload.pop("cursor", None)
        with self._lock:
            self.blocked.discard(self.key(op, base_payload))

    def is_blocked(self, op: str, payload: dict[str, Any]) -> bool:
        """Expose completed-page state for lifecycle integration tests."""
        with self._lock:
            return self.key(op, payload) in self.blocked


_DOC = """Recall your recorded conversation history (raw turns) — structured.

Read back verbatim turns from the durable log: this session's turns that
scrolled out of context (seq spans come from the [context compressed] map)
plus your earlier sessions. Pick an op:

  • op="expand", lo=180, hi=184 — turns in the seq span [lo, hi], oldest
    first. Results are explicit pages that never silently truncate; pass the
    returned cursor unchanged to continue.
  • op="search", query="flight number", k=10 — full-text search over your
    whole history (across your past sessions). Whether the keyword matches a
    user, assistant, or tool-result row, each result includes that row's full
    user-bounded turn. Query with keywords, not full sentences (all terms
    must appear); use OR for alternatives and a generous k to cast a wide net:
    query="tank OR aquarium OR goldfish", k=20. Your current in-progress turn
    is never a hit — it is already in front of you.
    Optional: kind="model_turn"/"tool_result"; all_agents=true to span every
    agent; session_id/agent_id to pin a specific one (take precedence). If a
    question asks what happened on a date, pass created_on="YYYY-MM-DD"; use
    created_from/created_to for an inclusive date range. Date filters use the
    source message's created_at and may be used with an empty query. If a
    large tool result was saved outside the DB, search can return a saved tool
    output match with file_path and nearby matching lines.
  • op="recall_tool", tool_call_id="call_abc" — a tool call and its result.
    For truncated large outputs, this also reports the saved full-output file.
  • op="days_between", start="2024-11-01", end="2024-12-16" — signed
    calendar-day difference (end minus start). Accepts strict ISO dates and
    timestamps, including Z or +/-HH:MM timezones. Set inclusive=true to count
    both endpoints while preserving direction. This operation never pages.

Search turns show their matched seq(s), actual complete seq span, loaded end,
and whether the turn payload is complete. Other ops return individual rows
with their seq. A page ending in next_cursor is incomplete; continue with the
SAME arguments plus cursor=next_cursor. Never retry the same cursor. The
cursor is bound to the original arguments and result snapshot; changing the
query, range, filters, or k fails. An empty result is stated explicitly and
means the history genuinely holds nothing for that span/query. For anything
beyond these operations, use a more advanced Python recall tool if one is
available to you.

Args:
    op (str): One of "expand", "search", "recall_tool", "days_between".
    lo (int | str): expand only — first positive seq of the span; an ASCII
        decimal integer string is accepted for model compatibility.
    hi (int | str): expand only — last positive seq of the span; an ASCII
        decimal integer string is accepted for model compatibility.
    query (str): search only — keyword query (OR supported).
    k (int): search only — max hits to return (default 10).
    kind (str): search only — optional row-kind filter
        ("model_turn" / "tool_result").
    all_agents (bool): search only — span every agent's history.
    session_id (str): search only — pin one conversation
        (e.g. "cron:<job>").
    agent_id (str): search only — pin one agent's history.
    created_on (str): search only — exact ISO calendar date.
    created_from (str): search only — inclusive ISO start date.
    created_to (str): search only — inclusive ISO end date.
    tool_call_id (str): recall_tool only — the tool call to re-read.
    start (str): days_between only — strict ISO start date/timestamp.
    end (str): days_between only — strict ISO end date/timestamp.
    inclusive (bool): days_between only — include both endpoints.
    cursor (str): Opaque continuation cursor returned by a previous page.
"""

# Keys rendered per row, in display order, when present and non-empty.
_ROW_META_KEYS = (
    "kind",
    "role",
    "name",
    "headline",
    "session_id",
    "created_at",
)

_STRUCTURED_FIELD_MAX_BYTES = 4096
_MEDIA_REF_MAX_BYTES = 2048


def _parse_row_blocks(value: Any) -> list[dict[str, Any]]:
    """Decode one durable blocks payload without exposing malformed data."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _bounded_structured_value(value: Any) -> str:
    """Render a structured scalar under a per-field safety bound."""
    if isinstance(value, str):
        rendered = value
    else:
        try:
            rendered = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        except (TypeError, ValueError):
            rendered = str(value)
    if len(rendered.encode("utf-8")) <= _STRUCTURED_FIELD_MAX_BYTES:
        return rendered
    prefix, _ = _utf8_prefix(rendered, _STRUCTURED_FIELD_MAX_BYTES - 3)
    return prefix + "..."


def _safe_media_ref(block: dict[str, Any]) -> str | None:
    """Return a compact media reference without ever inlining binary data."""
    if block.get("type") != "data":
        return None
    source = block.get("source")
    source = source if isinstance(source, dict) else {}
    media_type = str(source.get("media_type") or "")
    kind = media_type.split("/", 1)[0] if "/" in media_type else "file"
    if kind not in ("image", "audio", "video"):
        kind = "file"
    name = _bounded_structured_value(block.get("name") or "")
    raw_url = source.get("url") if source.get("type") == "url" else None
    if raw_url and not str(raw_url).lower().startswith("data:"):
        ref = str(raw_url)
        if len(ref.encode("utf-8")) > _MEDIA_REF_MAX_BYTES:
            ref, _ = _utf8_prefix(ref, _MEDIA_REF_MAX_BYTES - 3)
            ref += "..."
    else:
        ref = f"<{media_type or 'binary'}>"
    return f"[{kind}: {name} — {ref}]" if name else f"[{kind}: {ref}]"


def _render_tool_result_output(output: Any) -> str:
    """Flatten safe result text/media without serializing opaque payloads."""
    if isinstance(output, str):
        return _bounded_structured_value(output)
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and item.get("text"):
            parts.append(_bounded_structured_value(item["text"]))
            continue
        media_ref = _safe_media_ref(item)
        if media_ref:
            parts.append(media_ref)
    return "\n".join(parts)


def _render_row_blocks(row: dict[str, Any], body: str) -> list[str]:
    """Render useful structured context omitted from flattened content."""
    rendered: list[str] = []
    for block in _parse_row_blocks(row.get("blocks")):
        block_type = block.get("type")
        if block_type == "text":
            text = str(block.get("text") or "").rstrip()
            if text and not body:
                rendered.append(text)
            continue
        if block_type == "tool_call":
            fields = " ".join(
                f"{key}={block[key]}"
                for key in ("name", "id")
                if block.get(key) not in (None, "")
            )
            call = "[tool_call" + (f" {fields}" if fields else "") + "]"
            if block.get("input") is not None:
                call += "\ninput=" + _bounded_structured_value(
                    block["input"],
                )
            rendered.append(call)
            continue
        if block_type == "tool_result":
            fields = " ".join(
                f"{key}={block[key]}"
                for key in ("name", "id", "state")
                if block.get(key) not in (None, "")
            )
            result = "[tool_result" + (f" {fields}" if fields else "") + "]"
            if not body and block.get("output") is not None:
                output = _render_tool_result_output(block["output"])
                if output:
                    result += "\n" + output
            rendered.append(result)
            continue
        media_ref = _safe_media_ref(block)
        if media_ref and media_ref not in body:
            rendered.append(media_ref)
    return rendered


def _render_rows(rows: list[dict]) -> str:
    """Rows → readable text; the caller applies the global output bound."""
    parts: list[str] = []
    for row in rows:
        if row.get("_truncated"):
            parts.append(
                f"[… truncated at {row.get('_row_cap')} rows — "
                "narrow the span]",
            )
            continue
        turn = row.get("turn")
        if isinstance(turn, list):
            matched = ",".join(
                str(seq) for seq in row.get("matched_seqs", [row.get("seq")])
            )
            span = f"{row.get('turn_start_seq')}–" f"{row.get('turn_end_seq')}"
            lineage = " ".join(
                f"{key}={row[key]}"
                for key in ("session_id", "agent_id")
                if row.get(key) not in (None, "")
            )
            header = f"— matched_seq={matched} turn_seq={span}"
            if row.get("turn_complete") is False:
                header += (
                    " turn_complete=false"
                    f" loaded_through={row.get('turn_loaded_end_seq')}"
                )
            if lineage:
                header += f" {lineage}"
            rendered_turn = _render_rows(turn)
            matched_row = next(
                (
                    item
                    for item in turn
                    if item.get("seq") == row.get("match_seq")
                ),
                None,
            )
            match_content = str(row.get("content") or "").rstrip()
            # Saved large tool-output matches carry an excerpt in the search
            # hit while the durable turn row contains only its bounded
            # preview. Preserve that otherwise-hidden evidence.
            if (
                matched_row
                and match_content
                != str(
                    matched_row.get("content") or "",
                ).rstrip()
            ):
                header += f"\n[matched content excerpt]\n{match_content}"
            parts.append(
                header + (f"\n{rendered_turn}" if rendered_turn else ""),
            )
            continue
        meta = " ".join(
            f"{k}={row[k]}"
            for k in _ROW_META_KEYS
            if row.get(k) not in (None, "")
        )
        head = f"— seq={row.get('seq')}" + (f" {meta}" if meta else "")
        body = str(row.get("content") or "").rstrip()
        row_parts = [head]
        if body:
            row_parts.append(body)
        row_parts.extend(_render_row_blocks(row, body))
        parts.append("\n".join(row_parts))
    return "\n\n".join(parts)


def _utf8_prefix(text: str, max_bytes: int) -> tuple[str, int]:
    """Return a UTF-8-safe prefix and the number of consumed characters."""
    if max_bytes <= 0:
        return "", 0
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text, len(text)
    prefix = raw[:max_bytes].decode("utf-8", errors="ignore")
    return prefix, len(prefix)


def _bound_observation(text: str, max_bytes: int) -> str:
    """Bound every recall observation, including failures and empty reads."""
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    notice_bytes = len(_RECALL_OBSERVATION_TRUNCATED.encode("utf-8"))
    if notice_bytes >= max_bytes:
        return _utf8_prefix(_RECALL_OBSERVATION_TRUNCATED, max_bytes)[0]
    prefix, _ = _utf8_prefix(text, max_bytes - notice_bytes)
    return prefix + _RECALL_OBSERVATION_TRUNCATED


def _result_fingerprint(rows: list[dict]) -> str:
    encoded = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _encode_cursor(
    row_index: int,
    char_offset: int,
    *,
    request_fingerprint: str,
    result_fingerprint: str,
) -> str:
    payload = json.dumps(
        {
            "c": char_offset,
            "q": request_fingerprint,
            "r": row_index,
            "s": result_fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"v1.{token}"


def _parse_cursor(
    cursor: str | None,
    total_rows: int,
    *,
    request_fingerprint: str,
    result_fingerprint: str,
) -> tuple[int, int]:
    """Decode and validate a request- and snapshot-bound page cursor."""
    if not cursor:
        return 0, 0
    try:
        prefix, token = str(cursor).split(".", 1)
        if prefix != "v1" or not token:
            raise ValueError("unsupported cursor version")
        padding = "=" * (-len(token) % 4)
        decoded = base64.b64decode(
            token + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(decoded.decode("utf-8"))
        row_index = int(payload["r"])
        char_offset = int(payload["c"])
        cursor_request = str(payload["q"])
        cursor_result = str(payload["s"])
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
    ) as exc:
        raise ValueError(
            "cursor must be the exact value returned by recall_history",
        ) from exc
    if cursor_request != request_fingerprint:
        raise ValueError(
            "cursor belongs to a different recall request; restart without "
            "cursor or restore the original arguments",
        )
    if cursor_result != result_fingerprint:
        raise RecallSnapshotChangedError(
            "recall results changed since the previous page; restart the "
            "same request without cursor",
        )
    if row_index < 0 or row_index > total_rows or char_offset < 0:
        raise ValueError("cursor is outside the available recall result")
    if row_index == total_rows and char_offset:
        raise ValueError("cursor is outside the available recall result")
    return row_index, char_offset


def _render_page(
    rows: list[dict],
    *,
    label: str,
    cursor: str | None,
    max_bytes: int,
    request_fingerprint: str,
) -> tuple[str, dict[str, Any]]:
    """Render an explicit page without creating a recall artifact."""
    result_fingerprint = _result_fingerprint(rows)
    row_index, char_offset = _parse_cursor(
        cursor,
        len(rows),
        request_fingerprint=request_fingerprint,
        result_fingerprint=result_fingerprint,
    )
    if len(label.encode("utf-8")) <= 160:
        bounded_label = label
    else:
        bounded_label, _ = _utf8_prefix(label, 157)
        bounded_label += "..."
    intro = f"{len(rows)} row(s) for {bounded_label}; recall page:"
    parts = [intro]
    used = len(intro.encode("utf-8"))
    # Leave room for a continuation footer. Production configuration enforces
    # a minimum 1000-byte page; tests may use a similarly small bound.
    content_limit = max(128, max_bytes - 512)
    next_cursor: str | None = None

    while row_index < len(rows):
        rendered = _render_rows([rows[row_index]])
        if char_offset:
            if char_offset >= len(rendered):
                raise ValueError("cursor is outside the available recall row")
            rendered = rendered[char_offset:]
        separator = "\n\n"
        available = content_limit - used - len(separator.encode("utf-8"))
        if available <= 0:
            raise ValueError(
                "recall page byte limit is too small to make progress",
            )
        if len(rendered.encode("utf-8")) <= available:
            parts.append(separator + rendered)
            used += len((separator + rendered).encode("utf-8"))
            row_index += 1
            char_offset = 0
            continue
        chunk, consumed_chars = _utf8_prefix(rendered, available)
        if chunk:
            parts.append(separator + chunk)
        next_cursor = _encode_cursor(
            row_index,
            char_offset + consumed_chars,
            request_fingerprint=request_fingerprint,
            result_fingerprint=result_fingerprint,
        )
        break

    if next_cursor:
        parts.append(
            "\n\n[recall page incomplete] Continue with the same operation "
            f'and cursor="{next_cursor}". Do not repeat the previous cursor.',
        )
    else:
        parts.append("\n\n[recall page complete]")
    page = {
        "cursor": cursor,
        "next_cursor": next_cursor,
        "total_rows": len(rows),
        "complete": next_cursor is None,
    }
    return "".join(parts), page


def _run_days_between(
    ms: Any,
    start: Optional[str],
    end: Optional[str],
    inclusive: bool,
    cursor: Optional[str],
) -> tuple[str, bool, dict[str, Any]]:
    """Validate and execute the non-paginated date operation."""
    if start is None or end is None:
        return (
            'RECALL FAILED — op="days_between" needs start and end ISO '
            "date/timestamp strings.",
            False,
            {},
        )
    if cursor is not None:
        return (
            'RECALL FAILED — op="days_between" does not paginate; omit '
            "cursor.",
            False,
            {},
        )
    difference = ms.days_between(start, end, inclusive=bool(inclusive))
    return (
        f"days_between(start={start!r}, end={end!r}, "
        f"inclusive={bool(inclusive)}) = {difference}",
        True,
        {},
    )


def _execution_error_detail(op: str) -> str:
    """Operation-specific failure wording for tool observations."""
    if op == "days_between":
        return (
            "the date difference was NOT computed; fix the parameters and "
            "retry"
        )
    return (
        "the history was NOT read. This is an execution error, not an empty "
        "history: fix the parameters and retry, or say explicitly that you "
        "could not retrieve the context"
    )


def _run_search(
    ms: Any,
    query: Optional[str],
    *,
    session_id: Optional[str],
    agent_id: Optional[str],
    all_agents: bool,
    kind: Optional[str],
    k: int,
    created_on: Optional[str],
    created_from: Optional[str],
    created_to: Optional[str],
) -> tuple[list[dict], str]:
    """Validate and execute one keyword/date search."""
    if not (query or "").strip() and not any(
        (created_on, created_from, created_to),
    ):
        raise ValueError(
            'op="search" needs a query or a created-at date filter',
        )
    rows = ms.search(
        query or "",
        session_id=session_id,
        agent_id=agent_id,
        all_agents=bool(all_agents),
        kind=kind,
        k=int(k),
        created_on=created_on,
        created_from=created_from,
        created_to=created_to,
    )
    label = f"search {(query or '')!r}"
    if created_on:
        label += f" created_on={created_on!r}"
    elif created_from or created_to:
        label += f" created_from={created_from!r} created_to={created_to!r}"
    return rows, label


def make_recall_history(
    *,
    history_db_path: str,
    session_id: str | None,
    agent_id: str | None = None,
    loop_guard: RecallLoopGuard | None = None,
    page_max_bytes: int = DEFAULT_MAX_BYTES,
):
    """Build a ``recall_history`` tool bound to one session's history.

    Runs in-process (no subprocess, no sandbox): every op is a bound-parameter
    read-only query, so the model never supplies code. A fresh
    :class:`MemorySpace` per call keeps the read-only ATTACH + authorizer
    setup identical to the REPL's and leaks no connection across calls.
    """

    def _open_ms() -> Any:
        # Imported lazily (not at module top) for symmetry with the sandboxed
        # cell, which imports memoryspace by bare name — and so a broken
        # memoryspace degrades this tool, not the whole scroll import chain.
        from .memoryspace import MemorySpace

        return MemorySpace(
            history_db_path=history_db_path,
            session_id=session_id,
            agent_id=agent_id,
        )

    def _run(  # pylint: disable=too-many-return-statements
        op: str,
        lo: Optional[int],
        hi: Optional[int],
        query: Optional[str],
        k: int,
        kind: Optional[str],
        all_agents: bool,
        q_session_id: Optional[str],
        q_agent_id: Optional[str],
        created_on: Optional[str],
        created_from: Optional[str],
        created_to: Optional[str],
        tool_call_id: Optional[str],
        start: Optional[str],
        end: Optional[str],
        inclusive: bool,
        cursor: Optional[str],
        request_fingerprint: str,
    ) -> tuple[str, bool, dict[str, Any]]:
        """Execute one op. Returns ``(text, ok, page_metadata)``."""
        if op not in _OPS:
            return (
                f"RECALL FAILED — unknown op {op!r}. Use one of: "
                f"{', '.join(_OPS)}.",
                False,
                {},
            )
        ms = _open_ms()
        try:
            if op == "expand":
                if lo is None or hi is None:
                    return (
                        'RECALL FAILED — op="expand" needs lo and hi '
                        "(seq span; one turn is lo == hi).",
                        False,
                        {},
                    )
                rows = ms.expand(int(lo), int(hi))
                label = f"expand [{int(lo)}, {int(hi)}]"
            elif op == "search":
                rows, label = _run_search(
                    ms,
                    query,
                    session_id=q_session_id,
                    agent_id=q_agent_id,
                    all_agents=all_agents,
                    kind=kind,
                    k=k,
                    created_on=created_on,
                    created_from=created_from,
                    created_to=created_to,
                )
            elif op == "recall_tool":
                if not (tool_call_id or "").strip():
                    return (
                        'RECALL FAILED — op="recall_tool" needs a '
                        "tool_call_id.",
                        False,
                        {},
                    )
                rows = ms.recall_tool(tool_call_id)
                label = f"recall_tool {tool_call_id!r}"
            else:  # days_between
                return _run_days_between(
                    ms,
                    start,
                    end,
                    inclusive,
                    cursor,
                )
        finally:
            ms.close()
        if not rows:
            _parse_cursor(
                cursor,
                0,
                request_fingerprint=request_fingerprint,
                result_fingerprint=_result_fingerprint([]),
            )
            # Distinct from a failure on purpose (see repl._format_observation
            # for the same discipline): this IS evidence of absence.
            return (
                f"0 rows for {label} — the history genuinely holds nothing "
                "there. For a search, verify the keywords and date filters "
                "before concluding.",
                True,
                {
                    "cursor": cursor,
                    "next_cursor": None,
                    "total_rows": 0,
                    "complete": True,
                },
            )
        text, page = _render_page(
            rows,
            label=label,
            cursor=cursor,
            max_bytes=page_max_bytes,
            request_fingerprint=request_fingerprint,
        )
        return text, True, page

    async def recall_history(
        op: str,
        lo: Optional[int | str] = None,
        hi: Optional[int | str] = None,
        query: Optional[str] = None,
        k: int = 10,
        kind: Optional[str] = None,
        all_agents: bool = False,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        created_on: Optional[str] = None,
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        inclusive: bool = False,
        cursor: Optional[str] = None,
    ) -> ToolChunk:
        normalized = _normalize_expand_args(op, lo, hi, page_max_bytes)
        if isinstance(normalized, ToolChunk):
            return normalized
        lo, hi = normalized
        payload = {
            "lo": lo,
            "hi": hi,
            "query": query,
            "k": k,
            "kind": kind,
            "all_agents": all_agents,
            "session_id": session_id,
            "agent_id": agent_id,
            "created_on": created_on,
            "created_from": created_from,
            "created_to": created_to,
            "tool_call_id": tool_call_id,
            "start": start,
            "end": end,
            "inclusive": inclusive,
            "cursor": cursor,
        }
        request_fingerprint = _request_fingerprint(op, payload)
        claim_generation: int | None = None
        if loop_guard is not None:
            claim_generation, blocked_notice = loop_guard.claim(op, payload)
            if blocked_notice is not None:
                return ToolChunk(
                    content=[
                        TextBlock(
                            type="text",
                            text=_bound_observation(
                                blocked_notice,
                                page_max_bytes,
                            ),
                        ),
                    ],
                    state=ToolResultState.ERROR,
                )
        block_target = False
        try:
            try:
                text, ok, page = await run_sync_io(
                    _run,
                    op,
                    lo,
                    hi,
                    query,
                    k,
                    kind,
                    all_agents,
                    session_id,
                    agent_id,
                    created_on,
                    created_from,
                    created_to,
                    tool_call_id,
                    start,
                    end,
                    inclusive,
                    cursor,
                    request_fingerprint,
                )
            except Exception as exc:  # noqa: BLE001 - surface, never crash
                if loop_guard is not None and isinstance(
                    exc,
                    RecallSnapshotChangedError,
                ):
                    loop_guard.allow_restart(op, payload)
                logger.warning("recall_history failed", exc_info=True)
                error_type = (
                    "ValueError"
                    if isinstance(exc, RecallSnapshotChangedError)
                    else type(exc).__name__
                )
                detail = _execution_error_detail(op)
                text, ok, page = (
                    f"RECALL FAILED — {detail} ({error_type}: {exc}).",
                    False,
                    {},
                )
            metadata: dict[str, Any] = {}
            if page:
                metadata[RECALL_PAGE_METADATA_KEY] = page
            text = _bound_observation(text, page_max_bytes)
            block_target = ok
            return ToolChunk(
                content=[TextBlock(type="text", text=text)],
                state=(
                    ToolResultState.SUCCESS if ok else ToolResultState.ERROR
                ),
                metadata=metadata,
            )
        finally:
            if loop_guard is not None and claim_generation is not None:
                loop_guard.finish(
                    op,
                    payload,
                    claim_generation,
                    block=block_target,
                )

    recall_history.__doc__ = _DOC
    # Attach the descriptor directly (not via @tool_descriptor) so the tool is
    # NOT auto-collected into the global builtin set — it exists only when the
    # scroll strategy wires it in. No ``requires_sandbox``: parameterized
    # read-only queries need no isolation (governance type: internal).
    descriptor = ToolDescriptor(
        name="recall_history",
        func=recall_history,
        async_execution=True,
        description=_DOC.splitlines()[0],
    )
    # pylint: disable-next=protected-access
    recall_history._tool_descriptor = descriptor  # type: ignore[attr-defined]
    return recall_history
