# -*- coding: utf-8 -*-
"""Context compaction: budget semantics without re-serializing the world.

Review of the merged #248 code on a live deploy: py-spy caught the event-loop
thread holding the GIL inside ``json_bytes`` while ``plan_history_compaction``
re-serialized the *entire* history on every loop iteration -- O(N) full passes
over a structure that reaches hundreds of megabytes on the field's largest
session, which parked every HTTP request (home page included) behind it for
minutes. The loop now carries serialized-size and token totals incrementally;
these tests pin both the complexity bound and the budget semantics.
"""

from __future__ import annotations

import json

import pytest

from services.file_agent_runtime import model_context
from services.file_agent_runtime.model_context import (
    _media_aware_bytes,
    estimate_input_tokens,
    plan_history_compaction,
)

pytestmark = pytest.mark.unit


def _tool_turn(seq: int, filler: str) -> dict:
    return {
        "messageSeq": seq,
        "role": "tool",
        "source": "runtime_action_result",
        "content": [{"type": "text", "text": f"tool output {seq} {filler}"}],
        "metadata": {"toolName": "read_project"},
    }


def _human_turn(seq: int, text: str) -> dict:
    return {
        "messageSeq": seq,
        "role": "user",
        "source": "user",
        "content": [{"type": "text", "text": text}],
        "metadata": {},
    }


def _snapshot_turn(seq: int) -> dict:
    payload = {
        "project": {"project_id": "project-1", "generation": seq},
        "generation": seq,
        "etag": f"sha256:{seq:064x}",
    }
    return {
        "messageSeq": seq,
        "role": "tool",
        "source": "runtime_action_result",
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)},
        ],
        "metadata": {"toolName": "read_project"},
    }


def _seqs(compacted: list) -> list[int]:
    """Message seqs of a compacted view, minus the elision summary.

    The returned view is ``[elision, *survivors]``: the leading system
    message describes the archive and carries no ``messageSeq``.
    """

    return [
        item["messageSeq"]
        for item in compacted
        if item is not None and item.get("source") != "context_compaction"
    ]


def test_compaction_does_not_reserialize_the_whole_history_per_turn(
    monkeypatch,
) -> None:
    """The budget check must not walk the whole list on every iteration.

    The old loop called ``json_bytes(result)`` (and, when the byte gate
    passed, ``estimate_input_tokens(result)``) inside the archive loop, so
    archiving K turns cost K full serializations of the entire history.
    With incremental accounting the only whole-list serializations left are
    the up-front budget probe and the initial total: two, constant in N.
    """

    calls = {"whole_list": 0}
    real_json_bytes = model_context.json_bytes

    def spy(value):
        if isinstance(value, list):
            calls["whole_list"] += 1
        return real_json_bytes(value)

    monkeypatch.setattr(model_context, "json_bytes", spy)

    # Forty fat tool turns: far over the 128 KiB history budget, so the
    # loop must archive most of them -- exactly the shape that used to
    # serialize the whole list once per archived turn.
    history = [_human_turn(1, "把第三集改成雨夜")]
    history += [_tool_turn(seq, "x" * 8192) for seq in range(2, 42)]
    history.append(_snapshot_turn(42))

    compacted, archived = plan_history_compaction(history)

    assert archived, "the over-budget history must archive something"
    assert calls["whole_list"] <= 2, (
        f"the archive loop re-serialized the whole history "
        f"{calls['whole_list']} times; incremental accounting allows 2"
    )
    # And the result still honours the budget it was compacted against.
    assert (
        _media_aware_bytes(compacted, budget_bytes=model_context.HISTORY_BYTES)
        <= model_context.HISTORY_BYTES
    )


def test_compaction_keeps_human_goals_and_the_newest_snapshot() -> None:
    history = [
        _human_turn(1, "目标：全片保持雨夜基调"),
        _tool_turn(2, "a" * 4096),
        _tool_turn(3, "b" * 4096),
        _human_turn(4, "反馈：第二幕再暗一点"),
        _tool_turn(5, "c" * 4096),
        _snapshot_turn(6),
        _tool_turn(7, "d" * 4096),
    ]
    budget = 12 * 1024
    compacted, archived = plan_history_compaction(
        history,
        max_bytes=budget,
    )

    kept_seqs = _seqs(compacted)
    # Human turns and the newest snapshot survive no matter how tight the
    # budget gets; only automated turns are archivable.
    assert 1 in kept_seqs
    assert 4 in kept_seqs
    assert 6 in kept_seqs
    assert archived
    archived_seqs = {entry["seq"] for entry in archived}
    assert archived_seqs <= {2, 3, 5, 7}
    # The returned view keeps the survivors in their original order:
    # archiving nulls slots in place internally, then the nulls are
    # dropped on the way out (upstream contract, unchanged).
    assert compacted[0].get("source") == "context_compaction"
    assert all(item is not None for item in compacted)
    assert kept_seqs == sorted(kept_seqs)
    assert kept_seqs[0] == 1
    assert kept_seqs[-1] == 7


def test_token_budget_is_accounted_incrementally_too() -> None:
    """A token cap alone must still drive archiving, without re-walking."""

    history = [_human_turn(1, "目标")]
    history += [
        _tool_turn(seq, "密度很高的中文内容" * 200) for seq in range(2, 22)
    ]
    full_tokens = estimate_input_tokens(history)
    cap = full_tokens // 4

    compacted, archived = plan_history_compaction(
        history,
        max_bytes=8 * 1024 * 1024,  # bytes never bind; tokens do
        max_tokens=cap,
    )

    assert archived, "the token cap must archive automated turns"
    # The budget gate runs before the elision summary is appended (that is
    # upstream semantics, unchanged by the incremental accounting), so the
    # cap is honoured by the archived view, not by view + summary.
    view = [
        item
        for item in compacted
        if item is not None and (item.get("source") != "context_compaction")
    ]
    assert estimate_input_tokens(view) <= cap
    assert 1 in _seqs(compacted)


def test_under_budget_history_passes_through_untouched() -> None:
    history = [_human_turn(1, "你好"), _tool_turn(2, "small")]
    compacted, archived = plan_history_compaction(history)
    assert archived == []
    assert compacted == history


def _legacy_plan(history, *, max_bytes, max_tokens=None):
    """The forward-scanning loop this rewrite replaced, kept as the oracle.

    It re-measures the whole view on every iteration, which is exactly the
    cost the rewrite removes; the cut it produces is the contract that must
    not move.
    """

    from copy import deepcopy

    result = deepcopy(history)
    latest_snapshot = None
    for index, item in enumerate(result):
        item["metadata"] = {
            key: value
            for key, value in (item.get("metadata") or {}).items()
            if key in model_context._COMPACTION_METADATA_KEYS
        }
        for part in item.get("content") or []:
            if isinstance(part, dict) and model_context._snapshot_content(
                part.get("text")
            ):
                latest_snapshot = index
    if model_context._media_aware_bytes(
        result, budget_bytes=max_bytes
    ) <= max_bytes and (
        max_tokens is None
        or model_context.estimate_input_tokens(result) <= max_tokens
    ):
        return result, []
    removed = 0
    archived = []
    relief = model_context._inline_media_relief(result, budget_bytes=max_bytes)
    total_bytes = model_context.json_bytes(result)
    total_tokens = (
        None
        if max_tokens is None
        else model_context.estimate_input_tokens(result)
    )
    for index, item in enumerate(result):
        human_input = (
            item.get("role") == "user"
            and item.get("source")
            not in model_context._AUTOMATED_HISTORY_SOURCES
        )
        if human_input or index == latest_snapshot:
            continue
        if total_bytes - relief <= max_bytes - 256 and (
            total_tokens is None or total_tokens <= max_tokens
        ):
            break
        seq = item.get("messageSeq")
        archived.append(
            {
                "seq": seq if isinstance(seq, int) else None,
                "role": item.get("role"),
                "source": item.get("source"),
                "content": item.get("content"),
            },
        )
        item_bytes = model_context.json_bytes(item)
        item_tokens = (
            0
            if total_tokens is None
            else model_context.estimate_input_tokens(item)
        )
        result[index] = None
        total_bytes -= item_bytes - 4
        relief -= model_context._inline_media_relief(
            item, budget_bytes=max_bytes
        )
        if total_tokens is not None:
            total_tokens -= item_tokens
        removed += 1
    elision = {
        "role": "system",
        "source": "context_compaction",
        "elidedMessageCount": removed,
    }
    history_map, seq_lo, seq_hi = model_context._render_archived_index(
        archived
    )
    if history_map:
        elision["archivedHistoryMap"] = history_map
        elision["recoverableSeqRange"] = [seq_lo, seq_hi]
    return [elision, *(item for item in result if item is not None)], archived


def test_the_cut_is_identical_to_the_forward_scan_it_replaced() -> None:
    """Same archived set, same view, across randomised history shapes.

    The rewrite only changes *when* a turn is serialized, so every budget
    boundary must land where the old loop put it -- otherwise context would
    silently be dropped or kept differently after the perf fix.
    """

    import random

    rng = random.Random(20261113)
    for trial in range(40):
        history = []
        seq = 1
        history.append(_human_turn(seq, "目标：全片保持雨夜基调"))
        for _ in range(rng.randint(3, 24)):
            seq += 1
            roll = rng.random()
            if roll < 0.2:
                history.append(
                    _human_turn(seq, "补充约束 " + "雨" * rng.randint(1, 200))
                )
            elif roll < 0.28:
                history.append(_snapshot_turn(seq))
            elif roll < 0.36:
                history.append(
                    {
                        "messageSeq": seq,
                        "role": "user",
                        "source": "review",
                        "content": [
                            {
                                "type": "text",
                                "text": "旧审阅 " + "r" * rng.randint(1, 500),
                            }
                        ],
                        "metadata": {},
                    }
                )
            else:
                history.append(
                    _tool_turn(seq, "x" * rng.choice([8, 64, 512, 4096]))
                )
        budget = rng.choice([1024, 4096, 16384, 65536])
        tokens = rng.choice([None, 400, 4000])

        new_view, new_archived = plan_history_compaction(
            history,
            max_bytes=budget,
            max_tokens=tokens,
        )
        old_view, old_archived = _legacy_plan(
            history,
            max_bytes=budget,
            max_tokens=tokens,
        )
        assert [item["seq"] for item in new_archived] == [
            item["seq"] for item in old_archived
        ], f"trial {trial}: archived set drifted (budget={budget})"
        assert new_view == old_view, f"trial {trial}: view drifted"


def test_only_the_budget_is_measured_not_the_whole_history(
    monkeypatch,
) -> None:
    """Serialized bytes stay proportional to the budget, not to the history.

    The old loop serialized every remaining turn on every iteration; even a
    single-pass rewrite would still serialize all ~640 MB of the field's
    largest conversation per model turn, holding the GIL while the home page
    waited. The probe now stops as soon as the view cannot fit, and turns
    older than the cut are never serialized -- so a 40 MB history must cost
    kilobytes, not tens of megabytes.
    """

    serialized = {"bytes": 0}
    real_json_bytes = model_context.json_bytes

    def spy(value):
        if isinstance(value, dict):
            serialized["bytes"] += real_json_bytes(value)
        return real_json_bytes(value)

    monkeypatch.setattr(model_context, "json_bytes", spy)

    history = [_human_turn(1, "目标")] + [
        _tool_turn(seq, "y" * 102_400) for seq in range(2, 402)
    ]
    total = real_json_bytes(history)

    compacted, archived = plan_history_compaction(history)

    assert archived, "the over-budget history must archive something"
    # Only the handful of turns around the cut is ever serialized: the probe
    # stops once the view cannot fit and the cut walks in a few turns from
    # the newest end. A constant number of turns, whatever the history size.
    assert serialized["bytes"] <= 8 * model_context.HISTORY_BYTES, (
        f"measured {serialized['bytes'] / 1e6:.1f} MB of a "
        f"{total / 1e6:.1f} MB history -- the cut must be found without "
        "serializing turns older than it"
    )
    # And the view it returns still honours the budget.
    assert (
        model_context._media_aware_bytes(
            compacted, budget_bytes=model_context.HISTORY_BYTES
        )
        <= model_context.HISTORY_BYTES
    )
