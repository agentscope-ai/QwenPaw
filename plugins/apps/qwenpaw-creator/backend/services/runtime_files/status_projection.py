# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-return-statements
"""Authoritative Agent status projection from file-native Runtime records.

The global status bar must describe durable Runtime truth, not whichever page
happens to be mounted.  Session records describe gates and the main Agent;
Task and SpecialistRun heads provide the concrete operation and its progress.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from domain.enums import (
    CreatorSessionStatus,
    SpecialistRole,
    SpecialistRunStatus,
    TaskKind,
    TaskStatus,
)

from .execution_models import SpecialistRunRecord, TaskRecord
from .models import CreatorSessionRecord


_ACTIVE_TASK_STATUSES = frozenset({TaskStatus.QUEUED, TaskStatus.RUNNING})
_ACTIVE_RUN_STATUSES = frozenset(
    {
        SpecialistRunStatus.QUEUED,
        SpecialistRunStatus.QUEUED_CAPACITY,
        SpecialistRunStatus.RUNNING_MODEL,
        SpecialistRunStatus.WAITING_RUNTIME,
        SpecialistRunStatus.WAITING_AUTHORIZATION,
    },
)
_MEASURABLE_TASK_KINDS = frozenset(
    {TaskKind.ASSET_INGEST, TaskKind.ASSET_IMPORT},
)

_TASK_PRESENTATION: dict[TaskKind, tuple[str, str]] = {
    TaskKind.ASSET_INGEST: ("source_ingest", "附件入库"),
    TaskKind.ASSET_IMPORT: ("source_ingest", "素材导入"),
    TaskKind.SOURCE_INTELLIGENCE: ("source_intelligence", "素材理解"),
    TaskKind.IMAGE_GENERATION: ("visual_development", "图片生成"),
    TaskKind.R2V_GENERATION: ("timeline_render", "视频生成"),
    TaskKind.AI_EDIT_EXECUTE: ("timeline_edit", "AI 剪辑执行"),
    TaskKind.COMPOSE: ("timeline_render", "视频合成"),
}

_RUN_PRESENTATION: dict[SpecialistRole, tuple[str, str]] = {
    SpecialistRole.SOURCE_INTELLIGENCE: ("source_intelligence", "素材理解"),
    SpecialistRole.VISUAL_DEVELOPMENT: ("visual_development", "视觉开发"),
    SpecialistRole.R2V_GENERATION_DIRECTOR: ("timeline_render", "视频生成"),
    SpecialistRole.AI_EDITING_DIRECTOR: ("timeline_edit", "AI 剪辑"),
}


@dataclass(frozen=True, slots=True)
class _ProjectedProgress:
    phase: str
    label: str
    updated_at: datetime | None
    completed: int | None = None
    total: int | None = None
    timeline_id: str | None = None
    element_id: str | None = None


def _progress_percent(task: TaskRecord) -> int | None:
    if task.kind not in _MEASURABLE_TASK_KINDS or task.progress is None:
        return None
    return round(task.progress * 100)


def _task_progress(task: TaskRecord) -> _ProjectedProgress:
    phase, base = _TASK_PRESENTATION[task.kind]
    percent = _progress_percent(task)
    if task.status is TaskStatus.QUEUED:
        label = f"{base}等待执行"
    elif task.status is TaskStatus.RUNNING:
        label = f"{base}中"
        if percent is not None:
            label = f"{label} · {percent}%"
    elif task.status is TaskStatus.SUCCEEDED:
        label = f"{base}已完成"
    elif task.status is TaskStatus.CANCELLED:
        label = f"{base}已取消"
    elif task.status is TaskStatus.QUARANTINED:
        label = f"{base}结果已隔离"
    else:
        label = f"{base}失败"
    timeline_id, element_id = _target_ids(task)
    return _ProjectedProgress(
        phase=phase,
        label=label,
        updated_at=task.updated_at,
        completed=percent,
        total=100 if percent is not None else None,
        timeline_id=timeline_id,
        element_id=element_id,
    )


def _run_progress(run: SpecialistRunRecord) -> _ProjectedProgress:
    phase, base = _RUN_PRESENTATION[run.role]
    if run.status in {
        SpecialistRunStatus.QUEUED,
        SpecialistRunStatus.QUEUED_CAPACITY,
    }:
        label = f"{base}等待执行"
    elif run.status is SpecialistRunStatus.RUNNING_MODEL:
        label = f"{base}中"
    elif run.status is SpecialistRunStatus.WAITING_RUNTIME:
        label = f"{base}等待工具结果"
    elif run.status is SpecialistRunStatus.WAITING_AUTHORIZATION:
        label = f"{base}等待执行授权"
    elif run.status is SpecialistRunStatus.SUCCEEDED:
        label = f"{base}已完成"
    elif run.status is SpecialistRunStatus.BLOCKED:
        label = f"{base}受阻"
    elif run.status is SpecialistRunStatus.STALE:
        label = f"{base}结果已过期"
    elif run.status is SpecialistRunStatus.CANCELLED:
        label = f"{base}已取消"
    else:
        label = f"{base}失败"
    timeline_id, element_id = _refs_target_ids(run.target_refs)
    return _ProjectedProgress(
        phase=phase,
        label=label,
        updated_at=run.updated_at,
        timeline_id=timeline_id,
        element_id=element_id,
    )


def _ref_target_ids(ref: str) -> tuple[str | None, str | None]:
    normalized = ref.removeprefix("project://")
    kind, separator, identifier = normalized.partition(":")
    if not separator:
        kind, separator, identifier = normalized.partition("/")
    if not separator or not identifier:
        return None, None
    if kind == "timeline":
        return identifier, None
    if kind == "element":
        return None, identifier
    return None, None


def _refs_target_ids(refs: Iterable[str]) -> tuple[str | None, str | None]:
    timeline_id: str | None = None
    element_id: str | None = None
    for ref in refs:
        timeline, element = _ref_target_ids(ref)
        timeline_id = timeline_id or timeline
        element_id = element_id or element
    return timeline_id, element_id


def _target_ids(task: TaskRecord) -> tuple[str | None, str | None]:
    refs = [str(task.metadata.get("targetRef") or ""), *task.input_refs]
    return _refs_target_ids(ref for ref in refs if ref)


def _session_progress(
    session: CreatorSessionRecord | None,
) -> _ProjectedProgress:
    if session is None:
        return _ProjectedProgress("creative_strategy", "待命中，可继续编辑项目", None)
    status = session.status
    if status is CreatorSessionStatus.PENDING_REVIEW:
        return _ProjectedProgress("review", "等待审阅", session.updated_at)
    if status is CreatorSessionStatus.WAITING_EXECUTION_AUTH:
        return _ProjectedProgress(
            "timeline_render",
            "等待执行授权",
            session.updated_at,
        )
    if status is CreatorSessionStatus.WAITING_USER_INPUT:
        return _ProjectedProgress(
            "creative_strategy",
            "等待用户输入",
            session.updated_at,
        )
    if status is CreatorSessionStatus.INTERRUPT_REQUESTED:
        return _ProjectedProgress(
            "creative_strategy",
            "正在停止所有 Agent",
            session.updated_at,
        )
    if status is CreatorSessionStatus.WAITING_RUNTIME:
        return _ProjectedProgress(
            "creative_strategy",
            "Agent 等待工具结果",
            session.updated_at,
        )
    if status is CreatorSessionStatus.RESUMING:
        return _ProjectedProgress(
            "creative_strategy",
            "Agent 正在恢复执行",
            session.updated_at,
        )
    if status is CreatorSessionStatus.RUNNING:
        return _ProjectedProgress(
            "creative_strategy",
            "Agent 正在处理",
            session.updated_at,
        )
    if status is CreatorSessionStatus.ERROR:
        return _ProjectedProgress(
            "creative_strategy",
            "Runtime 处理失败",
            session.updated_at,
        )
    if status is CreatorSessionStatus.CANCELLED:
        return _ProjectedProgress(
            "creative_strategy",
            "Agent 已停止",
            session.updated_at,
        )
    return _ProjectedProgress(
        "creative_strategy",
        "待命中，可继续编辑项目",
        session.updated_at,
    )


def build_agent_status_bar(
    session: CreatorSessionRecord | None,
    *,
    tasks: Iterable[TaskRecord] = (),
    runs: Iterable[SpecialistRunRecord] = (),
) -> dict[str, Any]:
    """Project the one status bar view used by every file-native API."""

    task_items = sorted(tasks, key=lambda item: item.updated_at, reverse=True)
    run_items = sorted(runs, key=lambda item: item.updated_at, reverse=True)
    active_tasks = [
        item for item in task_items if item.status in _ACTIVE_TASK_STATUSES
    ]
    active_runs = [
        item for item in run_items if item.status in _ACTIVE_RUN_STATUSES
    ]
    session_status = (
        session.status if session is not None else CreatorSessionStatus.IDLE
    )

    # Session gates are user decisions and therefore outrank background work.
    gate_statuses = {
        CreatorSessionStatus.PENDING_REVIEW,
        CreatorSessionStatus.WAITING_EXECUTION_AUTH,
        CreatorSessionStatus.WAITING_USER_INPUT,
        CreatorSessionStatus.INTERRUPT_REQUESTED,
    }
    if session_status in gate_statuses:
        projected = _session_progress(session)
    elif active_tasks:
        projected = _task_progress(active_tasks[0])
    elif active_runs:
        projected = _run_progress(active_runs[0])
    elif session_status in {
        CreatorSessionStatus.RUNNING,
        CreatorSessionStatus.RESUMING,
        CreatorSessionStatus.WAITING_RUNTIME,
        CreatorSessionStatus.ERROR,
        CreatorSessionStatus.CANCELLED,
    }:
        projected = _session_progress(session)
    else:
        terminal: list[tuple[datetime, _ProjectedProgress]] = [
            (item.updated_at, _task_progress(item)) for item in task_items
        ] + [(item.updated_at, _run_progress(item)) for item in run_items]
        projected = (
            max(terminal, key=lambda item: item[0])[1]
            if terminal
            else _session_progress(session)
        )

    active_task_run_ids = {item.run_id for item in active_tasks if item.run_id}
    independent_active_runs = [
        item for item in active_runs if item.run_id not in active_task_run_ids
    ]
    running_count = len(active_tasks) + len(independent_active_runs)
    if running_count == 0 and session_status in {
        CreatorSessionStatus.RUNNING,
        CreatorSessionStatus.RESUMING,
        CreatorSessionStatus.WAITING_RUNTIME,
        CreatorSessionStatus.INTERRUPT_REQUESTED,
    }:
        running_count = 1

    badges: list[dict[str, Any]] = []
    if session_status is CreatorSessionStatus.PENDING_REVIEW:
        badges.append(
            {
                "kind": "review",
                "label": "有待审阅变更",
                "count": 1,
                "actionTarget": "review",
            },
        )
    waiting_authorization_count = sum(
        item.status is SpecialistRunStatus.WAITING_AUTHORIZATION
        for item in active_runs
    )
    if session_status is CreatorSessionStatus.WAITING_EXECUTION_AUTH:
        waiting_authorization_count = max(waiting_authorization_count, 1)
    if waiting_authorization_count:
        badges.append(
            {
                "kind": "execution_authorization",
                "label": "等待执行授权",
                "count": waiting_authorization_count,
                "actionTarget": "execution-authorization",
            },
        )
    if session_status is CreatorSessionStatus.ERROR:
        badges.append({"kind": "error", "label": "Runtime 错误", "count": 1})
    elif not active_tasks and not active_runs and task_items:
        latest_task = task_items[0]
        latest_run_at = run_items[0].updated_at if run_items else None
        if (
            latest_run_at is None or latest_task.updated_at >= latest_run_at
        ) and latest_task.status in {
            TaskStatus.FAILED,
            TaskStatus.QUARANTINED,
        }:
            badges.append(
                {
                    "kind": "error",
                    "label": _task_progress(latest_task).label,
                    "count": 1,
                },
            )

    progress: dict[str, Any] = {
        "goalId": session.active_goal_id if session is not None else None,
        "phase": projected.phase,
        "label": projected.label,
        "latestMilestone": projected.label,
        "sourceEventSeq": session.last_event_seq if session is not None else 0,
        "updatedAt": (
            projected.updated_at.isoformat()
            if projected.updated_at is not None
            else "1970-01-01T00:00:00+00:00"
        ),
    }
    if projected.completed is not None:
        progress["completed"] = projected.completed
        progress["total"] = projected.total
    if projected.timeline_id is not None:
        progress["timelineId"] = projected.timeline_id
    if projected.element_id is not None:
        progress["elementId"] = projected.element_id

    result: dict[str, Any] = {"progress": progress, "badges": badges}
    if running_count:
        result["activity"] = {
            "label": projected.label,
            "runningTaskCount": running_count,
        }
    return result


__all__ = ["build_agent_status_bar"]
