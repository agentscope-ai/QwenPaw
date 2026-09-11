# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
# pylint: disable=superfluous-parens
"""Regression tests for ``scripts/run_tests.py`` (issue #7229).

The local test runner used to skip suites and report false success:
``-u`` iterated only ``tests/unit`` subdirectories (dropping root-level
test files), ``-a`` never ran ``tests/contract``, ``-i`` pointed at a
nonexistent ``tests/integrated`` directory and treated it as success.
These tests pin the corrected behaviour.
"""
from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "run_tests.py"


@pytest.fixture(scope="module")
def runner_module():
    """Load scripts/run_tests.py as a module (it is not importable)."""
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_local_test_runner",
        _SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def recorded_calls(runner_module, monkeypatch):
    """Stub pytest out and record which directories the runner invokes."""
    calls: list[str] = []

    def fake_run_pytest(
        project_root,
        test_path,
        coverage=False,
        parallel=False,
    ):
        calls.append(str(test_path))
        return 0

    monkeypatch.setattr(runner_module, "check_pytest", lambda: True)
    monkeypatch.setattr(runner_module, "run_pytest", fake_run_pytest)
    return calls


def test_all_mode_covers_unit_contract_and_integration(
    runner_module,
    recorded_calls,
    monkeypatch,
):
    """``-a`` must execute all three suites, not just unit+integrated."""
    monkeypatch.setattr(sys, "argv", ["run_tests.py", "-a"])
    assert runner_module.main() == 0

    paths = [Path(c) for c in recorded_calls]
    assert (_REPO_ROOT / "tests" / "unit") in paths
    assert (_REPO_ROOT / "tests" / "contract") in paths
    assert (_REPO_ROOT / "tests" / "integration") in paths
    assert len(paths) == 3


def test_unit_mode_runs_complete_unit_tree(
    runner_module,
    recorded_calls,
    monkeypatch,
):
    """``-u`` must run the whole tests/unit tree, root-level files too."""
    monkeypatch.setattr(sys, "argv", ["run_tests.py", "-u"])
    assert runner_module.main() == 0

    paths = [Path(c) for c in recorded_calls]
    # A single invocation covering the entire tree, not one call per
    # subdirectory (the old behaviour that skipped root-level files).
    assert paths == [_REPO_ROOT / "tests" / "unit"]


def test_integrated_flag_targets_tests_integration(
    runner_module,
    recorded_calls,
    monkeypatch,
):
    """``-i`` must point at tests/integration, not tests/integrated."""
    monkeypatch.setattr(sys, "argv", ["run_tests.py", "-i"])
    assert runner_module.main() == 0

    paths = [Path(c) for c in recorded_calls]
    assert paths == [_REPO_ROOT / "tests" / "integration"]
    assert not any("integrated" in c for c in recorded_calls)


def test_missing_suite_reports_error_not_success(
    runner_module,
    tmp_path,
):
    """A missing suite directory must fail loudly, never report success."""
    assert runner_module.run_unit_tests(tmp_path) == 1
    assert runner_module.run_contract_tests(tmp_path) == 1
    assert runner_module.run_integrated_tests(tmp_path) == 1


def test_missing_unit_subdir_reports_error(runner_module, tmp_path):
    """``-u <dir>`` with an unknown subdirectory must fail."""
    assert runner_module.run_unit_tests(tmp_path, subdir="nonexistent") == 1


def test_status_symbols_survive_limited_encodings(runner_module):
    """Printing status symbols must not crash on GBK/CP936 terminals."""
    strict = io.TextIOWrapper(io.BytesIO(), encoding="gbk", errors="strict")
    with pytest.raises(UnicodeEncodeError):
        strict.write("✓ done\n")  # the old failure mode

    buf = io.BytesIO()
    safe = io.TextIOWrapper(buf, encoding="gbk", errors="strict")
    runner_module._make_output_safe(safe)
    safe.write("✓ done ✗ fail ⚠ note ℹ info\n")  # must not raise
    safe.flush()
    assert b"done" in buf.getvalue()
