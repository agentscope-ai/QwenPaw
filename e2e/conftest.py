# -*- coding: utf-8 -*-
"""
QwenPaw E2E 测试框架 - Pytest 配置
"""
from __future__ import annotations

import sys
import os
import time
import logging
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import pytest
from pages.chat_page import ChatPage
from config.settings import config as app_config

# 禁用 pytest-playwright 插件的自动 fixture 注入，使用我们自定义的 fixture
# 这样可以确保 QWENPAW_HEADLESS 环境变量能正确控制浏览器显示模式
pytest_plugins = []

# 从 fixtures 模块导入所有自定义 fixture
# 包括 browser, page, browser_context 等，完全由我们控制
from fixtures import (  # noqa: F401,E402
    playwright_context,
    browser,
    browser_context,
    page,
    api_context,
    chat_page,
    clean_chat_page,
    authenticated_page,
    test_messages,
    test_user_data,
    test_file,
    large_test_file,
    api_url,
    retry_on_failure,
    base_url,
)



# ========== Page Object Fixtures ==========
# 注：通用 fixture（chat_page / clean_chat_page / api_context / page 等）
# 已在 fixtures/__init__.py 中定义。此处仅补充其他模块的 Page Object fixture，
# 按需延迟导入，避免启动期加载所有 Page 类。

def _make_page_fixture(import_path: str, class_name: str):
    """工厂：根据 Page 类生成 fixture（延迟导入）。"""
    def _fixture(page):
        module = __import__(import_path, fromlist=[class_name])
        return getattr(module, class_name)(page)
    _fixture.__name__ = class_name
    return _fixture


channels_page = pytest.fixture(scope="function", name="channels_page")(
    _make_page_fixture("pages.channels_page", "ChannelsPage")
)
sessions_page = pytest.fixture(scope="function", name="sessions_page")(
    _make_page_fixture("pages.sessions_page", "SessionsPage")
)
cronjobs_page = pytest.fixture(scope="function", name="cronjobs_page")(
    _make_page_fixture("pages.cronjobs_page", "CronJobsPage")
)
heartbeat_page = pytest.fixture(scope="function", name="heartbeat_page")(
    _make_page_fixture("pages.heartbeat_page", "HeartbeatPage")
)
backups_page = pytest.fixture(scope="function", name="backups_page")(
    _make_page_fixture("pages.backups_page", "BackupsPage")
)
agent_stats_page = pytest.fixture(scope="function", name="agent_stats_page")(
    _make_page_fixture("pages.agent_stats_page", "AgentStatsPage")
)
acp_page = pytest.fixture(scope="function", name="acp_page")(
    _make_page_fixture("pages.acp_page", "ACPPage")
)


# ========== 业务/数据 Fixtures ==========
@pytest.fixture(scope="function")
def dingtalk_config():
    """
    提供钉钉配置
    
    从环境变量读取配置，支持 CI/CD：
    - DINGTALK_WEBHOOK: 钉钉机器人 Webhook URL
    - DINGTALK_SECRET: 加签密钥
    - DINGTALK_CLIENT_ID: 钉钉应用 Client ID
    - DINGTALK_CLIENT_SECRET: 钉钉应用 Client Secret
    
    Returns:
        配置字典
    """
    return {
        'webhook': os.getenv('DINGTALK_WEBHOOK', ''),
        'secret': os.getenv('DINGTALK_SECRET', ''),
        'client_id': os.getenv('DINGTALK_CLIENT_ID', ''),
        'client_secret': os.getenv('DINGTALK_CLIENT_SECRET', ''),
    }

@pytest.fixture(scope="function")
def dingtalk_test_message():
    """
    提供钉钉测试消息
    
    Returns:
        测试消息字符串
    """
    import time
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    return f"自动化测试消息 - {timestamp}"

# 注：clean_chat_page / test_file / large_test_file 已由 fixtures/__init__.py 统一提供，
# 此处不再重复定义，避免 fixture 冲突导致 pytest 收集/执行异常（尤其是有头模式下）。


# ========== UI Smoke Mock Fixture ==========

@pytest.fixture(scope="function")
def mock_api(page):
    """
    Register all API route mocks for UI smoke tests.

    Intercepts all /api/ requests and returns mock JSON responses,
    so smoke tests only need a frontend dev server running.
    """
    from mocks import register_all
    register_all(page)
    yield page



@pytest.fixture(scope="session", autouse=True)
def warmup_server():
    """
    Session 级别的服务预热

    说明：这里特意不依赖 pytest-playwright 提供的 `playwright` fixture。
    原因：pytest-playwright 内部是基于 asyncio + Playwright Async API 实现的，
    一旦它的 fixture 被触发，就会在主线程创建 asyncio event loop，
    导致后续我们自定义的 `playwright_context`（Sync API）报错：
        "It looks like you are using Playwright Sync API inside the asyncio loop."
    所以这里统一用 Sync API 自行起一个临时 Playwright 实例做预热。

    步骤：
    1. 通过 API 健康检查确认后端可用（最多重试 ~30s）
    2. 访问首页等 DOM/networkidle/关键元素出现
    3. 额外缓冲，让懒加载组件就位

    任何步骤失败都不会阻塞测试（只打 warning），避免预热把整批用例卡住。
    """
    from playwright.sync_api import sync_playwright

    base_url = app_config.server.base_url
    logger = logging.getLogger(__name__)

    with sync_playwright() as pw:
        # ---------- 1. API 健康检查 ----------
        api_ready = False
        api_request = None
        try:
            api_request = pw.request.new_context(base_url=base_url)
            # 候选健康检查路径，逐个尝试，命中即视为后端 ready
            health_paths = ["/api/health", "/healthz", "/api/heartbeat", "/"]
            deadline = time.time() + 30  # 最多等 30s
            while time.time() < deadline and not api_ready:
                for path in health_paths:
                    try:
                        resp = api_request.get(path, timeout=5000)
                        # 2xx/3xx 都视为后端在线
                        if resp.status < 400:
                            api_ready = True
                            logger.info(f"✅ 后端 API 就绪: {path} -> {resp.status}")
                            break
                    except Exception:
                        continue
                if not api_ready:
                    time.sleep(1)
            if not api_ready:
                logger.warning("⚠️  后端 API 健康检查 30s 内未通过，继续尝试预热前端")
        except Exception as e:
            logger.warning(f"⚠️  API 健康检查异常（忽略）: {e}")
        finally:
            if api_request is not None:
                try:
                    api_request.dispose()
                except Exception:
                    pass

        # ---------- 2. 前端页面预热 ----------
        try:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            # 2.1 先访问首页等待 DOM 加载完成
            page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
            # 2.2 再等网络空闲，确保 SPA 异步资源加载完成
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            # 2.3 主动等待面包屑或主要导航出现，作为"前端 ready"的信号
            try:
                page.wait_for_selector(
                    'span[class*=breadcrumbCurrent], button:has-text("Create Agent"), nav, [class*=sider]',
                    timeout=10000,
                )
            except Exception:
                pass
            # 2.4 额外缓冲，让懒加载组件就位
            page.wait_for_timeout(2000)

            logger.info(f"✅ 服务预热完成: {base_url}")

            context.close()
            browser.close()
        except Exception as e:
            logger.warning(f"⚠️  服务预热失败（不阻塞测试）: {e}")

    yield


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """测试结束时的终端摘要 + 自动生成 Markdown 报告"""
    passed = len(terminalreporter.getreports('passed'))
    failed = len(terminalreporter.getreports('failed'))
    skipped = len(terminalreporter.getreports('skipped'))
    total = passed + failed + skipped

    terminalreporter.write_sep("=" * 60)
    terminalreporter.write_line("测试摘要:")
    terminalreporter.write_line(f"  总计：{total}")
    terminalreporter.write_line(f"  通过：{passed}")
    terminalreporter.write_line(f"  失败：{failed}")
    terminalreporter.write_line(f"  跳过：{skipped}")

    if total > 0:
        pass_rate = passed / total * 100
        terminalreporter.write_line(f"  通过率：{pass_rate:.1f}%")
    terminalreporter.write_sep("=" * 60)

    # 自动生成 Markdown 测试报告（已抽离到 utils/report_generator.py）
    try:
        from utils.report_generator import generate_markdown_report
        reports_dir = Path(__file__).parent / "reports"
        report_path = generate_markdown_report(terminalreporter, reports_dir)
        terminalreporter.write_line(f"📄 Markdown 报告已生成: {report_path}")
        terminalreporter.write_line(
            f"📄 最新报告快捷入口: {reports_dir / 'test-report-latest.md'}"
        )
    except Exception as e:
        terminalreporter.write_line(f"⚠️  Markdown 报告生成失败: {e}")


def _generate_markdown_report(terminalreporter, exitstatus, config):
    """根据测试结果自动生成 Markdown 格式的测试报告"""
    from collections import defaultdict
    from datetime import datetime

    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"test-report-{timestamp}.md"

    passed_reports = terminalreporter.getreports('passed')
    failed_reports = terminalreporter.getreports('failed')
    skipped_reports = terminalreporter.getreports('skipped')
    rerun_reports = terminalreporter.getreports('rerun') if hasattr(terminalreporter, 'getreports') else []

    passed_count = len(passed_reports)
    failed_count = len(failed_reports)
    skipped_count = len(skipped_reports)
    rerun_count = len(rerun_reports)
    total = passed_count + failed_count + skipped_count
    pass_rate = (passed_count / total * 100) if total > 0 else 0

    # 按测试文件分组统计
    module_stats = defaultdict(lambda: {"passed": 0, "failed": 0, "skipped": 0, "cases": []})

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

    # 模块名称映射
    module_name_map = {
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
        "tests/test_backups.py": "Backups 备份管理",
        "tests/test_agent_stats.py": "AgentStats 智能体统计",
        "tests/test_acp.py": "ACP 配置管理",
    }

    # 计算执行耗时（兼容 Python 3.14）
    duration_seconds = 0
    try:
        all_reports = passed_reports + failed_reports + skipped_reports
        duration_seconds = sum(getattr(r, 'duration', 0) for r in all_reports)
    except Exception:
        duration_seconds = 0
    duration_minutes = int(duration_seconds // 60)
    duration_secs = int(duration_seconds % 60)

    lines = []
    lines.append("# QwenPaw E2E 自动化测试报告\n")
    lines.append(f"**测试环境**: {app_config.server.base_url}  ")
    lines.append(f"**执行时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"**总耗时**: {duration_minutes} 分 {duration_secs} 秒  ")
    lines.append(f"**浏览器**: Chromium (Playwright, headless)  ")
    lines.append(f"**框架**: Pytest + Playwright  ")
    lines.append("")

    # 总览
    lines.append("---\n")
    lines.append("## 📊 测试结果总览\n")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 总用例数 | {total} |")
    lines.append(f"| ✅ 通过 | {passed_count} |")
    lines.append(f"| ❌ 失败 | {failed_count} |")
    lines.append(f"| ⏭️ 跳过 | {skipped_count} |")
    lines.append(f"| 🔄 重试 | {rerun_count} |")
    lines.append(f"| **通过率** | **{pass_rate:.1f}%** |")
    lines.append("")

    # 各模块测试结果
    lines.append("---\n")
    lines.append("## ✅ 各模块测试结果\n")
    lines.append("| 模块 | 测试文件 | 通过 | 失败 | 跳过 | 状态 |")
    lines.append("|------|---------|------|------|------|------|")

    for module_file in sorted(module_stats.keys()):
        stats = module_stats[module_file]
        module_display = module_name_map.get(module_file, module_file)
        module_total = stats["passed"] + stats["failed"] + stats["skipped"]
        status = "✅" if stats["failed"] == 0 else "❌"
        lines.append(
            f"| {module_display} | `{module_file}` | {stats['passed']} | {stats['failed']} | {stats['skipped']} | {status} |"
        )
    lines.append("")

    # 失败用例详情
    if failed_count > 0:
        lines.append("---\n")
        lines.append(f"## ❌ 失败用例详情（{failed_count} 个）\n")

        for idx, report in enumerate(failed_reports, 1):
            nodeid = report.nodeid
            # 提取文件名、类名、用例名
            parts = nodeid.split("::")
            test_file = parts[0] if len(parts) > 0 else ""
            test_class = parts[1] if len(parts) > 1 else ""
            test_name = parts[2].split("[")[0] if len(parts) > 2 else (parts[1].split("[")[0] if len(parts) > 1 else "")

            lines.append(f"### {idx}. {test_name}\n")
            lines.append(f"- **文件**: `{test_file}`")
            if test_class and test_class != test_name:
                lines.append(f"- **类**: `{test_class}`")
            lines.append(f"- **用例ID**: `{nodeid}`")

            # 提取错误信息
            if hasattr(report, 'longreprtext') and report.longreprtext:
                error_lines = report.longreprtext.strip().split('\n')
                # 取最后几行作为关键错误信息
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

            # 嵌入失败截图
            screenshot_path = getattr(report, 'screenshot_path', None)
            if screenshot_path and Path(screenshot_path).exists():
                relative_screenshot = Path(screenshot_path).relative_to(reports_dir)
                lines.append("")
                lines.append(f"**📸 失败截图：**")
                lines.append("")
                lines.append(f"![失败截图]({relative_screenshot})")
            lines.append("")

    # 跳过用例
    if skipped_count > 0:
        lines.append("---\n")
        lines.append(f"## ⏭️ 跳过用例（{skipped_count} 个）\n")
        lines.append("| 用例 | 原因 |")
        lines.append("|------|------|")
        for report in skipped_reports:
            reason = ""
            if hasattr(report, 'longreprtext') and report.longreprtext:
                reason = report.longreprtext.strip().split('\n')[-1]
            elif hasattr(report, 'wasxfail'):
                reason = report.wasxfail
            lines.append(f"| `{report.nodeid}` | {reason} |")
        lines.append("")

    # 用例执行截图
    all_reports_with_screenshots = [
        r for r in (passed_reports + failed_reports)
        if getattr(r, 'screenshot_path', None) and Path(getattr(r, 'screenshot_path', '')).exists()
    ]
    if all_reports_with_screenshots:
        lines.append("---\n")
        lines.append(f"## 📸 用例执行截图（{len(all_reports_with_screenshots)} 张）\n")

        from collections import OrderedDict
        screenshot_by_module = OrderedDict()
        for report in all_reports_with_screenshots:
            module = report.nodeid.split("::")[0]
            screenshot_by_module.setdefault(module, []).append(report)

        for module, reports in screenshot_by_module.items():
            module_display = module_name_map.get(module, module)
            lines.append(f"### {module_display}\n")
            for report in reports:
                parts = report.nodeid.split("::")
                test_name = parts[-1].split("[")[0] if parts else report.nodeid
                status_icon = "✅" if report.passed else "❌"
                relative_screenshot = Path(report.screenshot_path).relative_to(reports_dir)
                lines.append(f"**{status_icon} {test_name}**\n")
                lines.append(f"![{test_name}]({relative_screenshot})\n")
        lines.append("")

    # 尾部
    lines.append("---\n")
    lines.append(f"> 报告自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"> HTML 报告: `reports/pytest-report.html`")

    report_content = "\n".join(lines)
    report_path.write_text(report_content, encoding="utf-8")

    # 同时写一份固定名称的报告（方便快速查看最新结果）
    latest_path = reports_dir / "test-report-latest.md"
    latest_path.write_text(report_content, encoding="utf-8")

    terminalreporter.write_line(f"📄 Markdown 报告已生成: {report_path}")
    terminalreporter.write_line(f"📄 最新报告快捷入口: {latest_path}")


# ========== pytest-html 中文报告 Hook ==========

def pytest_configure(config):
    """配置报告元数据和自定义标记"""
    # UI smoke / integration tier markers
    config.addinivalue_line("markers", "ui_smoke: UI smoke test (mocked API, no backend needed)")
    config.addinivalue_line("markers", "integration: Integration test (requires running backend + API keys)")
    # pytest-html 4.x: 通过 pytest-metadata 的 stash 设置元数据
    if hasattr(config, 'stash'):
        try:
            from pytest_metadata.plugin import metadata_key
            metadata = config.stash[metadata_key]
        except (ImportError, KeyError):
            metadata = {}
    elif hasattr(config, '_metadata'):
        metadata = config._metadata
    else:
        metadata = {}

    # 移除无关的默认元数据
    for key in list(metadata.keys()):
        if key in ['Java', 'Packages', 'Plugins', 'JAVA_HOME']:
            metadata.pop(key, None)

    metadata['项目名称'] = 'QwenPaw E2E 自动化测试'
    metadata['测试环境'] = app_config.server.base_url
    metadata['浏览器'] = 'Chromium (Playwright)'
    metadata['测试框架'] = 'Pytest + Playwright'

    # 每次测试开始前清理上一次的截图和旧报告
    reports_dir = Path(__file__).parent / "reports"
    if reports_dir.exists():
        # 清空截图目录（递归清理，包括 steps 子目录），只保留当前运行的截图
        screenshots_dir = reports_dir / "screenshots"
        if screenshots_dir.exists():
            import shutil
            # 先删除 steps 子目录（步骤截图）
            steps_dir = screenshots_dir / "steps"
            if steps_dir.exists():
                shutil.rmtree(steps_dir, ignore_errors=True)
            # 再清理根目录下的最终截图
            for old_screenshot in screenshots_dir.glob("*.png"):
                try:
                    old_screenshot.unlink()
                except OSError:
                    pass

        # 清理旧的 Markdown 报告，只保留 test-report-latest.md
        keep_files = {"test-report-latest.md"}
        for md_file in reports_dir.glob("test-report-*.md"):
            if md_file.name not in keep_files:
                try:
                    md_file.unlink()
                except OSError:
                    pass


def pytest_html_report_title(report):
    """设置 HTML 报告标题为中文（pytest-html 4.x hook）"""
    try:
        report.title = "QwenPaw E2E 自动化测试报告"
    except Exception:
        pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """将测试函数的 docstring 附加到报告中，并在测试完成时自动截图"""
    outcome = yield
    report = outcome.get_result()
    report.description = str(item.function.__doc__ or '').strip()

    # 在测试调用阶段结束时自动截图（无论通过或失败）
    if report.when == "call":
        page = item.funcargs.get("page")
        if page is not None:
            try:
                # 等待页面稳定后再截图，确保内容渲染完成
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)

                screenshots_dir = Path(__file__).parent / "reports" / "screenshots"
                screenshots_dir.mkdir(parents=True, exist_ok=True)
                safe_name = report.nodeid.replace("/", "_").replace("::", "__").replace("[", "_").replace("]", "")
                screenshot_path = screenshots_dir / f"{safe_name}.png"
                page.screenshot(path=str(screenshot_path), full_page=True)
                report.screenshot_path = str(screenshot_path)
                _logger.info(f"Screenshot saved: {screenshot_path}")
            except Exception as screenshot_error:
                _logger.warning(f"Failed to capture screenshot: {screenshot_error}")
                report.screenshot_path = None
        else:
            report.screenshot_path = None


@pytest.hookimpl(optionalhook=True)
def pytest_html_results_summary(prefix, summary, postfix):
    """在报告摘要区域添加中文项目说明"""
    prefix.extend([
        "<p>📊 本报告由 QwenPaw E2E 自动化测试框架自动生成。</p>",
        "<p>✅ 通过 | ❌ 失败 | ⏭️ 跳过 | 🔄 重试</p>",
    ])


@pytest.hookimpl(optionalhook=True)
def pytest_html_results_table_header(cells):
    """在报告表格表头中插入描述列"""
    try:
        from py.xml import html
        cells.insert(2, html.th("描述", class_="sortable"))
    except ImportError:
        pass


@pytest.hookimpl(optionalhook=True)
def pytest_html_results_table_row(report, cells):
    """在报告表格每行中插入描述信息"""
    try:
        from py.xml import html
        doc = getattr(report, 'description', '') or ''
        cells.insert(2, html.td(doc))
    except ImportError:
        pass


# ========== 清理 ==========

_logger = logging.getLogger(__name__)

# 报告文件保留天数
REPORT_RETENTION_DAYS = 7


def pytest_sessionfinish(session, exitstatus):
    """测试会话结束后清理过期的报告和日志文件"""
    reports_dir = Path(__file__).parent / "reports"
    if not reports_dir.exists():
        return

    cutoff_time = time.time() - REPORT_RETENTION_DAYS * 86400
    cleaned_count = 0

    cleanup_patterns = ["*.png", "*.html", "*.log", "*.webm"]
    for pattern in cleanup_patterns:
        for file_path in reports_dir.glob(pattern):
            try:
                if file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    cleaned_count += 1
            except OSError:
                pass

    # 清理 screenshots 子目录中的过期截图
    screenshots_dir = reports_dir / "screenshots"
    if screenshots_dir.exists():
        for file_path in screenshots_dir.glob("*.png"):
            try:
                if file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    cleaned_count += 1
            except OSError:
                pass

    # 清理过期的 Markdown 报告（保留 test-report-latest.md）
    for md_file in reports_dir.glob("test-report-*.md"):
        try:
            if md_file.name != "test-report-latest.md" and md_file.stat().st_mtime < cutoff_time:
                md_file.unlink()
                cleaned_count += 1
        except OSError:
            pass

    if cleaned_count > 0:
        _logger.info(f"Cleaned up {cleaned_count} report files older than {REPORT_RETENTION_DAYS} days")
