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
model-authored Python and therefore requires the sandbox, which on platforms
without one (e.g. Windows sans WSL2) means per-call approval or refusal.
Fold stubs and the eviction index point at THIS tool first so the common
re-read path works everywhere.
"""

# NOTE: no ``from __future__ import annotations`` here — FunctionTool builds
# the model-facing JSON schema from the wrapped function's runtime
# annotations, and stringified ones fail pydantic's resolution.
import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ....runtime.tool_registry import ToolDescriptor

logger = logging.getLogger(__name__)

_OPS = ("expand", "search", "recall_tool")
_DEFAULT_RECALL_MAX_BYTES = 16 * 1024
_MAX_RECALL_MAX_BYTES = 50 * 1024
_RECALL_TRUNCATION_NOTICE = (
    "\n\n[recall output truncated]\n"
    "The recall result exceeded its bounded live-context budget. Do NOT "
    "recall this tool result. Narrow the seq range, use a more specific "
    "keyword search, or continue from the archived summary."
)
_RECALL_BLOCKED_NOTICE = (
    "RECALL LOOP BLOCKED — this exact recall target was already returned "
    "and then truncated or folded out of the current live turn. Do not "
    "retry it with the same parameters. Narrow the seq range, use a more "
    "specific keyword search, or continue from the archived summary."
)
_RECALL_IN_FLIGHT_NOTICE = (
    "RECALL LOOP BLOCKED — this exact recall target is already running in "
    "the current turn. Do not issue duplicate concurrent recalls. Wait for "
    "the first result, then narrow the seq range or keyword search if needed."
)


@dataclass
class RecallLoopGuard:
    """Atomically guard folded, truncated, and concurrent recall targets."""

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
        normalized = dict(payload)
        normalized.setdefault("k", 10)
        normalized.setdefault("all_agents", False)
        relevant = {
            key: normalized.get(key)
            for key in (
                "lo",
                "hi",
                "query",
                "k",
                "kind",
                "all_agents",
                "session_id",
                "agent_id",
                "tool_call_id",
            )
            if normalized.get(key) is not None
        }
        return f"{op}:" + json.dumps(
            relevant,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def begin_turn(self, turn_id: str | None) -> None:
        with self._lock:
            if turn_id != self.turn_id:
                self.turn_id = turn_id
                self._generation += 1
                self.blocked.clear()
                self._in_flight.clear()

    def block(self, op: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self.blocked.add(self.key(op, payload))

    def is_blocked(self, op: str, payload: dict[str, Any]) -> bool:
        with self._lock:
            return self.key(op, payload) in self.blocked

    def claim(
        self,
        op: str,
        payload: dict[str, Any],
    ) -> tuple[int | None, str | None]:
        """Claim a target, returning its generation or a blocking notice."""
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
        """Release a claim and optionally block it for the claimed turn."""
        key = self.key(op, payload)
        with self._lock:
            # A slow result from an earlier turn must not release or block a
            # new turn's claim for the same target.
            if self._in_flight.get(key) != generation:
                return
            self._in_flight.pop(key, None)
            if block and generation == self._generation:
                self.blocked.add(key)


_DOC = """Recall your recorded conversation history (raw turns) — structured.

Read back verbatim turns from the durable log: this session's turns that
scrolled out of context (seq spans come from the [context compressed] map)
plus your earlier sessions. Pick an op:

  • op="expand", lo=180, hi=184 — the full turns in the seq span [lo, hi],
    oldest first (one turn is lo == hi). The primary way to re-read what the
    eviction index or a [scroll folded] stub points you at.
  • op="search", query="flight number", k=10 — full-text search over your
    whole history (across your past sessions). Query with keywords, not full
    sentences (all terms must appear); use OR for alternatives and a generous
    k to cast a wide net: query="tank OR aquarium OR goldfish", k=20. Your
    current in-progress turn is never a hit — it is already in front of you.
    Optional: kind="model_turn"/"tool_result"; all_agents=true to span every
    agent; session_id/agent_id to pin a specific one (take precedence). If a
    large tool result was saved outside the DB, search can return a saved tool
    output match with file_path and nearby matching lines.
  • op="recall_tool", tool_call_id="call_abc" — a tool call and its result.
    For truncated large outputs, this also reports the saved full-output file.

Rows come back with their seq so you can expand further. Commit an answer
only from FULL turn text (expand/search return it), never from a headline
alone. An empty result is stated explicitly and means the history genuinely
holds nothing for that span/query — differently-phrased searches are worth
one retry. For anything beyond these three reads (listing sessions, custom
SQL, counting/ranking), use a more advanced Python recall tool if one is
available to you.

Args:
    op (str): One of "expand", "search", "recall_tool".
    lo (int): expand only — first seq of the span.
    hi (int): expand only — last seq of the span.
    query (str): search only — keyword query (OR supported).
    k (int): search only — max hits to return (default 10).
    kind (str): search only — optional row-kind filter
        ("model_turn" / "tool_result").
    all_agents (bool): search only — span every agent's history.
    session_id (str): search only — pin one conversation
        (e.g. "cron:<job>").
    agent_id (str): search only — pin one agent's history.
    tool_call_id (str): recall_tool only — the tool call to re-read.
    max_bytes (int): Maximum response size in bytes. Defaults to a bounded
        16 KiB so one recall cannot immediately force another compaction.
"""

# Keys rendered per row, in display order, when present and non-empty.
_ROW_META_KEYS = ("kind", "role", "name", "headline", "session_id")


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
        meta = " ".join(
            f"{k}={row[k]}"
            for k in _ROW_META_KEYS
            if row.get(k) not in (None, "")
        )
        head = f"— seq={row.get('seq')}" + (f" {meta}" if meta else "")
        body = str(row.get("content") or "").rstrip()
        parts.append(f"{head}\n{body}" if body else head)
    return "\n\n".join(parts)


def make_recall_history(
    *,
    history_db_path: str,
    session_id: str | None,
    agent_id: str | None = None,
    loop_guard: RecallLoopGuard | None = None,
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
        tool_call_id: Optional[str],
    ) -> tuple[str, bool]:
        """Execute one op. Returns ``(text, ok)``."""
        if op not in _OPS:
            return (
                f"RECALL FAILED — unknown op {op!r}. Use one of: "
                f"{', '.join(_OPS)}.",
                False,
            )
        ms = _open_ms()
        try:
            if op == "expand":
                if lo is None or hi is None:
                    return (
                        'RECALL FAILED — op="expand" needs lo and hi '
                        "(seq span; one turn is lo == hi).",
                        False,
                    )
                rows = ms.expand(int(lo), int(hi))
                label = f"expand [{int(lo)}, {int(hi)}]"
            elif op == "search":
                if not (query or "").strip():
                    return (
                        'RECALL FAILED — op="search" needs a non-empty '
                        "query.",
                        False,
                    )
                rows = ms.search(
                    query,
                    session_id=q_session_id,
                    agent_id=q_agent_id,
                    all_agents=bool(all_agents),
                    kind=kind,
                    k=int(k),
                )
                label = f"search {query!r}"
            else:  # recall_tool
                if not (tool_call_id or "").strip():
                    return (
                        'RECALL FAILED — op="recall_tool" needs a '
                        "tool_call_id.",
                        False,
                    )
                rows = ms.recall_tool(tool_call_id)
                label = f"recall_tool {tool_call_id!r}"
        finally:
            ms.close()
        if not rows:
            # Distinct from a failure on purpose (see repl._format_observation
            # for the same discipline): this IS evidence of absence.
            return (
                f"0 rows for {label} — the history genuinely holds nothing "
                "there. For a search, one retry with different keywords is "
                "worth it before concluding.",
                True,
            )
        return f"{len(rows)} row(s) for {label}:\n\n{_render_rows(rows)}", True

    async def recall_history(
        op: str,
        lo: Optional[int] = None,
        hi: Optional[int] = None,
        query: Optional[str] = None,
        k: int = 10,
        kind: Optional[str] = None,
        all_agents: bool = False,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        max_bytes: int = _DEFAULT_RECALL_MAX_BYTES,
    ) -> ToolChunk:
        payload = {
            "lo": lo,
            "hi": hi,
            "query": query,
            "k": k,
            "kind": kind,
            "all_agents": all_agents,
            "session_id": session_id,
            "agent_id": agent_id,
            "tool_call_id": tool_call_id,
        }
        claim_generation: int | None = None
        if loop_guard is not None:
            claim_generation, blocked_notice = loop_guard.claim(op, payload)
            if blocked_notice is not None:
                return ToolChunk(
                    content=[TextBlock(type="text", text=blocked_notice)],
                    state=ToolResultState.SUCCESS,
                )
        block_target = False
        try:
            try:
                text, ok = await asyncio.to_thread(
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
                    tool_call_id,
                )
            except (
                Exception
            ) as exc:  # noqa: BLE001 - surface, never crash the loop
                logger.warning("recall_history failed", exc_info=True)
                text, ok = (
                    "RECALL FAILED — the history was NOT read "
                    f"({type(exc).__name__}: {exc}). This is an execution "
                    "error, not an empty history: fix the parameters and "
                    "retry, or say explicitly that you could not retrieve "
                    "the context.",
                    False,
                )
            bounded_max_bytes = max(
                1024,
                min(int(max_bytes), _MAX_RECALL_MAX_BYTES),
            )
            encoded = text.encode("utf-8")
            metadata: dict[str, Any] = {}
            if len(encoded) > bounded_max_bytes:
                notice = _RECALL_TRUNCATION_NOTICE.encode("utf-8")
                excerpt_budget = max(0, bounded_max_bytes - len(notice))
                excerpt = encoded[:excerpt_budget].decode(
                    "utf-8",
                    errors="ignore",
                )
                if "\n" in excerpt:
                    excerpt = excerpt.rsplit("\n", 1)[0]
                text = excerpt + _RECALL_TRUNCATION_NOTICE
                metadata = {
                    "qwenpaw_recall": {
                        "truncated": True,
                        "original_bytes": len(encoded),
                        "max_bytes": bounded_max_bytes,
                    },
                }
                block_target = True
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
