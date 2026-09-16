# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Manual eval-set regression for the six-dimension review prompt.

Runs the *real* VLM against the curated cases and grades against the
human-annotated ``expected.json`` (bar: zero misses, <=1 false alarm per
case). Manual invocation (never runs in CI):

    RENDER_REVIEW_EVAL=1 CREATOR_DATA_ROOT=... QWENPAW_KEYRING_ACCOUNT=... \
        pytest tests/render_review/test_eval_set.py -m manual -s
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    AudioCreation,
    ElementLocation,
    OverlayCreation,
    Project,
    ProjectSettings,
    SourceAssetVersion,
    Timeline,
    TimelineElement,
    TimelineSpan,
)
from services.render_review.review import derive_plan_context, review_render

pytestmark = [
    pytest.mark.manual,
    pytest.mark.manual_real,
    pytest.mark.skipif(
        os.environ.get("RENDER_REVIEW_EVAL") != "1",
        reason="manual real-VLM eval; set RENDER_REVIEW_EVAL=1 to run",
    ),
]

CASES_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures/render_review/cases"
)
PROJECT_ID = "project-render-review-eval"
TARGET_REF = "timeline:timeline:main"
MAX_FALSE_ALARMS_PER_CASE = 1


def _load_cases() -> list[tuple[str, Path, dict]]:
    cases = []
    for case_dir in sorted(CASES_DIR.iterdir()):
        expected_path = case_dir / "expected.json"
        video_path = case_dir / "video.mp4"
        if not expected_path.is_file() or not video_path.is_file():
            continue
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        cases.append((case_dir.name, video_path, expected))
    return cases


def _project_for_case(expected: dict) -> Project:
    labels = expected.get("plan_context") or {}
    project = Project.new(
        project_id=PROJECT_ID,
        name="Render Review Eval",
        description=str(labels.get("project_brief") or ""),
        settings=ProjectSettings(
            content_type=labels.get("content_type"),
            target_duration_seconds=labels.get("target_duration_seconds"),
        ),
    )
    elements: dict[str, TimelineElement] = {}
    if labels.get("expects_voiceover"):
        version_id = "asset-version-eval-vo"
        project.assets.source_versions_by_id[version_id] = SourceAssetVersion(
            version_id=version_id,
            logical_asset_id="asset:eval-vo",
            name="旁白",
            file_id="file-eval-vo",
            checksum="0" * 64,
            media_kind="audio",
            media_type="audio/wav",
            created_at=project.created_at,
            metadata={"sourceKind": "tts_generation"},
        )
        elements["audio:vo1"] = TimelineElement(
            element_id="audio:vo1",
            span=TimelineSpan(start_tick=0, duration_tick=1000),
            creation=AudioCreation(source_asset_version_id=version_id),
        )
    if labels.get("expects_subtitles"):
        elements["overlay:sub1"] = TimelineElement(
            element_id="overlay:sub1",
            span=TimelineSpan(start_tick=0, duration_tick=1000),
            location=ElementLocation(),
            creation=OverlayCreation(
                overlay_kind="pet_os",
                text="评测字幕",
                prompt="评测字幕",
            ),
        )
    timeline = Timeline(timeline_id="timeline:main", elements_by_id=elements)
    project.timelines.items["timeline:main"] = timeline
    project.timelines.order.append("timeline:main")
    return project


def _grade(report, expected: dict) -> dict:
    expected_failures = set(expected.get("expected_failures") or [])
    acceptable_extra = set(expected.get("acceptable_extra_failures") or [])
    flagged = {i.dimension.value for i in report.findings if not i.passed}
    missed = sorted(expected_failures - flagged)
    false_alarms = sorted(flagged - expected_failures - acceptable_extra)
    return {
        "case": expected.get("case"),
        "verdict": report.verdict,
        "flagged": sorted(flagged),
        "missed": missed,
        "false_alarms": false_alarms,
        "findings": [
            {"dimension": i.dimension.value, "severity": i.severity}
            | i.model_dump(include={"evidence_timestamp_ms", "suggestion"})
            for i in report.findings
            if not i.passed
        ],
    }


def test_eval_set_zero_miss_low_false_alarm(tmp_path: Path) -> None:
    cases = _load_cases()
    assert len(cases) >= 7, "eval set is incomplete"
    os.environ.setdefault("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Render Review Eval"),
    )

    results = []
    for case_name, video_path, expected in cases:
        plan_context = derive_plan_context(
            _project_for_case(expected),
            TARGET_REF,
        )
        report = asyncio.run(
            review_render(
                services,
                project_id=PROJECT_ID,
                video_path=video_path,
                video_id=case_name,
                round_number=1,
                plan_context=plan_context,
            ),
        )
        graded = _grade(report, expected)
        results.append(graded)
        print(json.dumps(graded, ensure_ascii=False))

    total_missed = [(i["case"], i["missed"]) for i in results if i["missed"]]
    over_alarmed = [
        (item["case"], item["false_alarms"])
        for item in results
        if len(item["false_alarms"]) > MAX_FALSE_ALARMS_PER_CASE
    ]
    summary = {
        "cases": len(results),
        "missed": total_missed,
        "over_alarmed": over_alarmed,
        "false_alarm_total": sum(len(i["false_alarms"]) for i in results),
    }
    print("EVAL SUMMARY:", json.dumps(summary, ensure_ascii=False))
    assert not total_missed, f"missed defects: {total_missed}"
    assert not over_alarmed, f"too many false alarms: {over_alarmed}"
