# -*- coding: utf-8 -*-
"""Public wording of ``summarize_workgraph_results`` (#7720 finding #1).

The agent-facing summary must name the prompt-sync gate with public,
actionable wording and must never leak internal ``missing`` refs.
"""

from __future__ import annotations

from services.file_agent_runtime.workgraph_execution import (
    summarize_workgraph_results,
)


def _gated(prompt_sync: bool, missing: list[str]) -> dict:
    item = {
        "nodeId": "storyboard:e1",
        "targetRef": "element:e1",
        "status": "BLOCKED",
        "reason": "GATED",
        "missing": missing,
    }
    if prompt_sync:
        item["promptSyncRequired"] = True
    return item


def test_summary_names_prompt_sync_gate_without_internal_refs() -> None:
    summary = summarize_workgraph_results(
        [_gated(True, ["visual:scene:home:var:day"])],
    )
    assert "尚未启动制作" in summary
    assert "1 项需要先同步分镜/提示词内容" in summary
    assert "保留现有内容并生成" in summary
    # The gate is named publicly; the internal dependency ref never leaks.
    assert "visual:scene:home:var:day" not in summary
    # No leftover generic bucket when every item is prompt-sync gated.
    assert "制作条件尚未满足" not in summary


def test_summary_splits_review_prompt_sync_and_other() -> None:
    summary = summarize_workgraph_results(
        [
            {"status": "BLOCKED", "reason": "WAITING_REVIEW"},
            _gated(True, ["分镜内容与提示词待同步"]),
            _gated(False, ["visual:scene:x"]),
        ],
    )
    assert "1 项需要先完成现有审阅" in summary
    assert "1 项需要先同步分镜/提示词内容" in summary
    assert "1 项制作条件尚未满足" in summary
    assert "visual:scene:x" not in summary


def test_summary_all_review_wording_unchanged() -> None:
    summary = summarize_workgraph_results(
        [
            {"status": "BLOCKED", "reason": "WAITING_REVIEW"},
            {"status": "BLOCKED", "reason": "WAITING_REVIEW"},
        ],
    )
    assert "2 项需要先完成现有审阅" in summary
    assert "同步分镜/提示词" not in summary
    assert "制作条件尚未满足" not in summary


def test_summary_mixed_branch_names_prompt_sync() -> None:
    summary = summarize_workgraph_results(
        [
            {"status": "SUCCEEDED", "taskId": "task-1"},
            _gated(True, ["分镜内容与提示词待同步"]),
        ],
    )
    # Not every item is a known pre-dispatch blocker, so the mixed wording
    # (需先同步, no 尚未启动制作 prefix) applies.
    assert "尚未启动制作" not in summary
    assert "已完成制作 1 项" in summary
    assert "1 项需先同步分镜/提示词内容，尚未开始" in summary
    assert "制作条件尚未满足" not in summary


def test_summary_waiting_review_with_sync_flag_not_double_counted() -> None:
    # P1 regression: a creative review outranks the prompt-sync gate, so the
    # same node must never count as both (that once yielded "-1 项").
    summary = summarize_workgraph_results(
        [
            {
                "status": "BLOCKED",
                "reason": "WAITING_REVIEW",
                "promptSyncRequired": True,
            },
        ],
    )
    assert "1 项需要先完成现有审阅" in summary
    assert "同步分镜/提示词" not in summary
    assert "制作条件尚未满足" not in summary
    assert "-1" not in summary


def test_summary_mixed_branch_review_sync_not_double_counted() -> None:
    # Same P1 guard on the mixed branch the review reproduced: a completed
    # task beside a review-blocked node that also carries the sync flag.
    summary = summarize_workgraph_results(
        [
            {"status": "SUCCEEDED", "taskId": "task-1"},
            {
                "status": "BLOCKED",
                "reason": "WAITING_REVIEW",
                "promptSyncRequired": True,
            },
        ],
    )
    assert "尚未启动制作" not in summary
    assert "已完成制作 1 项" in summary
    assert "1 项等待现有审阅，尚未开始" in summary
    assert "需先同步分镜/提示词" not in summary
    assert "制作条件尚未满足" not in summary
    assert "-1" not in summary
