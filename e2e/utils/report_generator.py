# -*- coding: utf-8 -*-
"""
QwenPaw E2E 测试报告生成器

根据 pytest 测试结果自动生成 Markdown 格式的测试报告。

从 conftest.py 中抽离出来，便于单独维护和复用。
"""
from __future__ import annotations

import logging
from collections import defaultdict, OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import config as app_config

logger = logging.getLogger(__name__)


# 模块名称到中文显示名的映射
MODULE_NAME_MAP = {
    "tests/test_agents.py": "Agents 智能体管理",
    "tests/test_channels.py": "Channels 频道管理",
    "tests/test_chat.py": "Chat 对话",
    "tests/test_cronjobs.py": "CronJobs 定时任务",
    "tests/test_cross_module.py": "Cross Module 跨模块",
    "tests/test_debug.py": "Debug 调试日志",
    "tests/test_environments.py": "Environments 环境变量",
    "tests/test_files.py": "Files 文件管理",
    "tests/test_heartbeat.py": "Heartbeat 心跳检测",
    "tests/test_login.py": "Login 登录",
    "tests/test_mcp.py": "MCP 客户端",
    "tests/test_models.py": "Models 模型管理",
    "tests/test_runtime_config.py": "Runtime Config 运行配置",
    "tests/test_security.py": "Security 安全防护",
    "tests/test_sessions.py": "Sessions 会话管理",
    "tests/test_skill_pool.py": "Skill Pool 技能池",
    "tests/test_skills.py": "Skills 技能管理",
    "tests/test_token_usage.py": "Token Usage 消耗统计",
    "tests/test_tools.py": "Tools 工具管理",
    "tests/test_voice.py": "Voice 语音配置",
}


def _aggregate_module_stats(passed_reports, failed_reports, skipped_reports):
    """按测试文件统计各模块的通过/失败/跳过数。"""
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
    """计算所有报告的总执行耗时（秒）。"""
    try:
        total = 0.0
        for group in report_groups:
            total += sum(getattr(r, "duration", 0) or 0 for r in group)
        return total
    except Exception:
        return 0.0


def _build_header(total, passed, failed, skipped, rerun, pass_rate, duration_seconds):
    """生成报告头部和总览。"""
    duration_minutes = int(duration_seconds // 60)
    duration_secs = int(duration_seconds % 60)

    lines = [
        "# QwenPaw E2E 自动化测试报告\n",
        f"**测试环境**: {app_config.server.base_url}  ",
        f"**执行时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**总耗时**: {duration_minutes} 分 {duration_secs} 秒  ",
        f"**浏览器**: Chromium (Playwright, headless)  ",
        f"**框架**: Pytest + Playwright  ",
        "",
        "---\n",
        "## 📊 测试结果总览\n",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 总用例数 | {total} |",
        f"| ✅ 通过 | {passed} |",
        f"| ❌ 失败 | {failed} |",
        f"| ⏭️ 跳过 | {skipped} |",
        f"| 🔄 重试 | {rerun} |",
        f"| **通过率** | **{pass_rate:.1f}%** |",
        "",
    ]
    return lines


def _build_module_table(module_stats):
    """生成各模块统计表。"""
    lines = [
        "---\n",
        "## ✅ 各模块测试结果\n",
        "| 模块 | 测试文件 | 通过 | 失败 | 跳过 | 状态 |",
        "|------|---------|------|------|------|------|",
    ]
    for module_file in sorted(module_stats.keys()):
        stats = module_stats[module_file]
        module_display = MODULE_NAME_MAP.get(module_file, module_file)
        status = "✅" if stats["failed"] == 0 else "❌"
        lines.append(
            f"| {module_display} | `{module_file}` | "
            f"{stats['passed']} | {stats['failed']} | {stats['skipped']} | {status} |"
        )
    lines.append("")
    return lines


def _build_failed_section(failed_reports, reports_dir: Path):
    """生成失败用例详情。"""
    if not failed_reports:
        return []

    lines = ["---\n", f"## ❌ 失败用例详情（{len(failed_reports)} 个）\n"]

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
        lines.append(f"- **文件**: `{test_file}`")
        if test_class and test_class != test_name:
            lines.append(f"- **类**: `{test_class}`")
        lines.append(f"- **用例ID**: `{nodeid}`")

        # 错误信息
        if hasattr(report, "longreprtext") and report.longreprtext:
            error_lines = report.longreprtext.strip().split("\n")
            short_error = error_lines[-1] if error_lines else "未知错误"
            lines.append(f"- **错误信息**: `{short_error}`")
            lines.append("")
            lines.append("<details>")
            lines.append("<summary>详细堆栈</summary>")
            lines.append("")
            lines.append("```")
            for error_line in error_lines[-15:]:
                lines.append(error_line)
            lines.append("```")
            lines.append("")
            lines.append("</details>")

        # 失败截图
        screenshot_path = getattr(report, "screenshot_path", None)
        if screenshot_path and Path(screenshot_path).exists():
            try:
                relative = Path(screenshot_path).relative_to(reports_dir)
                lines.append("")
                lines.append("**📸 失败截图：**")
                lines.append("")
                lines.append(f"![失败截图]({relative})")
            except ValueError:
                # 截图不在 reports_dir 下，跳过
                pass
        lines.append("")

    return lines


def _build_skipped_section(skipped_reports):
    """生成跳过用例列表。"""
    if not skipped_reports:
        return []

    lines = [
        "---\n",
        f"## ⏭️ 跳过用例（{len(skipped_reports)} 个）\n",
        "| 用例 | 原因 |",
        "|------|------|",
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
    """生成所有用例的截图集锦。"""
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
        f"## 📸 用例执行截图（{len(all_with_screenshots)} 张）\n",
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
            status_icon = "✅" if report.passed else "❌"
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
    根据 pytest terminalreporter 生成 Markdown 测试报告。

    Args:
        terminalreporter: pytest terminalreporter 对象
        reports_dir: 报告输出目录

    Returns:
        本次报告的路径（带时间戳）
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

    # 尾部
    lines += [
        "---\n",
        f"> 报告自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        "> HTML 报告: `reports/pytest-report.html`",
    ]

    report_content = "\n".join(lines)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"test-report-{timestamp}.md"
    report_path.write_text(report_content, encoding="utf-8")

    # 同时写一份固定名称的报告（方便快速查看最新结果）
    latest_path = reports_dir / "test-report-latest.md"
    latest_path.write_text(report_content, encoding="utf-8")

    return report_path
