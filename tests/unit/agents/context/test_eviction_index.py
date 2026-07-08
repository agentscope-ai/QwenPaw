# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""Unit tests for the in-context eviction index (pure logic, no DB).

Covers the two moves (``add_eviction`` + carry, ``compact``), the lossless
span/headline bookkeeping, the checkpoint round-trip, and the rendered map.
"""

from qwenpaw.agents.context.scroll.eviction_index import (
    EvictionIndex,
    Leaf,
    _TIER_CAP,
    _collapse,
    Block,
    Line,
)


def _add(idx: EvictionIndex, seq: int, headline: str = "") -> None:
    """Drop one single-turn eviction at ``seq`` onto the index."""
    leaves = [Leaf(seq=seq, headline=headline)] if headline else []
    idx.add_eviction(leaves, seq_lo=seq, seq_hi=seq)


def test_empty_index():
    idx = EvictionIndex(session_id="s")
    assert idx.is_empty
    # render still produces the constant recall preamble.
    assert "recall_history" in idx.render()


def test_single_eviction_is_addressable():
    idx = EvictionIndex(session_id="s")
    _add(idx, 5, "did a thing")
    assert not idx.is_empty
    out = idx.render()
    assert "did a thing" in out
    assert "seq 5" in out


def test_render_closes_with_live_turn_banner():
    """The seam banner is the structural anchor: it must be the LAST thing in
    the placeholder (after every tier), so it sits right before the live tail —
    telling the model the request is below, not a headline in the map above."""
    idx = EvictionIndex(session_id="s")
    _add(idx, 5, "old headline")
    out = idx.render()
    assert "CURRENT LIVE TURN" in out
    assert "END OF ARCHIVED INDEX" in out
    # The banner comes after the archived turns, not before them.
    assert out.index("old headline") < out.index("CURRENT LIVE TURN")
    # And it stays inside the system-info envelope, last before the close tag.
    assert out.index("CURRENT LIVE TURN") < out.index("</system-info>")


def test_describe_omits_the_model_facing_banner():
    """``describe()`` feeds the user-facing /compact reply — it should show the
    tier/span map only, not the model-only 'answer THIS' banner."""
    idx = EvictionIndex(session_id="s")
    _add(idx, 5, "old headline")
    described = idx.describe()
    assert "old headline" in described
    assert "CURRENT LIVE TURN" not in described


def test_eviction_without_headline_still_has_a_span():
    idx = EvictionIndex(session_id="s")
    idx.add_eviction([], seq_lo=10, seq_hi=14)
    out = idx.render()
    assert "(no milestone)" in out
    assert "seq 10" in out and "14" in out


def test_carry_rolls_up_when_a_level_fills():
    idx = EvictionIndex(session_id="s")
    # One short of the cap: no carry yet, all blocks on level 0.
    for i in range(1, _TIER_CAP):
        _add(idx, i, f"h{i}")
    assert len(idx._tiers) == 1
    assert len(idx._tiers[0]) == _TIER_CAP - 1

    # The cap-th eviction triggers a carry: keep the newest block, fold the
    # older (_TIER_CAP - 1) into one block one level up.
    _add(idx, _TIER_CAP, f"h{_TIER_CAP}")
    assert len(idx._tiers) == 2
    assert len(idx._tiers[0]) == 1  # newest block kept
    assert len(idx._tiers[1]) == 1  # the folded run


def test_carry_preserves_the_full_seq_span_losslessly():
    idx = EvictionIndex(session_id="s")
    for i in range(1, _TIER_CAP + 1):
        _add(idx, i, f"h{i}")
    spans = [(b.seq_lo, b.seq_hi) for level in idx._tiers for b in level]
    lo = min(s[0] for s in spans)
    hi = max(s[1] for s in spans)
    assert (lo, hi) == (1, _TIER_CAP)  # nothing dropped from the span


def test_compact_shrinks_then_reports_done():
    idx = EvictionIndex(session_id="s")
    for i in range(1, 6):
        _add(idx, i, f"h{i}")
    # Five blocks on level 0 → compact folds four up, keeps the newest.
    assert idx.compact() is True
    assert len(idx._tiers[0]) == 1
    # Keep compacting until a single block remains; it must terminate and
    # then report False.
    guard = 0
    while idx.compact():
        guard += 1
        assert guard < 50, "compact() failed to converge"
    # Once it returns False, the whole index is a single block.
    blocks = [b for level in idx._tiers for b in level]
    assert len(blocks) == 1
    # ...still spanning the full evicted range.
    assert (blocks[0].seq_lo, blocks[0].seq_hi) == (1, 5)


def test_compact_on_single_block_is_a_noop_false():
    idx = EvictionIndex(session_id="s")
    _add(idx, 1, "only")
    assert idx.compact() is False


def test_checkpoint_round_trip_is_identical():
    idx = EvictionIndex(session_id="sess", agent_id="ag")
    for i in range(1, _TIER_CAP + 3):  # force at least one carry
        _add(idx, i, f"h{i}")
    snap = idx.to_dict()
    restored = EvictionIndex.from_dict(snap)
    assert restored.to_dict() == snap
    assert restored.render() == idx.render()
    assert restored._agent_id == "ag"


def test_collapse_keeps_endpoint_headlines():
    blocks = [
        Block(
            seq_lo=1,
            seq_hi=2,
            lines=[Line(1, 1, "a", "a"), Line(2, 2, "b", "b")],
        ),
        Block(
            seq_lo=3,
            seq_hi=4,
            lines=[Line(3, 3, "c", "c"), Line(4, 4, "d", "d")],
        ),
    ]
    folded = _collapse(blocks)
    assert (folded.seq_lo, folded.seq_hi) == (1, 4)
    # Each input block becomes one line carrying its leftmost/rightmost head.
    assert [(ln.head, ln.tail) for ln in folded.lines] == [
        ("a", "b"),
        ("c", "d"),
    ]


def test_render_lists_tiers_oldest_on_top():
    idx = EvictionIndex(session_id="s")
    for i in range(1, _TIER_CAP + 2):  # produces tier 0 and tier 1
        _add(idx, i, f"h{i}")
    out = idx.render()
    assert out.index("Tier 1") < out.index("Tier 0")
