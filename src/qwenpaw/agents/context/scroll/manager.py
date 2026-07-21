# -*- coding: utf-8 -*-
"""ScrollContextManager — write-through + eviction-index context management.

The strategy form of the design in ``CONTEXT_MANAGEMENT.html``: instead of
subclassing the agent, it is injected into :class:`QwenPawAgent` and drives the
two delegated hooks.

* :meth:`on_save` — every live turn is persisted to the durable
  ``conversation_history`` as it enters the window (write-through).
* :meth:`compress` — past the token threshold, keep the recent tail (and the
  active turn), update a pointer-backed continuation summary, and fold the
  evicted middle into an in-context :class:`EvictionIndex`. The summary is a
  state router, never a replacement for raw history: every claim points back
  to durable evidence recallable through ``recall_history``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from agentscope.message import Msg, SystemMsg, TextBlock, UserMsg

from ....constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    SYNTHETIC_USER_MESSAGE_TAGS,
)
from . import _as_internals as as_internals
from .continuation_summary import (
    ContinuationSummary,
    build_update_prompt,
    parse_plain_markdown,
    redact_secrets,
    validate_summary_quality,
)
from .eviction_index import EvictionIndex, Leaf
from .history import HistoryStore
from .serialize import msg_to_entries
from ..types import ContextWindowUnfitError
from ...utils.tool_message_utils import _remove_unpaired_tool_messages

logger = logging.getLogger(__name__)

# Prefix of an in-place folded tool result (the last-resort pressure valve).
# Doubles as the idempotence marker: an output starting with it is already a
# stub and is never folded (or counted as reclaimable) again.
_FOLD_MARK = "[scroll folded]"
_RECALL_FOLD_MARK = "[scroll recall folded]"
_EMERGENCY_PREVIEW_MARK = "[scroll emergency preview]"
_PRE_TRIM_TARGET_RATIO = 0.75
_OUTPUT_RESERVE_RATIO = 0.05
_MAX_OUTPUT_RESERVE_TOKENS = 4096
_MIN_EMERGENCY_PREVIEW_BYTES = 1024
_SUMMARY_REBASE_INTERVAL = 8


class ScrollContextManager:
    """Context management as an injectable strategy (not an agent subclass).

    Holds the per-session bookkeeping that links live ``Msg`` ids to their
    durable ``seq`` rows and to their eviction-index leaves. One instance per
    agent; ``session_id`` (the conversation) and ``agent_id`` (which agent) are
    threaded onto each row so cross-session, per-agent recall works.
    """

    def __init__(
        self,
        *,
        history: HistoryStore,
        session_id: str,
        agent_id: str | None = None,
        offloader: Any = None,
        compact_tool_result_max_bytes: int | None = None,
        tool_results_dir: str | None = None,
        recall_loop_guard: Any = None,
    ) -> None:
        self._history = history
        self._session_id = session_id
        self._agent_id = agent_id
        # Kept for constructor compatibility with older integrations. Scroll
        # no longer folds live tool results at a fixed byte threshold; it
        # reclaims them only while the rebuilt context remains under pressure.
        del compact_tool_result_max_bytes, tool_results_dir
        self._recall_loop_guard = recall_loop_guard
        # Dialog archive: when an offloader is wired (``offload_dialog``, on by
        # default), evicted turns are also written to ``dialog/{date}.jsonl``
        # for external consumers. ``history.db`` remains the source of truth.
        self._offloader = offloader
        self._persisted_ids: set[
            str
        ] = set()  # msgs whose non-result row is stored
        self._persisted_tcids: set[
            str
        ] = set()  # tool_call_ids whose result row is stored
        self._seq_by_tcid: dict[
            str,
            int,
        ] = {}  # tool_call_id -> its result row's seq (fold stubs point here)
        self._synthetic_ids: set[str] = set()  # placeholder msgs we inserted
        self._seq_by_id: dict[
            str,
            tuple[int, int],
        ] = {}  # msg.id -> (first, last) seq
        self._model_turn_seq: dict[
            str,
            int,
        ] = {}  # msg.id -> seq of its model_turn row
        self._model_turn_nblk: dict[
            str,
            int,
        ] = {}  # msg.id -> #non-result blocks persisted
        self._leaf_by_id: dict[str, Leaf] = {}  # msg.id -> its index leaf
        self._index = EvictionIndex(session_id=session_id, agent_id=agent_id)
        self._continuation_summary: ContinuationSummary | None = None
        self._summary_update_failed = False
        self._summary_update_count = 0
        # What the most recent compress() actually did — /compact reads this
        # to report honestly (an in-place fold changes no message count, so
        # the reply can't infer it from a before/after len()). Transient, not
        # checkpointed.
        self.last_compress: dict[str, int] = {
            "evicted": 0,
            "pre_folded": 0,
            "live_folded": 0,
            "emergency_shortened": 0,
            "folded": 0,
        }
        # Warn once per overflow episode, not once per reasoning step.
        self._overflow_warned = False

    @staticmethod
    def _block_metadata(block: Any) -> dict[str, Any]:
        metadata = (
            block.get("metadata", {})
            if isinstance(block, dict)
            else getattr(block, "metadata", {})
        )
        return metadata if isinstance(metadata, dict) else {}

    def _tool_result_pointer_stub(self, block: Any) -> str:
        tcid = (
            block.get("id")
            if isinstance(block, dict)
            else getattr(block, "id", None)
        )
        if tcid:
            where = (
                'recall_history(op="recall_tool", ' f"tool_call_id={tcid!r})"
            )
        else:
            where = 'recall_history(op="search", query=...)'
        return (
            f"{_FOLD_MARK} old tool result content cleared; recover with "
            f"{where}"
        )

    @classmethod
    def _recall_page_stub(
        cls,
        block: Any,
        call_input: dict[str, Any] | None,
    ) -> str:
        page = cls._block_metadata(block).get("qwenpaw_recall_page", {})
        next_cursor = (
            page.get("next_cursor") if isinstance(page, dict) else None
        )
        if next_cursor and call_input:
            continuation = dict(call_input)
            continuation["cursor"] = next_cursor
            arguments = json.dumps(
                continuation,
                ensure_ascii=False,
                sort_keys=True,
            )
            return (
                f"{_RECALL_FOLD_MARK} consumed recall page cleared. Continue "
                "from the next page by calling recall_history with arguments "
                f"{arguments}. "
                "Do not repeat the previous cursor."
            )
        return (
            f"{_RECALL_FOLD_MARK} consumed recall page cleared. The exact "
            "page must not be repeated; use a narrower seq range or a more "
            "specific keyword search if more evidence is needed."
        )

    @staticmethod
    def _tool_call_inputs(agent: Any) -> dict[str, dict[str, Any]]:
        calls: dict[str, dict[str, Any]] = {}
        for msg in getattr(agent.state, "context", []) or []:
            for block in getattr(msg, "content", None) or []:
                if getattr(block, "type", None) != "tool_call":
                    continue
                if getattr(block, "name", None) != "recall_history":
                    continue
                raw = getattr(block, "input", None)
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except (TypeError, ValueError):
                        raw = {}
                if isinstance(raw, dict):
                    calls[str(getattr(block, "id", ""))] = raw
        return calls

    # -- delegated hooks -----------------------------------------------------

    def on_save(  # pylint: disable=unused-argument
        self,
        agent: Any,
        blocks: Any,
    ) -> None:
        """Write through any live-context blocks not yet persisted.

        Only disk/SQLite failures are swallowed (recorded as degraded
        durability) so the chat loop survives a write outage; any other
        exception is a real bug and is left to propagate rather than hidden.
        """
        self._persist_guarded(agent)

    def _persist_guarded(self, agent: Any) -> bool:
        """Write through, swallowing only disk/SQLite failures.

        Returns ``True`` on success, ``False`` if a write outage was caught and
        recorded as degraded durability. Any other exception is a real bug and
        is left to propagate. Shared by :meth:`on_save` (which ignores the
        result — best-effort) and :meth:`compress` (via
        :meth:`_persist_guarded_async`, which must NOT evict when this returns
        ``False``, or it would drop un-persisted turns).

        The SQLite writes are synchronous. ``on_save`` runs this directly on
        the event loop because its AgentScope hook is synchronous and its
        write is incremental (one turn); ``compress`` instead offloads it to a
        worker thread (see :meth:`_persist_guarded_async`) so the larger
        whole-window persist never blocks the loop. ``HistoryStore`` serializes
        both paths on its own lock.
        """
        if self._recall_loop_guard is not None:
            active = self._active_turn_tail(agent)
            turn_id = getattr(active[0], "id", None) if active else None
            self._recall_loop_guard.begin_turn(turn_id)
        # Teardown race: a stop/cancel can close the store while a final
        # ``on_save`` is still in flight. The connection was retired on
        # purpose, so skip the write quietly instead of degrading durability.
        if self._history.closed:
            return True
        try:
            self._persist_new(agent)
            return True
        except (sqlite3.Error, OSError) as exc:
            self._history.note_write_failure(exc)
            logger.exception("ScrollContextManager write-through failed")
            return False

    async def _persist_guarded_async(self, agent: Any) -> bool:
        """Run :meth:`_persist_guarded` off the event loop.

        ``compress`` is async and can persist the whole live window, which is
        the write worth keeping off the loop. The synchronous SQLite work runs
        in a worker thread; ``HistoryStore``'s connection is opened
        ``check_same_thread=False`` and every access is serialized by its lock,
        so this coexists safely with a concurrent on-loop ``on_save``.
        """
        return await asyncio.to_thread(self._persist_guarded, agent)

    async def _offload_dialog(self, middle: list[Msg]) -> None:
        """Best-effort legacy ``dialog/*.jsonl`` archive of evicted turns.

        No-op unless an offloader is wired in (``offload_dialog``, default on).
        Purely supplementary — the turns are already durable in history.db —
        so a write failure is logged and swallowed, never aborting eviction.
        """
        if self._offloader is None or not middle:
            return
        try:
            await self._offloader.offload_context(self._session_id, middle)
        except Exception:  # noqa: BLE001 - archive is best-effort
            logger.warning("scroll dialog offload failed", exc_info=True)

    # pylint: disable-next=too-many-statements,too-many-branches
    async def compress(
        self,
        agent: Any,
        context_config: Any = None,
    ) -> None:
        """Evict the middle into the index; fold tool results under pressure.

        A graduated pressure pipeline. Recoverable outputs from completed
        turns are the cheapest content to remove, so automatic compression
        tries those before evicting dialogue. The active turn remains intact
        until the existing post-eviction pressure valve:

        1. persist     — every live turn is now durable.
        2. trigger     — under the token threshold? nothing to do.
        3. pre-fold    — on automatic pressure, fold completed-turn tool
                         results toward the 75% health target. If the context
                         falls to the trigger or below, stop without eviction.
        4. split       — evictable middle | recent tail (+ active turn).
        5. summarize   — update pointer-backed task state from bounded input;
                         preserve the previous value on any failure.
        6. add_eviction— fold the middle (if any) into the index as a new
                         Tier 0 block, rebuild context = [index] + tail.
        7. live-fold   — still under real pressure after finished turns are
                         evicted: replace consumed old tool results with
                         recovery pointers. The newest stays verbatim.
        8. emergency  — above the effective hard limit, shorten the newest
                         unread text result to a visible head/tail preview.
        """
        cfg = context_config or agent.context_config
        self.last_compress = {
            "evicted": 0,
            "pre_folded": 0,
            "live_folded": 0,
            "emergency_shortened": 0,
            "folded": 0,
        }
        hard_limit = int(agent.model.context_size)
        output_reserve = min(
            _MAX_OUTPUT_RESERVE_TOKENS,
            max(1, int(hard_limit * _OUTPUT_RESERVE_RATIO)),
        )
        effective_hard_limit = hard_limit - output_reserve
        t0 = time.perf_counter()
        stage_t0 = t0
        timings: dict[str, float] = {}

        def mark(stage: str) -> None:
            nonlocal stage_t0
            now = time.perf_counter()
            timings[stage] = timings.get(stage, 0.0) + now - stage_t0
            stage_t0 = now

        def log_timings(outcome: str) -> None:
            total = time.perf_counter() - t0
            parts = " ".join(
                f"{name}={elapsed * 1000:.1f}ms"
                for name, elapsed in timings.items()
            )
            logger.info(
                "scroll: compact timing outcome=%s total=%.1fms %s",
                outcome,
                total * 1000,
                parts,
            )

        # 1) Durability first — everything in the window is now in the DB. If
        #    the write-through failed (degraded durability), do NOT evict: the
        #    middle isn't durable, so folding it in would leave seq pointers to
        #    rows that don't exist. Keep it live instead. Offloaded to a worker
        #    thread so the whole-window persist never blocks the event loop.
        if not await self._persist_guarded_async(agent):
            mark("persist")
            kwargs = await as_internals.prepare_model_input(agent)
            mark("prepare_input")
            tokens = await agent.model.count_tokens(**kwargs)
            mark("count_tokens")
            if tokens > effective_hard_limit:
                log_timings("persist_failed_unfit")
                raise ContextWindowUnfitError(
                    tokens=tokens,
                    hard_limit=effective_hard_limit,
                )
            log_timings("persist_failed")
            return
        mark("persist")

        # 2) Trigger check (reuse AgentScope's own token accounting). The
        #    count is kept — while nothing below rebuilds the context it is
        #    still exact, so the steady state pays ONE count per compress.
        kwargs = await as_internals.prepare_model_input(agent)
        mark("prepare_input")
        trigger = cfg.trigger_ratio * agent.model.context_size
        tokens = await agent.model.count_tokens(**kwargs)
        mark("count_tokens")
        if tokens < trigger:
            self._overflow_warned = False
            log_timings("below_trigger")
            return

        # 3) Before evicting dialogue, reclaim recoverable tool output from
        #    completed turns. This runs only for normal automatic pressure:
        #    manual /compact deliberately lowers trigger_ratio to request an
        #    eviction now, and must not be intercepted by this lighter pass.
        #    The 75% target provides hysteresis below the default 80% trigger;
        #    if no more safe candidates exist, anything at or below the trigger
        #    is still healthy enough to continue without eviction.
        base_cfg = getattr(agent, "context_config", cfg)
        base_trigger_ratio = float(
            getattr(base_cfg, "trigger_ratio", cfg.trigger_ratio),
        )
        is_forced_compaction = float(cfg.trigger_ratio) < base_trigger_ratio
        if (
            not is_forced_compaction
            and float(cfg.trigger_ratio) > _PRE_TRIM_TARGET_RATIO
        ):
            pre_folded, tokens = await self._fold_tool_results_under_pressure(
                agent,
                tokens=tokens,
                target=_PRE_TRIM_TARGET_RATIO * agent.model.context_size,
                include_active=False,
            )
            mark("pre_fold_tool_results")
            if pre_folded:
                self.last_compress["pre_folded"] = pre_folded
                self.last_compress["folded"] += pre_folded
                logger.info(
                    "scroll: pre-folded %d completed tool result(s)",
                    pre_folded,
                )
                if tokens <= trigger:
                    self._overflow_warned = False
                    log_timings("pre_trimmed_below_trigger")
                    return

        # 4) Pairing-safe split; keep the recent tail, evict the middle.
        requested_reserve = cfg.reserve_ratio * agent.model.context_size
        # Keep a useful recent raw tail without letting a million-token model
        # reserve an excessive 100k-token suffix. Mirrors the bounded recent
        # tail discipline used by mature compactors.
        minimum_recent = min(10_000, agent.model.context_size * 0.1)
        reserve = min(40_000, max(requested_reserve, minimum_recent))

        def real(msgs: list[Msg]) -> list[Msg]:
            return [m for m in msgs if m.id not in self._synthetic_ids]

        middle: list[Msg] = []
        tail = real(list(agent.state.context))
        if len(agent.state.context) > 1:
            to_compress, to_reserve = await as_internals.split_for_compression(
                agent,
                reserve,
                kwargs.get("tools", []),
            )
            mark("split")
            tail = real(to_reserve)
            # AgentScope may split the boundary Msg at block granularity and
            # put deep-copied fragments (with the original id) into both
            # halves. Restore every retained Msg from the live context so a
            # fragment cannot orphan a tool call or result.
            tail = self._restore_full_tail_messages(agent, tail)
            # A split boundary Msg appears in both halves under the same id.
            # Never index it while its complete live copy remains in the tail.
            tail_ids = {m.id for m in tail}
            active_tail = self._active_turn_tail(agent)
            active_ids = {m.id for m in active_tail}
            middle = [
                m
                for m in real(to_compress)
                if m.id not in tail_ids and m.id not in active_ids
            ]
            if active_tail:
                # Keep the whole active turn at the end in original order.
                tail = [m for m in tail if m.id not in active_ids]
                tail.extend(active_tail)
            middle, tail = self._repair_dangling_user_boundary(
                middle,
                tail,
                active_ids,
            )

        # 3c) Sanitize: AgentScope's pairing-safe split only guarantees
        #    intra-message block-level pairing. Standalone tool_result
        #    messages (AgentScope 1.x flat-timeline format) can still be
        #    orphaned across the compress/reserve boundary. Remove them
        #    before the model sees them — the alternative is a 400
        #    BadRequestError from the API.
        tail = _remove_unpaired_tool_messages(tail)

        if middle:
            # 3b) Optional legacy archive of the evicted turns (opt-in). The
            #     full turns are already durable in history.db; this is a
            #     redundant dialog/*.jsonl copy for external consumers. A
            #     write failure must never abort compaction.
            await self._offload_dialog(middle)
            mark("offload_dialog")

            # 5) Update the pointer-backed continuation state from bounded
            #    previews. Failure is non-fatal: the previous valid summary
            #    stays in place and the exact rows remain in history.db.
            await self._update_continuation_summary(agent, middle)
            mark("continuation_summary")

            # 6) Fold the evicted middle into the index as a new Tier 0 block.
            self._index_evicted(middle)
            mark("index_evicted")
            self._rebuild_context(agent, tail)
            self._prune_bookkeeping_to_live_context(agent)
            mark("rebuild_context")
            self.last_compress["evicted"] = len(middle)
            tokens = await self._live_tokens(agent)
            mark("live_tokens")

        # 7) Pressure-driven microcompaction. Do not clear live tool results
        #    merely because Scroll ran: eviction may already have relieved the
        #    pressure. If it did not, replace recoverable results one at a time
        #    (older completed turns before the active turn, then largest byte
        #    saving first) and stop as soon as the pressure target is met. An
        #    active result is eligible only after a later model-authored block
        #    proves it was consumed. The newest result stays verbatim under
        #    normal pressure. For manual /compact the
        #    configured reserve, rather than its synthetic near-zero trigger,
        #    is the meaningful target.
        pressure_threshold = max(trigger, reserve)
        if tokens > pressure_threshold:
            folded, tokens = await self._fold_tool_results_under_pressure(
                agent,
                tokens=tokens,
                target=pressure_threshold,
                include_active=True,
            )
            mark("fold_tool_results")
            if folded:
                self.last_compress["live_folded"] = folded
                self.last_compress["folded"] += folded
                logger.info(
                    "scroll: pressure-folded %d live tool result(s)",
                    folded,
                )
        # The newest result may not have received its first model read, so it
        # is excluded from normal pointer folding. If the remaining input
        # would leave no safe output budget, degrade that result only to a
        # visible head/tail preview. Its exact persisted row stays recallable.
        if tokens > effective_hard_limit:
            (
                emergency_shortened,
                tokens,
            ) = await self._shorten_newest_result_for_emergency(
                agent,
                tokens=tokens,
                target=effective_hard_limit,
            )
            mark("emergency_preview")
            if emergency_shortened:
                self.last_compress["emergency_shortened"] = emergency_shortened
                logger.warning(
                    "scroll: shortened newest tool result preview to preserve "
                    "model output capacity",
                )
        # Once per overflow episode, not once per reasoning step — the stuck
        # state repeats every step until the turn ends. Manual /compact
        # deliberately supplies a near-zero trigger to bypass the automatic
        # gate. That synthetic trigger is not a meaningful overflow threshold:
        # warn only if compaction also failed to reach the configured reserve
        # target. During normal automatic compaction ``trigger`` is larger
        # than ``reserve``, preserving the existing warning unchanged.
        overflow_threshold = pressure_threshold
        if tokens > effective_hard_limit:
            log_timings("unfit")
            raise ContextWindowUnfitError(
                tokens=tokens,
                hard_limit=effective_hard_limit,
            )
        if tokens > overflow_threshold:
            if not self._overflow_warned:
                self._overflow_warned = True
                logger.warning(
                    "scroll: context still over the compression trigger "
                    "(%d > %d) after compaction and tool-result folding",
                    tokens,
                    overflow_threshold,
                )
        else:
            self._overflow_warned = False
        log_timings("done")

    @staticmethod
    def _bounded_summary_text(value: Any, limit: int) -> str:
        """Return a compact head/tail preview without losing both endpoints."""
        text = redact_secrets(" ".join(str(value or "").split()))
        if len(text) <= limit:
            return text
        half = max(1, (limit - 25) // 2)
        return f"{text[:half]} [… omitted …] {text[-half:]}"

    def _evicted_span(self, messages: list[Msg]) -> tuple[int, int] | None:
        ranges = [
            self._seq_by_id.get(getattr(msg, "id", None) or str(id(msg)))
            for msg in messages
        ]
        known = [span for span in ranges if span is not None]
        if not known:
            return None
        return min(span[0] for span in known), max(span[1] for span in known)

    @classmethod
    def _summary_metadata_pointers(cls, value: Any) -> list[str]:
        """Extract pointers without copying metadata wholesale."""
        found: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).casefold()
                if isinstance(item, str) and item.strip():
                    if lowered in ("file_path", "path"):
                        found.append(f"[file:{item.strip()}]")
                    elif "artifact" in lowered:
                        found.append(f"[artifact:{item.strip()}]")
                found.extend(cls._summary_metadata_pointers(item))
        elif isinstance(value, list):
            for item in value:
                found.extend(cls._summary_metadata_pointers(item))
        return list(dict.fromkeys(found))

    def _summary_archived_context(
        self,
        middle: list[Msg],
        *,
        max_chars: int,
    ) -> str:
        """Render bounded evidence for the summary model.

        Tool outputs are capped aggressively; exact values remain available by
        the seq/tool-call pointers printed beside each preview.
        """
        chunks: list[str] = []
        for msg in middle:
            mid = getattr(msg, "id", None) or str(id(msg))
            span = self._seq_by_id.get(mid)
            pointer = f"[seq:{span[0]}-{span[1]}]" if span else "[seq:unknown]"
            chunks.append(f"{pointer} role={getattr(msg, 'role', 'unknown')}")
            for entry in msg_to_entries(msg):
                if entry.kind == "tool_result":
                    preview = self._bounded_summary_text(entry.content, 600)
                    chunks.append(
                        "  tool_result "
                        f"name={entry.name!r} id={entry.tool_call_id!r} "
                        f"state={entry.tool_state!r} preview={preview!r}",
                    )
                    pointers = self._summary_metadata_pointers(entry.metadata)
                    if pointers:
                        chunks.append(f"  recovery={' '.join(pointers)}")
                    continue
                text = self._bounded_summary_text(entry.content, 2000)
                if text:
                    chunks.append(f"  text={text!r}")
                if entry.headline:
                    headline = self._bounded_summary_text(
                        entry.headline,
                        2000,
                    )
                    chunks.append(
                        f"  headline={headline!r}",
                    )
                if entry.name or entry.tool_call_id:
                    tool_input = self._bounded_summary_text(
                        entry.tool_input,
                        600,
                    )
                    chunks.append(
                        f"  tool_call name={entry.name!r} "
                        f"id={entry.tool_call_id!r} input={tool_input!r}",
                    )
        rendered = "\n".join(chunks)
        if len(rendered) <= max_chars:
            return rendered
        return self._bounded_summary_text(rendered, max_chars)

    def _summary_rebase_context(
        self,
        summary: ContinuationSummary,
        *,
        max_chars: int,
    ) -> str:
        """Read bounded durable evidence cited by the current summary."""
        rows = self._history.read_summary_evidence(summary.seq_spans())
        chunks: list[str] = []
        for row in rows:
            pointer = f"[seq:{row['seq']}]"
            kind = str(row.get("kind") or "unknown")
            chunks.append(
                f"{pointer} role={row.get('role')!r} kind={kind!r} "
                f"name={row.get('name')!r}",
            )
            preview_limit = 600 if kind == "tool_result" else 2000
            preview = self._bounded_summary_text(
                row.get("content"),
                preview_limit,
            )
            if preview:
                chunks.append(f"  text={preview!r}")
            headline = self._bounded_summary_text(row.get("headline"), 2000)
            if headline:
                chunks.append(f"  headline={headline!r}")
            if row.get("tool_call_id"):
                chunks.append(
                    f"  tool_call_id={row['tool_call_id']!r} "
                    f"state={row.get('tool_state')!r}",
                )
            metadata = row.get("metadata")
            if isinstance(metadata, str) and metadata:
                try:
                    metadata = json.loads(metadata)
                except (TypeError, ValueError):
                    metadata = {}
            pointers = self._summary_metadata_pointers(metadata)
            if pointers:
                chunks.append(f"  recovery={' '.join(pointers)}")
        rendered = "\n".join(chunks)
        if len(rendered) <= max_chars:
            return rendered
        return self._bounded_summary_text(rendered, max_chars)

    @staticmethod
    def _response_text(response: Any) -> str:
        parts: list[str] = []
        for block in getattr(response, "content", None) or []:
            btype = (
                block.get("type")
                if isinstance(block, dict)
                else getattr(block, "type", None)
            )
            if btype == "text":
                parts.append(
                    str(
                        block.get("text", "")
                        if isinstance(block, dict)
                        else getattr(block, "text", "") or "",
                    ),
                )
        return "".join(parts).strip()

    async def _generate_plain_summary(
        self,
        agent: Any,
        prompt: str,
        *,
        max_tokens: int,
    ) -> str:
        """Call the chat model normally; structured output is never used."""
        if not callable(getattr(agent, "model", None)):
            return ""
        response = await agent.model(
            messages=[
                SystemMsg(
                    name="system",
                    content=(
                        "You update a compact continuation summary. Follow "
                        "the requested Markdown headings exactly."
                    ),
                ),
                UserMsg(name="user", content=prompt),
            ],
            tools=None,
            max_tokens=max_tokens,
            disable_thinking=True,
        )
        if not inspect.isasyncgen(response):
            return self._response_text(response)
        deltas: list[str] = []
        final = ""
        async for chunk in response:
            text = self._response_text(chunk)
            if getattr(chunk, "is_last", False):
                final = text
            elif text:
                deltas.append(text)
        return final or "".join(deltas).strip()

    async def _update_continuation_summary(
        self,
        agent: Any,
        middle: list[Msg],
    ) -> None:
        """Update, validate, and at most once retry the plain summary."""
        new_span = self._evicted_span(middle)
        if new_span is None or not callable(getattr(agent, "model", None)):
            return
        previous = self._continuation_summary
        covered = (
            (
                min(previous.covered_seq[0], new_span[0]),
                max(previous.covered_seq[1], new_span[1]),
            )
            if previous is not None
            else new_span
        )
        context_size = max(
            1,
            int(getattr(agent.model, "context_size", 0) or 0),
        )
        output_tokens = max(256, min(4000, context_size // 4))
        input_chars = max(4000, min(80_000, context_size * 2))
        rebase_due = bool(
            previous is not None
            and (self._summary_update_count + 1) % _SUMMARY_REBASE_INTERVAL
            == 0,
        )
        previous_spans = previous.seq_spans() if previous is not None else ()
        # A rebase must not pretend that a head/tail sample proves hundreds of
        # omitted rows. Defer it until the cited evidence is small enough to
        # read faithfully within the bounded summary input.
        source_backed_rebase = bool(
            rebase_due
            and previous_spans
            and sum(hi - lo + 1 for lo, hi in previous_spans) <= 20,
        )
        new_context = self._summary_archived_context(
            middle,
            max_chars=(
                input_chars // 2 if source_backed_rebase else input_chars
            ),
        )
        if source_backed_rebase and previous is not None:
            durable_context = self._summary_rebase_context(
                previous,
                max_chars=input_chars // 2,
            )
            archived_context = (
                "Durable evidence cited by the previous summary:\n"
                f"{durable_context}\n\nNewly archived context:\n{new_context}"
            )
            self.last_compress["summary_rebased"] = 1
        else:
            archived_context = new_context

        evidence_text = archived_context
        if not source_backed_rebase and previous is not None:
            evidence_text = previous.render() + "\n" + evidence_text
        repair_issues: tuple[str, ...] = ()
        updated: ContinuationSummary | None = None
        failure: Exception | None = None
        for attempt in range(2):
            prompt = build_update_prompt(
                previous=previous,
                archived_context=archived_context,
                covered_seq=covered,
                repair_issues=repair_issues,
                source_backed_rebase=source_backed_rebase,
            )
            try:
                plain_text = await self._generate_plain_summary(
                    agent,
                    prompt,
                    max_tokens=output_tokens,
                )
                if len(plain_text) > 16_000:
                    raise ValueError(
                        "plain Markdown summary exceeds hard limit",
                    )
                candidate = parse_plain_markdown(
                    plain_text,
                    covered_seq=covered,
                )
                if candidate is None:
                    raise ValueError(
                        "empty or malformed plain Markdown summary",
                    )
                endpoints = {
                    endpoint
                    for lo, hi in candidate.seq_spans()
                    for endpoint in (lo, hi)
                }
                issues = validate_summary_quality(
                    candidate,
                    evidence_text=evidence_text,
                    existing_seqs=self._history.existing_seqs(endpoints),
                )
                if issues:
                    raise ValueError("; ".join(issues))
                updated = candidate
                break
            except Exception as exc:  # noqa: BLE001 - retry is best-effort
                failure = exc
                repair_issues = (str(exc) or type(exc).__name__,)
                if attempt == 0:
                    self.last_compress["summary_retries"] = 1

        if updated is None:
            self._summary_update_failed = True
            logger.warning(
                "scroll: continuation summary update failed after retry; "
                "preserving the previous valid summary",
                exc_info=(
                    type(failure),
                    failure,
                    failure.__traceback__,
                )
                if failure is not None
                else None,
            )
            return
        self._continuation_summary = updated
        self._summary_update_failed = False
        self._summary_update_count += 1

    async def _live_tokens(self, agent: Any) -> int:
        """Token count of the live context as the model would receive it."""
        return await agent.model.count_tokens(
            **(await as_internals.prepare_model_input(agent)),
        )

    @staticmethod
    def _block_type(block: Any) -> str | None:
        return (
            block.get("type")
            if isinstance(block, dict)
            else getattr(block, "type", None)
        )

    def _live_tool_results(self, agent: Any) -> list[tuple[Any, Any]]:
        """Return live ``(message, tool_result)`` pairs in wire order."""
        results: list[tuple[Any, Any]] = []
        for msg in getattr(agent.state, "context", []) or []:
            if getattr(msg, "id", None) in self._synthetic_ids:
                continue
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue
            results.extend(
                (msg, block)
                for block in content
                if self._block_type(block) == "tool_result"
            )
        return results

    def _consumed_active_result_ids(self, agent: Any) -> set[int]:
        """Identify active results already observed by a later model call.

        AgentScope appends each model step to the active assistant message. A
        result is therefore known to have been consumed only when a later
        model-authored block (text, reasoning, or another tool call) follows
        it. Merely having another tool result after it is insufficient: those
        results may come from parallel calls and all still need their first
        model read. The structural rule survives process resume without an
        ephemeral "seen" flag.
        """
        consumed: set[int] = set()
        later_model_output = False
        for msg in reversed(self._active_turn_tail(agent)):
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue
            is_assistant = getattr(msg, "role", None) == "assistant"
            for block in reversed(content):
                if self._block_type(block) == "tool_result":
                    if later_model_output:
                        consumed.add(id(block))
                elif is_assistant:
                    later_model_output = True
        return consumed

    # pylint: disable-next=too-many-branches
    def _tool_result_fold_candidates(
        self,
        agent: Any,
        *,
        include_active: bool,
    ) -> list[tuple[bool, int, int, Any, str]]:
        """Return profitable fold candidates ordered by recovery priority.

        When ``include_active`` is false, only completed-turn results are
        returned. Otherwise results outside the active turn are still less
        relevant and sort first. Within either group, prefer the largest byte
        saving, then the older result. The newest result in the entire live
        context is never a candidate. A fixed size threshold is deliberately
        absent: a result is eligible only when its pointer is actually smaller
        than its output.
        """
        results = self._live_tool_results(agent)
        active_messages = {id(msg) for msg in self._active_turn_tail(agent)}
        consumed_active = self._consumed_active_result_ids(agent)
        recall_inputs = self._tool_call_inputs(agent)

        candidates: list[tuple[bool, int, int, Any, str]] = []
        for ordinal, (msg, block) in enumerate(results[:-1]):
            is_active = id(msg) in active_messages
            if is_active and not include_active:
                continue
            if is_active and id(block) not in consumed_active:
                continue
            if self._is_folded_stub(block):
                continue
            existing_output = (
                block.get("output")
                if isinstance(block, dict)
                else getattr(block, "output", None)
            )
            name = (
                block.get("name")
                if isinstance(block, dict)
                else getattr(block, "name", None)
            )
            tool_call_id = (
                block.get("id")
                if isinstance(block, dict)
                else getattr(block, "id", None)
            )
            if name == "recall_history":
                text = self._recall_page_stub(
                    block,
                    recall_inputs.get(str(tool_call_id)),
                )
            else:
                text = self._tool_result_pointer_stub(block)
            replacement = [TextBlock(type="text", text=text)]
            savings = len(str(existing_output).encode("utf-8")) - len(
                str(replacement).encode("utf-8"),
            )
            if savings <= 0:
                continue
            candidates.append(
                (is_active, -savings, ordinal, block, text),
            )

        candidates.sort(key=lambda item: item[:3])
        return candidates

    async def _fold_tool_results_under_pressure(
        self,
        agent: Any,
        *,
        tokens: int,
        target: float,
        include_active: bool,
    ) -> tuple[int, int]:
        """Fold profitable live results until ``tokens`` reaches ``target``."""
        candidates = self._tool_result_fold_candidates(
            agent,
            include_active=include_active,
        )
        folded = 0
        for _, _, _, block, text in candidates:
            output = [TextBlock(type="text", text=text)]
            if isinstance(block, dict):
                block["output"] = output
            else:
                block.output = output
            folded += 1
            tokens = await self._live_tokens(agent)
            if tokens <= target:
                break
        return folded, tokens

    @staticmethod
    def _emergency_preview_text(
        text: str,
        *,
        max_bytes: int,
        tool_call_id: str,
    ) -> str:
        """Build a bounded, visible head/tail preview with an exact pointer."""
        recovery = (
            'recover the exact result with recall_history(op="recall_tool", '
            f"tool_call_id={tool_call_id!r})"
        )
        framing = (
            f"{_EMERGENCY_PREVIEW_MARK}\n"
            "[… middle removed to preserve model output capacity …]\n"
            f"{recovery}"
        )
        budget = max(0, max_bytes - len(framing.encode("utf-8")) - 2)
        raw = text.encode("utf-8")
        head_size = budget // 2
        tail_size = budget - head_size
        head = raw[:head_size].decode("utf-8", errors="ignore")
        tail = raw[-tail_size:].decode("utf-8", errors="ignore")
        return (
            f"{_EMERGENCY_PREVIEW_MARK}\n{head}\n"
            "[… middle removed to preserve model output capacity …]\n"
            f"{tail}\n{recovery}"
        )

    async def _shorten_newest_result_for_emergency(
        self,
        agent: Any,
        *,
        tokens: int,
        target: int,
    ) -> tuple[int, int]:
        """Shrink the newest unread result only to avoid ``CONTEXT_UNFIT``.

        Normal folding deliberately protects the newest result because the
        model may not have read it yet. Above the effective hard limit, retain
        a progressively smaller visible head/tail preview instead of replacing
        it with an opaque pointer. The exact result is already durable.
        """
        results = self._live_tool_results(agent)
        if not results:
            return 0, tokens
        _, block = results[-1]
        tool_call_id = (
            block.get("id")
            if isinstance(block, dict)
            else getattr(block, "id", None)
        )
        if not tool_call_id or str(tool_call_id) not in self._persisted_tcids:
            return 0, tokens
        output = (
            block.get("output")
            if isinstance(block, dict)
            else getattr(block, "output", None)
        )
        if isinstance(output, str):
            source = output
        elif isinstance(output, list) and output:
            if any(self._block_type(item) != "text" for item in output):
                return 0, tokens
            source = "\n".join(
                str(
                    item.get("text", "")
                    if isinstance(item, dict)
                    else getattr(item, "text", "") or "",
                )
                for item in output
            )
        else:
            return 0, tokens

        source_bytes = len(source.encode("utf-8"))
        if source_bytes <= _MIN_EMERGENCY_PREVIEW_BYTES:
            return 0, tokens
        preview_bytes = max(
            _MIN_EMERGENCY_PREVIEW_BYTES,
            min(8192, source_bytes // 2),
        )
        changed = False
        while tokens > target:
            preview = self._emergency_preview_text(
                source,
                max_bytes=preview_bytes,
                tool_call_id=str(tool_call_id),
            )
            replacement = [TextBlock(type="text", text=preview)]
            if isinstance(block, dict):
                block["output"] = replacement
            else:
                block.output = replacement
            changed = True
            tokens = await self._live_tokens(agent)
            if (
                tokens <= target
                or preview_bytes <= _MIN_EMERGENCY_PREVIEW_BYTES
            ):
                break
            preview_bytes = max(
                _MIN_EMERGENCY_PREVIEW_BYTES,
                preview_bytes // 2,
            )
        return int(changed), tokens

    # -- write-through -------------------------------------------------------

    def _persist_new(  # pylint: disable=too-many-branches
        self,
        agent: Any,
    ) -> None:
        """Write through live-context blocks not yet persisted.

        AgentScope 2.0 extends the last assistant Msg in place (one Msg per
        reply accumulates ``[text, tool_call, tool_result, ...]``). So each
        tool_result is written once per ``tool_call_id``; the msg's single
        non-result row is written once, then refreshed in place as the Msg
        grows — so every cell's tool-call blocks and any later ``⟦…⟧`` headline
        persist. Synthetic placeholders are never persisted.
        """
        # pylint: disable=import-outside-toplevel
        from ...memory.base_memory_manager import BaseMemoryManager

        for raw_msg in agent.state.context:
            msg = BaseMemoryManager.message_without_auto_memory_search(
                raw_msg,
            )
            if msg is None:
                continue
            mid = getattr(msg, "id", None) or str(id(msg))
            if mid in self._synthetic_ids:
                continue
            anon_pos = 0  # stable index for results lacking a tool_call_id
            for entry in msg_to_entries(msg):
                if entry.kind == "tool_result":
                    # Key on the call id, else this result's position in the
                    # msg — a fixed function of (msg.id, block order), so it
                    # matches on a later reload instead of drifting with a
                    # set's size.
                    tcid = entry.tool_call_id or f"{mid}#anon{anon_pos}"
                    anon_pos += 1
                    if tcid in self._persisted_tcids:
                        continue
                    seq = self._history.append(
                        session_id=self._session_id,
                        agent_id=self._agent_id,
                        entry=entry,
                        dedup_key=tcid,
                    )
                    self._persisted_tcids.add(tcid)
                    self._seq_by_tcid[tcid] = seq
                else:
                    nblk = len(entry.blocks or ())
                    if mid in self._persisted_ids:
                        # Msg extended in place — refresh the row when it grew
                        # (more tool calls) or a headline appeared later.
                        prev_seq = self._model_turn_seq.get(mid)
                        if prev_seq is None:
                            continue
                        new_headline = (
                            bool(entry.headline)
                            and mid not in self._leaf_by_id
                        )
                        if (
                            nblk <= self._model_turn_nblk.get(mid, 0)
                            and not new_headline
                        ):
                            continue
                        self._history.update_entry(
                            prev_seq,
                            content=entry.content,
                            headline=entry.headline,
                            blocks=entry.blocks,
                            tool_call_id=entry.tool_call_id,
                            name=entry.name,
                            tool_state=entry.tool_state,
                            tool_input=entry.tool_input,
                        )
                        self._model_turn_nblk[mid] = nblk
                        if new_headline:
                            self._leaf_by_id[mid] = Leaf(
                                seq=prev_seq,
                                headline=entry.headline or "",
                            )
                        continue
                    seq = self._history.append(
                        session_id=self._session_id,
                        agent_id=self._agent_id,
                        entry=entry,
                        dedup_key=mid,
                    )
                    self._persisted_ids.add(mid)
                    self._model_turn_seq[mid] = seq
                    self._model_turn_nblk[mid] = nblk
                    # A model turn with a headline becomes an index leaf.
                    if entry.headline:
                        self._leaf_by_id[mid] = Leaf(
                            seq=seq,
                            headline=entry.headline,
                        )
                # Track the msg's seq span (it grows as results are appended)
                # so eviction recovers the whole turn by range.
                lo, hi = self._seq_by_id.get(mid, (seq, seq))
                self._seq_by_id[mid] = (min(lo, seq), max(hi, seq))

    # -- eviction ------------------------------------------------------------

    @staticmethod
    def _is_continuation_stub(msg: Any) -> bool:
        """True for runtime-injected user-role messages that extend a turn.

        Loop gates and stop handlers append tagged ``role="user"`` stubs
        ("Continue working on the task.") to keep a turn going. They are NOT
        new requests: anchoring the active turn on one would make the REAL
        request evictable middle again — the #5746 failure, loop-session
        flavor.
        """
        metadata = getattr(msg, "metadata", None)
        if not isinstance(metadata, dict):
            return False
        tag = metadata.get(QWENPAW_MESSAGE_TAG_KEY)
        return tag in SYNTHETIC_USER_MESSAGE_TAGS

    def _active_turn_tail(self, agent: Any) -> list[Msg]:
        """Return the current user turn and its in-progress assistant tail.

        AgentScope's token-based split may evict the latest user request when
        a long tool-running turn exceeds the reserve budget. Under scroll that
        is unsafe: the model then only sees the eviction index and may answer
        an older visible message instead of the active task. Keep the latest
        real user message and everything after it live until the turn
        finishes. Continuation stubs the runtime injects mid-turn are skipped
        when anchoring — the extended turn stays anchored on the real request
        that started it.
        """
        context = list(getattr(agent.state, "context", []) or [])
        for idx in range(len(context) - 1, -1, -1):
            msg = context[idx]
            mid = getattr(msg, "id", None)
            if mid in self._synthetic_ids:
                continue
            if getattr(msg, "role", None) != "user":
                continue
            if self._is_continuation_stub(msg):
                continue
            return [
                m
                for m in context[idx:]
                if getattr(m, "id", None) not in self._synthetic_ids
            ]
        return []

    def _restore_full_tail_messages(
        self,
        agent: Any,
        tail: list[Msg],
    ) -> list[Msg]:
        """Replace split boundary fragments with their full live messages.

        AgentScope's compression splitter can divide one message's content
        blocks between ``to_compress`` and ``to_reserve``.  Both fragments
        keep the same message id, which is useful for native summarization but
        unsafe for Scroll: Scroll retains the reserve half verbatim, where a
        block-level split can create orphan tool calls/results.  Message ids
        are stable in the live context, so use them to recover the original
        object.  Unknown ids are kept unchanged for compatibility with custom
        AgentScope splitters.
        """
        live_by_id = {
            getattr(msg, "id", None): msg
            for msg in getattr(agent.state, "context", []) or []
            if getattr(msg, "id", None) not in self._synthetic_ids
        }
        return [live_by_id.get(getattr(msg, "id", None), msg) for msg in tail]

    def _repair_dangling_user_boundary(
        self,
        middle: list[Msg],
        tail: list[Msg],
        active_ids: set[str],
    ) -> tuple[list[Msg], list[Msg]]:
        """Avoid evicting only the user half of a completed exchange.

        AgentScope's token split optimizes for a recent-tail token budget, so
        it can place a user request at the end of ``middle`` while keeping the
        corresponding assistant reply at the front of ``tail``. That is a poor
        scroll boundary: user rows do not carry headlines, so the eviction
        index must call the model to label a user-only span, and the live
        window keeps an answer whose question was just archived. Pull the
        leading non-user reply block(s) into ``middle`` unless they belong to
        the active turn, preserving completed exchanges as the unit of
        eviction. ``reserve`` is a soft target; semantic boundaries win.
        """
        if not middle or not tail:
            return middle, tail
        if getattr(middle[-1], "role", None) != "user":
            return middle, tail

        move_count = 0
        for msg in tail:
            mid = getattr(msg, "id", None)
            if mid in active_ids or getattr(msg, "role", None) == "user":
                break
            move_count += 1
        if not move_count:
            return middle, tail
        moved = tail[:move_count]
        rest = tail[move_count:]
        logger.info(
            "scroll: moved %d reply msg(s) across split boundary to avoid "
            "user-only eviction",
            len(moved),
        )
        return [*middle, *moved], rest

    @staticmethod
    def _is_folded_stub(block: Any) -> bool:
        """True if this result's output is already a fold stub."""
        out = getattr(block, "output", None)
        if isinstance(out, str):
            return out.startswith((_FOLD_MARK, _RECALL_FOLD_MARK))
        if isinstance(out, list) and out:
            first = out[0]
            text = (
                first.get("text", "")
                if isinstance(first, dict)
                else getattr(first, "text", "") or ""
            )
            return str(text).startswith((_FOLD_MARK, _RECALL_FOLD_MARK))
        return False

    def _rebuild_context(
        self,
        agent: Any,
        tail: list[Msg],
    ) -> None:
        """Rebuild from separate summary/index state plus the live tail."""
        memory = self._index.render()
        if self._continuation_summary is not None:
            memory = (
                self._continuation_summary.render_background(
                    stale=self._summary_update_failed,
                )
                + "\n\n"
                + memory
            )
        placeholder = UserMsg(name="memory", content=memory)
        self._synthetic_ids.add(placeholder.id)
        agent.state.context = [placeholder] + tail

    def _prune_bookkeeping_to_live_context(self, agent: Any) -> None:
        """Discard dedup/index helpers for messages no longer live.

        Durable content and recovery spans already live in ``history.db`` and
        the eviction index by the time this runs. Keeping per-message maps for
        archived turns only bloats every subsequent session checkpoint. A
        boundary message retained in the rebuilt tail keeps its original id,
        so its update/dedup bookkeeping remains intact.
        """
        live_msg_ids: set[str] = set()
        live_tool_ids: set[str] = set()
        for msg in getattr(agent.state, "context", []) or []:
            mid = getattr(msg, "id", None) or str(id(msg))
            live_msg_ids.add(str(mid))
            for block in getattr(msg, "content", None) or []:
                btype = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if btype not in ("tool_call", "tool_result"):
                    continue
                tcid = (
                    block.get("id")
                    if isinstance(block, dict)
                    else getattr(block, "id", None)
                )
                if tcid:
                    live_tool_ids.add(str(tcid))

        self._persisted_ids.intersection_update(live_msg_ids)
        self._persisted_tcids.intersection_update(live_tool_ids)
        self._synthetic_ids.intersection_update(live_msg_ids)
        self._seq_by_id = {
            key: value
            for key, value in self._seq_by_id.items()
            if key in live_msg_ids
        }
        self._model_turn_seq = {
            key: value
            for key, value in self._model_turn_seq.items()
            if key in live_msg_ids
        }
        self._model_turn_nblk = {
            key: value
            for key, value in self._model_turn_nblk.items()
            if key in live_msg_ids
        }
        self._leaf_by_id = {
            key: value
            for key, value in self._leaf_by_id.items()
            if key in live_msg_ids
        }
        self._seq_by_tcid = {
            key: value
            for key, value in self._seq_by_tcid.items()
            if key in live_tool_ids
        }

    def _index_evicted(self, middle: list[Msg]) -> None:
        """Append the evicted middle to the index as one fresh Tier 0 block.

        The block spans every evicted ``seq``; its leaves are the model turns
        that carry a headline. A span with no headlined turn keeps the bare
        ``(no milestone)`` marker and remains precisely recallable by seq.
        """
        leaves: list[Leaf] = []
        lo: int | None = None
        hi: int | None = None
        for m in middle:
            mid = getattr(m, "id", None) or str(id(m))
            rng = self._seq_by_id.get(mid)
            if rng:
                lo = rng[0] if lo is None else min(lo, rng[0])
                hi = rng[1] if hi is None else max(hi, rng[1])
            leaf = self._leaf_by_id.get(mid)
            if leaf:
                leaves.append(leaf)
        if lo is None or hi is None:  # no known seq (shouldn't happen)
            return
        self._index.add_eviction(
            leaves,
            seq_lo=lo,
            seq_hi=hi,
        )

    def describe_index(self) -> str:
        """The eviction-index tier/span map for the ``/compact`` reply (empty
        if nothing has been evicted yet)."""
        return self._index.describe()

    def describe_summary(self) -> str:
        """Return the deterministic Markdown continuation state, if any."""
        if self._continuation_summary is None:
            return ""
        return self._continuation_summary.render()

    # -- checkpoint ----------------------------------------------------------

    def to_dict(self) -> dict:
        """Snapshot the dedup bookkeeping + eviction index for the agent
        checkpoint.

        All maps are keyed by ``msg.id``, which round-trips identically through
        ``AgentState`` (de)serialization — so on reload these seed the dedup
        sets and ``_persist_new`` recognizes the restored window as already
        durable instead of re-appending it.
        """
        return {
            "persisted_ids": sorted(self._persisted_ids),
            "persisted_tcids": sorted(self._persisted_tcids),
            "seq_by_tcid": dict(self._seq_by_tcid),
            "synthetic_ids": sorted(self._synthetic_ids),
            "seq_by_id": {
                k: [lo, hi] for k, (lo, hi) in self._seq_by_id.items()
            },
            "model_turn_seq": dict(self._model_turn_seq),
            "model_turn_nblk": dict(self._model_turn_nblk),
            "leaf_by_id": {
                k: [lf.seq, lf.headline] for k, lf in self._leaf_by_id.items()
            },
            "index": self._index.to_dict(),
            "continuation_summary": (
                self._continuation_summary.to_dict()
                if self._continuation_summary is not None
                else None
            ),
            "summary_update_failed": self._summary_update_failed,
            "summary_update_count": self._summary_update_count,
        }

    def load_state(self, data: Any) -> None:
        """Rehydrate bookkeeping from :meth:`to_dict`. Tolerant of partial or
        absent data (older checkpoints) — anything missing stays at its
        freshly-constructed empty default."""
        if not isinstance(data, dict):
            return
        self._persisted_ids = set(data.get("persisted_ids", ()))
        self._persisted_tcids = set(data.get("persisted_tcids", ()))
        self._seq_by_tcid = dict(data.get("seq_by_tcid", {}))
        self._synthetic_ids = set(data.get("synthetic_ids", ()))
        self._seq_by_id = {
            k: (lo, hi) for k, (lo, hi) in data.get("seq_by_id", {}).items()
        }
        self._model_turn_seq = dict(data.get("model_turn_seq", {}))
        self._model_turn_nblk = dict(data.get("model_turn_nblk", {}))
        self._leaf_by_id = {
            k: Leaf(seq=seq, headline=headline)
            for k, (seq, headline) in data.get("leaf_by_id", {}).items()
        }
        if "index" in data:
            self._index = EvictionIndex.from_dict(data["index"])
        raw_summary = data.get("continuation_summary")
        if isinstance(raw_summary, dict):
            self._continuation_summary = ContinuationSummary.from_dict(
                raw_summary,
            )
        self._summary_update_failed = bool(
            data.get("summary_update_failed", False),
        )
        try:
            self._summary_update_count = max(
                0,
                int(data.get("summary_update_count", 0) or 0),
            )
        except (TypeError, ValueError):
            self._summary_update_count = 0

    def purge_old(self, retention_days: int, *, dry_run: bool = False) -> int:
        """Drop durable history older than ``retention_days`` (0 = keep
        forever). Returns the number of rows removed (or, with ``dry_run``,
        that would be removed — nothing is deleted)."""
        if retention_days <= 0:
            return 0
        return self._history.purge(
            before=self._cutoff(retention_days),
            dry_run=dry_run,
        )

    @staticmethod
    def _cutoff(retention_days: int) -> str:
        """ISO-8601 UTC instant ``retention_days`` ago — the purge boundary."""
        return (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()

    def close(self) -> None:
        self._history.close()
