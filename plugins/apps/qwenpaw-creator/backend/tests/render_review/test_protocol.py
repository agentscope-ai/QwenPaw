# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Unit tests for the six-dimension review protocol and report schema."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from schemas.render_review import (
    AudioProfile,
    RenderReviewReport,
    ReviewDimension,
    ReviewFrame,
)
from services.render_review.protocol import (
    MAX_REVIEW_ROUNDS,
    build_review_user_text,
    findings_feedback_payload,
    parse_review_report,
)
from services.render_review.review import derive_plan_context

pytestmark = pytest.mark.unit


def _findings_payload(**overrides) -> dict:
    findings = []
    for dimension in ReviewDimension:
        entry = {
            "dimension": dimension.value,
            "passed": True,
            "severity": "minor",
            "evidence_timestamp_ms": None,
            "suggestion": "",
        }
        entry.update(overrides.get(dimension.value, {}))
        findings.append(entry)
    return {"findings": findings, "verdict": "pass"}


def _parse(payload: dict, *, round_number: int = 1) -> RenderReviewReport:
    return parse_review_report(
        json.dumps(payload, ensure_ascii=False),
        video_ref="artifact-version:v1",
        round_number=round_number,
    )


def test_parse_review_report_pass_roundtrip_accepts_fenced_json() -> None:
    payload = _findings_payload()
    text = "审阅完成：\n```json\n" + json.dumps(payload) + "\n```"
    report = parse_review_report(
        text,
        video_ref="artifact-version:v1",
        round_number=1,
    )
    assert report.verdict == "pass"
    assert len(report.findings) == len(ReviewDimension)
    assert report.failed_findings() == []
    restored = RenderReviewReport.model_validate(report.model_dump())
    assert restored == report


def test_parse_review_report_normalizes_weak_failures_to_pass() -> None:
    payload = _findings_payload(
        pacing={
            "passed": False,
            "severity": "minor",
            "evidence_timestamp_ms": 4000,
        },
    )
    payload["verdict"] = "revise"
    assert _parse(payload).verdict == "pass"
    # A major failure without frame evidence is discarded (fail closed).
    payload = _findings_payload(
        visual_quality={"passed": False, "severity": "major"},
    )
    report = _parse(payload)
    assert report.verdict == "pass"
    assert report.failed_findings() == []


def test_parse_review_report_rejects_missing_dimensions() -> None:
    payload = _findings_payload()
    payload["findings"] = payload["findings"][:-1]
    with pytest.raises(ValueError, match="missing dimensions"):
        _parse(payload)


def test_findings_feedback_payload_contains_only_failures() -> None:
    payload = _findings_payload(
        sound={
            "passed": False,
            "severity": "major",
            "evidence_timestamp_ms": 2000,
            "suggestion": "补齐 2s 起缺失的配音轨",
        },
    )
    feedback = findings_feedback_payload(_parse(payload, round_number=2))
    assert feedback["type"] == "render_review_feedback"
    assert feedback["round"] == 2
    assert feedback["max_rounds"] == MAX_REVIEW_ROUNDS
    assert [item["dimension"] for item in feedback["findings"]] == ["sound"]


def test_build_review_user_text_lists_all_evidence() -> None:
    frames = [ReviewFrame(timestamp_ms=0, image_path="/tmp/f0.jpg")]
    profile = AudioProfile(
        has_audio=True,
        integrated_lufs=-19.2,
    )
    text = build_review_user_text(
        frames=frames,
        audio_profile=profile,
        video_duration_seconds=5.0,
        plan_context={
            "target_duration_seconds": 5,
            "edit_plan": {"concept": "猫的越狱日记"},
        },
    )
    assert "t=0ms" in text
    for dimension in ReviewDimension:
        assert dimension.value in text
    # The edit-plan contract ships verbatim, exactly once.
    assert "【剪辑契约" in text
    assert text.count("猫的越狱日记") == 1


def test_build_review_user_text_scopes_live_tutorial_rubric() -> None:
    profile = AudioProfile(has_audio=False)
    ordinary = build_review_user_text(
        frames=[],
        audio_profile=profile,
        video_duration_seconds=3.0,
        plan_context={},
    )
    tutorial = build_review_user_text(
        frames=[],
        audio_profile=profile,
        video_duration_seconds=3.0,
        plan_context={
            "live_operation_tutorial": True,
            "live_operation_take_count": 2,
        },
    )
    assert "【真实操作教程专项验收】" not in ordinary
    assert "【真实操作教程专项验收】" in tutorial
    assert "三层深度" in tutorial


def test_plan_context_detects_live_tutorial_and_any_text_caption() -> None:
    live_version = SimpleNamespace(
        metadata={"sourceKind": "live_operation_take"},
    )
    edit = SimpleNamespace(
        enabled=True,
        creation=SimpleNamespace(type="edit"),
        render_source=SimpleNamespace(version_id="asset-version-live"),
    )
    caption = SimpleNamespace(
        enabled=True,
        creation=SimpleNamespace(type="overlay", text="点击搜索框"),
        render_source=None,
    )
    timeline = SimpleNamespace(
        edit_plan=None,
        elements_by_id={"edit-1": edit, "caption-1": caption},
    )
    project = SimpleNamespace(
        settings=None,
        description="GitHub 使用教程",
        timelines=SimpleNamespace(items={"timeline:main": timeline}),
        assets=SimpleNamespace(
            source_versions_by_id={"asset-version-live": live_version},
        ),
    )

    context = derive_plan_context(project, "timeline:main")

    assert context["expects_subtitles"] is True
    assert context["live_operation_tutorial"] is True
    assert context["live_operation_take_count"] == 1


def test_dimensions_match_the_vendored_appeal_rubric() -> None:
    from vendor.media_toolkit.review_rubrics import APPEAL_RUBRIC_ROWS

    rubric_keys = [row.key for row in APPEAL_RUBRIC_ROWS]
    dimension_keys = [item.value for item in ReviewDimension]
    assert dimension_keys == rubric_keys + ["engineering"]


def test_concept_score_threshold_gates_the_verdict() -> None:
    # The concept row is score-driven: a failing concept needs no frame
    # timestamp (other timestamp-less rows get normalized back to pass).
    report = _parse(_findings_payload(concept={"passed": True, "score": 5}))
    assert report.verdict == "revise"
    concept = next(
        f for f in report.findings if f.dimension is ReviewDimension.CONCEPT
    )
    assert not concept.passed
    assert concept.severity == "major"
    passing = _parse(_findings_payload(concept={"passed": True, "score": 8}))
    assert passing.verdict == "pass"
