# -*- coding: utf-8 -*-
"""
QwenPaw E2E Test Framework - Pytest Configuration
"""
from __future__ import annotations

import sys
import os
import time
import logging
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import pytest
from pages.chat_page import ChatPage
from config.settings import config as app_config

# Disable pytest-playwright's auto-injected fixtures and use our custom ones.
# This ensures QWENPAW_HEADLESS correctly controls the browser display mode.
pytest_plugins = []

# Module-level logger (must be defined before any function uses _logger)
_logger = logging.getLogger(__name__)

# Import all custom fixtures from the fixtures module.
# Includes browser, page, browser_context, etc. — fully under our control.
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
# Note: shared fixtures (chat_page / clean_chat_page / api_context / page, etc.)
# are defined in fixtures/__init__.py. Here we only add Page Object fixtures
# for other modules, lazily importing them to avoid loading every Page class
# at startup.

def _make_page_fixture(import_path: str, class_name: str):
    """Factory: build a fixture from a Page class (lazy import)."""
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


# ========== Business / Data Fixtures ==========
@pytest.fixture(scope="function")
def dingtalk_config():
    """
    Provide DingTalk configuration.

    Reads configuration from environment variables; CI/CD friendly:
    - DINGTALK_WEBHOOK: DingTalk bot webhook URL
    - DINGTALK_SECRET: Signing secret
    - DINGTALK_CLIENT_ID: DingTalk app Client ID
    - DINGTALK_CLIENT_SECRET: DingTalk app Client Secret

    Returns:
        Configuration dict
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
    Provide a DingTalk test message.

    Returns:
        Test message string
    """
    import time
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    return f"Automation test message - {timestamp}"

# Note: clean_chat_page / test_file / large_test_file are provided by
# fixtures/__init__.py. Don't redefine them here, to avoid fixture conflicts
# that would break pytest collection/execution (especially in headed mode).


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



def pytest_collection_modifyitems(config, items):
    """Auto-skip tests marked with @pytest.mark.requires_llm when no model key is configured."""
    if os.getenv("QWENPAW_DASHSCOPE_API_KEY"):
        return
    skip_llm = pytest.mark.skip(reason="QWENPAW_DASHSCOPE_API_KEY not set — LLM tests skipped")
    for item in items:
        if "requires_llm" in item.keywords:
            item.add_marker(skip_llm)


@pytest.fixture(scope="session", autouse=True)
def warmup_server():
    """
    Session-scoped service warmup.

    Note: this intentionally does not depend on the `playwright` fixture
    provided by pytest-playwright. The reason is that pytest-playwright is
    implemented on top of asyncio + Playwright Async API; once its fixture
    fires, it creates an asyncio event loop on the main thread, causing our
    custom `playwright_context` (Sync API) to raise:
        "It looks like you are using Playwright Sync API inside the asyncio loop."
    So we use the Sync API to start a temporary Playwright instance for warmup.

    Steps:
    1. Confirm backend availability via an API health check (retry up to ~30s).
    2. Visit the homepage and wait for DOM/networkidle/key elements to appear.
    3. Buffer a bit more to let lazy-loaded components settle.

    Failures in any step do not block tests (warning only) to avoid letting
    warmup stall the entire run.
    """
    from playwright.sync_api import sync_playwright

    base_url = app_config.server.base_url
    logger = logging.getLogger(__name__)

    with sync_playwright() as pw:
        # ---------- 1. API health check ----------
        api_ready = False
        api_request = None
        try:
            api_request = pw.request.new_context(base_url=base_url)
            # Candidate health check paths; first hit means the backend is ready.
            health_paths = ["/api/health", "/healthz", "/api/heartbeat", "/"]
            deadline = time.time() + 30  # Wait up to 30s
            while time.time() < deadline and not api_ready:
                for path in health_paths:
                    try:
                        resp = api_request.get(path, timeout=5000)
                        # Treat 2xx/3xx as backend online
                        if resp.status < 400:
                            api_ready = True
                            logger.info(f"Backend API ready: {path} -> {resp.status}")
                            break
                    except Exception:
                        continue
                if not api_ready:
                    time.sleep(1)
            if not api_ready:
                logger.warning("Backend API health check did not pass within 30s; continuing to warm up the frontend")
        except Exception as e:
            logger.warning(f"API health check error (ignored): {e}")
        finally:
            if api_request is not None:
                try:
                    api_request.dispose()
                except Exception:
                    pass

        # ---------- 2. Frontend warmup ----------
        try:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            # 2.1 Visit the homepage and wait for DOM to finish loading
            page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
            # 2.2 Wait for network idle to ensure SPA async resources are loaded
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            # 2.3 Actively wait for breadcrumb or main navigation as a "frontend ready" signal
            try:
                page.wait_for_selector(
                    'span[class*=breadcrumbCurrent], button:has-text("Create Agent"), nav, [class*=sider]',
                    timeout=10000,
                )
            except Exception:
                pass
            # 2.4 Extra buffer to let lazy-loaded components settle
            page.wait_for_timeout(2000)

            logger.info(f"Service warmup complete: {base_url}")

            context.close()
            browser.close()
        except Exception as e:
            logger.warning(f"Service warmup failed (does not block tests): {e}")

    yield


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Terminal summary on test completion + auto-generate the Markdown report"""
    passed = len(terminalreporter.getreports('passed'))
    failed = len(terminalreporter.getreports('failed'))
    skipped = len(terminalreporter.getreports('skipped'))
    total = passed + failed + skipped

    terminalreporter.write_sep("=" * 60)
    terminalreporter.write_line("Test Summary:")
    terminalreporter.write_line(f"  Total: {total}")
    terminalreporter.write_line(f"  Passed: {passed}")
    terminalreporter.write_line(f"  Failed: {failed}")
    terminalreporter.write_line(f"  Skipped: {skipped}")

    if total > 0:
        pass_rate = passed / total * 100
        terminalreporter.write_line(f"  Pass rate: {pass_rate:.1f}%")
    terminalreporter.write_sep("=" * 60)

    # Auto-generate the Markdown test report (extracted to utils/report_generator.py)
    try:
        from utils.report_generator import generate_markdown_report
        reports_dir = Path(__file__).parent / "reports"
        report_path = generate_markdown_report(terminalreporter, reports_dir)
        terminalreporter.write_line(f"Markdown report generated: {report_path}")
        terminalreporter.write_line(
            f"Latest report shortcut: {reports_dir / 'test-report-latest.md'}"
        )
    except Exception as e:
        terminalreporter.write_line(f"Markdown report generation failed: {e}")


# ========== pytest-html report hooks ==========

def pytest_configure(config):
    """Configure report metadata and custom markers"""
    # UI smoke / integration tier markers
    config.addinivalue_line("markers", "ui_smoke: UI smoke test (mocked API, no backend needed)")
    config.addinivalue_line("markers", "integration: Integration test (requires running backend + API keys)")
    # pytest-html 4.x: set metadata via pytest-metadata's stash
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

    # Remove irrelevant default metadata
    for key in list(metadata.keys()):
        if key in ['Java', 'Packages', 'Plugins', 'JAVA_HOME']:
            metadata.pop(key, None)

    metadata['Project'] = 'QwenPaw E2E Automation'
    metadata['Test Environment'] = app_config.server.base_url
    metadata['Browser'] = 'Chromium (Playwright)'
    metadata['Framework'] = 'Pytest + Playwright'

    # Clean up the previous run's screenshots and old reports before each test session
    reports_dir = Path(__file__).parent / "reports"
    if reports_dir.exists():
        # Clear the screenshots directory (recursive, including steps subdir);
        # only keep screenshots from the current run.
        screenshots_dir = reports_dir / "screenshots"
        if screenshots_dir.exists():
            import shutil
            # First delete the steps subdir (step screenshots)
            steps_dir = screenshots_dir / "steps"
            if steps_dir.exists():
                shutil.rmtree(steps_dir, ignore_errors=True)
            # Then clean up the final screenshots in the root
            for old_screenshot in screenshots_dir.glob("*.png"):
                try:
                    old_screenshot.unlink()
                except OSError:
                    pass

        # Clean up old Markdown reports, keeping only test-report-latest.md
        keep_files = {"test-report-latest.md"}
        for md_file in reports_dir.glob("test-report-*.md"):
            if md_file.name not in keep_files:
                try:
                    md_file.unlink()
                except OSError:
                    pass


def pytest_html_report_title(report):
    """Set the HTML report title (pytest-html 4.x hook)"""
    try:
        report.title = "QwenPaw E2E Automation Test Report"
    except Exception:
        pass


@pytest.hookimpl(optionalhook=True)
def pytest_html_results_summary(prefix, summary, postfix):
    """Add a project description in the report summary section"""
    prefix.extend([
        "<p>This report is auto-generated by the QwenPaw E2E automation framework.</p>",
        "<p>Passed | Failed | Skipped | Reruns</p>",
    ])


@pytest.hookimpl(optionalhook=True)
def pytest_html_results_table_header(cells):
    """Insert a description column in the report table header"""
    try:
        from py.xml import html
        cells.insert(2, html.th("Description", class_="sortable"))
    except ImportError:
        pass


@pytest.hookimpl(optionalhook=True)
def pytest_html_results_table_row(report, cells):
    """Insert description info into each report table row"""
    try:
        from py.xml import html
        doc = getattr(report, 'description', '') or ''
        cells.insert(2, html.td(doc))
    except ImportError:
        pass


# ========== Cleanup ==========

# Number of days to retain report files
REPORT_RETENTION_DAYS = 7


def pytest_sessionfinish(session, exitstatus):
    """Clean up expired report and log files after the test session ends"""
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

    # Clean up expired screenshots under the screenshots subdir
    screenshots_dir = reports_dir / "screenshots"
    if screenshots_dir.exists():
        for file_path in screenshots_dir.glob("*.png"):
            try:
                if file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    cleaned_count += 1
            except OSError:
                pass

    # Clean up expired Markdown reports (keep test-report-latest.md)
    for md_file in reports_dir.glob("test-report-*.md"):
        try:
            if md_file.name != "test-report-latest.md" and md_file.stat().st_mtime < cutoff_time:
                md_file.unlink()
                cleaned_count += 1
        except OSError:
            pass

    if cleaned_count > 0:
        _logger.info(f"Cleaned up {cleaned_count} report files older than {REPORT_RETENTION_DAYS} days")
