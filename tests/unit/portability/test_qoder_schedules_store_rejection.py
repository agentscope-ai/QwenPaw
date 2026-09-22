# -*- coding: utf-8 -*-
"""Qoder schedule store discovery: v1/v2 selection, rejection and mapping.

The existing suite covers the happy v2 path plus three safety limits.
These cases cover the rest of the discovery contract: the v1 fallback,
every way a store can be refused, the malformed-entry warnings, the
status-derived lifecycle fallback, and the whole schedule-mapping table
including the exact interval cron phases.
"""

# pylint: disable=protected-access
# pylint: disable=use-implicit-booleaness-not-comparison

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from qwenpaw.portability.models import SourceScheduledTask
from qwenpaw.portability.providers import qoder_schedules
from qwenpaw.portability.providers.qoder_schedules import (
    discover_qoder_scheduled_tasks,
)

_STORE_RELATIVE = (
    Path("globalStorage") / "aicoding.aicoding-agent" / "schedule"
)
_START = "2026-08-20T00:00:00Z"


def _store_path(user_data: Path, version: int) -> Path:
    return user_data / _STORE_RELATIVE / f"tasks.v{version}.json"


def _write_store(
    user_data: Path,
    *,
    version: int,
    tasks: list[Any] | None = None,
    runs: Any = None,
    raw: str | bytes | None = None,
) -> Path:
    """Write one store file and return its path."""
    path = _store_path(user_data, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        if isinstance(raw, bytes):
            path.write_bytes(raw)
        else:
            path.write_text(raw, encoding="utf-8")
        return path
    payload: dict[str, Any] = {
        "version": version,
        "tasks": tasks if tasks is not None else [],
    }
    if version == 2:
        payload["runs"] = runs if runs is not None else []
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _v2_task(
    task_id: str,
    *,
    repeat: Any = None,
    start_at: str = _START,
    timezone: str = "UTC",
    schedule: Any = "__unset__",
    **overrides: Any,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": task_id,
        "title": f"Task {task_id}",
        "prompt": f"Run {task_id}",
        "lifecycle": "active",
        "enabled": True,
        "source": "slash",
        "createdAt": "2026-08-18T00:00:00Z",
        "updatedAt": "2026-08-18T00:00:00Z",
    }
    if schedule == "__unset__":
        task["schedule"] = {
            "startAt": start_at,
            "timezone": timezone,
            "repeat": {"frequency": "none"} if repeat is None else repeat,
        }
    elif schedule is not None:
        task["schedule"] = schedule
    task.update(overrides)
    return task


def _v1_task(
    task_id: str,
    *,
    status: str = "pending",
    fire_at: str = "2026-09-01T08:00:00Z",
    **overrides: Any,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": task_id,
        "title": f"Legacy {task_id}",
        "prompt": f"Legacy prompt {task_id}",
        "status": status,
        "fireAt": fire_at,
        "timezone": "UTC",
    }
    task.update(overrides)
    return task


def _discover_once(user_data: Path) -> SourceScheduledTask:
    """Discover and require exactly one staged task."""
    tasks, _warnings, _count = discover_qoder_scheduled_tasks(user_data)
    assert len(tasks) == 1
    return tasks[0]


def _only_warning(user_data: Path) -> str:
    tasks, warnings, count = discover_qoder_scheduled_tasks(user_data)
    assert tasks == []
    assert count == 0
    assert len(warnings) == 1
    return warnings[0]


# --------------------------------------------------------------------------
# store selection: v2 presence is authoritative, v1 is the fallback
# --------------------------------------------------------------------------


def test_no_store_present_yields_no_tasks_or_warnings(
    tmp_path: Path,
) -> None:
    assert discover_qoder_scheduled_tasks(tmp_path) == ([], [], 0)


def test_v1_store_is_used_when_v2_is_absent(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_store(user_data, version=1, tasks=[_v1_task("legacy-1")])

    task = _discover_once(user_data)

    assert task.source_id == "qoder:schedule:legacy-1"
    assert task.schedule_type == "once"
    assert task.run_at is not None
    assert task.run_at.isoformat() == "2026-09-01T08:00:00+00:00"
    assert task.cron == ""
    assert task.enabled is True
    assert task.metadata["legacy_store"] is True
    assert task.metadata["source_store_version"] == 1
    assert task.metadata["schedule_fidelity"] == "exact"
    assert task.metadata["review_reasons"] == [
        "activation_requires_user_review",
        "legacy_v1_definition",
    ]
    assert task.metadata["source_schedule"] == {
        "kind": "at",
        "at": "2026-09-01T08:00:00Z",
        "timezone": "UTC",
    }


def test_v1_source_task_count_is_reported(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_store(
        user_data,
        version=1,
        tasks=[_v1_task("a"), _v1_task("b", status="running")],
    )

    tasks, warnings, count = discover_qoder_scheduled_tasks(user_data)

    assert count == 2
    assert [task.source_id for task in tasks] == ["qoder:schedule:a"]
    assert warnings == []


@pytest.mark.parametrize(
    "status",
    ["running", "completed", "failed", "cancelled"],
)
def test_v1_terminal_statuses_are_filtered_without_warning(
    tmp_path: Path,
    status: str,
) -> None:
    user_data = tmp_path / "User"
    _write_store(user_data, version=1, tasks=[_v1_task("t", status=status)])

    tasks, warnings, count = discover_qoder_scheduled_tasks(user_data)

    assert tasks == []
    assert warnings == []
    assert count == 1


@pytest.mark.parametrize("enabled", [True, False])
def test_v1_enabled_flag_decides_source_enabled(
    tmp_path: Path,
    enabled: bool,
) -> None:
    user_data = tmp_path / "User"
    _write_store(
        user_data,
        version=1,
        tasks=[_v1_task("t", enabled=enabled)],
    )

    task = _discover_once(user_data)

    assert task.enabled is enabled
    assert task.metadata["source_enabled"] is enabled
    if enabled:
        assert "source_task_paused" not in task.metadata["review_reasons"]
    else:
        assert task.metadata["review_reasons"] == [
            "activation_requires_user_review",
            "source_task_paused",
            "legacy_v1_definition",
        ]


def test_v1_task_without_enabled_flag_defaults_to_lifecycle(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    _write_store(user_data, version=1, tasks=[_v1_task("t")])

    task = _discover_once(user_data)

    assert task.enabled is True


def test_v1_unparsable_fire_at_is_retained_for_review(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    _write_store(
        user_data,
        version=1,
        tasks=[_v1_task("t", fire_at="not-a-timestamp")],
    )

    task = _discover_once(user_data)

    assert task.schedule_type == "unsupported"
    assert task.run_at is None
    assert task.metadata["schedule_review_reason"] == "invalid_start_at"
    assert task.metadata["review_reasons"] == [
        "activation_requires_user_review",
        "legacy_v1_definition",
        "invalid_start_at",
    ]


def test_v2_presence_wins_even_when_v1_also_exists(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_store(user_data, version=2, tasks=[_v2_task("v2-only")])
    _write_store(user_data, version=1, tasks=[_v1_task("v1-hidden")])

    tasks, warnings, count = discover_qoder_scheduled_tasks(user_data)

    assert [task.source_id for task in tasks] == ["qoder:schedule:v2-only"]
    assert count == 1
    assert warnings == []


def test_broken_v2_never_falls_back_to_v1(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_store(user_data, version=2, raw="not json at all")
    _write_store(user_data, version=1, tasks=[_v1_task("v1-hidden")])

    tasks, warnings, count = discover_qoder_scheduled_tasks(user_data)

    assert tasks == []
    assert count == 0
    assert len(warnings) == 1
    assert warnings[0].endswith("Qoder v1 was not used.")
    assert "Could not read Qoder schedule store" in warnings[0]


def test_dangling_v2_symlink_is_refused_before_v1(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    v2_path = _store_path(user_data, 2)
    v2_path.parent.mkdir(parents=True, exist_ok=True)
    v2_path.symlink_to(tmp_path / "nowhere.json")
    _write_store(user_data, version=1, tasks=[_v1_task("v1-hidden")])

    warning = _only_warning(user_data)

    assert "Refused symbolic-link Qoder schedule store" in warning
    assert "Qoder v1 was not used" in warning


# --------------------------------------------------------------------------
# store rejection paths
# --------------------------------------------------------------------------


def test_store_that_is_not_a_regular_file_is_refused(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    fifo = _store_path(user_data, 2)
    fifo.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(fifo)

    warning = _only_warning(user_data)

    assert "is not a regular file" in warning


def test_store_directory_is_refused(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    directory = _store_path(user_data, 2)
    directory.mkdir(parents=True)

    warning = _only_warning(user_data)

    assert "is not a regular file" in warning


def test_uninspectable_path_reports_inspection_failure() -> None:
    # A name longer than the filesystem limit makes both is_symlink() and
    # lstat() raise OSError; discovery must report it, not crash.
    overlong = Path("/" + "x" * 5000)

    tasks, warnings, count = discover_qoder_scheduled_tasks(overlong)

    assert tasks == []
    assert count == 0
    assert len(warnings) == 1
    assert "Could not inspect Qoder schedule store" in warnings[0]
    assert "File name too long" in warnings[0]
    assert "Qoder v1 was not used" in warnings[0]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\xff\xfe\x00not utf-8", "Could not read Qoder schedule store"),
        ("[" * 50000, "maximum recursion depth exceeded"),
        ("[1, 2", "Could not read Qoder schedule store"),
    ],
    ids=["invalid-utf8", "recursion", "truncated-json"],
)
def test_undecodable_store_is_refused(
    tmp_path: Path,
    raw: str | bytes,
    expected: str,
) -> None:
    user_data = tmp_path / "User"
    _write_store(user_data, version=2, raw=raw)

    warning = _only_warning(user_data)

    assert expected in warning


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 1, "tasks": [], "runs": []},
        {"version": "2", "tasks": []},
        [1, 2, 3],
        "a string",
    ],
    ids=["wrong-version", "version-not-int", "list-payload", "string-payload"],
)
def test_payload_with_unsupported_version_is_refused(
    tmp_path: Path,
    payload: Any,
) -> None:
    user_data = tmp_path / "User"
    _write_store(user_data, version=2, raw=json.dumps(payload))

    warning = _only_warning(user_data)

    assert "has an unsupported or malformed version (expected 2)" in warning


@pytest.mark.parametrize(
    "tasks_value",
    [{"a": 1}, "tasks", 7, None],
    ids=["dict", "string", "int", "missing"],
)
def test_payload_without_tasks_array_is_refused(
    tmp_path: Path,
    tasks_value: Any,
) -> None:
    user_data = tmp_path / "User"
    payload: dict[str, Any] = {"version": 2, "runs": []}
    if tasks_value is not None:
        payload["tasks"] = tasks_value
    _write_store(user_data, version=2, raw=json.dumps(payload))

    warning = _only_warning(user_data)

    assert "has no valid tasks array" in warning


@pytest.mark.parametrize(
    "runs_value",
    [{"a": 1}, "runs", None],
    ids=["dict", "string", "missing"],
)
def test_v2_payload_without_runs_array_is_refused(
    tmp_path: Path,
    runs_value: Any,
) -> None:
    user_data = tmp_path / "User"
    payload: dict[str, Any] = {"version": 2, "tasks": []}
    if runs_value is not None:
        payload["runs"] = runs_value
    _write_store(user_data, version=2, raw=json.dumps(payload))

    warning = _only_warning(user_data)

    assert "has no valid runs array" in warning


def test_v1_payload_without_runs_array_is_accepted(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_store(
        user_data,
        version=1,
        raw=json.dumps({"version": 1, "tasks": [_v1_task("a")]}),
    )

    task = _discover_once(user_data)

    assert task.source_id == "qoder:schedule:a"


def test_torn_read_is_reported_as_changed_not_raised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_data = tmp_path / "User"
    _write_store(user_data, version=2, tasks=[])

    def _boom(*_args: Any, **_kwargs: Any) -> bytes:
        raise ValueError("portable source changed during import")

    monkeypatch.setattr(qoder_schedules, "read_regular_file", _boom)

    warning = _only_warning(user_data)

    assert "changed while being read" in warning
    assert "[Errno" not in warning


def test_read_os_error_keeps_the_errno_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_data = tmp_path / "User"
    _write_store(user_data, version=2, tasks=[])

    def _boom(*_args: Any, **_kwargs: Any) -> bytes:
        raise OSError(5, "io failure")

    monkeypatch.setattr(qoder_schedules, "read_regular_file", _boom)

    warning = _only_warning(user_data)

    assert "Could not read Qoder schedule store" in warning
    assert "[Errno 5] io failure" in warning
    assert "changed while being read" not in warning


def test_v1_read_failure_is_reported_without_v2_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_data = tmp_path / "User"
    _write_store(user_data, version=1, tasks=[])

    def _boom(*_args: Any, **_kwargs: Any) -> bytes:
        raise OSError(5, "io failure")

    monkeypatch.setattr(qoder_schedules, "read_regular_file", _boom)

    warning = _only_warning(user_data)

    assert "Qoder v1 was not used" not in warning
    assert "Could not read Qoder schedule store" in warning


def test_path_presence_treats_os_error_as_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When probing a path raises, the store must be treated as authoritative
    # damage rather than as "absent", so v1 is never silently used instead.
    user_data = tmp_path / "User"
    _write_store(user_data, version=2, tasks=[_v2_task("v2-task")])
    _write_store(user_data, version=1, tasks=[_v1_task("v1-hidden")])

    original_symlink = Path.is_symlink
    original_exists = Path.exists

    def _raising_symlink(self: Path) -> bool:
        if self.name == "tasks.v2.json":
            raise OSError(36, "File name too long")
        return original_symlink(self)

    def _missing(self: Path) -> bool:
        if self.name == "tasks.v2.json":
            return False
        return original_exists(self)

    monkeypatch.setattr(Path, "is_symlink", _raising_symlink)
    monkeypatch.setattr(Path, "exists", _missing)

    tasks, warnings, count = discover_qoder_scheduled_tasks(user_data)

    # The OSError branch keeps v2 authoritative, so the v1 store stays hidden.
    assert [task.source_id for task in tasks] == ["qoder:schedule:v2-task"]
    assert count == 1
    assert warnings == []


def test_path_presence_negative_control_lets_v1_win(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove the case above discriminates: a plain False hides v2."""
    user_data = tmp_path / "User"
    _write_store(user_data, version=2, tasks=[_v2_task("v2-task")])
    _write_store(user_data, version=1, tasks=[_v1_task("v1-hidden")])

    original_symlink = Path.is_symlink
    original_exists = Path.exists

    def _absent_symlink(self: Path) -> bool:
        if self.name == "tasks.v2.json":
            return False
        return original_symlink(self)

    def _absent_exists(self: Path) -> bool:
        if self.name == "tasks.v2.json":
            return False
        return original_exists(self)

    monkeypatch.setattr(Path, "is_symlink", _absent_symlink)
    monkeypatch.setattr(Path, "exists", _absent_exists)

    tasks, _warnings, count = discover_qoder_scheduled_tasks(user_data)

    assert [task.source_id for task in tasks] == ["qoder:schedule:v1-hidden"]
    assert count == 1


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("missing", False),
        ("regular", True),
        ("directory", True),
        ("dangling-symlink", True),
    ],
)
def test_path_presence_recognizes_damaged_entries(
    tmp_path: Path,
    kind: str,
    expected: bool,
) -> None:
    if kind == "missing":
        candidate = tmp_path / "gone.json"
    elif kind == "regular":
        candidate = tmp_path / "real.json"
        candidate.write_text("{}", encoding="utf-8")
    elif kind == "directory":
        candidate = tmp_path / "a-dir"
        candidate.mkdir()
    else:
        candidate = tmp_path / "link.json"
        candidate.symlink_to(tmp_path / "nowhere.json")

    assert qoder_schedules._path_present(candidate) is expected


def test_path_presence_reports_os_error_as_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "real.json"
    candidate.write_text("{}", encoding="utf-8")

    def _raise(self: Path) -> bool:
        raise OSError(36, "File name too long")

    monkeypatch.setattr(Path, "is_symlink", _raise)

    assert qoder_schedules._path_present(candidate) is True
