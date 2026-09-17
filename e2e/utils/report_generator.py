# -*- coding: utf-8 -*-
"""
QwenPaw E2E Test Report Generator

Automatically generates a Markdown test report from pytest results.

Split out from conftest.py for easier maintenance and reuse.
"""
from __future__ import annotations

import logging
from collections import defaultdict, OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import config as app_config

logger = logging.getLogger(__name__)


# Mapping from module file name to display name
MODULE_NAME_MAP = {
    "tests/test_agents.py": "Agents",
    "tests/test_channels.py": "Channels",
    "tests/test_chat.py": "Chat",
    "tests/test_cronjobs.py": "CronJobs",
    "tests/test_cross_module.py": "Cross Module",
    "tests/test_debug.py": "Debug Logs",
    "tests/test_environments.py": "Environments",
    "tests/test_files.py": "Files",
    "tests/test_heartbeat.py": "Heartbeat",
    "tests/test_login.py": "Login",
    "tests/test_mcp.py": "MCP Clients",
    "tests/test_models.py": "Models",
    "tests/test_runtime_config.py": "Runtime Config",
    "tests/test_security.py": "Security",
    "tests/test_sessions.py": "Sessions",
    "tests/test_skill_pool.py": "Skill Pool",
    "tests/test_skills.py": "Skills",
    "tests/test_token_usage.py": "Token Usage",
    "tests/test_tools.py": "Tools",
    "tests/test_voice.py": "Voice",
}


def _aggregate_module_stats(passed_reports, failed_reports, skipped_reports):
    """Aggregate passed/failed/skipped counts per test file."""
    module_stats = defaultdict(
        lambda: {"passed": 0, "failed": 0, "skipped": 0, "cases": []}
    )

    for report in passed_reports:
        module = report.nodeid.split("::")[0]
        module_stats[module]["passed"] += 1

    for report in failed_reports:
        module = report.nodeid.split("::")[0]
        module_stats[module]["failed"] += 1
        module_stats[module]["cases"].append(report)

    for report in skipped_reports:
        module = report.nodeid.split("::")[0]
        module_stats[module]["skipped"] += 1

    return module_stats


def _calc_total_duration(*report_groups) -> float:
    """Compute the total execution duration across all reports (seconds)."""
    try:
        total = 0.0
        for group in report_groups:
            total += sum(getattr(r, "duration", 0) or 0 for r in group)
        return total
    except Exception:
        return 0.0


def _build_header(total, passed, failed, skipped, rerun, pass_rate, duration_seconds):
    """Build the report header and overview."""
    duration_minutes = int(duration_seconds // 60)
    duration_secs = int(duration_seconds % 60)

    lines = [
        "# QwenPaw E2E Automation Test Report\n",
        f"**Test Environment**: {app_config.server.base_url}  ",
        f"**Execution Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Total Duration**: {duration_minutes}m {duration_secs}s  ",
        f"**Browser**: Chromium (Playwright, headless)  ",
        f"**Framework**: Pytest + Playwright  ",
        "",
        "---\n",
        "## Test Results Overview\n",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total | {total} |",
        f"| Passed | {passed} |",
        f"| Failed | {failed} |",
        f"| Skipped | {skipped} |",
        f"| Reruns | {rerun} |",
        f"| **Pass Rate** | **{pass_rate:.1f}%** |",
        "",
    ]
    return lines


def _build_module_table(module_stats):
    """Build the per-module statistics table."""
    lines = [
        "---\n",
        "## Per-Module Test Results\n",
        "| Module | Test File | Passed | Failed | Skipped | Status |",
        "|--------|-----------|--------|--------|---------|--------|",
    ]
    for module_file in sorted(module_stats.keys()):
        stats = module_stats[module_file]
        module_display = MODULE_NAME_MAP.get(module_file, module_file)
        status = "OK" if stats["failed"] == 0 else "FAIL"
        lines.append(
            f"| {module_display} | `{module_file}` | "
            f"{stats['passed']} | {stats['failed']} | {stats['skipped']} | {status} |"
        )
    lines.append("")
    return lines


def _build_failed_section(failed_reports, reports_dir: Path):
    """Build the failed-test details section."""
    if not failed_reports:
        return []

    lines = ["---\n", f"## Failed Tests ({len(failed_reports)})\n"]

    for idx, report in enumerate(failed_reports, 1):
        nodeid = report.nodeid
        parts = nodeid.split("::")
        test_file = parts[0] if len(parts) > 0 else ""
        test_class = parts[1] if len(parts) > 1 else ""
        if len(parts) > 2:
            test_name = parts[2].split("[")[0]
        elif len(parts) > 1:
            test_name = parts[1].split("[")[0]
        else:
            test_name = ""

        lines.append(f"### {idx}. {test_name}\n")
        lines.append(f"- **File**: `{test_file}`")
        if test_class and test_class != test_name:
            lines.append(f"- **Class**: `{test_class}`")
        lines.append(f"- **Test ID**: `{nodeid}`")

        # Error message
        if hasattr(report, "longreprtext") and report.longreprtext:
            error_lines = report.longreprtext.strip().split("\n")
            short_error = error_lines[-1] if error_lines else "Unknown error"
            lines.append(f"- **Error**: `{short_error}`")
            lines.append("")
            lines.append("<details>")
            lines.append("<summary>Full stack trace</summary>")
            lines.append("")
            lines.append("```")
            for error_line in error_lines[-15:]:
                lines.append(error_line)
            lines.append("```")
            lines.append("")
            lines.append("</details>")

        # Failure screenshot
        screenshot_path = getattr(report, "screenshot_path", None)
        if screenshot_path and Path(screenshot_path).exists():
            try:
                relative = Path(screenshot_path).relative_to(reports_dir)
                lines.append("")
                lines.append("**Failure screenshot:**")
                lines.append("")
                lines.append(f"![failure screenshot]({relative})")
            except ValueError:
                # Screenshot is not under reports_dir; skip.
                pass
        lines.append("")

    return lines


def _build_skipped_section(skipped_reports):
    """Build the skipped-tests list."""
    if not skipped_reports:
        return []

    lines = [
        "---\n",
        f"## Skipped Tests ({len(skipped_reports)})\n",
        "| Test | Reason |",
        "|------|--------|",
    ]
    for report in skipped_reports:
        reason = ""
        if hasattr(report, "longreprtext") and report.longreprtext:
            reason = report.longreprtext.strip().split("\n")[-1]
        elif hasattr(report, "wasxfail"):
            reason = report.wasxfail
        lines.append(f"| `{report.nodeid}` | {reason} |")
    lines.append("")
    return lines


def _build_screenshot_section(passed_reports, failed_reports, reports_dir: Path):
    """Build a screenshot gallery for all tests."""
    all_with_screenshots = [
        r
        for r in (list(passed_reports) + list(failed_reports))
        if getattr(r, "screenshot_path", None)
        and Path(getattr(r, "screenshot_path", "")).exists()
    ]
    if not all_with_screenshots:
        return []

    lines = [
        "---\n",
        f"## Test Execution Screenshots ({len(all_with_screenshots)})\n",
    ]

    screenshot_by_module: "OrderedDict[str, list]" = OrderedDict()
    for report in all_with_screenshots:
        module = report.nodeid.split("::")[0]
        screenshot_by_module.setdefault(module, []).append(report)

    for module, reports in screenshot_by_module.items():
        module_display = MODULE_NAME_MAP.get(module, module)
        lines.append(f"### {module_display}\n")
        for report in reports:
            parts = report.nodeid.split("::")
            test_name = parts[-1].split("[")[0] if parts else report.nodeid
            status_icon = "OK" if report.passed else "FAIL"
            try:
                relative = Path(report.screenshot_path).relative_to(reports_dir)
            except ValueError:
                continue
            lines.append(f"**{status_icon} {test_name}**\n")
            lines.append(f"![{test_name}]({relative})\n")
        lines.append("")

    return lines


def generate_markdown_report(terminalreporter, reports_dir: Path) -> Path:
    """
    Generate a Markdown test report from a pytest terminalreporter.

    Args:
        terminalreporter: pytest terminalreporter object
        reports_dir: Output directory for the report

    Returns:
        Path to the generated report (with timestamp)
    """
    reports_dir.mkdir(parents=True, exist_ok=True)

    passed_reports = terminalreporter.getreports("passed")
    failed_reports = terminalreporter.getreports("failed")
    skipped_reports = terminalreporter.getreports("skipped")
    rerun_reports = (
        terminalreporter.getreports("rerun")
        if hasattr(terminalreporter, "getreports")
        else []
    )

    passed_count = len(passed_reports)
    failed_count = len(failed_reports)
    skipped_count = len(skipped_reports)
    rerun_count = len(rerun_reports)
    total = passed_count + failed_count + skipped_count
    pass_rate = (passed_count / total * 100) if total > 0 else 0

    module_stats = _aggregate_module_stats(
        passed_reports, failed_reports, skipped_reports
    )
    duration_seconds = _calc_total_duration(
        passed_reports, failed_reports, skipped_reports
    )

    lines: list[str] = []
    lines += _build_header(
        total, passed_count, failed_count, skipped_count,
        rerun_count, pass_rate, duration_seconds,
    )
    lines += _build_module_table(module_stats)
    lines += _build_failed_section(failed_reports, reports_dir)
    lines += _build_skipped_section(skipped_reports)
    lines += _build_screenshot_section(passed_reports, failed_reports, reports_dir)

    # Footer
    lines += [
        "---\n",
        f"> Report auto-generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        "> HTML report: `reports/pytest-report.html`",
    ]

    report_content = "\n".join(lines)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"test-report-{timestamp}.md"
    report_path.write_text(report_content, encoding="utf-8")

    # Also write a fixed-name report for quick access to the latest result.
    latest_path = reports_dir / "test-report-latest.md"
    latest_path.write_text(report_content, encoding="utf-8")

    return report_path
