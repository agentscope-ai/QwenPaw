# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Unit tests for the six-dimension review protocol and report schema."""

from __future__ import annotations

import json

import pytest

from schemas.render_review import (
    AudioProfile,
    LoudnessSegment,
    RenderReviewReport,
    ReviewDimension,
    ReviewFinding,
    ReviewFrame,
)
from services.render_review.protocol import (
    MAX_REVIEW_ROUNDS,
    build_review_user_text,
    findings_feedback_payload,
    parse_review_report,
    review_system_prompt,
)

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


def test_parse_review_report_pass_roundtrip() -> None:
    payload = _findings_payload()
    report = parse_review_report(
        json.dumps(payload, ensure_ascii=False),
        video_ref="artifact-version:v1",
        round_number=1,
    )
    assert report.verdict == "pass"
    assert report.round == 1
    assert len(report.findings) == len(ReviewDimension)
    assert report.failed_findings() == []
    # Schema round-trip stays lossless.
    restored = RenderReviewReport.model_validate(report.model_dump())
    assert restored == report


def test_parse_review_report_major_failure_forces_revise() -> None:
    payload = _findings_payload(
        engineering={
            "passed": False,
            "severity": "major",
            "evidence_timestamp_ms": 1500,
            "suggestion": "移除 1.5s 处的黑帧",
        },
    )
    payload["verdict"] = "pass"  # Model verdict is normalized away.
    report = parse_review_report(
        json.dumps(payload, ensure_ascii=False),
        video_ref="artifact-version:v1",
        round_number=2,
    )
    assert report.verdict == "revise"
    failed = report.failed_findings()
    assert [item.dimension for item in failed] == [ReviewDimension.ENGINEERING]
    assert failed[0].evidence_timestamp_ms == 1500


def test_parse_review_report_minor_failures_stay_pass() -> None:
    payload = _findings_payload(
        pacing={
            "passed": False,
            "severity": "minor",
            "evidence_timestamp_ms": 4000,
            "suggestion": "压缩 4s 附近的重复镜头",
        },
    )
    payload["verdict"] = "revise"
    report = parse_review_report(
        json.dumps(payload, ensure_ascii=False),
        video_ref="artifact-version:v1",
        round_number=1,
    )
    assert report.verdict == "pass"


def test_parse_review_report_failure_without_evidence_is_discarded() -> None:
    payload = _findings_payload(
        visual_quality={
            "passed": False,
            "severity": "major",
            "evidence_timestamp_ms": None,
            "suggestion": "总体观感不佳",
        },
    )
    report = parse_review_report(
        json.dumps(payload, ensure_ascii=False),
        video_ref="artifact-version:v1",
        round_number=1,
    )
    assert report.verdict == "pass"
    assert report.failed_findings() == []


def test_parse_review_report_accepts_fenced_json() -> None:
    payload = _findings_payload()
    text = "审阅完成：\n```json\n" + json.dumps(payload) + "\n```"
    report = parse_review_report(
        text,
        video_ref="artifact-version:v1",
        round_number=1,
    )
    assert report.verdict == "pass"


def test_parse_review_report_missing_dimension_raises() -> None:
    payload = _findings_payload()
    payload["findings"] = payload["findings"][:-1]
    with pytest.raises(ValueError, match="missing dimensions"):
        parse_review_report(
            json.dumps(payload),
            video_ref="artifact-version:v1",
            round_number=1,
        )


def test_parse_review_report_rejects_non_json() -> None:
    with pytest.raises(ValueError):
        parse_review_report(
            "画面不错，通过。",
            video_ref="artifact-version:v1",
            round_number=1,
        )


def test_findings_feedback_payload_contains_only_failures() -> None:
    report = RenderReviewReport(
        video_ref="artifact-version:v9",
        round=2,
        verdict="revise",
        findings=[
            ReviewFinding(
                dimension=ReviewDimension.SOUND,
                passed=False,
                severity="major",
                evidence_timestamp_ms=2000,
                suggestion="补齐 2s 起缺失的配音轨",
            ),
            ReviewFinding(
                dimension=ReviewDimension.CRAFT,
                passed=True,
            ),
        ],
    )
    payload = findings_feedback_payload(report)
    assert payload["type"] == "render_review_feedback"
    assert payload["round"] == 2
    assert payload["max_rounds"] == MAX_REVIEW_ROUNDS
    assert len(payload["findings"]) == 1
    assert payload["findings"][0]["dimension"] == "sound"


def test_build_review_user_text_lists_all_evidence() -> None:
    frames = [
        ReviewFrame(timestamp_ms=0, image_path="/tmp/f0.jpg"),
        ReviewFrame(timestamp_ms=5000, image_path="/tmp/f1.jpg"),
    ]
    profile = AudioProfile(
        has_audio=True,
        integrated_lufs=-19.2,
        loudness_segments=[
            LoudnessSegment(
                start_ms=0,
                end_ms=5000,
                mean_momentary_lufs=-18.0,
                silent=False,
            ),
        ],
    )
    text = build_review_user_text(
        frames=frames,
        audio_profile=profile,
        video_duration_seconds=5.0,
        plan_context={"target_duration_seconds": 5},
    )
    assert "t=0ms" in text
    assert "t=5000ms" in text
    assert "-19.2" in text
    assert "target_duration_seconds" in text
    for dimension in ReviewDimension:
        assert dimension.value in text
    system_prompt = review_system_prompt()
    assert "verdict" in system_prompt
    assert "evidence_timestamp_ms" in system_prompt


# ── eight-row rubric alignment (WT-B2) ───────────────────────────────────────


def test_dimensions_match_the_vendored_appeal_rubric() -> None:
    from vendor.media_toolkit.review_rubrics import APPEAL_RUBRIC_ROWS

    rubric_keys = [row.key for row in APPEAL_RUBRIC_ROWS]
    dimension_keys = [item.value for item in ReviewDimension]
    # Seven verbatim Appeal rows plus the Creator engineering row.
    assert dimension_keys == rubric_keys + ["engineering"]


def test_concept_score_at_threshold_forces_revise() -> None:
    payload = _findings_payload(
        concept={"passed": True, "score": 5},
    )
    report = parse_review_report(
        json.dumps(payload, ensure_ascii=False),
        video_ref="artifact-version:v1",
        round_number=1,
    )
    assert report.verdict == "revise"
    concept = next(
        item
        for item in report.findings
        if item.dimension is ReviewDimension.CONCEPT
    )
    assert not concept.passed
    assert concept.severity == "major"
    assert "execution polish cannot rescue an empty concept" in (
        concept.suggestion
    )


def test_concept_score_above_threshold_passes() -> None:
    payload = _findings_payload(
        concept={"passed": True, "score": 8},
    )
    report = parse_review_report(
        json.dumps(payload, ensure_ascii=False),
        video_ref="artifact-version:v1",
        round_number=1,
    )
    assert report.verdict == "pass"


def test_concept_failure_needs_no_timestamp() -> None:
    # The concept row is score-driven: a failing concept without a frame
    # timestamp must stand (other rows get normalized back to pass).
    payload = _findings_payload(
        concept={
            "passed": False,
            "severity": "major",
            "score": 3,
            "suggestion": "概念空洞，重立意后重剪",
        },
        rhythm={"passed": False, "severity": "major"},
    )
    report = parse_review_report(
        json.dumps(payload, ensure_ascii=False),
        video_ref="artifact-version:v1",
        round_number=1,
    )
    concept = next(
        item
        for item in report.findings
        if item.dimension is ReviewDimension.CONCEPT
    )
    rhythm = next(
        item
        for item in report.findings
        if item.dimension is ReviewDimension.RHYTHM
    )
    assert not concept.passed
    assert rhythm.passed, "timestamp-less non-concept failure is normalized"
    assert report.verdict == "revise"


def test_user_text_carries_the_edit_plan_contract() -> None:
    frames = [ReviewFrame(timestamp_ms=0, image_path="/tmp/f0.jpg")]
    profile = AudioProfile(has_audio=False)
    text = build_review_user_text(
        frames=frames,
        audio_profile=profile,
        video_duration_seconds=5.0,
        plan_context={
            "target_duration_seconds": 5,
            "edit_plan": {"concept": "猫的越狱日记"},
        },
    )
    assert "【剪辑契约" in text
    assert "猫的越狱日记" in text
    # The plan context section itself no longer duplicates the plan.
    assert text.count("猫的越狱日记") == 1
