# -*- coding: utf-8 -*-
"""ScrollContextManager — write-through + eviction-index context management.

The strategy form of the design in ``CONTEXT_MANAGEMENT.html``: instead of
subclassing the agent, it is injected into :class:`QwenPawAgent` and drives the
two delegated hooks.

* :meth:`on_save` — every live turn is persisted to the durable
  ``conversation_history`` as it enters the window (write-through).
* :meth:`compress` — past the token threshold, keep the recent tail (and the
  active turn), update a continuation summary, and fold the
  evicted middle into an in-context :class:`EvictionIndex`. The summary is a
  state cache, never a replacement for raw history. Code records its durable
  provenance range; exact navigation and recovery stay in the eviction index.
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
    SCROLL_MEMORY_MESSAGE_TAG,
    SYNTHETIC_USER_MESSAGE_TAGS,
)
from . import _as_internals as as_internals
from .continuation_summary import (
    ContinuationSummary,
    SummaryMode,
    build_update_prompt,
    parse_plain_markdown,
    redact_secrets,
    validate_summary_quality,
)
from .eviction_index import EvictionIndex, Leaf, render_live_turn_banner
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
_PRE_TRIM_MIN_CHARS = 200
_PROTECTED_RECENT_TOOL_RESULTS = 5
_OUTPUT_RESERVE_RATIO = 0.05
_MAX_OUTPUT_RESERVE_TOKENS = 4096
_SUMMARY_UPDATE_TIMEOUT_SECONDS = 60.0
_OVERFLOW_FORCE_TRIGGER_RATIO = 1e-6
_SummaryRecords = tuple[
    list[tuple[int, str]],
    list[tuple[int, str]],
    list[tuple[int, str]],
]


class _SummaryCandidateError(ValueError):
    """A returned summary candidate failed local format or quality checks."""


class _SummaryInputBudgetError(ValueError):
    """The fixed summary prompt cannot fit beside its output reserve."""


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
        # Tool results included in a model request that completed
        # successfully. This explicit acknowledgement lets hard-limit
        # recovery fold old results in the active turn without guessing from
        # block order. It is checkpointed with the rest of the manager state.
        self._seen_tool_result_ids: set[str] = set()
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
        # What the most recent compress() actually did — /compact reads this
        # to report honestly (an in-place fold changes no message count, so
        # the reply can't infer it from a before/after len()). Transient, not
        # checkpointed.
        self.last_compress: dict[str, int] = {
            "evicted": 0,
            "pre_folded": 0,
            "live_folded": 0,
            "active_folded": 0,
            "folded": 0,
        }
        # Warn once per overflow episode, not once per reasoning step.
        self._overflow_warned = False

    @staticmethod
    def should_compress(tokens: float, trigger: float) -> bool:
        """Return Scroll's pressure-boundary decision.

        Usage exactly at the trigger remains live. Memory middleware calls the
        same predicate so long-term-memory work cannot be predicted when
        Scroll itself will perform no compaction.
        """
        return tokens > trigger

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

    def model_input_tool_result_ids(self, agent: Any) -> set[str]:
        """Snapshot tool results about to be submitted to the model.

        The caller must acknowledge this snapshot only after the model call
        succeeds. Capturing and acknowledgement are deliberately separate so
        a rejected/failed request cannot make unread evidence foldable.
        """
        ids: set[str] = set()
        for _, block in self._live_tool_results(agent):
            tcid = (
                block.get("id")
                if isinstance(block, dict)
                else getattr(block, "id", None)
            )
            if tcid:
                ids.add(str(tcid))
        return ids

    def acknowledge_model_input_tool_results(
        self,
        tool_result_ids: set[str],
    ) -> None:
        """Mark a successfully submitted model input's results as seen."""
        self._seen_tool_result_ids.update(
            str(item) for item in tool_result_ids
        )

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

    async def recover_from_context_overflow(self, agent: Any) -> bool:
        """Force one compaction after a provider rejects an oversized input."""
        base_config = getattr(agent, "context_config", None)
        if base_config is None:
            return False
        try:
            forced_config = base_config.model_copy(
                update={"trigger_ratio": _OVERFLOW_FORCE_TRIGGER_RATIO},
            )
        except Exception:
            logger.warning(
                "Could not clone context_config for context-overflow "
                "recovery; skipping the recovery attempt.",
                exc_info=True,
            )
            return False

        await self.compress(agent, forced_config)
        return bool(
            self.last_compress.get("evicted")
            or self.last_compress.get("folded"),
        )

    # pylint: disable-next=too-many-statements,too-many-branches
    async def compress(
        self,
        agent: Any,
        context_config: Any = None,
        instructions: Any = None,
    ) -> None:
        """Evict the middle into the index; fold tool results under pressure.

        A graduated pressure pipeline. Recoverable outputs from completed
        turns are the cheapest content to remove, so automatic compression
        tries those before evicting dialogue. The active turn remains intact
        until the existing post-eviction pressure valve:

        1. persist     — every live turn is now durable.
        2. trigger     — under the token threshold? nothing to do.
        3. pre-fold    — on automatic pressure, batch-fold every eligible
                         completed-turn tool result outside the protected
                         recent tail. If the context falls to the trigger or
                         below, stop without eviction.
        4. split       — evictable middle | recent tail (+ active turn).
        5. summarize   — update compact task state from bounded input;
                         preserve the previous value on any failure.
        6. add_eviction— fold the middle (if any) into the index as a new
                         Tier 0 block, rebuild context = [index] + tail.
        7. live-fold   — still under real pressure after finished turns are
                         evicted: replace remaining eligible completed-turn
                         results with recovery pointers.
        8. active-fold— above the effective hard limit, fold old active-turn
                         results that a successful model call already read.
        """
        cfg = context_config or agent.context_config
        self.last_compress = {
            "evicted": 0,
            "pre_folded": 0,
            "live_folded": 0,
            "active_folded": 0,
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
        if not self.should_compress(tokens, trigger):
            self._overflow_warned = False
            log_timings("at_or_below_trigger")
            return

        # 3) Before evicting dialogue, reclaim recoverable tool output from
        #    completed turns. This runs only for normal automatic pressure:
        #    manual /compact deliberately lowers trigger_ratio to request an
        #    eviction now, and must not be intercepted by this lighter pass.
        #    Fold every eligible result in one batch rather than stopping at an
        #    intermediate target. This pays at most one prefix-cache reset per
        #    pressure episode and leaves a stable, compact prompt for later
        #    turns. The complete active turn and five newest tool results stay
        #    verbatim; outputs at or below 200 characters are not worth
        #    replacing with recovery pointers.
        base_cfg = getattr(agent, "context_config", cfg)
        base_trigger_ratio = float(
            getattr(base_cfg, "trigger_ratio", cfg.trigger_ratio),
        )
        is_forced_compaction = float(cfg.trigger_ratio) < base_trigger_ratio
        if not is_forced_compaction:
            pre_folded, tokens = await self._batch_fold_completed_tool_results(
                agent,
                tokens=tokens,
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

            # 5) Update the continuation state from bounded
            #    previews. Failure is non-fatal: the previous valid summary
            #    stays in place and the exact rows remain in history.db.
            await self._update_continuation_summary(
                agent,
                middle,
                focus_hint=self._summary_focus_hint(instructions),
            )
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
        #    (completed turns only, with the recent five-result tail protected)
        #    and stop as soon as the pressure target is met. The complete
        #    active turn stays verbatim under normal pressure. For manual
        #    /compact the configured reserve, rather than its synthetic
        #    near-zero trigger, is the meaningful target.
        pressure_threshold = max(trigger, reserve)
        if tokens > pressure_threshold:
            folded, tokens = await self._fold_tool_results_under_pressure(
                agent,
                tokens=tokens,
                target=pressure_threshold,
            )
            mark("fold_tool_results")
            if folded:
                self.last_compress["live_folded"] = folded
                self.last_compress["folded"] += folded
                logger.info(
                    "scroll: pressure-folded %d live tool result(s)",
                    folded,
                )
        # 8) A single long tool-running turn can itself exceed the input hard
        #    limit after every completed turn has been folded/evicted. At this
        #    final boundary, reclaim only active-turn results proven to have
        #    appeared in a successful prior model request. The current user
        #    request, pending/unread results, and the five newest results stay
        #    verbatim. Fold the whole safe batch, then recount exactly once.
        if tokens > effective_hard_limit:
            active_folded, tokens = await self._batch_fold_seen_active_results(
                agent,
                tokens=tokens,
            )
            mark("active_turn_fold")
            if active_folded:
                self.last_compress["active_folded"] = active_folded
                self.last_compress["folded"] += active_folded
                logger.info(
                    "scroll: hard-limit-folded %d seen active-turn tool "
                    "result(s)",
                    active_folded,
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
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        marker = " [… omitted …] "
        if limit <= len(marker) + 1:
            return text[:limit]
        content_budget = limit - len(marker)
        head = content_budget // 2
        tail = content_budget - head
        return f"{text[:head]}{marker}{text[-tail:]}"

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

    @staticmethod
    def _summary_timestamp(value: Any) -> str | None:
        """Render a timestamp without guessing the timezone.

        AgentScope currently creates naive local wall-clock timestamps by
        default. Aware values are normalized to UTC; naive values remain
        useful temporal evidence but are explicitly marked as having an
        unspecified timezone. Malformed values are omitted.
        """
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip()
        try:
            parsed = datetime.fromisoformat(
                raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw,
            )
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return (
                f"{parsed.isoformat(timespec='seconds')} "
                "timezone=unspecified"
            )
        utc_value = parsed.astimezone(timezone.utc)
        return utc_value.isoformat(timespec="seconds").replace(
            "+00:00",
            "Z",
        )

    def _durable_folded_result_contents(
        self,
        messages: list[Msg],
    ) -> dict[tuple[str, int], str | None]:
        """Recover pre-folded tool output by its exact persisted seq."""
        result_seqs: dict[tuple[str, int], int] = {}
        for msg in messages:
            mid = getattr(msg, "id", None) or str(id(msg))
            anonymous_position = 0
            result_position = 0
            for entry in msg_to_entries(msg):
                if entry.kind != "tool_result":
                    continue
                durable_key = entry.tool_call_id
                if not durable_key:
                    durable_key = f"{mid}#anon{anonymous_position}"
                    anonymous_position += 1
                if str(entry.content or "").startswith(
                    (_FOLD_MARK, _RECALL_FOLD_MARK),
                ):
                    seq = self._seq_by_tcid.get(str(durable_key))
                    if seq is not None:
                        result_seqs[(mid, result_position)] = seq
                result_position += 1

        contents = self._history.contents_by_seqs(set(result_seqs.values()))
        return {
            key: contents.get(seq)
            for key, seq in result_seqs.items()
            if seq in contents
        }

    @staticmethod
    def _summary_result_content(
        durable_contents: dict[tuple[str, int], str | None],
        key: tuple[str, int],
        fallback: str | None,
    ) -> str | None:
        """Prefer durable original output, falling back to the live value."""
        original = durable_contents.get(key)
        return original if original is not None else fallback

    def _summary_archived_context(
        self,
        middle: list[Msg],
        *,
        max_chars: int,
        durable_contents: (dict[tuple[str, int], str | None] | None) = None,
    ) -> str:
        """Render role-aware bounded evidence for the summary model.

        The summary exists to preserve the semantics of what is about to be
        evicted.  A global head/tail truncation can hide every user fact in the
        middle of a long tool-heavy span, so allocate the budget by semantic
        priority instead: user text and headlines first, assistant state and
        tool calls second, bounded tool-result previews last.  Exact tool
        output remains recoverable through the printed durable pointers.

        Pre-folding mutates the live ``Msg`` before this method runs. For a
        folded tool result, recover its original content by exact durable seq
        so the summary model sees a bounded preview of the real outcome rather
        than only the recovery stub.
        """
        if durable_contents is None:
            durable_contents = self._durable_folded_result_contents(middle)
        records = self._summary_archived_records(
            middle,
            durable_contents,
        )
        return self._render_summary_records(records, max_chars)

    def _summary_archived_records(
        self,
        middle: list[Msg],
        durable_contents: dict[tuple[str, int], str | None],
    ) -> _SummaryRecords:
        """Serialize summary evidence once before token-budget fitting."""
        essential: list[tuple[int, str]] = []
        supporting: list[tuple[int, str]] = []
        tool_results: list[tuple[int, str]] = []
        order = 0
        for msg in middle:
            mid = getattr(msg, "id", None) or str(id(msg))
            span = self._seq_by_id.get(mid)
            pointer = f"[seq:{span[0]}-{span[1]}]" if span else "[seq:unknown]"
            role = getattr(msg, "role", "unknown")
            prefix = f"{pointer} role={role}"
            timestamp = self._summary_timestamp(
                getattr(msg, "created_at", None),
            )
            if timestamp:
                prefix += f" created_at={timestamp}"
            result_position = 0
            for entry in msg_to_entries(msg):
                if entry.kind == "tool_result":
                    result_content = self._summary_result_content(
                        durable_contents,
                        (mid, result_position),
                        entry.content,
                    )
                    preview = self._bounded_summary_text(result_content, 600)
                    chunk = (
                        f"{prefix}\n  tool_result "
                        f"name={entry.name!r} id={entry.tool_call_id!r} "
                        f"state={entry.tool_state!r} preview={preview!r}"
                    )
                    pointers = self._summary_metadata_pointers(entry.metadata)
                    if pointers:
                        chunk += f"\n  recovery={' '.join(pointers)}"
                    tool_results.append((order, chunk))
                    order += 1
                    result_position += 1
                    continue
                text_limit = 8000 if role == "user" else 2000
                text = self._bounded_summary_text(entry.content, text_limit)
                if text:
                    target = essential if role == "user" else supporting
                    target.append((order, f"{prefix}\n  text={text!r}"))
                    order += 1
                if entry.headline:
                    headline = self._bounded_summary_text(
                        entry.headline,
                        2000,
                    )
                    essential.append(
                        (order, f"{prefix}\n  headline={headline!r}"),
                    )
                    order += 1
                if entry.name or entry.tool_call_id:
                    tool_input = self._bounded_summary_text(
                        entry.tool_input,
                        600,
                    )
                    supporting.append(
                        (
                            order,
                            f"{prefix}\n  tool_call name={entry.name!r} "
                            f"id={entry.tool_call_id!r} "
                            f"input={tool_input!r}",
                        ),
                    )
                    order += 1

        return essential, supporting, tool_results

    def _render_summary_records(
        self,
        records: _SummaryRecords,
        max_chars: int,
    ) -> str:
        """Render cached evidence records under one character candidate."""
        essential, supporting, tool_results = records
        selected = self._fit_summary_records(essential, max_chars)
        used = sum(len(text) + 1 for _, text in selected)
        remaining = max(0, max_chars - used)

        # Preserve a share for actual tool outcomes. Assistant narration is
        # useful, but it must not consume the whole remainder before an error
        # or exact result preview can be seen.
        if supporting and tool_results and remaining > 0:
            # The per-group fitter accounts for separators within each group;
            # reserve the separator introduced when the two groups are joined.
            remaining -= 1
        tool_budget = min(
            sum(len(text) + 1 for _, text in tool_results),
            remaining // 3,
        )
        support_budget = remaining - tool_budget
        selected.extend(
            self._fit_summary_records(supporting, support_budget),
        )
        selected.extend(
            self._fit_summary_records(tool_results, tool_budget),
        )
        selected.sort(key=lambda item: item[0])
        return "\n".join(text for _, text in selected)

    @classmethod
    def _fit_summary_records(
        cls,
        records: list[tuple[int, str]],
        budget: int,
    ) -> list[tuple[int, str]]:
        """Fit every record fairly instead of dropping the middle records."""
        if not records or budget <= 0:
            return []
        total = sum(len(text) + 1 for _, text in records)
        if total <= budget:
            return list(records)

        # A non-empty record plus its separator costs at least two chars. In
        # pathological histories with more records than the budget can encode,
        # sample across the full time range instead of overflowing the hard
        # input bound or retaining only a head/tail slice.
        max_records = max(1, (budget + 1) // 2)
        if len(records) > max_records:
            if max_records == 1:
                records = [records[-1]]
            else:
                last = len(records) - 1
                records = [
                    records[round(index * last / (max_records - 1))]
                    for index in range(max_records)
                ]

        text_budget = max(1, budget - (len(records) - 1))
        share, extra = divmod(text_budget, len(records))
        return [
            (
                order,
                cls._bounded_summary_text(
                    text,
                    share + (1 if index < extra else 0),
                ),
            )
            for index, (order, text) in enumerate(records)
        ]

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

    @staticmethod
    def _summary_focus_hint(instructions: Any) -> str:
        """Extract text-only, one-shot compaction guidance."""
        value = getattr(instructions, "hint", instructions)
        if isinstance(value, str):
            return value
        if not isinstance(value, list):
            return ""
        parts: list[str] = []
        for block in value:
            block_type = (
                block.get("type")
                if isinstance(block, dict)
                else getattr(block, "type", None)
            )
            if block_type != "text":
                continue
            text = (
                block.get("text", "")
                if isinstance(block, dict)
                else getattr(block, "text", "")
            )
            if text:
                parts.append(str(text))
        return "\n".join(parts)

    async def _generate_plain_summary(
        self,
        agent: Any,
        prompt: str,
        *,
        max_tokens: int,
        language: str = "en",
    ) -> str:
        """Call the chat model normally; structured output is never used."""
        if not callable(getattr(agent, "model", None)):
            return ""
        messages = self._summary_messages(prompt, language)
        response = await agent.model(
            messages=messages,
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

    @staticmethod
    def _summary_messages(prompt: str, language: str) -> list[Msg]:
        """Build the exact message list used for counting and generation."""
        system_content = (
            "你负责更新一份紧凑的 continuation summary。严格遵循指定的 "
            "Markdown headings，并使用中文填写自然语言内容。"
            if str(language).lower().startswith("zh")
            else (
                "You update a compact continuation summary. Follow the "
                "requested Markdown headings exactly and write natural-"
                "language content in English."
            )
        )
        return [
            SystemMsg(name="system", content=system_content),
            UserMsg(name="user", content=prompt),
        ]

    async def _fit_summary_prompt(
        self,
        agent: Any,
        records: _SummaryRecords,
        *,
        mode: SummaryMode,
        previous: ContinuationSummary | None,
        covered: tuple[int, int],
        repair_issues: tuple[str, ...],
        focus_hint: str,
        language: str,
        output_tokens: int,
    ) -> tuple[str, str]:
        """Fit evidence using model token accounting, with output reserved."""
        context_size = max(
            1,
            int(getattr(agent.model, "context_size", 0) or 0),
        )
        safety_tokens = max(32, min(1024, context_size // 50))
        input_budget = context_size - output_tokens - safety_tokens
        if input_budget <= 0:
            raise _SummaryInputBudgetError(
                "no input tokens remain after summary output reserve",
            )

        async def build_and_count(max_chars: int) -> tuple[str, str, int]:
            archived_context = self._render_summary_records(
                records,
                max_chars,
            )
            prompt = build_update_prompt(
                mode=mode,
                previous=previous,
                archived_context=archived_context,
                covered_seq=covered,
                repair_issues=repair_issues,
                focus_hint=focus_hint,
                language=language,
            )
            tokens = await agent.model.count_tokens(
                messages=self._summary_messages(prompt, language),
                tools=None,
            )
            return prompt, archived_context, tokens

        # First ensure that the fixed instructions and previous state fit.
        empty_prompt, _, empty_tokens = await build_and_count(0)
        if empty_tokens > input_budget:
            raise _SummaryInputBudgetError(
                "summary instructions and previous state exceed input budget",
            )

        high = 80_000
        prompt, archived_context, tokens = await build_and_count(high)
        if tokens <= input_budget:
            return prompt, archived_context

        best_prompt = empty_prompt
        best_context = ""
        low = 1
        high -= 1
        while low <= high:
            mid = (low + high) // 2
            (
                candidate_prompt,
                candidate_context,
                tokens,
            ) = await build_and_count(mid)
            if tokens <= input_budget:
                best_prompt = candidate_prompt
                best_context = candidate_context
                low = mid + 1
            else:
                high = mid - 1
        if not best_context:
            raise _SummaryInputBudgetError(
                "no archived evidence fits the summary input budget",
            )
        return best_prompt, best_context

    def _source_backed_previous_summary(
        self,
        existing_endpoints: set[int] | None = None,
    ) -> ContinuationSummary | None:
        """Return the previous summary only while its range is durable."""
        previous = self._continuation_summary
        if previous is None:
            return None
        endpoints = set(previous.covered_seq)
        existing = (
            self._history.existing_seqs(endpoints)
            if existing_endpoints is None
            else existing_endpoints
        )
        if existing == endpoints:
            return previous
        logger.info(
            "scroll: previous continuation summary references expired "
            "history; rebuilding from new durable evidence",
        )
        # Never reassign claims from purged evidence to a newer seq range
        # merely to satisfy pointer validation. The expired summary is no
        # longer source-backed, so discard it and build a fresh state from the
        # newly archived, durable span.
        self._continuation_summary = None
        return None

    def reconcile_loaded_context(self, agent: Any) -> bool:
        """Remove an expired summary from a restored model-facing context.

        Session state is normally saved before retention purges durable
        history.  A later restore can therefore contain a continuation
        summary whose provenance endpoints no longer exist.  Validate it
        eagerly, before the below-trigger fast path can return, and rebuild
        the synthetic memory message without the unsupported summary.
        """
        previous = self._continuation_summary
        if (
            previous is None
            or self._source_backed_previous_summary() is not None
        ):
            return False
        tail: list[Msg] = []
        for msg in list(getattr(agent.state, "context", ()) or ()):
            metadata = getattr(msg, "metadata", None)
            is_memory = (
                isinstance(metadata, dict)
                and metadata.get(QWENPAW_MESSAGE_TAG_KEY)
                == SCROLL_MEMORY_MESSAGE_TAG
            )
            if is_memory:
                self._synthetic_ids.discard(getattr(msg, "id", ""))
                continue
            tail.append(msg)
        self._summary_update_failed = False
        self._rebuild_context(agent, tail)
        return True

    async def _validated_summary_attempt(
        self,
        agent: Any,
        prompt: str,
        *,
        output_tokens: int,
        language: str,
        covered: tuple[int, int],
        evidence_text: str,
        timeout: float,
    ) -> ContinuationSummary:
        """Generate and locally validate one summary candidate."""
        if timeout <= 0:
            raise asyncio.TimeoutError
        plain_text = await asyncio.wait_for(
            self._generate_plain_summary(
                agent,
                prompt,
                max_tokens=output_tokens,
                language=language,
            ),
            timeout=timeout,
        )
        if len(plain_text) > 16_000:
            raise _SummaryCandidateError(
                "plain Markdown summary exceeds hard limit",
            )
        candidate = parse_plain_markdown(
            plain_text,
            covered_seq=covered,
        )
        if candidate is None:
            raise _SummaryCandidateError(
                "empty or malformed plain Markdown summary",
            )
        endpoints = {
            endpoint
            for lo, hi in candidate.seq_spans()
            for endpoint in (lo, hi)
        }
        existing_seqs = await asyncio.to_thread(
            self._history.existing_seqs,
            endpoints,
        )
        issues = validate_summary_quality(
            candidate,
            evidence_text=evidence_text,
            existing_seqs=existing_seqs,
        )
        if issues:
            raise _SummaryCandidateError("; ".join(issues))
        return candidate

    async def _update_continuation_summary(
        self,
        agent: Any,
        middle: list[Msg],
        *,
        focus_hint: str = "",
    ) -> None:
        """Update the summary within one end-to-end timeout."""
        try:
            async with asyncio.timeout(_SUMMARY_UPDATE_TIMEOUT_SECONDS):
                await self._update_continuation_summary_inner(
                    agent,
                    middle,
                    focus_hint=focus_hint,
                )
        except TimeoutError as exc:
            self._summary_update_failed = True
            logger.warning(
                "scroll: continuation summary update timed out after "
                "%g seconds; preserving the previous valid summary",
                _SUMMARY_UPDATE_TIMEOUT_SECONDS,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    async def _update_continuation_summary_inner(
        self,
        agent: Any,
        middle: list[Msg],
        *,
        focus_hint: str = "",
    ) -> None:
        """Update, validate, and at most once retry the plain summary."""
        new_span = self._evicted_span(middle)
        if new_span is None or not callable(getattr(agent, "model", None)):
            return
        previous = self._continuation_summary
        if previous is not None:
            endpoints = set(previous.covered_seq)
            existing = await asyncio.to_thread(
                self._history.existing_seqs,
                endpoints,
            )
            previous = self._source_backed_previous_summary(existing)
        language = str(
            getattr(
                getattr(agent, "_agent_config", None),
                "language",
                getattr(agent, "_language", "en"),
            )
            or "en",
        )
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
        durable_contents = await asyncio.to_thread(
            self._durable_folded_result_contents,
            middle,
        )
        summary_records = await asyncio.to_thread(
            self._summary_archived_records,
            middle,
            durable_contents,
        )
        repair_issues: tuple[str, ...] = ()
        updated: ContinuationSummary | None = None
        failure: Exception | None = None
        deadline = time.monotonic() + _SUMMARY_UPDATE_TIMEOUT_SECONDS
        for attempt in range(2):
            summary_mode: SummaryMode = (
                "update" if previous is not None else "initial"
            )
            try:
                prompt, new_context = await self._fit_summary_prompt(
                    agent,
                    summary_records,
                    mode=summary_mode,
                    previous=previous,
                    covered=covered,
                    repair_issues=repair_issues,
                    focus_hint=focus_hint,
                    language=language,
                    output_tokens=output_tokens,
                )
                evidence_text = new_context
                if previous is not None:
                    evidence_text = previous.render() + "\n" + evidence_text
                updated = await self._validated_summary_attempt(
                    agent,
                    prompt,
                    output_tokens=output_tokens,
                    language=language,
                    covered=covered,
                    evidence_text=evidence_text,
                    timeout=deadline - time.monotonic(),
                )
                break
            except asyncio.TimeoutError:
                failure = TimeoutError(
                    "continuation summary generation timed out after "
                    f"{_SUMMARY_UPDATE_TIMEOUT_SECONDS:g} seconds",
                )
                # The timeout is a provider/connection failure, not a quality
                # issue that a repair prompt can fix. Preserve a still-valid
                # previous summary as stale without making a second call.
                break
            except _SummaryCandidateError as exc:
                failure = exc
                repair_issues = (str(exc) or type(exc).__name__,)
                if attempt == 0:
                    self.last_compress["summary_retries"] = 1
            except Exception as exc:  # noqa: BLE001 - provider failure
                # Authentication, rate-limit, transport, and provider errors
                # cannot be repaired by asking the same provider again with a
                # quality prompt. Preserve the previous valid state now.
                failure = exc
                break

        if updated is None:
            self._summary_update_failed = True
            logger.warning(
                "scroll: continuation summary update failed; "
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

    def _tool_result_text_chars(self, block: Any) -> int:
        """Return the number of visible text characters in a tool result."""
        output = (
            block.get("output")
            if isinstance(block, dict)
            else getattr(block, "output", None)
        )
        if isinstance(output, str):
            return len(output)
        if not isinstance(output, list):
            return 0
        total = 0
        for item in output:
            if self._block_type(item) != "text":
                continue
            text = (
                item.get("text", "")
                if isinstance(item, dict)
                else getattr(item, "text", "")
            )
            total += len(str(text or ""))
        return total

    @staticmethod
    def _replace_tool_result_with_pointer(block: Any, text: str) -> None:
        output = [TextBlock(type="text", text=text)]
        if isinstance(block, dict):
            block["output"] = output
        else:
            block.output = output

    # pylint: disable-next=too-many-branches
    def _tool_result_fold_candidates(
        self,
        agent: Any,
        *,
        seen_active_only: bool = False,
    ) -> list[tuple[int, int, Any, str]]:
        """Return profitable fold candidates ordered by recovery priority.

        Normally only completed-turn results are returned. For hard-limit
        recovery, ``seen_active_only`` selects only results in the active turn
        that a successful model request already consumed. The five newest
        results are always protected. A result is eligible only when it has
        more than 200 visible text characters and its pointer is actually
        smaller than its output.
        """
        results = self._live_tool_results(agent)
        active_messages = {id(msg) for msg in self._active_turn_tail(agent)}
        recall_inputs = self._tool_call_inputs(agent)
        protected_results = {
            id(block) for _, block in results[-_PROTECTED_RECENT_TOOL_RESULTS:]
        }

        candidates: list[tuple[int, int, Any, str]] = []
        for ordinal, (msg, block) in enumerate(results):
            is_active = id(msg) in active_messages
            if id(block) in protected_results:
                continue
            if self._is_folded_stub(block):
                continue
            if self._tool_result_text_chars(block) <= _PRE_TRIM_MIN_CHARS:
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
            tool_call_id = str(tool_call_id or "")
            if seen_active_only:
                if (
                    not is_active
                    or tool_call_id not in self._seen_tool_result_ids
                    or tool_call_id not in self._persisted_tcids
                ):
                    continue
            elif is_active:
                continue
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
                (-savings, ordinal, block, text),
            )

        candidates.sort(key=lambda item: item[:2])
        return candidates

    async def _batch_fold_completed_tool_results(
        self,
        agent: Any,
        *,
        tokens: int,
    ) -> tuple[int, int]:
        """Fold all safe completed-turn results, then recount exactly once."""
        candidates = self._tool_result_fold_candidates(agent)
        for _, _, block, text in candidates:
            self._replace_tool_result_with_pointer(block, text)
        if not candidates:
            return 0, tokens
        return len(candidates), await self._live_tokens(agent)

    async def _batch_fold_seen_active_results(
        self,
        agent: Any,
        *,
        tokens: int,
    ) -> tuple[int, int]:
        """Fold all acknowledged active results, then recount exactly once."""
        candidates = self._tool_result_fold_candidates(
            agent,
            seen_active_only=True,
        )
        for _, _, block, text in candidates:
            self._replace_tool_result_with_pointer(block, text)
        if not candidates:
            return 0, tokens
        return len(candidates), await self._live_tokens(agent)

    async def _fold_tool_results_under_pressure(
        self,
        agent: Any,
        *,
        tokens: int,
        target: float,
    ) -> tuple[int, int]:
        """Fold profitable live results until ``tokens`` reaches ``target``."""
        candidates = self._tool_result_fold_candidates(agent)
        folded = 0
        for _, _, block, text in candidates:
            self._replace_tool_result_with_pointer(block, text)
            folded += 1
            tokens = await self._live_tokens(agent)
            if tokens <= target:
                break
        return folded, tokens

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
                            metadata=entry.metadata,
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
        """Avoid evicting only the user boundary of a completed turn.

        AgentScope's token split optimizes for a recent-tail token budget, so
        it can place a user request at the end of ``middle`` while keeping the
        corresponding assistant reply at the front of ``tail``. That is a poor
        scroll boundary: user rows do not carry headlines, so the eviction
        index must call the model to label a user-only span, and the live
        window keeps an answer whose question was just archived. Pull the
        leading non-user reply block(s) into ``middle`` unless they belong to
        the active turn, preserving completed turns as the unit of
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
        context_size = int(
            getattr(getattr(agent, "model", None), "context_size", 0) or 0,
        )
        index_detail_budget = max(
            512,
            min(16_000, int(context_size * 0.05)),
        )
        memory = self._index.render(
            detail_char_budget=index_detail_budget,
        )
        if self._continuation_summary is not None:
            body = (
                self._index.render(
                    include_envelope=False,
                    include_live_banner=False,
                    detail_char_budget=index_detail_budget,
                )
                + "\n\n"
                + self._continuation_summary.render_background(
                    stale=self._summary_update_failed,
                    include_envelope=False,
                )
                + "\n"
                + render_live_turn_banner()
            )
            memory = f"<system-info>\n{body}\n</system-info>"
        placeholder = UserMsg(
            name="memory",
            content=memory,
            metadata={
                QWENPAW_MESSAGE_TAG_KEY: SCROLL_MEMORY_MESSAGE_TAG,
            },
        )
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
        self._seen_tool_result_ids.intersection_update(live_tool_ids)
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
            "seen_tool_result_ids": sorted(self._seen_tool_result_ids),
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
        }

    def load_state(self, data: Any) -> None:
        """Rehydrate bookkeeping from :meth:`to_dict`. Tolerant of partial or
        absent data (older checkpoints) — anything missing stays at its
        freshly-constructed empty default."""
        if not isinstance(data, dict):
            return
        self._persisted_ids = set(data.get("persisted_ids", ()))
        self._persisted_tcids = set(data.get("persisted_tcids", ()))
        self._seen_tool_result_ids = set(
            data.get("seen_tool_result_ids", ()),
        )
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
