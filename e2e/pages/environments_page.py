# -*- coding: utf-8 -*-
"""
QwenPaw Environments page object.

Wraps all interactions on the environment variables configuration page and
exposes business-level methods.

Rebuilt for the unified environment management page (#7538, commit 76bfb704):

* The page is no longer an editable table.  It renders three read-oriented
  sections — "Custom variables", "Live settings" and "Read-only settings" —
  where each row shows the key in a ``<code>`` element and the value masked.
* Adding and editing go through a Modal (``Add Variable`` / ``Edit variable``)
  whose primary button is ``Apply now`` and which writes immediately
  (``PATCH /api/envs``).  There is no page-level Save button any more.
* Deleting goes through ``Modal.confirm`` (``Delete Variable`` / okText
  ``Delete``); a configured catalogue entry can additionally be ``Reset``.
* The pre-#7538 row checkboxes, batch delete and per-row "insert row below"
  action were removed from the product, so this page object does not expose
  them.

Selector strategy: class names are CSS-module scoped as
``[name]__[local]__[hash:base64:5]`` and this page's stylesheet shares the
``index.module.less`` filename with ``components/PageHeader``, so every
generated class begins with ``index-module__``.  Local names are therefore
matched double-underscore bounded (``__row__``, ``__page__``) to avoid
hitting neighbours like ``__envRow__`` or ``__pageHeader__``.  Because the
hash changes whenever the styles change, behavioural anchors (``aria-label``,
visible text, ``placeholder``) are preferred wherever the page provides them.

The console UI is English-only under e2e (``locale="en-US"`` in
``e2e/fixtures/__init__.py``), so no Chinese text fallbacks are kept.
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator, expect

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class EnvironmentsPage(BasePage):
    """
    Environments page object.

    Wraps the user interactions available on the environment variables page:
    - Open the page and wait for the catalogue
    - Count / locate variable rows by key
    - Add a variable through the editor Modal
    - Edit a variable through the editor Modal
    - Delete a variable through the confirm dialog
    - Filter variables with the search box
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/environments"

    # ========== Selector definitions ==========

    # Page load indicator: `styles.page` root.
    ENV_PAGE_CONTAINER = 'div[class*="__page__"]'
    PAGE_LOAD_INDICATOR = ENV_PAGE_CONTAINER
    # Rendered only once the catalogue has loaded (loading/error render
    # `styles.state` instead), so it doubles as the "data arrived" signal.
    SECTION_HEADING = 'div[class*="__sectionHeading__"]'
    CUSTOM_SECTION_HEADING = f'{SECTION_HEADING}:has-text("Custom variables")'
    CUSTOM_COUNT_SELECTOR = f'{CUSTOM_SECTION_HEADING} span'

    # Rows and their cells.
    ENV_ROW = 'div[class*="__row__"]'
    IDENTITY_CODE = 'div[class*="__identity__"] code'
    VALUE_CODE = 'div[class*="__valueText__"] code'

    # Actions.
    ADD_BTN = 'button:has-text("Add Variable")'
    SEARCH_INPUT = 'input[aria-label="Search variables"]'
    EDIT_BTN = 'button[aria-label="Edit"]'
    DELETE_BTN = 'button[aria-label="Delete"]'
    RESET_BTN = 'button[aria-label="Reset"]'
    SHOW_VALUE_BTN = 'button[aria-label="Show value"]'

    # Editor Modal.  `ConfigProvider prefixCls="qwenpaw"` (console/src/App.tsx)
    # makes antd emit `qwenpaw-*`; `ant-*` is kept as a degraded alternate
    # because both prefixes ship in the stylesheet.
    #
    # All modal selectors are `:visible`-scoped: antd does not destroy a
    # closed Modal by default, so an unscoped `.first` could resolve to a
    # stale hidden node left over from a previous interaction.
    MODAL = '.qwenpaw-modal:visible, .ant-modal:visible'
    MODAL_TITLE = (
        '.qwenpaw-modal:visible .qwenpaw-modal-title, '
        '.ant-modal:visible .ant-modal-title'
    )
    MODAL_KEY_INPUT = (
        '.qwenpaw-modal:visible input[placeholder="VARIABLE_NAME"], '
        '.ant-modal:visible input[placeholder="VARIABLE_NAME"]'
    )
    MODAL_VALUE_INPUT = (
        '.qwenpaw-modal:visible input[placeholder="value"], .ant-modal:visible input[placeholder="value"], '
        '.qwenpaw-modal:visible input[placeholder="Value"], .ant-modal:visible input[placeholder="Value"]'
    )
    MODAL_OK_CANDIDATES = (
        '.qwenpaw-modal:visible .qwenpaw-modal-footer button.qwenpaw-btn-primary',
        '.ant-modal:visible .ant-modal-footer button.ant-btn-primary',
        '.qwenpaw-modal:visible button:has-text("Apply now")',
        '.ant-modal:visible button:has-text("Apply now")',
    )
    MODAL_CANCEL_CANDIDATES = (
        '.qwenpaw-modal:visible .qwenpaw-modal-footer button:has-text("Cancel")',
        '.ant-modal:visible .ant-modal-footer button:has-text("Cancel")',
        '.qwenpaw-modal:visible button:has-text("Cancel")',
        '.ant-modal:visible button:has-text("Cancel")',
        '.qwenpaw-modal:visible .qwenpaw-modal-close',
        '.ant-modal:visible .ant-modal-close',
    )

    # Confirm dialog (static `Modal.confirm`, same prefix via holderRender).
    # `:visible`-scoped for the same stale-DOM reason: a static dialog is
    # created per call and several methods confirm more than once.
    CONFIRM_MODAL = '.qwenpaw-modal-confirm:visible, .ant-modal-confirm:visible'
    CONFIRM_BTNS_SCOPES = (
        '.qwenpaw-modal-confirm-btns',
        '.ant-modal-confirm-btns',
    )
    # okButtonProps {danger: !reset} => dangerous on delete, primary on reset.
    CONFIRM_OK_STYLES = ("dangerous", "primary")

    # Toasts (`useAppMessage()` → antd App context, same prefix).
    MESSAGE_NOTICE = (
        '.qwenpaw-message-notice-content, .qwenpaw-message-custom-content, '
        '.ant-message-notice-content, .ant-message-custom-content'
    )

    # Shipped copy for the outcomes tests assert on.
    MSG_APPLIED = "Environment variable applied"
    MSG_INVALID_KEY_FORMAT = "Invalid key format"
    MSG_DUPLICATE_KEY = "Duplicate key"

    # ========== Navigation ==========

    def open(self) -> "EnvironmentsPage":
        """Open the Environments page."""
        logger.info("Opening Environments page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "EnvironmentsPage":
        """Wait for the page shell and the loaded catalogue."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        expect(self.page.locator(self.SECTION_HEADING).first).to_be_visible(timeout=timeout)
        expect(self.page.locator(self.ADD_BTN).first).to_be_visible(timeout=timeout)
        return self

    # ========== Environment variable queries ==========

    def get_env_rows(self) -> List[Locator]:
        """Return all variable rows across the three sections."""
        rows = self.page.locator(self.ENV_ROW).all()
        logger.info(f"Found {len(rows)} environment variable rows")
        return rows

    def row_for_key(self, env_key: str) -> Locator:
        """Return the row whose identity cell shows exactly `env_key`.

        Positional anchors are unusable on this page: all three sections share
        `styles.row`, so `.last` points into the read-only catalogue rather
        than at a freshly created variable.
        """
        return self.page.locator(self.ENV_ROW).filter(
            has=self.page.locator(f'{self.IDENTITY_CODE}:text-is("{env_key}")')
        ).first

    def get_env_key(self, row: Locator) -> str:
        """Return the environment variable key shown by a row."""
        key_cell = row.locator(self.IDENTITY_CODE).first
        if key_cell.count() > 0:
            return key_cell.inner_text().strip()
        return ""

    def get_env_value(self, row: Locator) -> str:
        """Return the value shown by a row.

        Custom variables render their value masked ("••••••••") until the
        "Show value" action is used, so callers that need the real value
        should read it from the API instead of relying on this method.
        """
        value_cell = row.locator(self.VALUE_CODE).first
        if value_cell.count() > 0:
            return value_cell.inner_text().strip()
        return ""

    def get_custom_var_count(self, timeout: Optional[int] = None) -> int:
        """Return the count the "Custom variables" heading reports."""
        count_el = self.page.locator(self.CUSTOM_COUNT_SELECTOR).first
        expect(count_el).to_be_visible(timeout=timeout or self.timeout)
        raw = count_el.inner_text().strip()
        if not raw.isdigit():
            raise AssertionError(f"Custom variables count is not an integer: {raw!r}")
        return int(raw)

    # ========== Environment variable operations ==========

    def click_add(self, timeout: Optional[int] = None) -> Locator:
        """Click "Add Variable" and return the editor Modal."""
        timeout = timeout or self.timeout
        add_btn = self.page.locator(self.ADD_BTN).first
        expect(add_btn).to_be_visible(timeout=timeout)
        add_btn.click()
        modal = self.page.locator(self.MODAL).first
        expect(modal).to_be_visible(timeout=timeout)
        expect(self.page.locator(self.MODAL_KEY_INPUT).first).to_be_visible(timeout=timeout)
        logger.info("Opened the Add Variable modal")
        return modal

    def fill_modal(self, key: Optional[str] = None, value: Optional[str] = None) -> None:
        """Fill the Key / Value inputs of the open editor Modal."""
        if key is not None:
            key_input = self.page.locator(self.MODAL_KEY_INPUT).first
            expect(key_input).to_be_visible(timeout=self.timeout)
            key_input.fill(key)
        if value is not None:
            value_input = self.page.locator(self.MODAL_VALUE_INPUT).first
            expect(value_input).to_be_visible(timeout=self.timeout)
            value_input.fill(value)
        self.page.wait_for_timeout(200)

    def _first_visible(self, candidates) -> Locator:
        """Return the first candidate selector resolving to a visible node.

        Walked in priority order on purpose: Playwright resolves `.first` on a
        comma-separated selector list by *document* position, so expressing
        "prefer the precise anchor, fall back to the loose one" as one list
        would let the loose one win whenever it appears earlier in the DOM.
        """
        for selector in candidates:
            candidate = self.page.locator(selector).first
            try:
                if candidate.count() > 0 and candidate.is_visible():
                    return candidate
            except Exception:
                continue
        return self.page.locator(candidates[0]).first

    def _confirm_ok_button(self) -> Locator:
        """Return the visible confirm dialog's OK button (Delete or Reset)."""
        dialog = self.page.locator(self.CONFIRM_MODAL).first
        candidates = []
        for scope in self.CONFIRM_BTNS_SCOPES:
            prefix = "qwenpaw" if "qwenpaw" in scope else "ant"
            for style in self.CONFIRM_OK_STYLES:
                candidates.append(dialog.locator(f"{scope} button.{prefix}-btn-{style}"))
        for candidate in candidates:
            try:
                if candidate.count() > 0 and candidate.first.is_visible():
                    return candidate.first
            except Exception:
                continue
        return candidates[0].first

    def click_apply(self) -> None:
        """Click the Modal primary button ("Apply now") — this writes."""
        ok_btn = self._first_visible(self.MODAL_OK_CANDIDATES)
        expect(ok_btn).to_be_visible(timeout=self.timeout)
        ok_btn.click()
        logger.info("Clicked Apply now")

    def click_modal_cancel(self) -> None:
        """Dismiss the editor Modal without writing."""
        cancel_btn = self._first_visible(self.MODAL_CANCEL_CANDIDATES)
        expect(cancel_btn).to_be_visible(timeout=self.timeout)
        cancel_btn.click()
        logger.info("Cancelled the editor modal")

    def _expect_modal_closed(self) -> None:
        """Wait until the editor Modal is gone.

        `to_be_hidden()` rather than `to_have_count(0)`: antd keeps a closed
        Modal's DOM in place, so counting nodes would still see the Key input
        after a successful close and never pass.
        """
        expect(self.page.locator(self.MODAL_KEY_INPUT).first).to_be_hidden(
            timeout=self.timeout
        )

    def add_variable(self, key: str, value: str) -> None:
        """Create a custom variable through the UI and wait for it to appear."""
        self.click_add()
        self.fill_modal(key=key, value=value)
        self.click_apply()
        self._expect_modal_closed()
        expect(self.row_for_key(key)).to_be_visible(timeout=self.timeout)
        logger.info(f"Added variable {key}")

    def edit_variable(self, key: str, new_value: str) -> None:
        """Edit an existing variable's value through the row action."""
        row = self.row_for_key(key)
        expect(row).to_be_visible(timeout=self.timeout)
        expect(row.locator(self.EDIT_BTN).first).to_be_visible(timeout=self.timeout)
        row.locator(self.EDIT_BTN).first.click()
        expect(self.page.locator(self.MODAL_KEY_INPUT).first).to_be_visible(timeout=self.timeout)
        self.fill_modal(value=new_value)
        self.click_apply()
        self._expect_modal_closed()
        expect(self.row_for_key(key)).to_be_visible(timeout=self.timeout)
        logger.info(f"Edited variable {key}")

    def delete_variable(self, key: str) -> None:
        """Delete a custom variable through the row action + confirm dialog."""
        row = self.row_for_key(key)
        expect(row).to_be_visible(timeout=self.timeout)
        expect(row.locator(self.DELETE_BTN).first).to_be_visible(timeout=self.timeout)
        row.locator(self.DELETE_BTN).first.click()
        expect(self.page.locator(self.CONFIRM_MODAL).first).to_be_visible(timeout=self.timeout)
        confirm_ok = self._confirm_ok_button()
        expect(confirm_ok).to_be_visible(timeout=self.timeout)
        confirm_ok.click()
        # CONFIRM_MODAL is :visible-scoped, so count 0 means "no dialog showing".
        expect(self.page.locator(self.CONFIRM_MODAL)).to_have_count(0, timeout=self.timeout)
        logger.info(f"Deleted variable {key}")

    def search(self, query: str) -> None:
        """Filter the catalogue with the search box."""
        search_input = self.page.locator(self.SEARCH_INPUT).first
        expect(search_input).to_be_visible(timeout=self.timeout)
        search_input.fill(query)
        self.page.wait_for_timeout(500)
        logger.info(f"Filtered variables by {query!r}")

    # ========== Assertion methods ==========

    def assert_env_row_count(self, expected_count: int, timeout: Optional[int] = None) -> "EnvironmentsPage":
        """Assert the total variable row count across all sections."""
        expect(self.page.locator(self.ENV_ROW)).to_have_count(
            expected_count, timeout=timeout or self.timeout
        )
        return self

    def assert_env_exists(self, env_key: str, timeout: Optional[int] = None) -> "EnvironmentsPage":
        """Assert that a variable row with this key is visible."""
        expect(self.row_for_key(env_key)).to_be_visible(timeout=timeout or self.timeout)
        return self

    def assert_env_absent(self, env_key: str, timeout: Optional[int] = None) -> "EnvironmentsPage":
        """Assert that no variable row with this key exists."""
        expect(self.row_for_key(env_key)).to_have_count(0, timeout=timeout or self.timeout)
        return self
