# -*- coding: utf-8 -*-
"""
QwenPaw E2E test framework - Page Object base class.

Provides common page operations; every page object should inherit from this class.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from config.settings import config


logger = logging.getLogger(__name__)


class BasePage:
    """
    Page Object base class.

    Provides common page operations including:
    - Navigation
    - Element lookup
    - Wait helpers
    - Screenshots
    - Assertion helpers
    """

    # Subclasses should override these attributes
    PAGE_TITLE: str = ""
    PAGE_URL: str = ""

    # Generic selectors (subclasses may override)
    SUCCESS_MESSAGE = '.ant-message-success, .qwenpaw-message-success, .qwenpaw-notification-success'
    ERROR_MESSAGE = '.ant-message-error, .qwenpaw-message-error, .qwenpaw-notification-error'
    LOADING_SPINNER = '.ant-spin, .qwenpaw-spin, [class*=loading]'

    def __init__(self, page: Page):
        self.page = page
        self.timeout = config.browser.timeout

    # ========== Navigation methods ==========

    def goto(self, url: Optional[str] = None) -> "BasePage":
        """
        Navigate to the given URL.

        Args:
            url: Target URL; falls back to PAGE_URL when omitted.

        Returns:
            self
        """
        target_url = url or self.PAGE_URL
        logger.info(f"Navigating to: {target_url}")
        self.page.goto(target_url, wait_until="commit", timeout=self.timeout)
        return self

    def refresh(self) -> "BasePage":
        """Reload the page."""
        logger.info("Refreshing page")
        self.page.reload(wait_until="commit", timeout=self.timeout)
        return self

    # ========== Element lookup methods ==========

    def find(self, selector: str, timeout: Optional[int] = None) -> Locator:
        """
        Find a single element.

        Args:
            selector: CSS selector.
            timeout: Timeout in milliseconds; only applied when explicitly passed.

        Returns:
            Locator object.
        """
        locator = self.page.locator(selector).first
        if timeout is not None:
            locator.wait_for(state="attached", timeout=timeout)
        return locator

    def find_all(self, selector: str) -> List[Locator]:
        """
        Find multiple elements.

        Args:
            selector: CSS selector.

        Returns:
            List of Locator objects.
        """
        return self.page.locator(selector).all()

    def find_by_text(self, text: str, exact: bool = False) -> Locator:
        """
        Find an element by text.

        Args:
            text: Text content.
            exact: Whether to require an exact match.

        Returns:
            Locator object.
        """
        return self.page.get_by_text(text, exact=exact).first

    def find_by_role(self, role: str, name: Optional[str] = None) -> Locator:
        """
        Find an element by ARIA role.

        Args:
            role: ARIA role.
            name: Optional name attribute.

        Returns:
            Locator object.
        """
        if name:
            return self.page.get_by_role(role, name=name).first
        return self.page.get_by_role(role).first

    def find_by_placeholder(self, placeholder: str) -> Locator:
        """
        Find an input by placeholder text.

        Args:
            placeholder: Placeholder text.

        Returns:
            Locator object.
        """
        return self.page.get_by_placeholder(placeholder).first

    def find_by_label(self, label: str) -> Locator:
        """
        Find an element by label.

        Args:
            label: Label text.

        Returns:
            Locator object.
        """
        return self.page.get_by_label(label).first

    def find_by_testid(self, testid: str) -> Locator:
        """
        Find an element by data-testid.

        Args:
            testid: Test ID value.

        Returns:
            Locator object.
        """
        return self.page.get_by_test_id(testid).first

    # ========== Wait methods ==========

    def wait_for_element(self, selector: str, timeout: Optional[int] = None, state: str = "visible") -> Locator:
        """
        Wait for an element to reach the given state.

        Args:
            selector: CSS selector.
            timeout: Timeout in milliseconds.
            state: Target state (visible, hidden, detached, attached).

        Returns:
            Locator object.
        """
        locator = self.page.locator(selector).first
        locator.wait_for(state=state, timeout=timeout or self.timeout)
        return locator

    def wait_for_text(self, text: str, timeout: Optional[int] = None) -> None:
        """
        Wait for the given text to appear in the page.

        Args:
            text: Expected text.
            timeout: Timeout in milliseconds.
        """
        import json
        safe_text = json.dumps(text)
        self.page.wait_for_function(
            f"document.body.innerText.includes({safe_text})",
            timeout=timeout or self.timeout
        )

    def wait_for_url(self, url_pattern: str, timeout: Optional[int] = None) -> None:
        """
        Wait for the URL to match a pattern.

        Args:
            url_pattern: URL pattern.
            timeout: Timeout in milliseconds.
        """
        self.page.wait_for_url(url_pattern, timeout=timeout or self.timeout)

    def wait_for_loading(self, timeout: Optional[int] = None) -> None:
        """Wait for the page to finish loading."""
        self.page.wait_for_load_state("networkidle", timeout=timeout or self.timeout)

    def wait(self, milliseconds: int) -> None:
        """
        Hard wait (use only when necessary).

        Args:
            milliseconds: Milliseconds to wait.
        """
        self.page.wait_for_timeout(milliseconds)

    # ========== Action methods ==========

    def click(self, selector: str, timeout: Optional[int] = None) -> "BasePage":
        """
        Click an element.

        Args:
            selector: CSS selector.
            timeout: Timeout in milliseconds.

        Returns:
            self
        """
        locator = self.find(selector)
        locator.click(timeout=timeout or self.timeout)
        logger.debug(f"Clicked: {selector}")
        return self

    def fill(self, selector: str, value: str) -> "BasePage":
        """
        Fill an input.

        Args:
            selector: CSS selector.
            value: Value to fill.

        Returns:
            self
        """
        locator = self.find(selector)
        locator.fill(value)
        logger.debug(f"Filled {selector} with: {value[:50]}...")
        return self

    def type_slowly(self, selector: str, value: str, delay: int = 50) -> "BasePage":
        """
        Type slowly (useful for testing input events).

        Args:
            selector: CSS selector.
            value: Value to type.
            delay: Delay between characters in milliseconds.

        Returns:
            self
        """
        locator = self.find(selector)
        locator.type(value, delay=delay)
        logger.debug(f"Typed slowly: {value[:50]}...")
        return self

    def press(self, selector: str, key: str) -> "BasePage":
        """
        Press a key.

        Args:
            selector: CSS selector.
            key: Key name (Enter, Tab, Escape, etc.).

        Returns:
            self
        """
        locator = self.find(selector)
        locator.press(key)
        logger.debug(f"Pressed {key} on {selector}")
        return self

    def hover(self, selector: str) -> "BasePage":
        """
        Hover over an element.

        Args:
            selector: CSS selector.

        Returns:
            self
        """
        locator = self.find(selector)
        locator.hover()
        logger.debug(f"Hovered: {selector}")
        return self

    def upload_file(self, selector: str, file_path: str) -> "BasePage":
        """
        Upload a file.

        Args:
            selector: File input selector.
            file_path: File path to upload.

        Returns:
            self
        """
        locator = self.find(selector)
        locator.set_input_files(file_path)
        logger.info(f"Uploaded file: {file_path}")
        return self

    def select_option(self, selector: str, value: str) -> "BasePage":
        """
        Select a dropdown option.

        Args:
            selector: Selector.
            value: Option value.

        Returns:
            self
        """
        locator = self.find(selector)
        locator.select_option(value)
        logger.debug(f"Selected option: {value}")
        return self

    # ========== Assertion helpers ==========

    def assert_visible(self, selector: str, timeout: Optional[int] = None) -> bool:
        """
        Assert that an element is visible.

        Args:
            selector: CSS selector.
            timeout: Timeout in milliseconds.

        Returns:
            Whether the element is visible.
        """
        try:
            expect(self.find(selector)).to_be_visible(timeout=timeout or self.timeout)
            return True
        except (TimeoutError, AssertionError, Exception):
            return False

    def assert_text(self, selector: str, expected_text: str, timeout: Optional[int] = None) -> bool:
        """
        Assert element text content.

        Args:
            selector: CSS selector.
            expected_text: Expected text.
            timeout: Timeout in milliseconds.

        Returns:
            Whether the text matches.
        """
        try:
            expect(self.find(selector)).to_contain_text(expected_text, timeout=timeout or self.timeout)
            return True
        except TimeoutError:
            return False

    def assert_count(self, selector: str, expected_count: int, timeout: Optional[int] = None) -> bool:
        """
        Assert the number of matching elements.

        Args:
            selector: CSS selector.
            expected_count: Expected count.
            timeout: Timeout in milliseconds.

        Returns:
            Whether the count matches.
        """
        try:
            expect(self.page.locator(selector)).to_have_count(expected_count, timeout=timeout or self.timeout)
            return True
        except TimeoutError:
            return False

    def assert_url(self, expected_url: str, timeout: Optional[int] = None) -> bool:
        """
        Assert the current URL.

        Args:
            expected_url: Expected URL.
            timeout: Timeout in milliseconds.

        Returns:
            Whether the URL matches.
        """
        try:
            expect(self.page).to_have_url(expected_url, timeout=timeout or self.timeout)
            return True
        except TimeoutError:
            return False

    # ========== Screenshots and debugging ==========

    def screenshot(self, name: str, full_page: bool = True) -> str:
        """
        Capture a screenshot.

        Args:
            name: Screenshot name.
            full_page: Whether to capture the full page.

        Returns:
            Screenshot file path.
        """
        path = config.paths.screenshots_dir / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=full_page)
        logger.info(f"Screenshot saved: {path}")
        return str(path)

    # ---- Step screenshot (per-case directory + auto-incremented index + safe filename) ----
    def step_shot(self, action: str, full_page: bool = False) -> str:
        """
        Capture a screenshot at a key test step and archive it per test case.

        - The test case name is passed through page._qwenpaw_test_name (injected by conftest).
        - File name: <seq>_<safe action>_<HHMMSS_ms>.png
        - Defaults to viewport only (full_page=False) to avoid slow long-page captures
          while a "Thinking" spinner is on screen.
        - Screenshot failures only emit a warning so they do not pollute the test run.

        Args:
            action: Short step name (e.g. "open_page" / "send_message_before").
            full_page: Whether to capture the full page (defaults to False).

        Returns:
            Screenshot file path; empty string on failure.
        """
        try:
            from datetime import datetime as _dt
            test_name = getattr(self.page, "_qwenpaw_test_name", None) or "unknown_test"
            # Sanitise: keep only alphanumerics, dash, and underscore
            import re as _re
            safe_test = _re.sub(r"[^A-Za-z0-9_\-]", "_", test_name)[:80]
            safe_action = _re.sub(r"[^A-Za-z0-9_\-]", "_", action)[:60]

            # Per-case subdirectory
            case_dir = config.paths.screenshots_dir / "steps" / safe_test
            case_dir.mkdir(parents=True, exist_ok=True)

            # Auto-increment sequence (stored on page, counted per test case)
            seq = getattr(self.page, "_qwenpaw_step_seq", 0) + 1
            try:
                self.page._qwenpaw_step_seq = seq
            except Exception:
                pass

            ts = _dt.now().strftime("%H%M%S_%f")[:-3]
            filename = f"{seq:02d}_{safe_action}_{ts}.png"
            path = case_dir / filename
            self.page.screenshot(path=str(path), full_page=full_page)
            logger.info(f"[step_shot] {test_name} -> {seq:02d}_{safe_action}")
            return str(path)
        except Exception as e:
            logger.warning(f"[step_shot] failed for action={action}: {e}")
            return ""

    def get_page_title(self) -> str:
        """Return the page title."""
        return self.page.title()

    def get_page_url(self) -> str:
        """Return the current URL."""
        return self.page.url

    def get_text(self, selector: str) -> str:
        """Return the inner text of an element."""
        return self.find(selector).inner_text()

    def get_attribute(self, selector: str, attribute: str) -> Optional[str]:
        """Return an attribute value of an element."""
        return self.find(selector).get_attribute(attribute)

    def is_enabled(self, selector: str) -> bool:
        """Check whether an element is enabled."""
        return self.find(selector).is_enabled()

    def is_disabled(self, selector: str) -> bool:
        """Check whether an element is disabled."""
        return self.find(selector).is_disabled()
