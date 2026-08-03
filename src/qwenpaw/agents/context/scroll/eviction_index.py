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

Index roll-up is driven only by the per-tier block cap. Context pressure does
not force an early carry, so recent index detail is stable until a tier fills.

Nothing is lost — every line carries a ``seq`` span and the full turns stay in
``conversation_history``; a collapsed line is a zoomed-out view the model
re-expands with one ``ms.sql_query`` over its span.
"""

from __future__ import annotations

from dataclasses import dataclass

# Max blocks a tier holds before it carries up. The carry keeps the newest
# block and folds the other (_TIER_CAP - 1) into one block a tier higher.
_TIER_CAP = 10

# A headline may remain up to 2,000 characters in durable state, but the
# model-facing index is only a retrieval directory. Keep one rendered
# headline compact; the exact turn remains addressable by its seq.
_HEADLINE_VIEW_CHARS = 400

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
_ARCHIVED_INDEX_END = [
    "",
    "═══════════════ END OF ARCHIVED INDEX ═══════════════",
]

_LIVE_TURN_BANNER = [
    "",
    "The CURRENT LIVE TURN is the message(s) that follow this one. Answer the "
    "most recent USER message there — NEVER a ⟦headline⟧ listed in the map "
    "above; those are archived, not requests. If your current request is not "
    "visible in the live turn, recall it first (see above); if recall cannot "
    "retrieve it, say so — never answer an older message as if it were the "
    "request.",
]


def render_live_turn_banner() -> str:
    """Render the stable seam immediately before the live conversation."""
    return "\n".join(_LIVE_TURN_BANNER)


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
    ) -> None:
        """Drop one eviction onto Tier 0 as a new block, then run the carry.

        ``leaves`` are the evicted milestone turns; ``seq_lo``/``seq_hi`` is
        the *full* evicted span (tool results and unheadlined turns
        included) so a range query recovers everything.

        A span with no ``leaves`` (for example a legacy conversation or a
        routine stretch with no durable state change) gets a bare
        ``(no milestone)`` marker. Its full turns remain recoverable by the
        block's seq span.
        """
        lines = [
            Line(lf.seq, lf.seq, lf.headline, lf.headline) for lf in leaves
        ]
        if not lines:
            lines = [
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
        cap-triggered carry.
        """
        older, kept = self._tiers[k][:count], self._tiers[k][count:]
        self._tiers[k] = kept
        if k + 1 == len(self._tiers):
            self._tiers.append([])
        self._tiers[k + 1].append(_collapse(older))
        self._carry(k + 1)

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

    def render(
        self,
        *,
        include_envelope: bool = True,
        include_live_banner: bool = True,
        detail_char_budget: int | None = None,
    ) -> str:
        """The single placeholder message: the whole map + how to expand it.

        Tiers print oldest-first (highest tier on top) down to ``Tier 0`` (the
        most recently compressed) at the bottom, mirroring the live tail below.

        ``detail_char_budget`` bounds only the tier/block directory, not the
        stable preamble or seam banners. When supplied, individual headline
        views are shortened first, then blocks collapse to endpoint lines, and
        finally the whole directory becomes one recallable global seq span.
        Durable state and :meth:`describe` remain lossless.

        KV-cache safe: the intro + recall block and the ``Tier N`` banners are
        constant, and a new eviction only appends a block to the bottom of
        ``Tier 0`` — so every byte above it is unchanged and the cache holds up
        to the first new token. (A carry reshapes upper tiers and breaks it
        then, which is inherent to the roll-up.)
        """
        out = [
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
        out.extend(
            self._tier_lines(detail_char_budget=detail_char_budget),
        )
        out.extend(_ARCHIVED_INDEX_END)
        if include_live_banner:
            # With no continuation summary, the seam closes the block right
            # before the live tail. The manager can defer it until after task
            # state so that task state remains closest to the live request.
            out.extend(_LIVE_TURN_BANNER)
        body = "\n".join(out)
        return (
            f"<system-info>\n{body}\n</system-info>"
            if include_envelope
            else body
        )

    def describe(self) -> str:
        """The tier/span map without the ``render`` preamble — for the
        user-facing ``/compact`` reply. Empty string if nothing is indexed."""
        return "\n".join(self._tier_lines())

    @staticmethod
    def _bounded_headline(text: str, limit: int) -> str:
        """Shorten a model-visible headline without changing durable state."""
        if len(text) <= limit:
            return text
        return text[: max(1, limit - 3)].rstrip() + "..."

    @staticmethod
    def _lines_size(lines: list[str]) -> int:
        """Rendered character count including newline separators."""
        return len("\n".join(lines))

    @classmethod
    def _bounded_line_text(cls, line: Line, limit: int) -> str:
        """Keep both endpoint headlines visible for a collapsed line."""
        if line.head == line.tail:
            return cls._bounded_headline(line.head, limit)
        endpoint_limit = max(1, limit // 2)
        return (
            f"{cls._bounded_headline(line.head, endpoint_limit)} - "
            f"{cls._bounded_headline(line.tail, endpoint_limit)}"
        )

    def _tier_lines(
        self,
        *,
        detail_char_budget: int | None = None,
    ) -> list[str]:
        """Render a lossless or budgeted oldest-first tier directory."""
        headline_limit = (
            _HEADLINE_VIEW_CHARS if detail_char_budget is not None else None
        )
        expanded = self._expanded_tier_lines(headline_limit=headline_limit)
        if (
            detail_char_budget is None
            or self._lines_size(expanded) <= detail_char_budget
        ):
            return expanded

        endpoints = self._endpoint_tier_lines()
        if self._lines_size(endpoints) <= detail_char_budget:
            return endpoints
        return self._global_span_lines()

    def _expanded_tier_lines(
        self,
        *,
        headline_limit: int | None,
    ) -> list[str]:
        """Every block and headline, optionally shortened for model view."""
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
                    text = ln.text
                    if headline_limit is not None:
                        text = self._bounded_line_text(ln, headline_limit)
                    out.append(f"    · {ln.span}  ⟦ {text} ⟧")
        return out

    def _endpoint_tier_lines(self) -> list[str]:
        """One bounded endpoint line per block, preserving every block span."""
        out: list[str] = []
        endpoint_limit = _HEADLINE_VIEW_CHARS // 2
        for k in range(len(self._tiers) - 1, -1, -1):
            tier = self._tiers[k]
            if not tier:
                continue
            label = "recently compressed" if k == 0 else "older msgs"
            out.append(f"===== Tier {k} ({label}; details folded) =====")
            for block in tier:
                head = self._bounded_headline(block.first, endpoint_limit)
                tail = self._bounded_headline(block.last, endpoint_limit)
                text = head if head == tail else f"{head} - {tail}"
                span = (
                    f"seq {block.seq_lo}"
                    if block.seq_lo == block.seq_hi
                    else f"seq {block.seq_lo}–{block.seq_hi}"
                )
                out.append(f"  · {span}  ⟦ {text} ⟧")
        return out

    def _global_span_lines(self) -> list[str]:
        """Last-resort bounded directory retaining one exact recall span."""
        blocks = [block for tier in self._tiers for block in tier]
        if not blocks:
            return []
        lo = min(block.seq_lo for block in blocks)
        hi = max(block.seq_hi for block in blocks)
        return [
            "===== Archived index (details folded to fit context) =====",
            f"  [seq {lo}–{hi}]",
            "    · Index details omitted; recover this span with "
            f'recall_history(op="expand", lo={lo}, hi={hi})',
        ]
