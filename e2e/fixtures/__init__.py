# -*- coding: utf-8 -*-
"""
QwenPaw E2E 测试框架 - Pytest Fixtures

提供测试所需的浏览器、页面、API 客户端等 fixture。
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


# 配置日志
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
# Session 级别 Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def playwright_context():
    """
    创建 Playwright 会话（session 级别）
    
    Yields:
        Playwright 实例
    """
    logger.info("Starting Playwright session")
    
    with sync_playwright() as p:
        yield p
    
    logger.info("Playwright session ended")


@pytest.fixture(scope="session")
def browser(playwright_context):
    """
    创建浏览器实例（session 级别复用）
    
    Yields:
        Browser 实例
    """
    cfg = config.browser
    
    logger.info(f"Launching browser: {cfg.browser_type}, headless={cfg.headless}")
    
    browser_kwargs = {
        "headless": cfg.headless,
        "slow_mo": cfg.slow_mo,
        "args": cfg.args,
    }
    
    # 根据浏览器类型启动
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
    创建 API 请求上下文

    注意：这里依赖我们自定义的 `playwright_context`（Sync API），
    而不是 pytest-playwright 插件的 `playwright` fixture。
    原因：pytest-playwright 是基于 Async API 的，一旦它的 fixture 被触发，
    会在主线程安装 asyncio event loop，导致我们 Sync API 报
    "using Sync API inside the asyncio loop"。

    Yields:
        APIRequestContext 实例
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
# Function 级别 Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def browser_context(browser: Browser, request: pytest.FixtureRequest) -> Generator[BrowserContext, None, None]:
    """
    创建浏览器上下文（每个测试函数独立）
    
    支持：
    - 独立 Cookie/Storage
    - 失败时录制视频
    - 自定义 viewport
    
    Yields:
        BrowserContext 实例
    """
    test_name = request.node.name
    logger.info(f"Creating browser context for test: {test_name}")
    
    # 录制视频配置（失败时保存）
    video_dir = config.paths.videos_dir if config.test.video_on_fail else None
    
    context = browser.new_context(
        viewport={
            "width": config.browser.viewport_width,
            "height": config.browser.viewport_height,
        },
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        # 使用 en-US locale 与被测系统（纯英文 UI）保持一致，
        # 避免 Chrome 检测到 locale 不匹配而弹出翻译弹窗遮挡页面元素
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
    创建页面实例（每个测试函数独立）
    
    支持：
    - 失败时自动截图
    - 超时配置
    - 控制台日志捕获
    
    Yields:
        Page 实例
    """
    test_name = request.node.name
    logger.info(f"Creating page for test: {test_name}")
    
    page = browser_context.new_page()
    page.set_default_timeout(config.browser.timeout)

    # 注入用例名 + 步骤序号，供 BasePage.step_shot 自动归档使用
    try:
        page._qwenpaw_test_name = test_name
        page._qwenpaw_step_seq = 0
    except Exception:
        pass

    # 捕获控制台日志
    page.on("console", lambda msg: logger.debug(f"Browser console: {msg.type} - {msg.text}"))
    page.on("pageerror", lambda err: logger.error(f"Page error: {err}"))
    
    yield page

    # 测试失败时截图（用 getattr 兜底：API-only 的用例可能没触发 pytest_runtest_makereport hook，
    # 导致 node 上没有 rep_call 属性。这里用 getattr 避免 AttributeError 污染 teardown。）
    rep_call = getattr(request.node, "rep_call", None)
    if config.test.screenshot_on_fail and rep_call is not None and rep_call.failed:
        try:
            screenshot_path = config.paths.screenshots_dir / f"{test_name}_failure.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            logger.info(f"Screenshot saved: {screenshot_path}")

            # 保存视频
            if config.test.video_on_fail and page.video:
                video_path = config.paths.videos_dir / f"{test_name}_failure.webm"
                page.video.save_as(str(video_path))
                logger.info(f"Video saved: {video_path}")
        except Exception as e:
            logger.warning(f"Failed to capture screenshot/video: {e}")

    page.close()
    
    logger.info(f"Page closed for test: {test_name}")


# 添加 hook 来跟踪测试调用状态
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    """跟踪测试执行状态，用于失败时截图"""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture(scope="function")
def chat_page(page: Page) -> ChatPage:
    """
    创建 Chat 页面对象
    
    Yields:
        ChatPage 实例
    """
    logger.info("Creating ChatPage instance")
    chat = ChatPage(page)
    yield chat


@pytest.fixture(scope="function")
def clean_chat_page(page: Page) -> Generator[ChatPage, None, None]:
    """
    创建 ChatPage 实例，测试结束后自动清理所有会话数据。

    适用于会创建新对话的测试用例，确保测试后不留残余数据。

    Yields:
        ChatPage 实例
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
    已认证的页面（如果需要登录）
    
    目前 QwenPaw 使用免认证模式，如需登录可扩展此 fixture
    
    Yields:
        Page 实例
    """
    # 如果需要登录，在这里添加登录逻辑
    # 例如：
    # page.goto(f"{config.base_url}/login")
    # page.fill('[name="username"]', "test_user")
    # page.fill('[name="password"]', "test_password")
    # page.click('button[type="submit"]')
    # page.wait_for_load_state("networkidle")
    
    logger.info("Authenticated page ready (using免认证 mode)")
    yield page


# ============================================================================
# 数据 Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def test_file(tmp_path: Path) -> Path:
    """
    创建测试文件
    
    Yields:
        测试文件路径
    """
    test_file = tmp_path / "test_upload.txt"
    test_content = """QwenPaw 测试文件

这是一个用于 E2E 测试的文件上传功能验证文件。

QwenPaw 是一个智能助手平台，支持以下功能：
1. 聊天对话
2. 文件处理
3. 技能调用
4. 自动化任务
5. 多 channel 支持

版本：v1.0.0
创建日期：2026-04-13
用途：E2E 测试
"""
    test_file.write_text(test_content, encoding="utf-8")
    logger.info(f"Test file created: {test_file}")
    yield test_file


@pytest.fixture(scope="function")
def large_test_file(tmp_path: Path) -> Path:
    """
    创建大测试文件（用于测试文件大小限制）
    
    Yields:
        大文件路径
    """
    large_file = tmp_path / "large_file.txt"
    
    # 创建 11MB 的文件（超过 10MB 限制）
    chunk = "A" * (1024 * 1024)  # 1MB
    with open(large_file, 'w', encoding='utf-8') as f:
        for _ in range(11):
            f.write(chunk)
    
    logger.info(f"Large test file created: {large_file} (11MB)")
    yield large_file


@pytest.fixture(scope="function")
def test_messages() -> list:
    """
    测试消息数据
    
    Returns:
        消息列表
    """
    return [
        "你好，请介绍一下你自己",
        "我想学习 Python 编程",
        "我应该从哪里开始？",
        "能推荐一些学习资源吗？",
    ]


@pytest.fixture(scope="function")
def test_user_data() -> dict:
    """
    测试用户数据
    
    Returns:
        用户数据字典
    """
    return {
        "user_id": config.test.user_id,
        "channel": config.test.channel,
        "session_id": f"{config.test.channel}:{config.test.user_id}",
    }


# ============================================================================
# 工具 Fixtures
# ============================================================================

@pytest.fixture(scope="function")
def retry_on_failure(request: pytest.FixtureRequest):
    """
    失败重试装饰器
    
    用法：
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
    """获取基础 URL"""
    return config.server.base_url


@pytest.fixture(scope="session")
def api_url() -> str:
    """获取 API URL"""
    return config.server.api_base_url
