# -*- coding: utf-8 -*-
"""
QwenPaw E2E Test Framework - Utility Functions

Provides common test helper functions.
"""
from __future__ import annotations

import os
import json
import time
import logging
from pathlib import Path
from typing import Optional, Any, Dict, List
from datetime import datetime
from playwright.sync_api import Page, Locator, APIRequestContext

from config.settings import config


logger = logging.getLogger(__name__)


# ============================================================================
# Screenshots and recording
# ============================================================================

def take_screenshot(page: Page, name: str, full_page: bool = True) -> str:
    """
    Take a screenshot.

    Args:
        page: Playwright Page instance
        name: Screenshot name
        full_page: Whether to capture the full page

    Returns:
        Screenshot file path
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{name}_{timestamp}.png"
    path = config.paths.screenshots_dir / filename

    page.screenshot(path=str(path), full_page=full_page)
    logger.info(f"Screenshot saved: {path}")
    return str(path)


def save_video(page: Page, name: str) -> Optional[str]:
    """
    Save the recorded video.

    Args:
        page: Playwright Page instance
        name: Video name

    Returns:
        Video file path, or None
    """
    if not page.video:
        logger.warning("Video recording not enabled")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{name}_{timestamp}.webm"
    path = config.paths.videos_dir / filename

    page.video.save_as(str(path))
    logger.info(f"Video saved: {path}")
    return str(path)


# ============================================================================
# API helpers
# ============================================================================

def api_get(api_context: APIRequestContext, endpoint: str, params: Optional[Dict] = None) -> Dict:
    """
    Send a GET request.

    Args:
        api_context: API request context
        endpoint: API endpoint
        params: Query parameters

    Returns:
        Response JSON
    """
    # endpoint already includes path, api_context has base_url
    logger.info(f"GET {endpoint}")

    response = api_context.get(endpoint, params=params)
    assert response.ok, f"API request failed: {response.status} {response.status_text}"

    return response.json()


def api_post(api_context: APIRequestContext, endpoint: str, data: Optional[Dict] = None) -> Dict:
    """
    Send a POST request.

    Args:
        api_context: API request context
        endpoint: API endpoint
        data: Request data

    Returns:
        Response JSON
    """
    # endpoint already includes path, api_context has base_url
    logger.info(f"POST {endpoint}, data: {data}")

    response = api_context.post(endpoint, data=data)
    assert response.ok, f"API request failed: {response.status} {response.status_text}"

    return response.json()


def api_delete(api_context: APIRequestContext, endpoint: str) -> Dict:
    """
    Send a DELETE request.

    Args:
        api_context: API request context
        endpoint: API endpoint

    Returns:
        Response JSON
    """
    logger.info(f"DELETE {endpoint}")

    response = api_context.delete(endpoint)
    assert response.ok, f"DELETE {endpoint} failed: {response.status} {response.status_text}"

    return response.json()


# ============================================================================
# Waiting and retries
# ============================================================================

def wait_for_condition(condition_func, timeout: int = 30000, interval: int = 500) -> Any:
    """
    Wait for a condition to be satisfied.

    Args:
        condition_func: Condition function; returning a truthy value indicates success
        timeout: Timeout (milliseconds)
        interval: Check interval (milliseconds)

    Returns:
        Return value of the condition function

    Raises:
        TimeoutError: Timed out
    """
    start_time = time.time()
    timeout_sec = timeout / 1000

    while time.time() - start_time < timeout_sec:
        result = condition_func()
        if result:
            logger.debug(f"Condition met after {time.time() - start_time:.2f}s")
            return result

        time.sleep(interval / 1000)

    raise TimeoutError(f"Condition not met within {timeout}ms")


def retry_operation(operation_func, max_retries: int = 3, delay: float = 1.0) -> Any:
    """
    Retry an operation.

    Args:
        operation_func: Operation function
        max_retries: Maximum number of retries
        delay: Retry interval (seconds)

    Returns:
        Operation result

    Raises:
        Exception: All retries failed
    """
    if max_retries <= 0:
        raise ValueError(f"max_retries must be positive, got {max_retries}")

    last_exception = None

    for attempt in range(max_retries):
        try:
            return operation_func()
        except Exception as e:
            last_exception = e
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")

            if attempt < max_retries - 1:
                time.sleep(delay)

    raise last_exception


# ============================================================================
# File operations
# ============================================================================

def create_test_file(tmp_path: Path, filename: str, content: str) -> Path:
    """
    Create a test file.

    Args:
        tmp_path: Temporary directory
        filename: File name
        content: File content

    Returns:
        File path
    """
    file_path = tmp_path / filename
    file_path.write_text(content, encoding="utf-8")
    logger.info(f"Test file created: {file_path}")
    return file_path


def read_test_data(filename: str) -> str:
    """
    Read a test data file.

    Args:
        filename: File name

    Returns:
        File content
    """
    file_path = config.paths.data_dir / filename

    if not file_path.exists():
        raise FileNotFoundError(f"Test data file not found: {file_path}")

    return file_path.read_text(encoding="utf-8")


def load_json_data(filename: str) -> Dict:
    """
    Load JSON test data.

    Args:
        filename: File name

    Returns:
        JSON data
    """
    content = read_test_data(filename)
    return json.loads(content)


# ============================================================================
# Assertion helpers
# ============================================================================

def assert_element_visible(page: Page, selector: str, timeout: int = 5000) -> bool:
    """
    Assert that an element is visible.

    Args:
        page: Playwright Page instance
        selector: CSS selector
        timeout: Timeout

    Returns:
        Whether visible
    """
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout)
        return True
    except Exception as e:
        logger.debug(f"Element not visible: {selector}, error: {e}")
        return False


def assert_text_contains(page: Page, selector: str, expected_text: str, timeout: int = 5000) -> bool:
    """
    Assert that text contains the expected substring.

    Args:
        page: Playwright Page instance
        selector: CSS selector
        expected_text: Expected text
        timeout: Timeout

    Returns:
        Whether contained
    """
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout)
        text = locator.inner_text()
        return expected_text.lower() in text.lower()
    except Exception as e:
        logger.debug(f"Text assertion failed: {e}")
        return False


def assert_count(page: Page, selector: str, expected_count: int, timeout: int = 5000) -> bool:
    """
    Assert the number of matching elements.

    Args:
        page: Playwright Page instance
        selector: CSS selector
        expected_count: Expected count
        timeout: Timeout

    Returns:
        Whether matched
    """
    try:
        locator = page.locator(selector)
        locator.first.wait_for(state="attached", timeout=timeout)
        actual_count = locator.count()
        return actual_count == expected_count
    except Exception as e:
        logger.debug(f"Count assertion failed: {e}")
        return False


# ============================================================================
# Logging and reporting
# ============================================================================

def log_test_step(step_name: str, details: Optional[str] = None):
    """
    Log a test step.

    Args:
        step_name: Step name
        details: Additional details
    """
    logger.info(f"STEP: {step_name}")
    if details:
        logger.info(f"  Details: {details}")


def log_test_result(test_name: str, status: str, message: str):
    """
    Log a test result.

    Args:
        test_name: Test name
        status: Test status ("PASS"/"FAIL"/"SKIP")
        message: Description
    """
    logger.info(f"TEST: {test_name} - {status} - {message}")


def generate_test_summary(results: List[Dict]) -> str:
    """
    Generate a test summary.

    Args:
        results: List of test results

    Returns:
        Summary text
    """
    total = len(results)
    passed = sum(1 for r in results if r.get("passed", False))
    failed = total - passed
    pass_rate = (passed / total * 100) if total > 0 else 0.0

    summary = f"""
{'='*60}
Test Summary
{'='*60}
Total: {total}
Passed: {passed}
Failed: {failed}
Pass rate: {pass_rate:.1f}%
{'='*60}
"""

    if failed > 0:
        summary += "\nFailed tests:\n"
        for r in results:
            if not r.get("passed", False):
                summary += f"  - {r.get('name', 'Unknown')}: {r.get('error', 'Unknown error')}\n"

    return summary


# ============================================================================
# Misc utilities
# ============================================================================

def generate_unique_id(prefix: str = "test") -> str:
    """
    Generate a unique ID.

    Args:
        prefix: Prefix

    Returns:
        Unique ID
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{timestamp}"


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename (strip illegal characters).

    Args:
        filename: Original filename

    Returns:
        Sanitized filename
    """
    illegal_chars = '<>:"/\\|？*'
    for char in illegal_chars:
        filename = filename.replace(char, '_')
    return filename


def get_env_bool(env_var: str, default: bool = False) -> bool:
    """
    Get a boolean value from an environment variable.

    Args:
        env_var: Environment variable name
        default: Default value

    Returns:
        Boolean value
    """
    value = os.getenv(env_var, str(default)).lower()
    return value in ("true", "1", "yes")
