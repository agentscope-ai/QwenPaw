# -*- coding: utf-8 -*-
"""Qoder schedule entry validation, lifecycle fallback and review metadata.

The store-level and mapping-level cases live in the sibling modules; these
cover what happens to individual entries: the malformed / unsafe / duplicate
id warnings, the v2 status-derived lifecycle fallback, the prompt source
precedence, and the review reasons that keep an imported task inert.
"""

# pylint: disable=protected-access

from __future__ import annotations

import json
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


def _write_v2(user_data: Path, tasks: list[Any]) -> None:
    path = user_data / _STORE_RELATIVE / "tasks.v2.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 2, "tasks": tasks, "runs": []}),
        encoding="utf-8",
    )


def _task(task_id: str = "a", **overrides: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": task_id,
        "title": "T",
        "prompt": "P",
        "lifecycle": "active",
        "enabled": True,
        "schedule": {
            "startAt": _START,
            "timezone": "UTC",
            "repeat": {"frequency": "none"},
        },
    }
    task.update(overrides)
    return task


def _discover(user_data: Path) -> tuple[list[SourceScheduledTask], list[str]]:
    tasks, warnings, _count = discover_qoder_scheduled_tasks(user_data)
    return tasks, warnings


def _single(user_data: Path) -> SourceScheduledTask:
    tasks, warnings = _discover(user_data)
    assert len(tasks) == 1, warnings
    assert warnings == []
    return tasks[0]


def _single_retained(user_data: Path) -> SourceScheduledTask:
    """One staged task that discovery also flagged as needing review."""
    tasks, warnings = _discover(user_data)
    assert len(tasks) == 1, warnings
    assert len(warnings) == 1, warnings
    assert warnings[0].endswith("it was retained for review.")
    return tasks[0]


def _only_warnings(user_data: Path) -> list[str]:
    tasks, warnings = _discover(user_data)
    assert tasks == []
    return warnings


# --------------------------------------------------------------------------
# entry-level rejection warnings
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry",
    ["a string", 7, None, [1, 2], True],
    ids=["string", "int", "none", "list", "bool"],
)
def test_non_dict_entry_is_skipped_with_an_index_warning(
    tmp_path: Path,
    entry: Any,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [entry])

    warnings = _only_warnings(user_data)

    assert len(warnings) == 1
    assert warnings[0].startswith("Skipped malformed Qoder scheduled task")
    assert "at index 0 in " in warnings[0]


def test_malformed_entry_index_is_reported(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("ok"), "junk", "junk2"])

    tasks, warnings = _discover(user_data)

    assert [task.source_id for task in tasks] == ["qoder:schedule:ok"]
    assert len(warnings) == 2
    assert "at index 1 in " in warnings[0]
    assert "at index 2 in " in warnings[1]


@pytest.mark.parametrize(
    "task_id",
    ["", "   ", None, 7, ["a"], {}],
    ids=["empty", "blank", "missing", "int", "list", "dict"],
)
def test_entry_without_a_usable_id_is_skipped(
    tmp_path: Path,
    task_id: Any,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task(task_id)])

    warnings = _only_warnings(user_data)

    assert len(warnings) == 1
    assert warnings[0].startswith("Skipped Qoder scheduled task without an id")
    assert "at index 0 in " in warnings[0]


def test_oversized_id_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(qoder_schedules, "_MAX_SOURCE_ID_CHARS", 8)
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("0123456789abcdef")])

    warnings = _only_warnings(user_data)

    assert len(warnings) == 1
    assert warnings[0].startswith(
        "Skipped Qoder scheduled task with an unsafe or oversized id",
    )
    assert "at index 0 in " in warnings[0]
    assert "0123456789abcdef" not in warnings[0]


@pytest.mark.parametrize(
    "task_id",
    ["bad\x00id", "bad\x1bid", "bad\u200bid", "bad\nid"],
    ids=["nul", "escape", "zero-width", "newline"],
)
def test_id_with_control_characters_is_skipped(
    tmp_path: Path,
    task_id: str,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task(task_id)])

    warnings = _only_warnings(user_data)

    assert len(warnings) == 1
    assert "unsafe or oversized id" in warnings[0]


def test_duplicate_id_keeps_only_the_first_entry(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [_task("dup", title="first"), _task("dup", title="second")],
    )

    tasks, warnings = _discover(user_data)

    assert [task.source_id for task in tasks] == ["qoder:schedule:dup"]
    assert tasks[0].name == "first"
    assert len(warnings) == 1
    assert warnings[0].startswith("Skipped duplicate Qoder scheduled task id")
    assert "'dup'" in warnings[0]


@pytest.mark.parametrize(
    "lifecycle",
    ["", "zombie", "deleted", None, 5, ["active"]],
    ids=["blank", "zombie", "deleted", "none", "int", "list"],
)
def test_unknown_lifecycle_is_reported_not_imported(
    tmp_path: Path,
    lifecycle: Any,
) -> None:
    user_data = tmp_path / "User"
    task = _task("weird")
    task["lifecycle"] = lifecycle
    _write_v2(user_data, [task])

    warnings = _only_warnings(user_data)

    assert len(warnings) == 1
    assert "with an unknown lifecycle" in warnings[0]
    assert "'weird'" in warnings[0]


@pytest.mark.parametrize(
    ("lifecycle", "expected_enabled"),
    [
        ("ACTIVE", True),
        ("Active", True),
        ("  active  ", True),
        ("\tactive\n", True),
        ("PAUSED", False),
    ],
    ids=["upper", "capitalized", "padded", "tab-newline", "paused-upper"],
)
def test_lifecycle_is_trimmed_and_lowercased_before_validation(
    tmp_path: Path,
    lifecycle: str,
    expected_enabled: bool,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("norm", lifecycle=lifecycle)])

    task = _single(user_data)

    assert task.metadata["source_lifecycle"] == lifecycle.strip().lower()
    assert task.enabled is expected_enabled


def test_terminal_lifecycles_are_filtered_without_warning(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [
            _task("c", lifecycle="cancelled"),
            _task("d", lifecycle="completed"),
            _task("e", lifecycle="failed"),
        ],
    )

    tasks, warnings = _discover(user_data)

    assert tasks == []
    assert warnings == []


@pytest.mark.parametrize("field", ["deletedAt", "cancelledAt"])
def test_tombstone_fields_filter_an_otherwise_active_entry(
    tmp_path: Path,
    field: str,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("t", **{field: "2026-08-01T00:00:00Z"})])

    tasks, warnings = _discover(user_data)

    assert tasks == []
    assert warnings == []


def test_filtered_entries_still_count_towards_the_source_total(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [_task("keep"), _task("gone", lifecycle="cancelled"), "junk"],
    )

    tasks, warnings, count = discover_qoder_scheduled_tasks(user_data)

    assert count == 3
    assert [task.source_id for task in tasks] == ["qoder:schedule:keep"]
    assert len(warnings) == 1


# --------------------------------------------------------------------------
# v2 lifecycle fallback derived from the legacy status field
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected_lifecycle", "expected_enabled"),
    [("pending", "active", True), ("PENDING", "active", True)],
    ids=["pending", "pending-uppercase"],
)
def test_pending_status_derives_an_importable_lifecycle(
    tmp_path: Path,
    status: str,
    expected_lifecycle: str,
    expected_enabled: bool,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("s", lifecycle="", status=status)])

    task = _single(user_data)

    assert task.metadata["source_lifecycle"] == expected_lifecycle
    assert task.enabled is expected_enabled


@pytest.mark.parametrize(
    ("status", "expected_lifecycle"),
    [
        ("running", "completed"),
        ("completed", "completed"),
        ("failed", "completed"),
        ("cancelled", "cancelled"),
    ],
    ids=["running", "completed", "failed", "cancelled"],
)
def test_terminal_statuses_collapse_to_a_known_lifecycle(
    tmp_path: Path,
    status: str,
    expected_lifecycle: str,
) -> None:
    """A terminal status must be *recognized*, not fall through to unknown.

    Falling through would also drop the entry, but it would additionally
    emit an "unknown lifecycle" warning telling an operator the store is
    malformed when it is not.  Asserting silence plus the derived value is
    what distinguishes the two paths.
    """
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("s", lifecycle="", status=status)])

    tasks, warnings = _discover(user_data)

    assert tasks == []
    assert warnings == []
    assert (
        qoder_schedules._source_lifecycle({"status": status}, version=2)
        == expected_lifecycle
    )


@pytest.mark.parametrize("status", ["", "weird-state"], ids=["blank", "weird"])
def test_unrecognized_status_yields_an_empty_lifecycle_and_a_warning(
    tmp_path: Path,
    status: str,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("s", lifecycle="", status=status)])

    warnings = _only_warnings(user_data)

    assert len(warnings) == 1
    assert "unknown lifecycle ''" in warnings[0]


@pytest.mark.parametrize("enabled", [False, True])
def test_pending_status_honours_the_enabled_flag(
    tmp_path: Path,
    enabled: bool,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [_task("s", lifecycle="", status="pending", enabled=enabled)],
    )

    task = _single(user_data)

    expected = "active" if enabled else "paused"
    assert task.metadata["source_lifecycle"] == expected
    assert task.enabled is enabled
    if enabled:
        assert "source_task_paused" not in task.metadata["review_reasons"]
    else:
        assert "source_task_paused" in task.metadata["review_reasons"]


def test_explicit_lifecycle_wins_over_status(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [_task("s", lifecycle="paused", status="completed")],
    )

    task = _single(user_data)

    assert task.metadata["source_lifecycle"] == "paused"
    assert task.enabled is False
    assert "source_task_paused" in task.metadata["review_reasons"]


def test_lifecycle_text_is_bounded_and_lowercased(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        qoder_schedules,
        "_MAX_SMALL_METADATA_STRING_CHARS",
        4,
    )
    user_data = tmp_path / "User"
    # Truncation turns "activeXYZ" into "acti", an unknown lifecycle.
    _write_v2(user_data, [_task("s", lifecycle="activeXYZ")])

    warnings = _only_warnings(user_data)

    assert len(warnings) == 1
    assert "unknown lifecycle 'acti'" in warnings[0]


# --------------------------------------------------------------------------
# prompt source precedence and review metadata
# --------------------------------------------------------------------------


def test_prompt_field_wins_over_payload_message(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [_task("p", prompt="real prompt", payload={"message": "ignored"})],
    )

    task = _single(user_data)

    assert task.prompt == "real prompt"
    assert "payload" not in json.dumps(task.metadata)


def test_payload_message_is_used_when_prompt_is_blank(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [_task("p", prompt="   ", payload={"message": "from payload"})],
    )

    task = _single(user_data)

    assert task.prompt == "from payload"


@pytest.mark.parametrize(
    ("prompt", "payload"),
    [
        (None, {"message": None}),
        ("", {"message": 7}),
        ("", {"message": ["a"]}),
        ("", "not-a-dict"),
        (5, None),
        ("", {}),
        ("", None),
    ],
    ids=[
        "both-none",
        "message-int",
        "message-list",
        "payload-string",
        "prompt-int",
        "payload-empty",
        "payload-missing",
    ],
)
def test_unusable_prompt_sources_stay_empty(
    tmp_path: Path,
    prompt: Any,
    payload: Any,
) -> None:
    user_data = tmp_path / "User"
    overrides: dict[str, Any] = {"prompt": prompt}
    if payload is not None:
        overrides["payload"] = payload
    _write_v2(user_data, [_task("p", **overrides)])

    tasks, _warnings = _discover(user_data)

    assert len(tasks) == 1
    assert tasks[0].prompt == ""


def test_control_characters_in_a_prompt_make_it_unexecutable(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("p", prompt="rm -rf\x1b[31m now")])

    task = _single_retained(user_data)

    assert task.prompt == ""
    assert task.schedule_type == "unsupported"
    assert task.metadata["unsupported_reason"] == "source_prompt_unsafe"
    assert task.metadata["schedule_review_reason"] == "source_prompt_unsafe"
    assert task.metadata["prompt_audit"]["disposition"] == "omitted"
    assert "\x1b" not in json.dumps(task.metadata)


def test_title_is_normalized_and_audited(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("t", title="  multi   space\x07title  ")])

    task = _single(user_data)

    assert task.name == "multi space title"
    audit = task.metadata["title_audit"]
    assert audit["disposition"] == "normalized_or_truncated"
    assert audit["original_chars"] == len("  multi   space\x07title  ")
    assert "source_title_normalized" in task.metadata["review_reasons"]


def test_long_title_is_truncated_to_the_fallback_free_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(qoder_schedules, "_MAX_TITLE_CHARS", 12)
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("t", title="0123456789abcdefghijkl")])

    task = _single(user_data)

    assert len(task.name) == 12
    assert task.metadata["title_audit"]["disposition"] == (
        "normalized_or_truncated"
    )


def test_whitespace_title_falls_back_and_is_audited(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("t-9", title="   ")])

    task = _single(user_data)

    assert task.name == "Qoder schedule t-9"
    assert "source_title_normalized" in task.metadata["review_reasons"]
    assert task.metadata["title_audit"]["original_chars"] == 3


@pytest.mark.parametrize(
    "title",
    ["", None, 7, ["a"]],
    ids=["empty", "none", "int", "list"],
)
def test_absent_title_falls_back_without_an_audit(
    tmp_path: Path,
    title: Any,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("t-9", title=title)])

    task = _single(user_data)

    assert task.name == "Qoder schedule t-9"
    assert "title_audit" not in task.metadata
    assert "source_title_normalized" not in task.metadata["review_reasons"]


def test_goal_mode_adds_a_review_reason(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("g", goalEnabled=True)])

    task = _single(user_data)

    assert task.metadata["source_goal_enabled"] is True
    assert "goal_mode_compatibility_review" in task.metadata["review_reasons"]


@pytest.mark.parametrize(
    "goal",
    [False, None, "true", 1, [True]],
    ids=["false", "none", "string", "int", "list"],
)
def test_only_a_true_goal_flag_adds_a_review_reason(
    tmp_path: Path,
    goal: Any,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("g", goalEnabled=goal)])

    task = _single(user_data)

    assert task.metadata["source_goal_enabled"] is False
    assert "goal_mode_compatibility_review" not in (
        task.metadata["review_reasons"]
    )


def test_model_field_adds_a_compatibility_review(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("m", model="qwen-max")])

    task = _single(user_data)

    assert task.metadata["source_model"] == "qwen-max"
    assert "model_compatibility_review" in task.metadata["review_reasons"]


def test_review_reasons_are_deduplicated_in_order(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [
            _task(
                "r",
                lifecycle="paused",
                enabled=False,
                model="qwen-max",
                goalEnabled=True,
                executionTarget={"kind": "existingSession"},
                workspacePath="relative/dir",
            ),
        ],
    )

    task = _single(user_data)

    reasons = task.metadata["review_reasons"]
    assert reasons == [
        "activation_requires_user_review",
        "source_task_paused",
        "workspace_path_not_absolute",
        "model_compatibility_review",
        "goal_mode_compatibility_review",
        "legacy_existing_session_target_not_preserved",
    ]
    assert len(reasons) == len(set(reasons))


# --------------------------------------------------------------------------
# execution target preservation
# --------------------------------------------------------------------------


def test_execution_target_keeps_only_known_identity_fields(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [
            _task(
                "e",
                executionTarget={
                    "kind": "existingSession",
                    "sessionId": "s-1",
                    "questTaskId": "q-1",
                    "nested": {"secret": "do-not-copy"},
                    "history": [1, 2, 3],
                },
            ),
        ],
    )

    task = _single(user_data)

    assert task.metadata["source_execution_target"] == {
        "kind": "existingSession",
        "sessionId": "s-1",
        "questTaskId": "q-1",
    }
    assert "do-not-copy" not in json.dumps(task.metadata)
    assert (
        "legacy_existing_session_target_not_preserved"
        in task.metadata["review_reasons"]
    )


@pytest.mark.parametrize(
    ("target", "expected", "flags_legacy"),
    [
        ({"kind": "newSession"}, {"kind": "newSession"}, False),
        ({"sessionId": "s-2"}, {"sessionId": "s-2"}, False),
        ({"questTaskId": "q-2"}, {"questTaskId": "q-2"}, False),
        ({}, {}, False),
        ("existingSession", {}, False),
        (None, {}, False),
        (7, {}, False),
        (["existingSession"], {}, False),
        ({"kind": 5}, {}, False),
        ({"kind": "", "sessionId": 9}, {}, False),
    ],
    ids=[
        "new-session",
        "session-only",
        "quest-only",
        "empty-dict",
        "string",
        "none",
        "int",
        "list",
        "non-string-kind",
        "blank-and-non-string",
    ],
)
def test_execution_target_normalization_drops_unknown_shapes(
    tmp_path: Path,
    target: Any,
    expected: dict[str, str],
    flags_legacy: bool,
) -> None:
    user_data = tmp_path / "User"
    overrides: dict[str, Any] = {}
    if target is not None:
        overrides["executionTarget"] = target
    _write_v2(user_data, [_task("e", **overrides)])

    task = _single(user_data)

    assert task.metadata["source_execution_target"] == expected
    has_legacy = (
        "legacy_existing_session_target_not_preserved"
        in task.metadata["review_reasons"]
    )
    assert has_legacy is flags_legacy


def test_execution_target_helper_is_directly_bounded() -> None:
    assert qoder_schedules._safe_execution_target({"kind": "k" * 200}) == {
        "kind": "k" * 64,
    }
    assert qoder_schedules._safe_execution_target("nope") == {}


def test_execution_target_control_characters_are_replaced(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [_task("e", executionTarget={"kind": "new\x00Session"})],
    )

    task = _single(user_data)

    assert task.metadata["source_execution_target"] == {
        "kind": "new Session",
    }


# --------------------------------------------------------------------------
# metadata provenance
# --------------------------------------------------------------------------


def test_metadata_records_store_provenance(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [
            _task(
                "prov",
                source="slash",
                createdAt="2026-08-18T00:00:00Z",
                updatedAt="2026-08-19T00:00:00Z",
                nextRunAt="2026-08-20T00:00:00Z",
                ownerAuthority="local",
                ownerAccountId="acct-1",
                workspaceType="folder",
                targetRemoteAuthority="ssh-remote+host",
                status="pending",
            ),
        ],
    )

    task = _single(user_data)
    metadata = task.metadata

    assert metadata["provider"] == "qoder"
    assert metadata["source_store_version"] == 2
    assert metadata["source_store_path"].endswith("tasks.v2.json")
    assert metadata["source_task_id"] == "prov"
    assert metadata["source"] == "slash"
    assert metadata["created_at"] == "2026-08-18T00:00:00Z"
    assert metadata["updated_at"] == "2026-08-19T00:00:00Z"
    assert metadata["source_next_run_at"] == "2026-08-20T00:00:00Z"
    assert metadata["source_owner_authority"] == "local"
    assert metadata["source_owner_account_id"] == "acct-1"
    assert metadata["source_workspace_type"] == "folder"
    assert metadata["source_status"] == "pending"
    assert metadata["review_required"] is True
    assert metadata["target_default_enabled"] is False


def test_next_fire_at_is_used_when_next_run_at_is_absent(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("prov", nextFireAt="2026-08-21T00:00:00Z")])

    task = _single(user_data)

    assert task.metadata["source_next_run_at"] == "2026-08-21T00:00:00Z"


def test_source_schedule_records_the_v2_definition(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    repeat = {
        "frequency": "weekly",
        "time": "08:30",
        "weekdays": [3, 1, "x", 200, None, True],
        "minutes": 15,
        "minute": 7,
        "nested": {"a": 1},
    }
    _write_v2(
        user_data,
        [
            _task(
                "sched",
                schedule={
                    "startAt": _START,
                    "timezone": "UTC",
                    "repeat": repeat,
                    "extra": "dropped",
                },
            ),
        ],
    )

    task = _single_retained(user_data)

    assert task.metadata["source_schedule"] == {
        "startAt": _START,
        "timezone": "UTC",
        "repeat": {
            "frequency": "weekly",
            "minutes": 15,
            "minute": 7,
            "time": "08:30",
            "weekdays": [3, 1],
        },
    }
    assert "extra" not in json.dumps(task.metadata["source_schedule"])
    assert "nested" not in json.dumps(task.metadata["source_schedule"])


def test_out_of_range_repeat_numbers_are_dropped_from_the_record(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(
        user_data,
        [
            _task(
                "sched",
                schedule={
                    "startAt": _START,
                    "timezone": "UTC",
                    "repeat": {
                        "frequency": "interval",
                        "minutes": 10_000_001,
                        "minute": -10_000_001,
                    },
                },
            ),
        ],
    )

    task = _single_retained(user_data)

    assert task.metadata["source_schedule"]["repeat"] == {
        "frequency": "interval",
    }
    assert task.metadata["schedule_review_reason"] == (
        "invalid_interval_minutes"
    )


def test_source_schedule_without_a_definition_is_empty(
    tmp_path: Path,
) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("sched", schedule=None)])

    tasks, _warnings = _discover(user_data)

    assert len(tasks) == 1
    assert tasks[0].metadata["source_schedule"] == {}


def test_v2_has_no_legacy_store_flag(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("v2only")])

    task = _single(user_data)

    assert "legacy_store" not in task.metadata
    assert "legacy_v1_definition" not in task.metadata["review_reasons"]


def test_staged_task_is_never_enabled_by_default(tmp_path: Path) -> None:
    user_data = tmp_path / "User"
    _write_v2(user_data, [_task("inert", enabled=True)])

    task = _single(user_data)

    assert task.metadata["target_default_enabled"] is False
    assert task.metadata["review_required"] is True
    assert task.metadata["review_reasons"][0] == (
        "activation_requires_user_review"
    )
