# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for the scene-loop pre-compose review (WT-B4)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from domain.enums import TaskKind, TaskStatus
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
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.execution_models import TaskAttemptStatus

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
        update={
            "elements_by_id": {"el-1": element},
            "edit_plan": edit_plan,
        },
    )
    project.timelines.items["timeline:main"] = updated
    return project, updated


# ── fingerprint ──────────────────────────────────────────────────────────────


def test_fingerprint_changes_with_element_content() -> None:
    row = SceneLedgerRow(scene_id="scene-1", element_ids=["el-1"])
    _project, timeline = _timeline_with_scene(edit_plan=_plan([row]))
    first = scene_content_fingerprint(timeline, row)
    assert first == scene_content_fingerprint(timeline, row)

    element = timeline.elements_by_id["el-1"]
    mutated = element.model_copy(
        update={"span": TimelineSpan(start_tick=0, duration_tick=2000)},
    )
    changed = timeline.model_copy(
        update={"elements_by_id": {"el-1": mutated}},
    )
    assert scene_content_fingerprint(changed, row) != first


# ── compose gate ─────────────────────────────────────────────────────────────


def test_gate_skips_without_plan_or_ledger_or_exemption() -> None:
    _project, no_plan = _timeline_with_scene(edit_plan=None)
    validate_scene_ledger_locked(no_plan)

    _project, empty_ledger = _timeline_with_scene(edit_plan=_plan([]))
    validate_scene_ledger_locked(empty_ledger)

    row = SceneLedgerRow(scene_id="scene-1", element_ids=["el-1"])
    _project, exempted = _timeline_with_scene(
        edit_plan=_plan([row], mechanical_exemption=True),
    )
    validate_scene_ledger_locked(exempted)


def test_gate_blocks_draft_scenes() -> None:
    row = SceneLedgerRow(scene_id="scene-1", element_ids=["el-1"])
    _project, timeline = _timeline_with_scene(edit_plan=_plan([row]))
    with pytest.raises(ValidationError, match="未锁定场景: scene-1"):
        validate_scene_ledger_locked(timeline)


def test_gate_blocks_stale_locks_and_passes_fresh_ones() -> None:
    row = SceneLedgerRow(scene_id="scene-1", element_ids=["el-1"])
    _project, timeline = _timeline_with_scene(edit_plan=_plan([row]))
    fingerprint = scene_content_fingerprint(timeline, row)

    fresh = SceneLedgerRow(
        scene_id="scene-1",
        element_ids=["el-1"],
        status="locked",
        review_round=1,
        locked_fingerprint=fingerprint,
    )
    _project, locked = _timeline_with_scene(edit_plan=_plan([fresh]))
    validate_scene_ledger_locked(locked)

    stale = fresh.model_copy(update={"locked_fingerprint": "sha256:stale"})
    _project, drifted = _timeline_with_scene(edit_plan=_plan([stale]))
    with pytest.raises(ValidationError, match="需重审的场景: scene-1"):
        validate_scene_ledger_locked(drifted)


# ── check parsing ────────────────────────────────────────────────────────────


def _checks_payload(**overrides) -> str:
    checks = []
    for key in (
        "devices",
        "type_fonts",
        "composition_safety",
        "motion_quality",
        "technical",
        "watch_once",
    ):
        entry = {
            "key": key,
            "passed": True,
            "severity": "minor",
            "evidence": "",
            "suggestion": "",
        }
        entry.update(overrides.get(key, {}))
        checks.append(entry)
    return json.dumps(
        {"checks": checks, "impression": "节拍成立"},
        ensure_ascii=False,
    )


# ── review_scene flow ────────────────────────────────────────────────────────


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


def test_review_scene_locks_on_pass(monkeypatch) -> None:
    row = SceneLedgerRow(scene_id="scene-1", element_ids=["el-1"])
    project, _timeline = _timeline_with_scene(edit_plan=_plan([row]))
    services, committed = _services(project)

    async def fake_evidence(**kwargs):
        return [], [], ["该场景不含 Edit 片段：仅按动效/文本事实评审。"]

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

    async def fake_chat(content, **kwargs):
        return _checks_payload()

    monkeypatch.setattr(
        scene_review_module.vlm_model,
        "chat_completion",
        fake_chat,
    )

    result = asyncio.run(
        scene_review_module.review_scene(
            services,
            project_id="project-1",
            timeline_ref="timeline:timeline:main",
            scene_id="scene-1",
            idempotency_key="call-1",
        ),
    )
    assert result["status"] == "locked"
    assert result["reviewRound"] == 1
    assert committed, "a passing review must commit the lock"
    raw_row = committed[0]["timelines"]["items"]["timeline:main"]["edit_plan"][
        "scene_ledger"
    ][0]
    assert raw_row["status"] == "locked"
    assert raw_row["locked_fingerprint"] == result["fingerprint"]


def test_review_scene_rejects_on_major_failure(monkeypatch) -> None:
    row = SceneLedgerRow(scene_id="scene-1", element_ids=["el-1"])
    project, _timeline = _timeline_with_scene(edit_plan=_plan([row]))
    services, committed = _services(project)

    async def fake_evidence(**kwargs):
        return [], [], []

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

    async def fake_chat(content, **kwargs):
        return _checks_payload(
            devices={
                "passed": False,
                "severity": "major",
                "evidence": "契约声明的爪印转场未出现在任何帧",
                "suggestion": "补上爪印转场或从契约移除",
            },
        )

    monkeypatch.setattr(
        scene_review_module.vlm_model,
        "chat_completion",
        fake_chat,
    )

    result = asyncio.run(
        scene_review_module.review_scene(
            services,
            project_id="project-1",
            timeline_ref="timeline:timeline:main",
            scene_id="scene-1",
            idempotency_key="call-1",
        ),
    )
    assert result["status"] == "rejected"
    assert result["failedChecks"] == ["devices"]
    assert not committed, "a rejected review must not lock anything"


# ── wait=TASK scheduling ─────────────────────────────────────────────────────


class _FakeExecutionStore:
    """Durable-record stand-in: status transitions via attempts."""

    def __init__(self) -> None:
        self.tasks: dict = {}
        self.attempts: list[dict] = []

    def get_task(self, _project_id, task_id):
        task = self.tasks.get(task_id)
        if task is None:
            raise RecordNotFoundError(Path(f"/tasks/{task_id}"))
        return task

    def create_task(self, candidate):
        self.tasks[candidate.task_id] = candidate
        return candidate

    def append_attempt(self, _project_id, task_id, **kwargs):
        self.attempts.append(kwargs)
        task = self.tasks[task_id]
        status = kwargs["status"]
        if status is TaskAttemptStatus.RUNNING:
            update = {
                "status": TaskStatus.RUNNING,
                "last_attempt_seq": task.last_attempt_seq + 1,
            }
        elif status is TaskAttemptStatus.SUCCEEDED:
            update = {
                "status": TaskStatus.SUCCEEDED,
                "result": kwargs.get("output"),
            }
        else:
            update = {
                "status": TaskStatus.FAILED,
                "error": kwargs.get("error"),
            }
        self.tasks[task_id] = task.model_copy(update=update)
        return self.tasks[task_id]


def test_schedule_review_scene_runs_as_a_durable_task(monkeypatch) -> None:
    row = SceneLedgerRow(scene_id="scene-1", element_ids=["el-1"])
    project, _timeline = _timeline_with_scene(edit_plan=_plan([row]))
    services, committed = _services(project)
    store = _FakeExecutionStore()
    monkeypatch.setattr(
        scene_review_module,
        "ProjectExecutionStore",
        lambda root: store,
    )

    async def fake_evidence(**kwargs):
        return [], [], ["该场景不含 Edit 片段：仅按动效/文本事实评审。"]

    monkeypatch.setattr(
        scene_review_module,
        "_collect_evidence",
        fake_evidence,
    )

    async def fake_chat(content, **kwargs):
        return _checks_payload()

    monkeypatch.setattr(
        scene_review_module.vlm_model,
        "chat_completion",
        fake_chat,
    )

    async def run():
        task = await scene_review_module.schedule_review_scene(
            services,
            project_id="project-1",
            timeline_ref="timeline:timeline:main",
            scene_id="scene-1",
            idempotency_key="call-1",
        )
        assert task.kind is TaskKind.REVIEW_SCENE
        assert task.status is TaskStatus.QUEUED
        # Replay converges on the durable record: same task, no re-run.
        again = await scene_review_module.schedule_review_scene(
            services,
            project_id="project-1",
            timeline_ref="timeline:timeline:main",
            scene_id="scene-1",
            idempotency_key="call-1",
        )
        assert again.task_id == task.task_id
        jobs = list(scene_review_module._REVIEW_JOBS.values())
        if jobs:
            await asyncio.gather(*jobs)
        return task

    task = asyncio.run(run())
    final = store.tasks[task.task_id]
    assert final.status is TaskStatus.SUCCEEDED
    assert final.result["status"] == "locked"
    assert committed, "the worker must commit the lock through the boundary"
    statuses = [attempt["status"] for attempt in store.attempts]
    assert statuses == [TaskAttemptStatus.RUNNING, TaskAttemptStatus.SUCCEEDED]
