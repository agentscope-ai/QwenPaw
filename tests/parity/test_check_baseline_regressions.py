# -*- coding: utf-8 -*-
"""Contracts for the deterministic baseline failure gate."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "check_baseline_regressions.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("baseline_checker", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load baseline checker: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_allows_only_the_same_known_failure() -> None:
    checker = _load_checker()
    known = [
        {
            "test_id": "tests.test_example::test_expected",
            "kind": "failure",
            "error_type": "AssertionError",
            "summary_pattern": "expected 1",
        },
    ]
    observed = [
        {
            "test_id": "tests.test_example::test_expected",
            "kind": "failure",
            "error_type": "AssertionError",
            "summary": "expected 1 but received 2",
        },
    ]

    assert checker.compare_failures(known, observed) == []


def test_rejects_a_new_failure() -> None:
    checker = _load_checker()
    observed = [
        {
            "test_id": "tests.test_example::test_new",
            "kind": "failure",
            "error_type": "AssertionError",
            "summary": "new regression",
        },
    ]

    errors = checker.compare_failures([], observed)

    assert errors == [
        "新增失败 tests.test_example::test_new "
        "(failure/AssertionError): new regression",
    ]


def test_rejects_error_kind_or_type_drift() -> None:
    checker = _load_checker()
    known = [
        {
            "test_id": "tests.test_example::test_expected",
            "kind": "failure",
            "error_type": "AssertionError",
            "summary_pattern": "expected",
        },
    ]
    observed = [
        {
            "test_id": "tests.test_example::test_expected",
            "kind": "error",
            "error_type": "RuntimeError",
            "summary": "fixture crashed",
        },
    ]

    errors = checker.compare_failures(known, observed)

    assert errors == [
        "失败类型漂移 tests.test_example::test_expected: "
        "期望 failure/AssertionError，实际 error/RuntimeError",
    ]


def test_resolved_known_failure_does_not_block() -> None:
    checker = _load_checker()
    known = [
        {
            "test_id": "tests.test_example::test_fixed",
            "kind": "failure",
            "error_type": "AssertionError",
            "summary_pattern": "old failure",
        },
    ]

    assert checker.compare_failures(known, []) == []


def test_parses_failure_and_error_from_junit(tmp_path: Path) -> None:
    checker = _load_checker()
    report = tmp_path / "report.xml"
    report.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="suite">
    <testcase classname="tests.test_example" name="test_failed">
      <failure type="AssertionError" message="expected 1">trace</failure>
    </testcase>
    <testcase classname="tests.test_example" name="test_error">
      <error type="RuntimeError" message="fixture crashed">trace</error>
    </testcase>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    assert checker.parse_junit_failures(report) == [
        {
            "test_id": "tests.test_example::test_failed",
            "kind": "failure",
            "error_type": "AssertionError",
            "summary": "expected 1 trace",
        },
        {
            "test_id": "tests.test_example::test_error",
            "kind": "error",
            "error_type": "RuntimeError",
            "summary": "fixture crashed trace",
        },
    ]


def test_evaluates_named_suite_from_manifest(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = tmp_path / "known.yaml"
    manifest.write_text(
        """schema_version: 1
suites:
  backend.full:
    known_failures:
      - test_id: tests.test_example::test_expected
        kind: failure
        error_type: AssertionError
        summary_pattern: expected 1
        blocks_multi_user: false
""",
        encoding="utf-8",
    )
    report = tmp_path / "report.xml"
    report.write_text(
        """<testsuite>
  <testcase classname="tests.test_example" name="test_expected">
    <failure type="AssertionError" message="expected 1 but received 2" />
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    result = checker.evaluate_reports(manifest, {"backend.full": report})

    assert result == {
        "observed_failures": 1,
        "known_failures_observed": 1,
        "resolved_known_failures": 0,
        "new_failures": 0,
        "errors": [],
    }


def test_rejects_report_for_unknown_suite(tmp_path: Path) -> None:
    checker = _load_checker()
    manifest = tmp_path / "known.yaml"
    manifest.write_text("schema_version: 1\nsuites: {}\n", encoding="utf-8")
    report = tmp_path / "report.xml"
    report.write_text("<testsuite />", encoding="utf-8")

    result = checker.evaluate_reports(manifest, {"backend.full": report})

    assert result["new_failures"] == 1
    assert result["errors"] == ["清单中不存在测试套件 backend.full"]


def test_cli_reports_zero_new_failures(tmp_path: Path) -> None:
    manifest = tmp_path / "known.yaml"
    manifest.write_text(
        "schema_version: 1\nsuites:\n  frontend.full:\n    known_failures: []\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.xml"
    report.write_text("<testsuite tests=\"1\"><testcase name=\"ok\" /></testsuite>", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--manifest",
            str(manifest),
            "--result",
            f"frontend.full={report}",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0
    assert "新增失败为 0" in completed.stdout
