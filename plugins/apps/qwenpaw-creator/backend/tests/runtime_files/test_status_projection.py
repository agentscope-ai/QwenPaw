# -*- coding: utf-8 -*-
from __future__ import annotations

from domain.enums import (
    CreatorSessionStatus,
    SpecialistRole,
    SpecialistRunStatus,
    TaskKind,
    TaskStatus,
)
from services.runtime_files.execution_models import (
    SpecialistRunRecord,
    TaskRecord,
)
from services.runtime_files.models import CreatorSessionRecord
from services.runtime_files.status_projection import build_agent_status_bar


def _session(
    status: CreatorSessionStatus = CreatorSessionStatus.IDLE,
) -> CreatorSessionRecord:
    return CreatorSessionRecord(
        session_id="session-1",
        project_id="project-1",
        status=status,
        active_goal_id="goal-1",
        last_event_seq=17,
    )


def _task(
    *,
    status: TaskStatus,
    progress: float | None = None,
) -> TaskRecord:
    return TaskRecord(
        task_id="task-1",
        project_id="project-1",
        kind=TaskKind.ASSET_INGEST,
        status=status,
        request_fingerprint="fingerprint-1",
        progress=progress,
        input_refs=["element:edit-1"],
    )


def test_active_task_supplies_real_operation_progress_and_target() -> None:
    view = build_agent_status_bar(
        _session(),
        tasks=[_task(status=TaskStatus.RUNNING, progress=0.42)],
    )

    assert view["progress"] == {
        "goalId": "goal-1",
        "phase": "source_ingest",
        "label": "附件入库中 · 42%",
        "latestMilestone": "附件入库中 · 42%",
        "sourceEventSeq": 17,
        "updatedAt": view["progress"]["updatedAt"],
        "completed": 42,
        "total": 100,
        "elementId": "edit-1",
    }
    assert view["activity"] == {
        "label": "附件入库中 · 42%",
        "runningTaskCount": 1,
    }


def test_session_decision_gate_outranks_background_task() -> None:
    view = build_agent_status_bar(
        _session(CreatorSessionStatus.PENDING_REVIEW),
        tasks=[_task(status=TaskStatus.RUNNING, progress=0.42)],
    )

    assert view["progress"]["label"] == "等待审阅"
    assert view["progress"]["phase"] == "review"
    assert view["badges"][0]["kind"] == "review"


def test_idle_status_reuses_latest_durable_completion() -> None:
    run = SpecialistRunRecord(
        run_id="run-1",
        project_id="project-1",
        round_id="round-1",
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        status=SpecialistRunStatus.SUCCEEDED,
        target_refs=["timeline:timeline:main"],
        input_generation=0,
        input_etag="etag-1",
    )
    view = build_agent_status_bar(_session(), runs=[run])

    assert view["progress"]["label"] == "视觉开发已完成"
    assert view["progress"]["timelineId"] == "timeline:main"
    assert "activity" not in view


def test_every_task_kind_has_a_presentation_or_degrades() -> None:
    # Field run 2026-08-09: review_scene tasks 500'd the session
    # bootstrap and blanked AgentDock history. Every TaskKind must map,
    # and unknown kinds must degrade instead of raising.
    from services.runtime_files import status_projection

    # pylint: disable-next=protected-access
    presentation = status_projection._TASK_PRESENTATION  # noqa: SLF001
    for kind in TaskKind:
        assert kind in presentation, kind
