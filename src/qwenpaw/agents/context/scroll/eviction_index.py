# -*- coding: utf-8 -*-
"""The eviction index — an in-context, tier-capped odometer of evicted turns.

The whole index lives in the prompt as ONE placeholder, so the model always
*sees the map* of what it evicted. The structure is a stack of tiers:

    Tier 0 (bottom)  the newest evictions; each block lists its turns in full.
    Tier k (k >= 1)  older history, carried up and squeezed to span endpoints.

Each tier holds at most ``_TIER_CAP`` blocks. Every eviction drops one new
block on Tier 0 (``add_eviction``). When a tier fills, it *carries*: keep the
newest block as-is, collapse the rest to one line each, and stack those lines
as a single new block one tier up. The carry cascades upward like a digit
rolling past 9 — recent history sits low and detailed, old history rides up
reduced to its endpoints.

``compact`` is the pressure valve: when the rebuilt context still overflows,
it forces an *early* carry so the index keeps shrinking until it fits.

Nothing is lost — every line carries a ``seq`` span and the full turns stay in
``conversation_history``; a collapsed line is a zoomed-out view the model
re-expands with one ``ms.sql_query`` over its span.
"""

from __future__ import annotations

from dataclasses import dataclass

# Max blocks a tier holds before it carries up. The carry keeps the newest
# block and folds the other (_TIER_CAP - 1) into one block a tier higher.
_TIER_CAP = 10

# The seam banner closing the index placeholder. It is the LAST thing the model
# reads before the live tail, so the structural signal sits right where the
# confusion happens: the placeholder is a ``user`` message and so is the real
# request that follows it (two consecutive ``user`` turns — the one shape we
# can't avoid, since Anthropic requires the first body message to be ``user``
# and can't take a ``system`` message mid-context). A weak model (GLM/DeepSeek)
# otherwise latches onto a ``⟦headline⟧`` in the map above and answers it. This
# banner is a positional delimiter — the same trick hermes-agent uses with its
# ``[CONTEXT SUMMARY]`` label — telling the model, at the seam, which side is
# archive and which side is the request. Constant text, so it never breaks the
# placeholder's KV-cache prefix.
_LIVE_TURN_BANNER = [
    "",
    "═══════════════ END OF ARCHIVED INDEX ═══════════════",
    "The CURRENT LIVE TURN is the message(s) that follow this one. Answer the "
    "most recent USER message there — NEVER a ⟦headline⟧ listed in the map "
    "above; those are archived, not requests. If your current request is not "
    "visible in the live turn, recall it first (see above); if recall cannot "
    "retrieve it, say so — never answer an older message as if it were the "
    "request.",
]


@dataclass(frozen=True)
class Leaf:
    """One evicted milestone turn: its durable ``seq`` and its ``headline``."""

    seq: int
    headline: str


@dataclass(frozen=True)
class Line:
    """One entry shown inside a block.

    ``seq_lo``/``seq_hi`` is the span the line stands for — a single turn has
    ``lo == hi``; a collapsed child block carries the child's whole span.
    ``head`` is the leftmost headline in that span, ``tail`` the rightmost.
    """

    seq_lo: int
    seq_hi: int
    head: str
    tail: str

    @property
    def text(self) -> str:
        """A single headline, or ``first - last`` for a span."""
        return (
            self.head
            if self.head == self.tail
            else f"{self.head} - {self.tail}"
        )

    @property
    def span(self) -> str:
        return (
            f"seq {self.seq_lo}"
            if self.seq_lo == self.seq_hi
            else f"seq {self.seq_lo}–{self.seq_hi}"
        )


@dataclass
class Block:
    """A run of lines at one tier; its ``seq`` span covers all of them."""

    seq_lo: int
    seq_hi: int
    lines: list[Line]

    @property
    def first(self) -> str:
        """Leftmost (oldest) headline anywhere in the block."""
        return self.lines[0].head

    @property
    def last(self) -> str:
        """Rightmost (newest) headline anywhere in the block."""
        return self.lines[-1].tail


def _collapse(blocks: list[Block]) -> Block:
    """Fold a run of blocks into ONE block: each input becomes a single line
    carrying that input's full span and its endpoint headlines.

    Self-similar: collapsing already-collapsed blocks just keeps the leftmost
    and rightmost headline of each, so a turn, a span, and a span-of-spans all
    reduce the same way — which lets the carry cascade to any depth losslessly.
    """
    return Block(
        seq_lo=min(b.seq_lo for b in blocks),
        seq_hi=max(b.seq_hi for b in blocks),
        lines=[Line(b.seq_lo, b.seq_hi, b.first, b.last) for b in blocks],
    )


class EvictionIndex:
    """A stack of tiers, each a list of blocks oldest-first."""

    def __init__(self, session_id: str, agent_id: str | None = None) -> None:
        self._session_id = session_id
        self._agent_id = agent_id
        self._tiers: list[list[Block]] = []

    @property
    def is_empty(self) -> bool:
        return not any(self._tiers)

    # -- the two moves -------------------------------------------------------

    def add_eviction(
        self,
        leaves: list[Leaf],
        *,
        seq_lo: int,
        seq_hi: int,
        fallback_lines: list[Line] | None = None,
    ) -> None:
        """Drop one eviction onto Tier 0 as a new block, then run the carry.

        ``leaves`` are the evicted milestone turns; ``seq_lo``/``seq_hi`` is
        the *full* evicted span (tool results and unheadlined turns
        included) so a range query recovers everything.

        ``fallback_lines`` stands in for a span that produced no ``leaves`` (a
        legacy 1.x span, or a tool-heavy stretch the model never headlined):
        generated ``Line`` entries — each a seq sub-range with a synthesized
        headline — that tile the span the way real milestones would. Empty or
        ``None`` keeps the bare ``(no milestone)`` marker. The full turns stay
        recoverable by the block's seq span either way.
        """
        lines = [
            Line(lf.seq, lf.seq, lf.headline, lf.headline) for lf in leaves
        ]
        if not lines:
            lines = fallback_lines or [
                Line(seq_lo, seq_hi, "(no milestone)", "(no milestone)"),
            ]
        if not self._tiers:
            self._tiers.append([])
        self._tiers[0].append(Block(seq_lo, seq_hi, lines))
        self._carry(0)

    def _carry(self, k: int) -> None:
        """If tier k is full, keep its newest block, fold the rest up,
        cascade."""
        if len(self._tiers[k]) < _TIER_CAP:
            return
        self._carry_run(k, len(self._tiers[k]) - 1)

    def _carry_run(self, k: int, count: int) -> None:
        """Carry the ``count`` oldest blocks of tier ``k`` up one tier.

        Keep the rest of tier ``k`` as-is, collapse the oldest ``count``
        blocks to one line each, stack them into a single new block on tier
        ``k + 1``, then cascade. Shared by the cap-triggered ``_carry`` and the
        pressure-triggered ``compact``.
        """
        older, kept = self._tiers[k][:count], self._tiers[k][count:]
        self._tiers[k] = kept
        if k + 1 == len(self._tiers):
            self._tiers.append([])
        self._tiers[k + 1].append(_collapse(older))
        self._carry(k + 1)

    def compact(self) -> bool:
        """Force one extra roll-up step under context pressure.

        Fires the same carry *early*: the lowest tier still holding >=2 blocks
        keeps its newest block and folds the rest up. When every tier holds
        <=1 block, the whole index is folded into one block at the top tier —
        so it can always shrink toward a single line. Returns True while it
        shrank, False once a single block remains.
        """
        for k, tier in enumerate(self._tiers):
            if len(tier) >= 2:
                self._carry_run(k, len(tier) - 1)
                return True
        # Every tier holds <=1 block: fold the whole index into one top block.
        # Sort by span so _collapse sees blocks oldest-first.
        all_blocks = sorted(
            (b for tier in self._tiers for b in tier),
            key=lambda b: b.seq_lo,
        )
        if len(all_blocks) >= 2:
            top = len(self._tiers) - 1
            self._tiers = [[] for _ in self._tiers]
            self._tiers[top] = [_collapse(all_blocks)]
            return True
        return False

    # -- serialization (checkpoint) ------------------------------------------

    def to_dict(self) -> dict:
        """Plain-data snapshot of the index, for agent checkpoints."""
        return {
            "session_id": self._session_id,
            "agent_id": self._agent_id,
            "tiers": [
                [
                    {
                        "seq_lo": b.seq_lo,
                        "seq_hi": b.seq_hi,
                        "lines": [
                            [ln.seq_lo, ln.seq_hi, ln.head, ln.tail]
                            for ln in b.lines
                        ],
                    }
                    for b in tier
                ]
                for tier in self._tiers
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvictionIndex":
        idx = cls(
            session_id=data.get("session_id", ""),
            agent_id=data.get("agent_id"),
        )
        # Older checkpoints serialized this under "levels"; read both.
        tiers = data.get("tiers", data.get("levels", []))
        for tier in tiers:
            idx._tiers.append(
                [
                    Block(
                        seq_lo=b["seq_lo"],
                        seq_hi=b["seq_hi"],
                        lines=[
                            Line(lo, hi, head, tail)
                            for lo, hi, head, tail in b["lines"]
                        ],
                    )
                    for b in tier
                ],
            )
        return idx

    # -- rendering -----------------------------------------------------------

    def render(self) -> str:
        """The single placeholder message: the whole map + how to expand it.

        Tiers print oldest-first (highest tier on top) down to ``Tier 0`` (the
        most recently compressed) at the bottom, mirroring the live tail below.

        KV-cache safe: the intro + recall block and the ``Tier N`` banners are
        constant, and a new eviction only appends a block to the bottom of
        ``Tier 0`` — so every byte above it is unchanged and the cache holds up
        to the first new token. (A carry reshapes upper tiers and breaks it
        then, which is inherent to the roll-up.)
        """
        out = [
            "<system-info>",
            "[context compressed] The turns below were evicted from the live "
            "window but remain durable in conversation_history. This is an "
            "ARCHIVED MAP for reference only — NOT the live conversation. "
            "Read it top (oldest) to bottom (most recently compressed); the "
            "live "
            "turns follow after the banner at the end. Each '·' line is a seq "
            "span you can re-expand.",
            "",
            "Re-expand a span with the recall_history tool: "
            'recall_history(op="expand", lo, hi) for the full turns (seq is '
            "a globally-unique address, so a span needs no other filter); "
            'op="search" finds a seq by keywords. For advanced recall '
            "(sessions, custom SQL) use a more advanced Python recall tool "
            "if one is available to you.",
            "",
        ]
        out.extend(self._tier_lines())
        # The seam banner closes the block right before the live tail — the
        # structural anchor that keeps the model answering the request below,
        # not a headline in the map above.
        out.extend(_LIVE_TURN_BANNER)
        out.append("</system-info>")
        return "\n".join(out)

    def describe(self) -> str:
        """The tier/span map without the ``render`` preamble — for the
        user-facing ``/compact`` reply. Empty string if nothing is indexed."""
        return "\n".join(self._tier_lines())

    def _tier_lines(self) -> list[str]:
        """Tiers oldest-first, each block's seq span and per-line headlines."""
        out: list[str] = []
        for k in range(len(self._tiers) - 1, -1, -1):
            tier = self._tiers[k]
            if not tier:
                continue
            label = "recently compressed" if k == 0 else "older msgs"
            out.append(f"===== Tier {k} ({label}) =====")
            for block in tier:
                out.append(f"  [seq {block.seq_lo}–{block.seq_hi}]")
                for ln in block.lines:
                    out.append(f"    · {ln.span}  ⟦ {ln.text} ⟧")
        return out
