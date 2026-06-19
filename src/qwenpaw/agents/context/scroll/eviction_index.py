"""The eviction index — an in-context, level-capped odometer of evicted turns.

The whole index lives in the prompt as ONE placeholder, so the model always
*sees the map* of what it evicted. The structure is a stack of levels:

    L0 (bottom)  the newest evictions; each block lists its turns in full.
    Lk (k >= 1)  older history, carried up and squeezed to span endpoints.

Each level holds at most ``_LEVEL_CAP`` blocks. Every eviction drops one new
block on L0 (``add_eviction``). When a level fills, it *carries*: keep the
newest block as-is, collapse the rest to one line each, and stack those lines
as a single new block one level up. The carry cascades upward like a digit
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

# Max blocks a level holds before it carries up. The carry keeps the newest
# block and folds the other (_LEVEL_CAP - 1) into one block a level higher.
_LEVEL_CAP = 10


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
        return self.head if self.head == self.tail else f"{self.head} - {self.tail}"

    @property
    def span(self) -> str:
        return (
            f"seq {self.seq_lo}"
            if self.seq_lo == self.seq_hi
            else f"seq {self.seq_lo}–{self.seq_hi}"
        )


@dataclass
class Block:
    """A run of lines at one level; its ``seq`` span covers all of them."""

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
    """A stack of levels, each a list of blocks oldest-first."""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._levels: list[list[Block]] = []

    @property
    def is_empty(self) -> bool:
        return not any(self._levels)

    # -- the two moves -------------------------------------------------------

    def add_eviction(
        self,
        leaves: list[Leaf],
        *,
        seq_lo: int,
        seq_hi: int,
        n_turns: int | None = None,
    ) -> None:
        """Drop one eviction onto L0 as a new block, then run the carry.

        ``leaves`` are the evicted milestone turns; ``seq_lo``/``seq_hi`` is the
        *full* evicted span (tool results and unheadlined turns included) so a
        range query recovers everything.
        """
        lines = [Line(lf.seq, lf.seq, lf.headline, lf.headline) for lf in leaves]
        if not lines:
            # An eviction with no headlined turns is still addressable by span.
            lines = [Line(seq_lo, seq_hi, "(no milestone)", "(no milestone)")]
        if not self._levels:
            self._levels.append([])
        self._levels[0].append(Block(seq_lo, seq_hi, lines))
        self._carry(0)

    def _carry(self, k: int) -> None:
        """If level k is full, keep its newest block, fold the rest up, cascade."""
        if len(self._levels[k]) < _LEVEL_CAP:
            return
        self._carry_run(k, len(self._levels[k]) - 1)

    def _carry_run(self, k: int, count: int) -> None:
        """Carry the ``count`` oldest blocks of level ``k`` up one level.

        Keep the rest of level ``k`` as-is, collapse the oldest ``count``
        blocks to one line each, stack them into a single new block on level
        ``k + 1``, then cascade. Shared by the cap-triggered ``_carry`` and the
        pressure-triggered ``compact``.
        """
        older, kept = self._levels[k][:count], self._levels[k][count:]
        self._levels[k] = kept
        if k + 1 == len(self._levels):
            self._levels.append([])
        self._levels[k + 1].append(_collapse(older))
        self._carry(k + 1)

    def compact(self) -> bool:
        """Force one extra roll-up step under context pressure.

        Fires the same carry *early*: the lowest level still holding >=2 blocks
        keeps its newest block and folds the rest up. When every level holds
        <=1 block, the whole index is folded into one block at the top level —
        so it can always shrink toward a single line. Returns True while it
        shrank, False once a single block remains.
        """
        for k in range(len(self._levels)):
            if len(self._levels[k]) >= 2:
                self._carry_run(k, len(self._levels[k]) - 1)
                return True
        # Every level holds <=1 block: fold the whole index into one top block.
        # Sort by span so _collapse sees blocks oldest-first.
        all_blocks = sorted(
            (b for level in self._levels for b in level),
            key=lambda b: b.seq_lo,
        )
        if len(all_blocks) >= 2:
            top = len(self._levels) - 1
            self._levels = [[] for _ in self._levels]
            self._levels[top] = [_collapse(all_blocks)]
            return True
        return False

    # -- serialization (checkpoint) ------------------------------------------

    def to_dict(self) -> dict:
        """Plain-data snapshot of the index, for agent checkpoints."""
        return {
            "session_id": self._session_id,
            "levels": [
                [
                    {
                        "seq_lo": b.seq_lo,
                        "seq_hi": b.seq_hi,
                        "lines": [
                            [ln.seq_lo, ln.seq_hi, ln.head, ln.tail]
                            for ln in b.lines
                        ],
                    }
                    for b in level
                ]
                for level in self._levels
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvictionIndex":
        idx = cls(session_id=data.get("session_id", ""))
        for level in data.get("levels", []):
            idx._levels.append([
                Block(
                    seq_lo=b["seq_lo"],
                    seq_hi=b["seq_hi"],
                    lines=[
                        Line(lo, hi, head, tail)
                        for lo, hi, head, tail in b["lines"]
                    ],
                )
                for b in level
            ])
        return idx

    # -- rendering -----------------------------------------------------------

    def render(self) -> str:
        """The single placeholder message: the whole map + how to expand it.

        Levels print coarsest-first (highest level on top, L0 at the bottom),
        so the model reads oldest -> newest, top -> bottom.
        """
        lines = [
            "<system-info>[context compressed] Evicted turns are durable; this "
            "is their index — newest evictions are listed per turn at the "
            "bottom, older spans are carried up and shown as endpoint pairs. "
            "Expand any span inside execute_python.",
        ]
        for k in range(len(self._levels) - 1, -1, -1):
            for block in self._levels[k]:
                lines.append(f"[L{k}] seq {block.seq_lo}–{block.seq_hi}")
                for ln in block.lines:
                    lines.append(f"  · {ln.span}  ⟦ {ln.text} ⟧")
        lines += [
            "Recall (inside execute_python):",
            "  • expand a span to its per-turn headlines: ms.sql_query("
            "\"SELECT seq, headline FROM hist.conversation_history WHERE "
            f"session_id='{self._session_id}' AND seq BETWEEN <lo> AND <hi> "
            "AND headline IS NOT NULL ORDER BY seq\")",
            "  • a span's (or one turn's) full content: ms.sql_query(\"SELECT "
            "seq, kind, role, content FROM hist.conversation_history WHERE "
            f"session_id='{self._session_id}' AND seq BETWEEN <lo> AND <hi> "
            "ORDER BY seq\")",
            "  • keyword search (FTS5): ms.sql_query(\"SELECT seq, kind, "
            "content FROM hist.conversation_history WHERE seq IN (SELECT rowid "
            "FROM hist.conversation_history_fts('YOUR KEYWORDS')) ORDER BY "
            "seq\")",
            "</system-info>",
        ]
        return "\n".join(lines)
