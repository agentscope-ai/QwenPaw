# -*- coding: utf-8 -*-
"""Defect bank, faithfulness checklist, probe parsing and script check."""

from __future__ import annotations

import json

import pytest

from services.run_review.defect_bank import (
    UNIVERSAL_DEFECTS,
    build_defect_question_block,
    program_defect_hints,
)
from services.run_review.faithfulness import build_faithfulness_elements
from services.run_review.media_review import parse_media_report
from services.run_review.script_review import (
    parse_script_check,
    script_check_has_findings,
)

pytestmark = pytest.mark.unit


def test_defect_bank_integrity() -> None:
    ids = [defect.defect_id for defect in UNIVERSAL_DEFECTS]
    assert len(ids) == 16
    assert len(set(ids)) == 16
    # Near-miss polarity: every question asks to CONFIRM absence.
    assert all("确认" in defect.question for defect in UNIVERSAL_DEFECTS)
    severities = {defect.severity for defect in UNIVERSAL_DEFECTS}
    assert severities == {"minor", "major"}


def test_defect_block_applicability_gating() -> None:
    single = build_defect_question_block(multi_shot_expected=False)
    multi = build_defect_question_block(multi_shot_expected=True)
    assert "uq_subject_1" not in single
    assert "uq_subject_1" in multi
    assert "uq_render_3" in single  # any-applicability rows always listed


def test_program_defect_hints_stay_facts() -> None:
    hints = program_defect_hints(
        {
            "video_index": {
                "cut_count": 1,
                "planned_shot_count": 5,
                "freeze_segments": [{"start_ms": 1000, "end_ms": 2500}],
                "scenes": [],
            },
            "cross_shot_consistency": {
                "suspect_pairs": [{"frame_a_ms": 100, "frame_b_ms": 3100}],
            },
        },
    )
    assert "uq_shot_count" in hints
    assert "计划 5 个镜头" in hints
    # Hints must keep the "suspicion, please verify" framing.
    assert "确认" in hints


def test_faithfulness_declared_elements_only() -> None:
    plan = {
        "planned_shots": [
            {
                "shot_id": "shot-1",
                "description": "特写：老人手持暖色灯笼，镜头缓缓推近",
                "dialogue": "",
                "duration_seconds": 3,
            },
            {
                "shot_id": "shot-2",
                "description": "全景：庭院夜景",
                "dialogue": "",
                "duration_seconds": 2,
            },
        ],
    }
    elements = build_faithfulness_elements(plan)
    keys = [element["key"] for element in elements]
    assert "faith_entity" in keys
    assert "faith_composition" in keys  # 特写/全景 declared
    assert "faith_tone" in keys  # 暖色/夜景 declared
    assert "faith_motion" in keys  # 推 declared
    assert "faith_sequence" in keys  # two shots


def test_faithfulness_undeclared_elements_are_not_asked() -> None:
    plan = {
        "planned_shots": [
            {
                "shot_id": "shot-1",
                "description": "一只猫在沙发上",
                "dialogue": "",
                "duration_seconds": 3,
            },
        ],
    }
    keys = [element["key"] for element in build_faithfulness_elements(plan)]
    assert keys == ["faith_entity"]


def _probe_response(extra: dict) -> str:
    findings = [
        {
            "check_key": key,
            "passed": True,
            "severity": "minor",
            "evidence_timestamp_ms": None,
            "suggestion": "",
        }
        for key in (
            "devices",
            "type_fonts",
            "composition_safety",
            "motion_quality",
            "technical",
            "watch_once",
        )
    ]
    return json.dumps({"findings": findings, **extra}, ensure_ascii=False)


def test_probe_parsing_anti_hallucination_rules() -> None:
    response = _probe_response(
        {
            "defect_findings": [
                # Valid CT with in-bounds evidence -> counts, forces revise.
                {
                    "probe_id": "uq_render_3",
                    "verdict": "CT",
                    "evidence_timestamp_ms": 2000,
                    "reason": "画面在 2s 处冻结",
                    "suggestion": "重新生成该段",
                },
                # NA without a reason -> kept but needs_review.
                {"probe_id": "uq_ai_texture", "verdict": "NA"},
                # CT citing a frame the VLM never saw -> needs_review.
                {
                    "probe_id": "uq_text_1",
                    "verdict": "CT",
                    "evidence_timestamp_ms": 99000,
                    "reason": "乱码",
                    "suggestion": "修字幕",
                },
            ],
        },
    )
    report = parse_media_report(
        response,
        kind="element_video",
        artifact_ref="artifact-version:v1",
        round_number=1,
        gate_block=None,
        stats=None,
        expected_defects={
            "uq_render_3": "major",
            "uq_ai_texture": "major",
            "uq_text_1": "major",
        },
        valid_timestamps=[0, 1000, 2000, 3000],
    )
    by_id = {item.probe_id: item for item in report.defect_findings}
    assert by_id["uq_render_3"].needs_review is False
    assert by_id["uq_ai_texture"].needs_review is True
    assert by_id["uq_text_1"].needs_review is True
    # Only the clean CT counts toward the verdict.
    assert [item.probe_id for item in report.confirmed_probes()] == [
        "uq_render_3",
    ]
    assert report.verdict == "revise"


@pytest.mark.parametrize("missing_field", ["reason", "suggestion"])
def test_confirmed_probe_requires_actionable_evidence(
    missing_field: str,
) -> None:
    probe = {
        "probe_id": "uq_render_3",
        "verdict": "CT",
        "evidence_timestamp_ms": 2000,
        "reason": "画面在 2s 处冻结",
        "suggestion": "重新生成该段",
    }
    probe[missing_field] = ""
    report = parse_media_report(
        _probe_response({"defect_findings": [probe]}),
        kind="element_video",
        artifact_ref="artifact-version:v1",
        round_number=1,
        gate_block=None,
        stats=None,
        expected_defects={"uq_render_3": "major"},
        valid_timestamps=[0, 1000, 2000],
    )
    assert report.defect_findings[0].needs_review is True
    assert report.confirmed_probes() == []
    assert report.verdict == "pass"


def test_probe_parsing_backward_compatible_without_probe_arrays() -> None:
    report = parse_media_report(
        _probe_response({}),
        kind="element_video",
        artifact_ref="artifact-version:v1",
        round_number=1,
        gate_block=None,
        stats=None,
    )
    assert report.defect_findings == []
    assert report.faithfulness_findings == []
    assert report.verdict == "pass"


def test_script_check_parser_enforces_evidence() -> None:
    check = parse_script_check(
        json.dumps(
            {
                "coverage_missing": [
                    {"source_quote": "灯笼必须贯穿全片", "note": "分镜未出现"},
                    {"note": "没有引用剧本原文，必须被丢弃"},
                ],
                "hallucinated": [
                    {"shot_ref": "shot-3", "claim": "出现机器人", "note": "剧本无此设定"},
                    {"shot_ref": "shot-4"},
                ],
                "unshootable": [{"shot_ref": "shot-5", "issue": "只有情绪词"}],
                "summary": "两处需修",
            },
            ensure_ascii=False,
        ),
    )
    assert len(check["coverage_missing"]) == 1
    assert len(check["hallucinated"]) == 1
    assert len(check["unshootable"]) == 1
    assert script_check_has_findings(check) is True
    assert (
        script_check_has_findings(
            {"coverage_missing": [], "hallucinated": [], "unshootable": []},
        )
        is False
    )
    assert script_check_has_findings(None) is False
