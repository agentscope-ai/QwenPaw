# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""Synchronous text review: classification, parsing, caps and fail-open."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from models import text_model
from services.run_review import admission, text_review
from services.run_review.text_review import (
    classify_pointer_groups,
    classify_pointers,
    maybe_sync_review,
    parse_sync_advisory,
    reviewable_changed_pointers,
)

pytestmark = pytest.mark.unit

PROJECT_JSON = {
    "project_id": "project-run-review",
    "strategy": {"creative_brief": "一只猫的雨天独白短片"},
}
MOTION_PTR = "/timelines/items/t/elements_by_id/e/creation/motion/concept"


def _advisory_payload(*, weak_concept: bool) -> str:
    scores = [
        {"row_key": k, "score": 8, "ok": True, "finding": "", "suggestion": ""}
        for k in ("concept", "contract", "rhythm")
    ]
    if weak_concept:
        scores[0] |= {
            "score": 3,
            "ok": False,
            "finding": "/strategy/creative_brief 只是素材罗列",
            "suggestion": "补一个一句话概念",
        }
    return json.dumps(
        {"scores": scores, "summary": "总体可用"},
        ensure_ascii=False,
    )


def _parse_advisory(text: str):
    return parse_sync_advisory(
        text,
        stage="text",
        transaction_id="txn-1",
        pointer_group="strategy",
        reviewed_pointers=["/strategy/creative_brief"],
        round_number=1,
    )


def _sync_review(tmp_path: Path, *, txn: str, project_json=None):
    return maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=project_json or PROJECT_JSON,
        changed_pointers=["/strategy/creative_brief"],
        transaction_id=txn,
    )


def test_classify_pointers_priority_and_match() -> None:
    assert classify_pointers(["/settings/resolution"]) is None
    # Declaration order decides the winner: strategy outranks motion.
    assert classify_pointers([MOTION_PTR, "/strategy/creative_brief"]) == (
        "strategy",
        "text",
        ["/strategy/creative_brief"],
    )
    assert classify_pointers([MOTION_PTR]) == (
        "motion",
        "motion",
        [MOTION_PTR],
    )


def test_parse_sync_advisory_derives_ok_deterministically() -> None:
    advisory = _parse_advisory(_advisory_payload(weak_concept=True))
    weak = advisory.weak_scores()
    assert [item.row_key for item in weak] == ["concept"]
    # A weak score without a cited finding cannot stand (fail-closed).
    payload = json.loads(_advisory_payload(weak_concept=True))
    payload["scores"][0]["finding"] = ""
    advisory = _parse_advisory(json.dumps(payload, ensure_ascii=False))
    assert advisory.weak_scores() == []
    # Every rubric row must be present.
    payload = json.loads(_advisory_payload(weak_concept=False))
    payload["scores"] = payload["scores"][:2]
    with pytest.raises(ValueError):
        _parse_advisory(json.dumps(payload))


def _stub_model(monkeypatch, responses: list[str]) -> list[str]:
    calls: list[str] = []

    async def fake_chat_completion(prompt, **kwargs):
        calls.append(prompt)
        return responses[min(len(calls), len(responses)) - 1]

    monkeypatch.setattr(text_model, "chat_completion", fake_chat_completion)
    return calls


def test_sync_review_lifecycle_rounds_dedup_cap_and_reset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Off means the model is never touched and no state is written.
    monkeypatch.delenv("CREATOR_SYNC_REVIEW_ENABLED", raising=False)
    monkeypatch.setattr(text_model, "chat_completion", None)
    assert _sync_review(tmp_path, txn="txn-off") is None
    assert not (tmp_path / "runtime").exists()

    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    weak = _advisory_payload(weak_concept=True)
    clean = _advisory_payload(weak_concept=False)
    calls = _stub_model(monkeypatch, [weak, weak, clean])

    def _review(brief: str, txn: str):
        document = json.loads(json.dumps(PROJECT_JSON))
        document["strategy"]["creative_brief"] = brief
        return _sync_review(tmp_path, txn=txn, project_json=document)

    advisory = _review("版本一", "txn-1")
    assert advisory is not None
    assert advisory["pointer_group"] == "strategy"
    assert _review("版本一", "txn-1b") is None, "identical content dedups"
    assert len(calls) == 1
    assert _review("版本二", "txn-2") is not None
    # Two consecutive advisories exhaust the group's budget.
    assert _review("版本三", "txn-3") is None
    assert len(calls) == 2
    # A clean review resets the counter for later work.
    state_path = tmp_path / "runtime" / "run-review" / "sync" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["strategy"]["rounds"] = 0
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert _review("版本四", "txn-4") is None  # clean review -> no advisory
    assert len(calls) == 3

    # Model failure is fail-open: commits never block on review errors.
    async def _boom(prompt, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(text_model, "chat_completion", _boom)
    assert _review("版本五", "txn-5") is None


def test_mixed_strategy_and_shots_commit_still_runs_script_check(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    monkeypatch.setattr(text_review, "_script_check_enabled", lambda: True)
    calls = _stub_model(
        monkeypatch,
        [_advisory_payload(weak_concept=False)],
    )
    observed: dict[str, str] = {}

    async def fake_script_check(*, strategy_payload, shots_payload):
        observed["strategy"] = strategy_payload
        observed["shots"] = shots_payload
        return {
            "coverage_missing": [
                {"source_quote": "雨天独白", "note": "分镜未承接"},
            ],
            "hallucinated": [],
            "unshootable": [],
            "summary": "有一处覆盖缺失",
        }

    monkeypatch.setattr(
        "services.run_review.script_review.run_script_check",
        fake_script_check,
    )
    project = {
        **PROJECT_JSON,
        "timelines": {
            "items": {
                "t": {
                    "elements_by_id": {
                        "e": {
                            "creation": {
                                "shots": {
                                    "items": {
                                        "s1": {"description": "猫看向窗外"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }
    result = maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=project,
        changed_pointers=[
            "/strategy/creative_brief",
            "/timelines/items/t/elements_by_id/e/creation/shots",
        ],
        transaction_id="txn-mixed",
    )
    assert result is not None
    assert result["pointer_group"] == "shots"
    assert len(calls) == 2, "strategy and shots are both reviewed"
    assert result["script_check"]["coverage_missing"]
    assert "雨天独白" in observed["strategy"]
    assert "猫看向窗外" in observed["shots"]


def test_mixed_pointer_groups_review_concurrently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    active = 0
    max_active = 0

    async def fake_chat_completion(_prompt, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return _advisory_payload(weak_concept=False)

    monkeypatch.setattr(text_model, "chat_completion", fake_chat_completion)
    project = {
        **PROJECT_JSON,
        "timelines": {
            "items": {
                "t": {
                    "elements_by_id": {
                        "e": {
                            "creation": {
                                "video_prompt": "纸船穿过晨光倒影",
                            },
                        },
                    },
                },
            },
        },
    }
    result = maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=project,
        changed_pointers=[
            "/strategy/creative_brief",
            "/timelines/items/t/elements_by_id/e/creation/video_prompt",
        ],
        transaction_id="txn-concurrent-groups",
    )
    assert result is None
    assert max_active == 2


def test_generation_text_blocker_survives_repair_turn_but_not_hard_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    weak = _advisory_payload(weak_concept=True)
    _stub_model(monkeypatch, [weak, weak])
    pointer = "/timelines/items/t/elements_by_id/e/creation/video_prompt"

    def review(prompt: str, txn: str):
        return maybe_sync_review(
            project_id="project-run-review",
            project_root=tmp_path,
            project_json={
                "timelines": {
                    "items": {
                        "t": {
                            "elements_by_id": {
                                "e": {"creation": {"video_prompt": prompt}},
                            },
                        },
                    },
                },
            },
            changed_pointers=[pointer],
            transaction_id=txn,
            gate_token=f"gate-{txn}",
        )

    reports_root = tmp_path / "runtime" / "run-review"
    assert review("纸船缓慢驶入晨雾", "txn-shots-1") is not None
    blockers = admission.active_sync_fences(reports_root)
    assert len(blockers) == 1
    assert blockers[0]["pointer_group"] == "shots"
    assert review("纸船穿过金色倒影驶入晨雾", "txn-shots-2") is not None
    assert not admission.active_sync_fences(reports_root)


def test_whole_element_create_expands_nested_generation_text() -> None:
    project = {
        "timelines": {
            "items": {
                "timeline:main": {
                    "elements_by_id": {
                        "elem:one": {
                            "creation": {
                                "type": "r2v",
                                "intent": "纸船驶向晨雾",
                                "shots": {
                                    "items": {
                                        "shot:1": {
                                            "description": "纸船随涟漪前进",
                                        },
                                    },
                                    "order": ["shot:1"],
                                },
                                "storyboard_prompt": "晨雾湖面与白色纸船",
                                "video_prompt": "纸船缓慢向前漂移",
                            },
                        },
                    },
                },
            },
        },
    }
    root = "/timelines/items/timeline:main/elements_by_id/elem:one"
    expanded = reviewable_changed_pointers(project, [root])
    assert f"{root}/creation/shots" in expanded
    assert f"{root}/creation/storyboard_prompt" in expanded
    assert f"{root}/creation/video_prompt" in expanded
    groups = classify_pointer_groups(expanded)
    assert groups
    assert groups[0][0] == "shots"
