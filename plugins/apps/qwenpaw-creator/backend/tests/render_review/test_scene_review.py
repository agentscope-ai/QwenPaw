# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for the scene-loop pre-compose review (WT-B4)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from domain.errors import ValidationError
from services.project_files.models import (
    EditCreation,
    EditPlan,
    EditPlanDesignFloor,
    ElementLocation,
    Project,
    SceneLedgerRow,
    TimelineElement,
    TimelineSpan,
)
from services.render_review import scene_review as scene_review_module
from services.render_review.scene_review import (
    scene_content_fingerprint,
    validate_scene_ledger_locked,
)

pytestmark = pytest.mark.unit


def _plan(rows: list[SceneLedgerRow], **overrides) -> EditPlan:
    defaults: dict = {
        "concept": "猫的越狱日记",
        "pacing": "hook 1.2s",
        "signature_device": "爪印转场",
        "design_floor": EditPlanDesignFloor(
            opening="标题卡",
            transitions="硬切",
            body="设计节拍",
            ending="硬停",
        ),
        "scene_ledger": rows,
    }
    defaults.update(overrides)
    return EditPlan(**defaults)


def _timeline_with_scene(*, edit_plan: EditPlan | None):
    project = Project.new(project_id="project-1", name="Scene")
    timeline = project.timelines.items["timeline:main"]
    element = TimelineElement(
        element_id="el-1",
        span=TimelineSpan(start_tick=0, duration_tick=1000),
        location=ElementLocation(),
        creation=EditCreation(intent="pick"),
    )
    updated = timeline.model_copy(
        update={"elements_by_id": {"el-1": element}, "edit_plan": edit_plan},
    )
    project.timelines.items["timeline:main"] = updated
    return project, updated


def test_gate_skips_unplanned_blocks_draft_and_stale_passes_fresh() -> None:
    row = SceneLedgerRow(scene_id="scene-1", element_ids=["el-1"])
    plans = (None, _plan([]), _plan([row], mechanical_exemption=True))
    for edit_plan in plans:
        _project, timeline = _timeline_with_scene(edit_plan=edit_plan)
        validate_scene_ledger_locked(timeline)

    _project, timeline = _timeline_with_scene(edit_plan=_plan([row]))
    with pytest.raises(ValidationError, match="未锁定场景: scene-1"):
        validate_scene_ledger_locked(timeline)
    fingerprint = scene_content_fingerprint(timeline, row)
    fresh = row.model_copy(
        update={"status": "locked", "locked_fingerprint": fingerprint},
    )
    _project, locked = _timeline_with_scene(edit_plan=_plan([fresh]))
    validate_scene_ledger_locked(locked)

    stale = fresh.model_copy(update={"locked_fingerprint": "sha256:stale"})
    _project, drifted = _timeline_with_scene(edit_plan=_plan([stale]))
    with pytest.raises(ValidationError, match="需重审的场景: scene-1"):
        validate_scene_ledger_locked(drifted)


def _checks_payload(**overrides) -> str:
    keys = (
        "devices type_fonts composition_safety "
        "motion_quality technical watch_once"
    ).split()
    checks = []
    for key in keys:
        entry = {"key": key, "passed": True, "severity": "minor"}
        entry |= {"evidence": "", "suggestion": "", **overrides.get(key, {})}
        checks.append(entry)
    return json.dumps(
        {"checks": checks, "impression": "节拍成立"},
        ensure_ascii=False,
    )


def _services(project) -> SimpleNamespace:
    committed: list = []

    class _Commits:
        @staticmethod
        def commit(*, base, candidate, **kwargs):
            committed.append(candidate)
            return SimpleNamespace(snapshot=SimpleNamespace(project=None))

    services = SimpleNamespace(
        root="/tmp/does-not-matter",
        projects=SimpleNamespace(
            read=lambda project_id: SimpleNamespace(project=project),
            project_root=lambda project_id: "/tmp/project-root",
        ),
        commits=_Commits(),
        poller=SimpleNamespace(note_commit=lambda snapshot: None),
    )
    return services, committed


def _stub_review_env(monkeypatch, *, payload: str) -> None:
    async def fake_evidence(**kwargs):
        return [], [], ["该场景不含 Edit 片段：仅按动效/文本事实评审。"]

    async def fake_chat(content, **kwargs):
        return payload

    monkeypatch.setattr(
        scene_review_module,
        "_collect_evidence",
        fake_evidence,
    )
    monkeypatch.setattr(
        scene_review_module,
        "ProjectExecutionStore",
        lambda root: SimpleNamespace(),
    )
    monkeypatch.setattr(
        scene_review_module.vlm_model,
        "chat_completion",
        fake_chat,
    )


def _run_review(services) -> dict:
    return asyncio.run(
        scene_review_module.review_scene(
            services,
            project_id="project-1",
            timeline_ref="timeline:timeline:main",
            scene_id="scene-1",
            idempotency_key="call-1",
        ),
    )


def test_review_scene_rejects_major_failure_then_locks_on_pass(
    monkeypatch,
) -> None:
    row = SceneLedgerRow(scene_id="scene-1", element_ids=["el-1"])
    project, _timeline = _timeline_with_scene(edit_plan=_plan([row]))
    services, committed = _services(project)
    _stub_review_env(
        monkeypatch,
        payload=_checks_payload(
            devices={
                "passed": False,
                "severity": "major",
                "evidence": "契约声明的爪印转场未出现在任何帧",
            },
        ),
    )
    result = _run_review(services)
    assert result["status"] == "rejected"
    assert result["failedChecks"] == ["devices"]
    assert not committed, "a rejected review must not lock anything"

    _stub_review_env(monkeypatch, payload=_checks_payload())
    result = _run_review(services)
    assert result["status"] == "locked"
    plan = committed[0]["timelines"]["items"]["timeline:main"]["edit_plan"]
    raw_row = plan["scene_ledger"][0]
    assert raw_row["locked_fingerprint"] == result["fingerprint"]
