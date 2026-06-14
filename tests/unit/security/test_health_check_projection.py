# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.security.integrity_protection import (
    run_confirmed_health_fix,
    run_health_check_scan,
)


def test_health_check_scan_is_read_only(tmp_path: Path) -> None:
    result = run_health_check_scan(tmp_path, deep=False)
    assert result.read_only is True
    assert result.progress == 100
    assert result.check_items
    assert result.scan_id.startswith("health-scan-")


def test_health_check_scan_includes_working_dir_item(tmp_path: Path) -> None:
    result = run_health_check_scan(tmp_path, deep=False)
    item_ids = {item["id"] for item in result.check_items}
    assert "working-dir" in item_ids


def test_health_check_deep_scan_exposes_deep_only_items(tmp_path: Path) -> None:
    shallow = run_health_check_scan(tmp_path, deep=False)
    deep = run_health_check_scan(tmp_path, deep=True)
    shallow_active = {
        item["id"]
        for item in shallow.check_items
        if not item.get("deep_only") and item.get("status") != "skipped"
    }
    deep_active = {
        item["id"] for item in deep.check_items if item.get("status") != "skipped"
    }
    assert len(deep_active) >= len(shallow_active)


def test_health_check_scan_projects_repair_suggestions(tmp_path: Path) -> None:
    result = run_health_check_scan(tmp_path, deep=False)
    assert result.repair_suggestions
    assert result.repair_suggestions[0]["label"] == "repair_missing_console_static_build"


def test_confirmed_health_fix_rejects_unknown_fix_id(tmp_path: Path) -> None:
    result = run_confirmed_health_fix(
        fix_id="not-a-real-fix",
        working_dir=tmp_path,
    )
    assert result.confirmed is False
    assert result.executed is False


def test_confirmed_health_fix_runs_doctor_fix_for_allowed_id(tmp_path: Path) -> None:
    with patch(
        "health_check.fix.run_doctor_fix",
        return_value=0,
    ) as mock_fix:
        result = run_confirmed_health_fix(
            fix_id="ensure-working-dir",
            working_dir=tmp_path,
        )
    assert result.confirmed is True
    assert result.executed is True
    assert result.exit_code == 0
    assert result.fix_id == "ensure-working-dir"
    mock_fix.assert_called_once()
