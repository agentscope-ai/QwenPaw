#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reject failures that are absent from the reviewed baseline allowlist."""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml


Failure = Mapping[str, Any]


def _brief(value: object) -> str:
    return " ".join(str(value or "").split())[:240]


def compare_failures(
    known_failures: Sequence[Failure],
    observed_failures: Sequence[Failure],
) -> list[str]:
    """Return regressions while allowing resolved reviewed failures."""
    known_by_id = {str(item["test_id"]): item for item in known_failures}
    errors: list[str] = []

    for observed in observed_failures:
        test_id = str(observed["test_id"])
        kind = str(observed.get("kind", "failure"))
        error_type = str(observed.get("error_type", ""))
        summary = _brief(observed.get("summary", ""))
        known = known_by_id.get(test_id)
        if known is None:
            errors.append(
                f"新增失败 {test_id} ({kind}/{error_type}): {summary}",
            )
            continue

        expected_kind = str(known.get("kind", "failure"))
        expected_type = str(known.get("error_type", ""))
        if kind != expected_kind or error_type != expected_type:
            errors.append(
                f"失败类型漂移 {test_id}: 期望 "
                f"{expected_kind}/{expected_type}，实际 {kind}/{error_type}",
            )
            continue

        pattern = str(known.get("summary_pattern", ""))
        if pattern and re.search(pattern, summary) is None:
            errors.append(
                f"错误摘要漂移 {test_id}: 不匹配 /{pattern}/，实际 {summary}",
            )

    return errors


def parse_junit_failures(report_path: Path) -> list[dict[str, str]]:
    """Read assertion failures and fixture/runtime errors from JUnit XML."""
    root = ET.parse(report_path).getroot()
    observed: list[dict[str, str]] = []
    for testcase in root.iter("testcase"):
        classname = testcase.attrib.get("classname", "").strip()
        name = testcase.attrib.get("name", "").strip()
        test_id = f"{classname}::{name}" if classname else name
        for kind in ("failure", "error"):
            node = testcase.find(kind)
            if node is None:
                continue
            summary = _brief(
                " ".join(
                    part
                    for part in (
                        node.attrib.get("message", ""),
                        node.text or "",
                    )
                    if part
                ),
            )
            observed.append(
                {
                    "test_id": test_id,
                    "kind": kind,
                    "error_type": node.attrib.get("type", ""),
                    "summary": summary,
                },
            )
            break
    return observed


def evaluate_reports(
    manifest_path: Path,
    reports: Mapping[str, Path],
) -> dict[str, int | list[str]]:
    """Evaluate named JUnit reports against their reviewed suite baselines."""
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    suites = manifest.get("suites", {})
    errors: list[str] = []
    observed_count = 0
    known_observed_count = 0
    resolved_count = 0

    for suite_id, report_path in reports.items():
        suite = suites.get(suite_id)
        if suite is None:
            errors.append(f"清单中不存在测试套件 {suite_id}")
            continue

        known = suite.get("known_failures", [])
        observed = parse_junit_failures(report_path)
        observed_count += len(observed)
        suite_errors = compare_failures(known, observed)
        errors.extend(f"[{suite_id}] {error}" for error in suite_errors)

        known_ids = {str(item["test_id"]) for item in known}
        observed_ids = {str(item["test_id"]) for item in observed}
        known_observed_count += len(known_ids & observed_ids)
        resolved_count += len(known_ids - observed_ids)

    return {
        "observed_failures": observed_count,
        "known_failures_observed": known_observed_count,
        "resolved_known_failures": resolved_count,
        "new_failures": len(errors),
        "errors": errors,
    }


def _parse_result(value: str) -> tuple[str, Path]:
    suite_id, separator, report = value.partition("=")
    if not separator or not suite_id or not report:
        raise argparse.ArgumentTypeError("--result 必须使用 suite_id=report.xml 格式")
    return suite_id, Path(report)


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/parity/known_baseline_failures.yaml"),
    )
    parser.add_argument(
        "--result",
        action="append",
        type=_parse_result,
        required=True,
        metavar="SUITE=JUNIT_XML",
    )
    args = parser.parse_args(argv)
    result = evaluate_reports(args.manifest, dict(args.result))

    for error in result["errors"]:
        print(error)
    print(
        "基线检查："
        f"观察失败 {result['observed_failures']}，"
        f"命中既有失败 {result['known_failures_observed']}，"
        f"已修复既有失败 {result['resolved_known_failures']}，"
        f"新增失败为 {result['new_failures']}",
    )
    return 1 if result["new_failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
