# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""Synchronous text review: classification, parsing, caps and fail-open."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from models import text_model
from services.run_review.text_review import (
    classify_pointers,
    maybe_sync_review,
    parse_sync_advisory,
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
    group, stage, _ = classify_pointers(
        [MOTION_PTR, "/strategy/creative_brief"],
    )
    assert (group, stage) == ("strategy", "text")
    assert classify_pointers([MOTION_PTR])[:2] == ("motion", "motion")


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
