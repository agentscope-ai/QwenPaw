# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.portability.providers import qoder_schedules
from qwenpaw.portability.providers.qoder_schedules import (
    discover_qoder_scheduled_tasks,
)


def _store_path(user_data: Path, version: int) -> Path:
    return (
        user_data
        / "globalStorage"
        / "aicoding.aicoding-agent"
        / "schedule"
        / f"tasks.v{version}.json"
    )


def _write_store(
    user_data: Path,
    *,
    version: int,
    tasks: list[object],
    runs: list[object] | None = None,
) -> Path:
    path = _store_path(user_data, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"version": version, "tasks": tasks}
    if version == 2:
        payload["runs"] = runs if runs is not None else []
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _v2_task(
    task_id: str,
    *,
    repeat: dict[str, object] | None = None,
    lifecycle: str = "active",
    start_at: str = "2026-08-20T00:00:00Z",
    timezone: str = "UTC",
    **overrides: object,
) -> dict[str, object]:
    task: dict[str, object] = {
        "id": task_id,
        "title": f"Task {task_id}",
        "prompt": f"Run {task_id}",
        "lifecycle": lifecycle,
        "enabled": lifecycle == "active",
        "schedule": {
            "startAt": start_at,
            "timezone": timezone,
            "repeat": repeat or {"frequency": "none"},
        },
        "source": "slash",
        "createdAt": "2026-08-18T00:00:00Z",
        "updatedAt": "2026-08-18T00:00:00Z",
    }
    task.update(overrides)
    return task


def test_v2_maps_active_and_paused_and_filters_terminal_tasks(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    existing_workspace = tmp_path / "project"
    existing_workspace.mkdir()
    missing_workspace = tmp_path / "missing-project"
    active = _v2_task(
        "daily",
        repeat={"frequency": "daily", "time": "08:05"},
        workspacePath=str(existing_workspace),
        completedAt="2026-08-18T01:00:00Z",
        model="qoder-model",
    )
    paused = _v2_task(
        "weekly",
        lifecycle="paused",
        repeat={
            "frequency": "weekly",
            "time": "09:30",
            "weekdays": [6, 1, 3, 1],
        },
        workspacePath=str(missing_workspace),
    )
    completed = _v2_task("completed", lifecycle="completed")
    deleted = _v2_task(
        "deleted",
        deletedAt="2026-08-18T02:00:00Z",
    )
    _write_store(
        user_data,
        version=2,
        tasks=[active, paused, completed, deleted],
        runs=[
            {
                "id": "run-not-imported",
                "taskId": "daily",
                "status": "completed",
            },
        ],
    )

    tasks, warnings, discovered = discover_qoder_scheduled_tasks(user_data)

    assert discovered == 4
    assert not warnings
    assert [task.source_id for task in tasks] == [
        "qoder:schedule:daily",
        "qoder:schedule:weekly",
    ]

    daily, weekly = tasks
    assert daily.schedule_type == "cron"
    assert daily.cron == "5 8 * * *"
    assert daily.enabled is True
    assert daily.cwd == str(existing_workspace)
    assert daily.metadata["workspace_status"] == "exists"
    assert daily.metadata["workspace_exists"] is True
    assert daily.metadata["target_default_enabled"] is False
    assert daily.metadata["review_required"] is True
    assert "model_compatibility_review" in daily.metadata["review_reasons"]

    assert weekly.schedule_type == "cron"
    assert weekly.cron == "30 9 * * mon,wed,sat"
    assert weekly.enabled is False
    assert weekly.metadata["source_lifecycle"] == "paused"
    assert weekly.metadata["workspace_status"] == "missing"
    assert weekly.metadata["workspace_exists"] is False
    assert "source_task_paused" in weekly.metadata["review_reasons"]
    assert "workspace_path_missing" in weekly.metadata["review_reasons"]


@pytest.mark.parametrize(
    ("case", "warning", "mentions_v1"),
    [
        ("missing-runs", "no valid runs array", True),
        ("oversized", "64-byte safety limit", True),
        ("symlink", "symbolic-link", False),
        ("too-many-tasks", "exceeding the 2-task safety limit", False),
    ],
)
def test_unsafe_v2_store_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    warning: str,
    mentions_v1: bool,
) -> None:
    user_data = tmp_path / "User"
    path = _store_path(user_data, 2)
    path.parent.mkdir(parents=True)
    if case == "missing-runs":
        path.write_text(
            json.dumps({"version": 2, "tasks": [_v2_task("task")]}),
            encoding="utf-8",
        )
    elif case == "oversized":
        monkeypatch.setattr(qoder_schedules, "_MAX_STORE_BYTES", 64)
        path.write_bytes(b"{" + (b"x" * 128))
    elif case == "symlink":
        target = tmp_path / "outside-store.json"
        target.write_text(
            json.dumps({"version": 2, "tasks": [], "runs": []}),
            encoding="utf-8",
        )
        path.symlink_to(target)
    else:
        monkeypatch.setattr(qoder_schedules, "_MAX_TASKS", 2)
        _write_store(
            user_data,
            version=2,
            tasks=[_v2_task(str(index)) for index in range(3)],
        )

    tasks, warnings, discovered = discover_qoder_scheduled_tasks(user_data)

    assert not tasks
    assert discovered == 0
    assert len(warnings) == 1
    assert warning in warnings[0]
    if mentions_v1:
        assert "Qoder v1 was not used" in warnings[0]


def test_oversized_prompt_is_audited_and_never_made_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_data = tmp_path / "User"
    prompt = "never execute this oversized instruction"
    monkeypatch.setattr(qoder_schedules, "_MAX_PROMPT_CHARS", 10)
    monkeypatch.setattr(qoder_schedules, "_MAX_PROMPT_BYTES", 100)
    _write_store(
        user_data,
        version=2,
        tasks=[_v2_task("oversized-prompt", prompt=prompt)],
    )

    tasks, warnings, discovered = discover_qoder_scheduled_tasks(user_data)

    assert discovered == 1
    assert len(tasks) == 1
    task = tasks[0]
    assert task.prompt == ""
    assert task.schedule_type == "unsupported"
    assert task.metadata["unsupported_reason"] == (
        "source_prompt_exceeds_limit"
    )
    assert task.metadata["schedule_review_reason"] == (
        "source_prompt_exceeds_limit"
    )
    audit = task.metadata["prompt_audit"]
    assert audit["disposition"] == "omitted"
    assert audit["original_chars"] == len(prompt)
    assert audit["original_bytes"] == len(prompt.encode("utf-8"))
    assert len(audit["sha256"]) == 64
    assert prompt not in json.dumps(task.metadata)
    assert warnings and "retained for review" in warnings[0]
