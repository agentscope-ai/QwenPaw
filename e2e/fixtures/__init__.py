# -*- coding: utf-8 -*-
"""
QwenPaw E2E Test Framework - Pytest Fixtures

Provides browser, page, API client and other fixtures required by tests.
"""
from __future__ import annotations

import os
import logging
import pytest
from pathlib import Path
from typing import Generator, Optional
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, APIRequestContext
from datetime import datetime

from config.settings import config, get_config
from pages.chat_page import ChatPage


# Configure logging
logging.basicConfig(
    level=getattr(logging, config.test.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(config.paths.logs_dir / f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler(),
    ]
)

logger = logging.getLogger(__name__)


# ============================================================================
# Session-scoped Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def playwright_context():
    """
    Create a Playwright session (session scope)

    Yields:
        Playwright instance
    """
    logger.info("Starting Playwright session")
    
    with sync_playwright() as p:
        yield p
    
    logger.info("Playwright session ended")


@pytest.fixture(scope="session")
def browser(playwright_context):
    """
    Create a browser instance (reused across the session)

    Yields:
        Browser instance
    """
    cfg = config.browser

    logger.info(f"Launching browser: {cfg.browser_type}, headless={cfg.headless}")

    browser_kwargs = {
        "headless": cfg.headless,
        "slow_mo": cfg.slow_mo,
        "args": cfg.args,
    }

    # Launch based on browser type
    if cfg.browser_type == "chromium":
        browser = playwright_context.chromium.launch(**browser_kwargs)
    elif cfg.browser_type == "firefox":
        browser = playwright_context.firefox.launch(**browser_kwargs)
    elif cfg.browser_type == "webkit":
        browser = playwright_context.webkit.launch(**browser_kwargs)
    else:
        raise ValueError(f"Unsupported browser type: {cfg.browser_type}")
    
    logger.info("Browser launched successfully")
    
    yield browser
    
    logger.info("Closing browser")
    browser.close()


@pytest.fixture(scope="session")
def api_context(playwright_context) -> Generator[APIRequestContext, None, None]:
    """
    Create an API request context.

    Note: this depends on our custom `playwright_context` (Sync API), not
    on the `playwright` fixture from the pytest-playwright plugin. Reason:
    pytest-playwright is built on the Async API; once its fixture fires,
    it installs an asyncio event loop on the main thread, which makes our
    Sync API raise "using Sync API inside the asyncio loop".

    Yields:
        APIRequestContext instance
    """
    logger.info("Creating API request context")

    api_request_context = playwright_context.request.new_context(
        base_url=config.server.base_url,
        extra_http_headers={
            "Content-Type": "application/json",
            "X-Agent-Id": "default",
        }
    )

    yield api_request_context

    api_request_context.dispose()


# ============================================================================
# Function-scoped Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def browser_context(browser: Browser, request: pytest.FixtureRequest) -> Generator[BrowserContext, None, None]:
    """
    Create a browser context (one per test function)

    Supports:
    - Isolated Cookies/Storage
    - Video recording on failure
    - Custom viewport

    Yields:
        BrowserContext instance
    """
    test_name = request.node.name
    logger.info(f"Creating browser context for test: {test_name}")

    # Video recording configuration (saved on failure)
    video_dir = config.paths.videos_dir if config.test.video_on_fail else None

    context = browser.new_context(
        viewport={
            "width": config.browser.viewport_width,
            "height": config.browser.viewport_height,
        },
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        # Use en-US locale to match the system under test (English-only UI),
        # preventing Chrome from showing a translation popup that would
        # obscure page elements on a locale mismatch.
        locale="en-US",
        timezone_id="Asia/Shanghai",
        record_video_dir=video_dir,
        record_video_size={
            "width": config.browser.viewport_width,
            "height": config.browser.viewport_height,
        } if video_dir else None,
    )
    
    yield context
    
    logger.info(f"Closing browser context for test: {test_name}")
    context.close()


@pytest.fixture(scope="function")
def page(browser_context: BrowserContext, request: pytest.FixtureRequest) -> Generator[Page, None, None]:
    """
    Create a page instance (one per test function)

    Supports:
    - Automatic screenshot on failure
    - Timeout configuration
    - Console log capture

    Yields:
        Page instance
    """
    test_name = request.node.name
    logger.info(f"Creating page for test: {test_name}")

    page = browser_context.new_page()
    page.set_default_timeout(config.browser.timeout)

    # Inject test name + step counter, used by BasePage.step_shot for auto-archiving
    try:
        page._qwenpaw_test_name = test_name
        page._qwenpaw_step_seq = 0
    except Exception:
        pass

    # Capture console logs
    page.on("console", lambda msg: logger.debug(f"Browser console: {msg.type} - {msg.text}"))
    page.on("pageerror", lambda err: logger.error(f"Page error: {err}"))

    yield page

    # Take a screenshot on test failure (use getattr as a fallback: API-only tests
    # may not trigger the pytest_runtest_makereport hook, so the node may lack the
    # rep_call attribute. getattr avoids AttributeError polluting teardown.)
    rep_call = getattr(request.node, "rep_call", None)
    if config.test.screenshot_on_fail and rep_call is not None and rep_call.failed:
        try:
            screenshot_path = config.paths.screenshots_dir / f"{test_name}_failure.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            logger.info(f"Screenshot saved: {screenshot_path}")

            # Save video
            if config.test.video_on_fail and page.video:
                video_path = config.paths.videos_dir / f"{test_name}_failure.webm"
                page.video.save_as(str(video_path))
                logger.info(f"Video saved: {video_path}")
        except Exception as e:
            logger.warning(f"Failed to capture screenshot/video: {e}")

    page.close()
    
    logger.info(f"Page closed for test: {test_name}")


# Hook to track test call state
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    """Track test execution state, used for screenshot-on-failure"""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture(scope="function")
def chat_page(page: Page) -> ChatPage:
    """
    Create a Chat page object

    Yields:
        ChatPage instance
    """
    logger.info("Creating ChatPage instance")
    chat = ChatPage(page)
    yield chat


@pytest.fixture(scope="function")
def clean_chat_page(page: Page) -> Generator[ChatPage, None, None]:
    """
    Create a ChatPage instance and clean up all session data after the test.

    Use for tests that create new conversations, to ensure no residual data
    is left behind.

    Yields:
        ChatPage instance
    """
    logger.info("Creating ChatPage instance (with cleanup)")
    chat = ChatPage(page)

    yield chat

    logger.info("Cleaning up test sessions")
    try:
        chat.delete_all_sessions()
    except Exception as cleanup_error:
        logger.warning(f"Session cleanup failed: {cleanup_error}")


@pytest.fixture(scope="function")
def authenticated_page(page: Page) -> Page:
    """
    Authenticated page (if login is required)

    QwenPaw currently uses an auth-free mode; extend this fixture if login
    is needed.

    Yields:
        Page instance
    """
    # If login is required, add the login logic here.
    # For example:
    # page.goto(f"{config.base_url}/login")
    # page.fill('[name="username"]', "test_user")
    # page.fill('[name="password"]', "test_password")
    # page.click('button[type="submit"]')
    # page.wait_for_load_state("networkidle")

    logger.info("Authenticated page ready (using auth-free mode)")
    yield page


# ============================================================================
# Data Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def test_file(tmp_path: Path) -> Path:
    """
    Create a test file

    Yields:
        Test file path
    """
    test_file = tmp_path / "test_upload.txt"
    test_content = """QwenPaw Test File

This is a file used to verify the E2E file upload functionality.

QwenPaw is an intelligent assistant platform supporting the following features:
1. Chat conversations
2. File processing
3. Skill invocation
4. Automated tasks
5. Multi-channel support

Version: v1.0.0
Created: 2026-04-13
Purpose: E2E testing
"""
    test_file.write_text(test_content, encoding="utf-8")
    logger.info(f"Test file created: {test_file}")
    yield test_file


@pytest.fixture(scope="function")
def large_test_file(tmp_path: Path) -> Path:
    """
    Create a large test file (used to test file size limits)

    Yields:
        Large file path
    """
    large_file = tmp_path / "large_file.txt"

    # Create an 11MB file (exceeds the 10MB limit)
    chunk = "A" * (1024 * 1024)  # 1MB
    with open(large_file, 'w', encoding='utf-8') as f:
        for _ in range(11):
            f.write(chunk)

    logger.info(f"Large test file created: {large_file} (11MB)")
    yield large_file


@pytest.fixture(scope="function")
def test_messages() -> list:
    """
    Test message data

    Returns:
        List of messages
    """
    return [
        "Hello, please introduce yourself",
        "I want to learn Python programming",
        "Where should I start?",
        "Can you recommend some learning resources?",
    ]


@pytest.fixture(scope="function")
def test_user_data() -> dict:
    """
    Test user data

    Returns:
        User data dictionary
    """
    return {
        "user_id": config.test.user_id,
        "channel": config.test.channel,
        "session_id": f"{config.test.channel}:{config.test.user_id}",
    }


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def retry_on_failure(request: pytest.FixtureRequest):
    """
    Retry-on-failure decorator

    Usage:
    @pytest.mark.parametrize("retry_on_failure", [3], indirect=True)
    def test_something(retry_on_failure):
        ...
    """
    max_retries = getattr(request, "param", 3)

    def runner(test_func, *args, **kwargs):
        last_exception = None
        for attempt in range(max_retries):
            try:
                return test_func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(config.server.retry_delay)

        raise last_exception

    return runner


@pytest.fixture(scope="session")
def base_url() -> str:
    """Get the base URL"""
    return config.server.base_url


@pytest.fixture(scope="session")
def api_url() -> str:
    """Get the API URL"""
    return config.server.api_base_url
