# -*- coding: utf-8 -*-
"""ScrollContextManager — write-through + eviction-index context management.

The strategy form of the design in ``CONTEXT_MANAGEMENT.html``: instead of
subclassing the agent, it is injected into :class:`QwenPawAgent` and drives the
two delegated hooks.

* :meth:`on_save` — every live turn is persisted to the durable
  ``conversation_history`` as it enters the window (write-through).
* :meth:`compress` — past the token threshold, keep a pinned head + recent tail
  and fold the evicted middle into an in-context :class:`EvictionIndex`. No
  summarization, nothing lost — every node points to a ``seq`` span recallable
  via the sandboxed ``recall_history_python`` REPL.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from agentscope.message import Msg, UserMsg

from . import _as_internals as as_internals
from .eviction_index import EvictionIndex, Leaf
from .history import HistoryStore
from .serialize import msg_to_entries

logger = logging.getLogger(__name__)


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
        pinned: int = 1,
        capped_results: dict[str, int] | None = None,
        offloader: Any = None,
    ) -> None:
        self._history = history
        self._session_id = session_id
        self._agent_id = agent_id
        self._pinned = pinned
        # Dialog archive: when an offloader is wired (``offload_dialog``, on by
        # default), evicted turns are also written to ``dialog/{date}.jsonl``
        # for external consumers. ``history.db`` remains the source of truth.
        self._offloader = offloader
        # Shared with the cap middleware: tool_call_id -> seq of results it
        # already wrote in full. We skip re-persisting their truncated stubs.
        self._capped_results = (
            capped_results if capped_results is not None else {}
        )
        self._persisted_ids: set[
            str
        ] = set()  # msgs whose non-result row is stored
        self._persisted_tcids: set[
            str
        ] = set()  # tool_call_ids whose result row is stored
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
        result — best-effort) and :meth:`compress` (which must NOT evict when
        this returns ``False``, or it would drop un-persisted turns).
        """
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

    async def compress(self, agent: Any, context_config: Any = None) -> None:
        """Evict the middle into the index; roll the index up under pressure.

        1. persist     — every live turn is now durable.
        2. trigger     — under the token threshold? nothing to do.
        3. split       — pinned head | evictable middle | recent tail.
        4. add_eviction— fold the middle into the index as a new Tier 0 block,
                         rebuild context = head + [index] + tail.
        5. compact     — while the rebuilt context still overflows, shrink the
                         index one step and rebuild. Always progresses.
        """
        cfg = context_config or agent.context_config

        # 1) Durability first — everything in the window is now in the DB. If
        #    the write-through failed (degraded durability), do NOT evict: the
        #    middle isn't durable, so folding it in would leave seq pointers to
        #    rows that don't exist. Keep it live instead.
        if not self._persist_guarded(agent):
            return

        # 2) Trigger check (reuse AgentScope's own token accounting).
        kwargs = await as_internals.prepare_model_input(agent)
        if (
            await agent.model.count_tokens(**kwargs)
            < cfg.trigger_ratio * agent.model.context_size
        ):
            return
        if len(agent.state.context) <= self._pinned + 1:
            return

        # 3) Pairing-safe split; keep pinned head + recent tail, evict the
        #    middle.
        reserve = cfg.reserve_ratio * agent.model.context_size
        to_compress, to_reserve = await as_internals.split_for_compression(
            agent,
            reserve,
            kwargs.get("tools", []),
        )
        real = lambda msgs: [
            m for m in msgs if m.id not in self._synthetic_ids
        ]
        head = real(to_compress[: self._pinned])
        tail = real(to_reserve)
        # AgentScope's pairing-safe split deep-copies the *boundary* Msg into
        # BOTH halves under the SAME id (its blocks divided between compress
        # and reserve). That id therefore appears in both to_compress and
        # to_reserve. Drop any tail id from the middle so we never fold a
        # still-live turn's seq span into the index — the reserve copy keeps it
        # visible, so it isn't evicted yet. It gets indexed in a later round
        # once it moves fully onto the compress side.
        tail_ids = {m.id for m in tail}
        middle = [
            m
            for m in real(to_compress[self._pinned :])
            if m.id not in tail_ids
        ]
        if not middle:
            return

        # 3b) Optional legacy archive of the evicted turns (opt-in). The full
        #     turns are already durable in history.db; this is a redundant
        #     dialog/*.jsonl copy for external consumers. A write failure must
        #     never abort compaction.
        await self._offload_dialog(middle)

        # 4) Fold the evicted middle into the index as a new Tier 0 block.
        self._index_evicted(middle)
        self._rebuild_context(agent, head, tail)

        # 5) Pressure-triggered compaction: shrink the index one step at a
        #    time until we fit (or it collapses to a single line). Always
        #    terminates.
        while (
            await agent.model.count_tokens(
                **(await as_internals.prepare_model_input(agent)),
            )
            > reserve
            and self._index.compact()
        ):
            self._rebuild_context(agent, head, tail)

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
        for msg in agent.state.context:
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
                    capped_seq = self._capped_results.get(tcid)
                    if capped_seq is not None:
                        # The cap middleware already wrote this result in
                        # full; don't persist the in-context truncated stub.
                        # Adopt its seq so the result still falls inside the
                        # eviction span.
                        seq = capped_seq
                    else:
                        seq = self._history.append(
                            session_id=self._session_id,
                            agent_id=self._agent_id,
                            entry=entry,
                            dedup_key=tcid,
                        )
                    self._persisted_tcids.add(tcid)
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

    def _rebuild_context(
        self,
        agent: Any,
        head: list[Msg],
        tail: list[Msg],
    ) -> None:
        """state.context = pinned head + the single index placeholder +
        tail."""
        placeholder = UserMsg(name="memory", content=self._index.render())
        self._synthetic_ids.add(placeholder.id)
        agent.state.context = head + [placeholder] + tail

    def _index_evicted(self, middle: list[Msg]) -> None:
        """Append the evicted middle to the index as one fresh Tier 0 block.

        The block spans every evicted ``seq`` (so a range query recovers the
        full turns, tool results included); its leaves are the model turns
        that carry a headline.
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
        }

    def load_state(self, data: Any) -> None:
        """Rehydrate bookkeeping from :meth:`to_dict`. Tolerant of partial or
        absent data (older checkpoints) — anything missing stays at its
        freshly-constructed empty default."""
        if not isinstance(data, dict):
            return
        self._persisted_ids = set(data.get("persisted_ids", ()))
        self._persisted_tcids = set(data.get("persisted_tcids", ()))
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
