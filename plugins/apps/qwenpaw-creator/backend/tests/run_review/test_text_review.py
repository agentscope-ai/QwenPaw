# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""Synchronous text review: classification, parsing, caps and fail-open."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.run_review import admission
from services.run_review.text_review import (
    classify_pointers,
    maybe_sync_review,
    parse_sync_advisory,
)

pytestmark = pytest.mark.unit

PROJECT_JSON = {
    "project_id": "project-run-review",
    "strategy": {
        "creative_brief": "一只猫的雨天独白短片",
        "creative_direction": "低饱和、慢节奏",
    },
    "timelines": {
        "items": {
            "timeline:main": {
                "elements_by_id": {
                    "element:e1": {
                        "creation": {
                            "shots": {
                                "items": {
                                    "shot:1": {"description": "猫看窗外"},
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


def _advisory_payload(*, weak_concept: bool) -> str:
    return json.dumps(
        {
            "scores": [
                {
                    "row_key": "concept",
                    "score": 3 if weak_concept else 9,
                    "ok": not weak_concept,
                    "finding": "/strategy/creative_brief 只是素材罗列"
                    if weak_concept
                    else "",
                    "suggestion": "补一个一句话概念" if weak_concept else "",
                },
                {
                    "row_key": "contract",
                    "score": 8,
                    "ok": True,
                    "finding": "",
                    "suggestion": "",
                },
                {
                    "row_key": "rhythm",
                    "score": 8,
                    "ok": True,
                    "finding": "",
                    "suggestion": "",
                },
            ],
            "summary": "总体可用",
        },
        ensure_ascii=False,
    )


def test_classify_pointers_priority_and_match() -> None:
    assert classify_pointers(["/settings/resolution"]) is None
    group, stage, matched = classify_pointers(
        [
            "/timelines/items/timeline:main/elements_by_id/element:e1"
            "/creation/motion/concept",
            "/strategy/creative_brief",
        ],
    )
    assert group == "strategy"
    assert stage == "text"
    assert matched == ["/strategy/creative_brief"]
    group, stage, _ = classify_pointers(
        [
            "/timelines/items/timeline:main/elements_by_id/element:e1"
            "/creation/motion/concept",
        ],
    )
    assert group == "motion"
    assert stage == "motion"


def test_parse_sync_advisory_derives_ok_deterministically() -> None:
    advisory = parse_sync_advisory(
        _advisory_payload(weak_concept=True),
        stage="text",
        transaction_id="txn-1",
        pointer_group="strategy",
        reviewed_pointers=["/strategy/creative_brief"],
        round_number=1,
    )
    weak = advisory.weak_scores()
    assert [item.row_key for item in weak] == ["concept"]
    assert weak[0].suggestion
    # Advisory hygiene: passing rows never carry finding/suggestion text.
    passing = [item for item in advisory.scores if item.ok]
    assert passing and all(
        not item.finding and not item.suggestion for item in passing
    )
    # A weak score without a cited finding cannot stand.
    payload = json.loads(_advisory_payload(weak_concept=True))
    payload["scores"][0]["finding"] = ""
    advisory = parse_sync_advisory(
        json.dumps(payload, ensure_ascii=False),
        stage="text",
        transaction_id="txn-1",
        pointer_group="strategy",
        reviewed_pointers=["/strategy/creative_brief"],
        round_number=1,
    )
    assert advisory.weak_scores() == []


def test_parse_sync_advisory_requires_all_rows() -> None:
    payload = json.loads(_advisory_payload(weak_concept=False))
    payload["scores"] = payload["scores"][:2]
    with pytest.raises(ValueError):
        parse_sync_advisory(
            json.dumps(payload),
            stage="text",
            transaction_id="txn-1",
            pointer_group="strategy",
            reviewed_pointers=[],
            round_number=1,
        )


def test_switch_off_is_a_no_op(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CREATOR_SYNC_REVIEW_ENABLED", raising=False)

    def _boom(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("text model must not be called when off")

    from models import text_model

    monkeypatch.setattr(text_model, "chat_completion", _boom)
    advisory = maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=PROJECT_JSON,
        changed_pointers=["/strategy/creative_brief"],
        transaction_id="txn-off",
    )
    assert advisory is None
    assert not (tmp_path / "runtime").exists()


def _enable(monkeypatch) -> None:
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")


def _stub_model(monkeypatch, responses: list[str]) -> list[str]:
    calls: list[str] = []

    async def fake_chat_completion(prompt, **kwargs):
        del kwargs
        calls.append(prompt)
        return responses[min(len(calls), len(responses)) - 1]

    from models import text_model

    monkeypatch.setattr(text_model, "chat_completion", fake_chat_completion)
    return calls


def test_weak_review_attaches_advisory_and_counts_round(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable(monkeypatch)
    calls = _stub_model(monkeypatch, [_advisory_payload(weak_concept=True)])
    advisory = maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=PROJECT_JSON,
        changed_pointers=["/strategy/creative_brief"],
        transaction_id="txn-1",
    )
    assert advisory is not None
    assert advisory["pointer_group"] == "strategy"
    assert advisory["round"] == 1
    assert len(calls) == 1
    assert "雨天独白" in calls[0]
    report = tmp_path / "runtime" / "run-review" / "sync" / "txn-1.json"
    assert report.is_file()

    # Identical content is never re-reviewed.
    again = maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=PROJECT_JSON,
        changed_pointers=["/strategy/creative_brief"],
        transaction_id="txn-2",
    )
    assert again is None
    assert len(calls) == 1


def test_round_cap_and_clean_reset(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)
    weak = _advisory_payload(weak_concept=True)
    clean = _advisory_payload(weak_concept=False)
    calls = _stub_model(monkeypatch, [weak, weak, clean])

    def _review(brief: str, txn: str):
        document = json.loads(json.dumps(PROJECT_JSON))
        document["strategy"]["creative_brief"] = brief
        return maybe_sync_review(
            project_id="project-run-review",
            project_root=tmp_path,
            project_json=document,
            changed_pointers=["/strategy/creative_brief"],
            transaction_id=txn,
        )

    assert _review("版本一", "txn-1") is not None
    assert _review("版本二", "txn-2") is not None
    # Two consecutive advisories exhaust the group's budget.
    assert _review("版本三", "txn-3") is None
    assert len(calls) == 2
    # A clean review resets the counter for later work.
    state = json.loads(
        (
            tmp_path / "runtime" / "run-review" / "sync" / "state.json"
        ).read_text(encoding="utf-8"),
    )
    state["strategy"]["rounds"] = 0
    (tmp_path / "runtime" / "run-review" / "sync" / "state.json").write_text(
        json.dumps(state),
        encoding="utf-8",
    )
    assert _review("版本四", "txn-4") is None  # clean review -> no advisory
    assert len(calls) == 3


def test_model_failure_is_fail_open(tmp_path: Path, monkeypatch) -> None:
    _enable(monkeypatch)

    async def fake_chat_completion(prompt, **kwargs):
        del prompt, kwargs
        raise RuntimeError("model exploded")

    from models import text_model

    monkeypatch.setattr(text_model, "chat_completion", fake_chat_completion)
    advisory = maybe_sync_review(
        project_id="project-run-review",
        project_root=tmp_path,
        project_json=PROJECT_JSON,
        changed_pointers=["/strategy/creative_brief"],
        transaction_id="txn-err",
    )
    assert advisory is None


def test_sync_admission_state_isolated_per_group(tmp_path: Path) -> None:
    root = tmp_path / "run-review"
    assert (
        admission.admit_sync_review(
            root,
            pointer_group="strategy",
            content_hash="h1",
        )
        == 1
    )
    admission.settle_sync_review(
        root,
        pointer_group="strategy",
        content_hash="h1",
        clean=False,
    )
    assert (
        admission.admit_sync_review(
            root,
            pointer_group="shots",
            content_hash="h1",
        )
        == 1
    )
