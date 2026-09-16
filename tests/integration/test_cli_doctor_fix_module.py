# -*- coding: utf-8 -*-
"""Integration tests for CLI doctor-fix internals.

Covers src/qwenpaw/cli/doctor_fix_runner.py (430 uncovered lines):
fix-id parsing, path allowlists, jobs.json cron normalization,
agent.json validity, atomic writes, backup markers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_parse_only_defaults_to_safe_ids() -> None:
    """Empty ``only`` returns sorted safe fix ids."""
    from qwenpaw.cli.doctor_fix_runner import (
        SAFE_FIX_IDS,
        _parse_only,
    )

    assert _parse_only(None) == sorted(SAFE_FIX_IDS)
    assert _parse_only("") == sorted(SAFE_FIX_IDS)
    assert _parse_only("   ") == sorted(SAFE_FIX_IDS)


@pytest.mark.integration
@pytest.mark.p1
def test_parse_only_explicit_ids() -> None:
    """Comma-separated ids parse in order, whitespace stripped."""
    from qwenpaw.cli.doctor_fix_runner import _parse_only

    result = _parse_only("ensure-working-dir, validate-all-jobs-json")
    assert result == ["ensure-working-dir", "validate-all-jobs-json"]


@pytest.mark.integration
@pytest.mark.p1
def test_parse_only_rejects_unknown_id() -> None:
    """Unknown fix ids raise ValueError listing known ids."""
    from qwenpaw.cli.doctor_fix_runner import _parse_only

    with pytest.raises(ValueError, match="unknown fix id"):
        _parse_only("nonexistent-fix")


@pytest.mark.integration
@pytest.mark.p1
def test_fix_id_sets_partition() -> None:
    """Fix-id categories are disjoint and union to ALL_FIX_IDS."""
    from qwenpaw.cli.doctor_fix_runner import (
        ALL_FIX_IDS,
        NONINTERACTIVE_FIX_IDS,
        READONLY_FIX_IDS,
        RISKY_FIX_IDS,
        SAFE_FIX_IDS,
        SYNC_FIX_IDS,
    )

    groups = [SAFE_FIX_IDS, READONLY_FIX_IDS, SYNC_FIX_IDS, RISKY_FIX_IDS]
    union = set()
    for g in groups:
        assert not union & g, "categories must be disjoint"
        union |= g
    assert union == ALL_FIX_IDS
    assert (
        NONINTERACTIVE_FIX_IDS
        == SAFE_FIX_IDS | READONLY_FIX_IDS | SYNC_FIX_IDS
    )


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_under_working_dir(tmp_path: Path) -> None:
    """Workspace inside working dir passes; outside fails."""
    from qwenpaw.cli.doctor_fix_runner import workspace_under_working_dir

    wd = tmp_path / "wd"
    wd.mkdir()
    inside = wd / "agents" / "default"
    inside.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    assert workspace_under_working_dir(inside, wd) is True
    assert workspace_under_working_dir(outside, wd) is False


@pytest.mark.integration
@pytest.mark.p1
def test_path_allowed_for_write(tmp_path: Path) -> None:
    """Writes allowed under wd, rejected outside."""
    from qwenpaw.cli.doctor_fix_runner import path_allowed_for_write

    wd = tmp_path / "wd"
    wd.mkdir()
    target = wd / "sub" / "file.json"
    target.parent.mkdir(parents=True)
    target.touch()
    outside = tmp_path / "outside.json"
    outside.touch()

    assert path_allowed_for_write(target, wd) is True
    assert path_allowed_for_write(outside, wd) is False


@pytest.mark.integration
@pytest.mark.p1
def test_relative_under_wd(tmp_path: Path) -> None:
    """Relative path computed under working dir."""
    from qwenpaw.cli.doctor_fix_runner import _relative_under_wd

    wd = tmp_path / "wd"
    (wd / "a" / "b").mkdir(parents=True)
    target = wd / "a" / "b" / "c.txt"
    target.touch()
    rel = _relative_under_wd(target, wd)
    assert rel == Path("a/b/c.txt")


@pytest.mark.integration
@pytest.mark.p1
def test_normalize_cron_fields_no_jobs() -> None:
    """Dict without jobs list returns unchanged False."""
    from qwenpaw.cli.doctor_fix_runner import (
        _normalize_cron_fields_in_jobs_dict,
    )

    data: dict = {"jobs": "not-a-list"}
    assert _normalize_cron_fields_in_jobs_dict(data) is False
    assert data == {"jobs": "not-a-list"}


@pytest.mark.integration
@pytest.mark.p1
def test_normalize_cron_fields_valid_cron_unchanged() -> None:
    """Already-normal cron expression produces no change."""
    from qwenpaw.cli.doctor_fix_runner import (
        _normalize_cron_fields_in_jobs_dict,
    )

    data: dict = {
        "jobs": [
            {
                "id": "j1",
                "schedule": {"cron": "0 8 * * *", "timezone": "UTC"},
            },
        ],
    }
    changed = _normalize_cron_fields_in_jobs_dict(data)
    assert changed is False
    jobs = data["jobs"]
    assert isinstance(jobs, list)
    assert jobs[0]["schedule"]["cron"] == "0 8 * * *"


@pytest.mark.integration
@pytest.mark.p1
def test_normalize_cron_fields_invalid_cron_raises() -> None:
    """Invalid cron expression raises ValueError with job id."""
    from qwenpaw.cli.doctor_fix_runner import (
        _normalize_cron_fields_in_jobs_dict,
    )

    data = {
        "jobs": [
            {"id": "bad", "schedule": {"cron": "not-cron"}},
        ],
    }
    with pytest.raises(ValueError, match="bad"):
        _normalize_cron_fields_in_jobs_dict(data)


@pytest.mark.integration
@pytest.mark.p1
def test_normalize_cron_skips_non_dict_entries() -> None:
    """Non-dict job entries and non-dict schedules are skipped."""
    from qwenpaw.cli.doctor_fix_runner import (
        _normalize_cron_fields_in_jobs_dict,
    )

    data = {"jobs": ["junk", {"id": "x"}, {"schedule": 42}]}
    assert _normalize_cron_fields_in_jobs_dict(data) is False


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_agent_json_valid_true(tmp_path: Path) -> None:
    """A minimal valid agent profile passes validation."""
    from qwenpaw.cli.doctor_fix_runner import _workspace_agent_json_valid

    path = tmp_path / "agent.json"
    minimal = {"id": "default", "name": "Default Agent"}
    path.write_text(json.dumps(minimal), encoding="utf-8")
    assert _workspace_agent_json_valid(path) is True


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_agent_json_invalid_json(tmp_path: Path) -> None:
    """Broken JSON returns False."""
    from qwenpaw.cli.doctor_fix_runner import _workspace_agent_json_valid

    path = tmp_path / "agent.json"
    path.write_text("{ not json", encoding="utf-8")
    assert _workspace_agent_json_valid(path) is False


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_agent_json_non_dict(tmp_path: Path) -> None:
    """Valid JSON that is not an object returns False."""
    from qwenpaw.cli.doctor_fix_runner import _workspace_agent_json_valid

    path = tmp_path / "agent.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert _workspace_agent_json_valid(path) is False


@pytest.mark.integration
@pytest.mark.p1
def test_workspace_agent_json_missing_file(tmp_path: Path) -> None:
    """Missing file returns False (OSError caught)."""
    from qwenpaw.cli.doctor_fix_runner import _workspace_agent_json_valid

    assert _workspace_agent_json_valid(tmp_path / "nope.json") is False


@pytest.mark.integration
@pytest.mark.p1
def test_atomic_write_text(tmp_path: Path) -> None:
    """Atomic write lands content and cleans the temp file."""
    from qwenpaw.cli.doctor_fix_runner import _atomic_write_text

    path = tmp_path / "deep" / "target.json"
    _atomic_write_text(path, '{"ok": true}')
    assert path.read_text(encoding="utf-8") == '{"ok": true}'
    # No leftover temp files.
    leftovers = list(tmp_path.rglob("*.tmp.*"))
    assert not leftovers


@pytest.mark.integration
@pytest.mark.p1
def test_backup_one_file_copies_existing(tmp_path: Path) -> None:
    """Existing file is copied into the session backup tree."""
    from qwenpaw.cli.doctor_fix_runner import _backup_one_file

    wd = tmp_path / "wd"
    wd.mkdir()
    source = wd / "jobs.json"
    source.write_text("{}", encoding="utf-8")
    session_files = tmp_path / "session" / "files"

    _backup_one_file(session_files, source, wd)
    assert (session_files / "jobs.json").read_text(encoding="utf-8") == "{}"


@pytest.mark.integration
@pytest.mark.p1
def test_backup_one_file_missing_marker(tmp_path: Path) -> None:
    """Missing source writes a .MISSING marker instead of copying."""
    from qwenpaw.cli.doctor_fix_runner import _backup_one_file

    wd = tmp_path / "wd"
    wd.mkdir()
    missing = wd / "gone.json"
    session_files = tmp_path / "session" / "files"

    _backup_one_file(session_files, missing, wd)
    marker = session_files / "gone.json.MISSING"
    assert marker.exists()


@pytest.mark.integration
@pytest.mark.p1
def test_effective_cli_api_host_port_explicit() -> None:
    """Explicit overrides win over saved last-api values."""
    from qwenpaw.cli.doctor_fix_runner import _effective_cli_api_host_port

    host, port = _effective_cli_api_host_port("0.0.0.0", 9999)
    assert host == "0.0.0.0"
    assert port == 9999


@pytest.mark.integration
@pytest.mark.p1
def test_planned_fix_dataclass() -> None:
    """PlannedFix is a frozen dataclass with expected fields."""
    from qwenpaw.cli.doctor_fix_runner import PlannedFix

    fix = PlannedFix(
        fix_id="ensure-working-dir",
        description="desc",
        paths_to_backup=(),
        apply_fn=lambda: None,
    )
    assert fix.fix_id == "ensure-working-dir"
    assert not fix.paths_to_backup
