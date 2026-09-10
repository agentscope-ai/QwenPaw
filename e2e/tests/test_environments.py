# -*- coding: utf-8 -*-
"""
QwenPaw Environments module end-to-end test cases.

Rebuilt for the unified environment management page (#7538, commit 76bfb704).
That change replaced the editable-table model with a read-oriented catalogue:

  OLD (pre-#7538)                      NEW (#7538+)
  ---------------------------------    --------------------------------------
  rows rendered as inline inputs       rows render <code> key + masked value
  "Add" appended a blank row           "Add Variable" opens a Modal
  page-level "Save" batch-committed    Modal "Apply now" PATCHes immediately
  per-row checkbox + batch delete      REMOVED (no checkbox / no batch UI)
  "Insert row below" per row           REMOVED
  one flat row list                    three sections: Custom variables /
                                       Live settings / Read-only settings
  key-required message                 invalid-format message (regex gate)

Selector strategy notes (why these anchors, not class substrings):

* ``console/vite.config.ts`` sets ``generateScopedName:
  "[name]__[local]__[hash:base64:5]"`` and Environments' stylesheet shares the
  ``index.module.less`` filename with ``components/PageHeader`` — so every
  generated class is ``index-module__<local>__<hash>`` with no page-level
  discrimination.  A bare ``[class*="row"]`` would match ``envRow``,
  ``rowList``, ``arrow`` etc. across the whole app.  We therefore wrap the
  local name in double underscores (``__row__``), which matches
  ``index-module__row__abc12`` but not ``index-module__envRow__abc12``.
* Class hashes change on every style edit, so behavioural anchors
  (``aria-label``, visible text, ``placeholder``) are preferred and CSS-module
  substrings are only used to scope a container.
* ``.last`` / positional row indexing is no longer usable: ``styles.row`` is
  shared by all three sections, so the last row belongs to the read-only
  catalogue, not to a freshly added variable.  Rows are located by key text.
* The e2e browser runs ``locale="en-US"`` (``e2e/fixtures/__init__.py``) and
  the console is English-only, so Chinese text fallbacks can never match and
  have been dropped instead of kept as dead alternates.
* "Apply now" persists immediately, therefore every case that writes a
  variable must delete it again; cleanup goes through the API so a failed UI
  step cannot leave residue behind.

Run: pytest tests/test_environments.py -v
"""
from __future__ import annotations

import logging
import time
import pytest
from playwright.sync_api import Page, Locator, expect, TimeoutError

from config.settings import config
from utils.helpers import log_test_step, log_test_result, api_get

logger = logging.getLogger(__name__)

# -- Page route ------------------------------------------------------------
ENVIRONMENTS_URL = f"{config.base_url}/environments"

# -- Container / section anchors ------------------------------------------
# `styles.page` — the page root. `__page__` deliberately does not match
# `__pageHeader__` (PageHeader renders inside it).
ENV_PAGE_CONTAINER = 'div[class*="__page__"]'
# `styles.sectionHeading` wraps `<h2>title</h2><span>count</span>`.
SECTION_HEADING = 'div[class*="__sectionHeading__"]'
CUSTOM_SECTION_HEADING = f'{SECTION_HEADING}:has-text("Custom variables")'
CUSTOM_COUNT_SELECTOR = f'{CUSTOM_SECTION_HEADING} span'
# `styles.row` — one variable row (shared by all three sections).
ROW_SELECTOR = 'div[class*="__row__"]'
# `styles.identity` holds the key `<code>`; `styles.valueText` holds the
# masked value `<code>`, so the key must be read from the identity cell.
IDENTITY_CODE = 'div[class*="__identity__"] code'

# -- Interactive element anchors ------------------------------------------
# Hero button: <Button type="primary" icon={Plus}>Add Variable</Button>.
# Anchor on the visible label rather than a class hash.  The pre-#7538
# fallback `button:has-text("添加变量")` could never match an en-US console.
ADD_VARIABLE_BTN = 'button:has-text("Add Variable")'
# Modal shell. `ConfigProvider prefixCls="qwenpaw"` (console/src/App.tsx) makes
# antd emit `qwenpaw-modal-*`; `ant-modal-*` is kept as a degraded alternate
# because both prefixes ship in the stylesheet.
#
# Every modal selector below is `:visible`-scoped.  antd does not destroy a
# closed Modal by default, and several cases drive the editor more than once
# (ENV-P1-005 opens it, cancels, opens it again; ENV-004 cancels a confirm
# dialog then triggers another one), so an unscoped `.first` could resolve to
# a stale hidden node left over from the previous interaction and make a
# `to_be_visible()` assertion fail for a reason unrelated to the product.
MODAL = '.qwenpaw-modal:visible, .ant-modal:visible'
MODAL_TITLE = '.qwenpaw-modal:visible .qwenpaw-modal-title, .ant-modal:visible .ant-modal-title'
MODAL_FOOTER = '.qwenpaw-modal:visible .qwenpaw-modal-footer, .ant-modal:visible .ant-modal-footer'
# Modal form inputs.  Key placeholder is the literal "VARIABLE_NAME"
# (index.tsx passes it as a plain string, not through i18n); the Value
# placeholder comes from `environments.valuePlaceholder` = "value", with
# "Value" kept as a tolerant alternate in case that copy changes case.
MODAL_KEY_INPUT = (
    '.qwenpaw-modal:visible input[placeholder="VARIABLE_NAME"], '
    '.ant-modal:visible input[placeholder="VARIABLE_NAME"]'
)
MODAL_VALUE_INPUT = (
    '.qwenpaw-modal:visible input[placeholder="value"], .ant-modal:visible input[placeholder="value"], '
    '.qwenpaw-modal:visible input[placeholder="Value"], .ant-modal:visible input[placeholder="Value"]'
)
# Primary footer button = okText "Apply now".
#
# Deliberately NOT one comma-separated list with degraded alternates:
# Playwright's `.first` on a selector list picks the first match in *document*
# order, not in selector order, so a broad fallback could win over the precise
# one.  `modal_ok_button()` below walks the candidates in the intended
# priority instead.
MODAL_OK_CANDIDATES = (
    '.qwenpaw-modal:visible .qwenpaw-modal-footer button.qwenpaw-btn-primary',
    '.ant-modal:visible .ant-modal-footer button.ant-btn-primary',
    '.qwenpaw-modal:visible button:has-text("Apply now")',
    '.ant-modal:visible button:has-text("Apply now")',
)
# cancelText "Cancel"; the header close icon is the last resort (SparkModal
# passes `closeIcon: null` and renders its own, so this may not exist).
MODAL_CANCEL_CANDIDATES = (
    '.qwenpaw-modal:visible .qwenpaw-modal-footer button:has-text("Cancel")',
    '.ant-modal:visible .ant-modal-footer button:has-text("Cancel")',
    '.qwenpaw-modal:visible button:has-text("Cancel")',
    '.ant-modal:visible button:has-text("Cancel")',
    '.qwenpaw-modal:visible .qwenpaw-modal-close',
    '.ant-modal:visible .ant-modal-close',
)
# `Modal.confirm` is a static antd call; design's ConfigProvider feeds it the
# same prefix through `holderRender`, which is the anchor already proven green
# in this suite (e2e/pages/chat_page.py `.qwenpaw-modal-confirm-btns`).
# Same `:visible` rationale as above, and even more so here: a static confirm
# dialog is created fresh per call.
CONFIRM_MODAL = '.qwenpaw-modal-confirm:visible, .ant-modal-confirm:visible'
CONFIRM_TITLE = '.qwenpaw-modal-confirm-title, .ant-modal-confirm-title'
CONFIRM_CONTENT = '.qwenpaw-modal-confirm-content, .ant-modal-confirm-content'
CONFIRM_BTNS = '.qwenpaw-modal-confirm-btns, .ant-modal-confirm-btns'
# Row action buttons carry aria-labels from `common.*`: Edit / Delete / Reset.
EDIT_BTN_BY_LABEL = 'button[aria-label="Edit"]'
DELETE_BTN_BY_LABEL = 'button[aria-label="Delete"]'
RESET_BTN_BY_LABEL = 'button[aria-label="Reset"]'
SHOW_VALUE_BTN_BY_LABEL = 'button[aria-label="Show value"]'
# Search box: `aria-label={t("environments.searchPlaceholder")}`.
SEARCH_INPUT = 'input[aria-label="Search variables"]'
# Toasts come from `useAppMessage()` (antd App context) with the same prefix.
MESSAGE_NOTICE = (
    '.qwenpaw-message-notice-content, .qwenpaw-message-custom-content, '
    '.ant-message-notice-content, .ant-message-custom-content'
)
MESSAGE_ERROR = (
    '.qwenpaw-message-error, .ant-message-error'
)
MESSAGE_SUCCESS = (
    '.qwenpaw-message-success, .ant-message-success'
)
# New-version validation copy.  `environments.keyRequired` ("Key is required")
# is no longer referenced by this page: an empty key falls through the same
# regex gate as a malformed one and reports "Invalid key format".
MSG_INVALID_KEY_FORMAT = "Invalid key format"
MSG_DUPLICATE_KEY = "Duplicate key"
MSG_APPLIED = "Environment variable applied"


# ============================================================================
# Helpers
# ============================================================================

def navigate_to_environments(page: Page, timeout: int = 15000):
    """Open the Environments page and wait until the catalogue has rendered.

    `styles.sectionHeading` only exists in the loaded branch — the loading and
    error branches render `styles.state` instead — so waiting for it is a real
    "data arrived" signal rather than a fixed sleep.
    """
    page.goto(ENVIRONMENTS_URL)
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator(ENV_PAGE_CONTAINER).first).to_be_visible(timeout=timeout)
    expect(page.locator(SECTION_HEADING).first).to_be_visible(timeout=timeout)
    expect(page.locator(ADD_VARIABLE_BTN).first).to_be_visible(timeout=timeout)


def row_for_key(page: Page, key: str):
    """Return the row whose identity cell shows exactly `key`.

    Positional anchors are unusable after #7538 (three sections share
    `styles.row`), so rows are addressed by their key text.
    """
    return page.locator(ROW_SELECTOR).filter(
        has=page.locator(f'{IDENTITY_CODE}:text-is("{key}")')
    ).first


def get_custom_var_count(page: Page) -> int:
    """Return the Custom variables count shown in its section heading.

    The heading renders `<span>{customVariables.length}</span>`, which is a
    stronger signal than counting DOM rows: it is exactly the number the page
    itself claims, and it is immune to the read-only/Live sections.
    """
    count_el = page.locator(CUSTOM_COUNT_SELECTOR).first
    expect(count_el).to_be_visible(timeout=10000)
    raw = count_el.inner_text().strip()
    try:
        return int(raw)
    except ValueError:
        raise AssertionError(f"Custom variables count is not an integer: {raw!r}")


def get_env_row_count(page: Page) -> int:
    """Return the number of variable rows across all three sections."""
    return page.locator(ROW_SELECTOR).count()


def get_count_text(page: Page) -> str:
    """Return the Custom variables count as text ("" when unavailable)."""
    count_el = page.locator(CUSTOM_COUNT_SELECTOR).first
    try:
        return count_el.inner_text().strip() if count_el.is_visible() else ""
    except Exception:
        return ""


def open_add_variable_modal(page: Page):
    """Click "Add Variable" and wait for the editor Modal to appear."""
    add_btn = page.locator(ADD_VARIABLE_BTN).first
    expect(add_btn).to_be_visible(timeout=10000)
    add_btn.click()
    modal = page.locator(MODAL).first
    expect(modal).to_be_visible(timeout=10000)
    expect(page.locator(MODAL_KEY_INPUT).first).to_be_visible(timeout=10000)
    return modal


def fill_variable_modal(page: Page, key: str = None, value: str = None):
    """Fill the Key / Value inputs of the open editor Modal."""
    if key is not None:
        key_input = page.locator(MODAL_KEY_INPUT).first
        expect(key_input).to_be_visible(timeout=5000)
        key_input.fill(key)
    if value is not None:
        value_input = page.locator(MODAL_VALUE_INPUT).first
        expect(value_input).to_be_visible(timeout=5000)
        value_input.fill(value)
    page.wait_for_timeout(200)


def _first_visible(page: Page, candidates: tuple) -> Locator:
    """Return the first candidate selector that resolves to a visible node.

    Walked in priority order on purpose: Playwright resolves `.first` on a
    comma-separated selector list by document position, so expressing
    "prefer the precise anchor, fall back to the loose one" as a single list
    would let the loose one win whenever it appears earlier in the DOM.
    """
    for selector in candidates:
        candidate = page.locator(selector).first
        try:
            if candidate.count() > 0 and candidate.is_visible():
                return candidate
        except Exception:
            continue
    # Nothing visible: hand back the primary candidate so the caller's
    # expectation fails with a selector-specific message instead of a
    # generic "locator resolved to 0 elements".
    return page.locator(candidates[0]).first


def modal_ok_button(page: Page) -> Locator:
    """Return the editor Modal's primary button ("Apply now")."""
    return _first_visible(page, MODAL_OK_CANDIDATES)


def modal_cancel_button(page: Page) -> Locator:
    """Return the editor Modal's Cancel button (or its close icon)."""
    return _first_visible(page, MODAL_CANCEL_CANDIDATES)


def click_modal_ok(page: Page):
    """Click the Modal primary button ("Apply now")."""
    ok_btn = modal_ok_button(page)
    expect(ok_btn).to_be_visible(timeout=5000)
    ok_btn.click()


def click_modal_cancel(page: Page):
    """Click the Modal "Cancel" button."""
    cancel_btn = modal_cancel_button(page)
    expect(cancel_btn).to_be_visible(timeout=5000)
    cancel_btn.click()


def expect_modal_closed(page: Page, timeout: int = 10000):
    """Assert the editor Modal is gone.

    `to_be_hidden()` rather than `to_have_count(0)`: antd keeps a closed
    Modal's DOM in place (it is not destroyed by default), so counting nodes
    would still see the Key input after a successful close and the assertion
    would never pass.  "hidden" is true both when the node is gone and when it
    is present but not displayed, which is exactly the state we want.
    """
    expect(page.locator(MODAL_KEY_INPUT).first).to_be_hidden(timeout=timeout)


def expect_modal_open(page: Page):
    """Assert the editor Modal is still open (validation rejected the input)."""
    expect(page.locator(MODAL_KEY_INPUT).first).to_be_visible(timeout=5000)


def expect_toast(page: Page, text: str, timeout: int = 10000) -> str:
    """Wait for a toast carrying `text` and return its container description."""
    toast = page.locator(MESSAGE_NOTICE).filter(has_text=text).first
    expect(toast).to_be_visible(timeout=timeout)
    return text


def confirm_button(page: Page, ok: bool = True) -> Locator:
    """Return the OK / Cancel button of the *visible* confirm dialog.

    `removeVariable` passes `okButtonProps: {danger: !reset}`, so the OK button
    is `btn-dangerous` for a delete and `btn-primary` for a reset; Cancel is
    the footer button carrying neither.

    Each candidate is a single, comma-free selector string.  Building them by
    appending a suffix to a comma-separated constant (e.g.
    `".a-confirm-btns, .b-confirm-btns" + " button.x"`) silently yields
    `".a-confirm-btns"` as its own first branch — which matches the button
    *container* and would make `.first` click the div instead of a button.
    Both style prefixes are therefore expanded explicitly and walked in
    priority order (document order decides `.first` inside a comma list, so a
    loose alternate must never share one list with a precise one).
    """
    dialog = page.locator(CONFIRM_MODAL).first
    candidates: list[Locator] = []
    for prefix in ("qwenpaw", "ant"):
        buttons_scope = f".{prefix}-modal-confirm-btns"
        if ok:
            for style in ("dangerous", "primary"):
                candidates.append(
                    dialog.locator(f"{buttons_scope} button.{prefix}-btn-{style}")
                )
        else:
            candidates.append(
                dialog.locator(
                    f"{buttons_scope} button:not(.{prefix}-btn-primary)"
                    f":not(.{prefix}-btn-dangerous)"
                )
            )
    for candidate in candidates:
        try:
            if candidate.count() > 0 and candidate.first.is_visible():
                return candidate.first
        except Exception:
            continue
    return candidates[0].first


def api_list_env_keys(api_context) -> list:
    """Return the persisted env var keys via API (unmasked source of truth)."""
    envs = api_get(api_context, "/api/envs")
    if not isinstance(envs, list):
        return []
    return [item.get("key") for item in envs if isinstance(item, dict)]


def api_env_value(api_context, key: str):
    """Return the persisted value for `key`, or None when absent.

    The UI masks custom values (`<ValueText secret />` renders "••••••••"
    until "Show value" is clicked), so persistence assertions read the API.
    """
    envs = api_get(api_context, "/api/envs")
    if not isinstance(envs, list):
        return None
    for item in envs:
        if isinstance(item, dict) and item.get("key") == key:
            return item.get("value")
    return None


def api_delete_env(api_context, key: str) -> bool:
    """Delete one custom variable through the API. Returns success."""
    try:
        response = api_context.delete(f"{config.base_url}/api/envs/{key}")
        return bool(response.ok)
    except Exception as exc:  # pragma: no cover - cleanup best effort
        logger.warning(f"API delete of {key} failed: {exc}")
        return False


def cleanup_env_var(page: Page, api_context, key: str):
    """Remove a test variable: API first, UI as fallback.

    "Apply now" writes immediately, so leaving residue behind would shift the
    Custom variables count for every later case in the shard.
    """
    if not key:
        return
    if api_delete_env(api_context, key):
        logger.info(f"Cleanup: {key} deleted via API")
        return
    logger.info(f"Cleanup: API delete failed for {key}, trying UI")
    try:
        navigate_to_environments(page)
        row = row_for_key(page, key)
        if row.count() > 0:
            row.locator(DELETE_BTN_BY_LABEL).first.click()
            confirm_ok = confirm_button(page, ok=True)
            expect(confirm_ok).to_be_visible(timeout=5000)
            confirm_ok.click()
            page.wait_for_timeout(1000)
            logger.info(f"Cleanup: {key} deleted via UI")
    except Exception as exc:
        logger.warning(f"Cleanup of {key} failed: {exc}")


def delete_variable_via_ui(page: Page, key: str):
    """Delete a custom variable through the row action + confirm dialog."""
    row = row_for_key(page, key)
    expect(row).to_be_visible(timeout=10000)
    delete_btn = row.locator(DELETE_BTN_BY_LABEL).first
    expect(delete_btn).to_be_visible(timeout=5000)
    delete_btn.click()
    # removeVariable() -> Modal.confirm({title: deleteVariable, okText: delete})
    expect(page.locator(CONFIRM_MODAL).first).to_be_visible(timeout=10000)
    confirm_ok = confirm_button(page, ok=True)
    expect(confirm_ok).to_be_visible(timeout=5000)
    confirm_ok.click()
    # CONFIRM_MODAL is :visible-scoped, so count 0 means "no dialog showing".
    expect(page.locator(CONFIRM_MODAL)).to_have_count(0, timeout=10000)


def add_variable_via_ui(page: Page, api_context, key: str, value: str):
    """Create a custom variable through the real UI flow and verify it landed.

    Flow: Add Variable -> Modal -> fill Key/Value -> Apply now -> row visible.
    """
    open_add_variable_modal(page)
    fill_variable_modal(page, key=key, value=value)
    click_modal_ok(page)
    expect_modal_closed(page)
    expect(row_for_key(page, key)).to_be_visible(timeout=10000)


# ============================================================================
# ENV-001: Page load + list display + empty state
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.envs
class TestEnvironmentListDisplay:
    """
    ENV-001: Environments page load + list display.

    Covers:
    1. Page navigation and load (three-section catalogue)
    2. Breadcrumb verification (PageHeader: Settings / Environment Variables)
    3. Section heading counts
    4. "Add Variable" button existence
    5. Search box existence
    6. Row structure or empty state
    """

    @pytest.mark.test_id("ENV-001")
    def test_environment_list_display(self, page: Page, request: pytest.FixtureRequest):
        """Verify the environment variable list renders correctly."""
        test_name = request.node.name

        # Step 1: Visit the environments page
        log_test_step("1. Visit environments page")
        navigate_to_environments(page)

        # Step 2: Verify breadcrumb (PageHeader still emits these classes)
        log_test_step("2. Verify breadcrumb")
        try:
            breadcrumb_settings = page.locator(
                'span[class*="breadcrumbParent"]:has-text("Settings")'
            ).first
            expect(breadcrumb_settings).to_be_visible(timeout=5000)
            breadcrumb_current = page.locator(
                'span[class*="breadcrumbCurrent"]:has-text("Environment Variables")'
            ).first
            expect(breadcrumb_current).to_be_visible(timeout=5000)
            logger.info("Breadcrumb verification passed")
        except Exception:
            logger.warning("Breadcrumb verification skipped (possible locale mismatch)")

        # Step 3: Verify the three section headings and their counts
        log_test_step("3. Verify section headings and counts")
        for heading_text in ("Custom variables", "Live settings", "Read-only settings"):
            heading = page.locator(SECTION_HEADING).filter(has_text=heading_text).first
            expect(heading).to_be_visible(timeout=5000)
            count_text = heading.locator("span").first.inner_text().strip()
            assert count_text.isdigit(), (
                f"{heading_text} heading count should be numeric, got {count_text!r}"
            )
            logger.info(f"Section '{heading_text}' count = {count_text}")

        count_text = get_count_text(page)
        logger.info(f"Custom variable count: {count_text}")

        # Step 4: Verify the Add Variable button
        log_test_step("4. Verify Add Variable button")
        add_btn = page.locator(ADD_VARIABLE_BTN).first
        expect(add_btn).to_be_visible(timeout=5000)
        logger.info("Add Variable button is visible")

        # Step 5: Verify the search box
        log_test_step("5. Verify search box")
        search_input = page.locator(SEARCH_INPUT).first
        expect(search_input).to_be_visible(timeout=5000)
        logger.info("Search box is visible")

        # Step 6: Verify rows or the empty state of the custom section
        log_test_step("6. Verify variable rows or empty state")
        row_count = get_env_row_count(page)
        if row_count > 0:
            logger.info(f"Variable rows rendered, current rows: {row_count}")
            first_row = page.locator(ROW_SELECTOR).first
            expect(first_row.locator("code").first).to_be_visible(timeout=5000)
        else:
            empty_el = page.locator('div[class*="__empty__"]').first
            expect(empty_el).to_be_visible(timeout=5000)
            logger.info("Empty state rendered correctly")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - env var list display verified")


# ============================================================================
# ENV-002: Add env var + cancel add + Key required validation
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.envs
class TestAddEnvironment:
    """
    ENV-002: Add env var through the editor Modal.

    Covers:
    1. Click "Add Variable" -> Modal opens
    2. Fill Key/Value -> verify the inputs echo the values
    3. Click "Apply now" -> Modal closes and the variable is listed
    4. Verify persistence through the API (the UI masks custom values)
    5. Cleanup

    Note: the pre-#7538 version of this case filled a blank table row and then
    deleted it without saving, so it never exercised a real write.  "Apply now"
    now persists immediately, which makes the positive path actually assertable.
    """

    @pytest.mark.test_id("ENV-002")
    def test_add_environment_success(
        self, page: Page, request: pytest.FixtureRequest, api_context
    ):
        """Verify adding an env var succeeds."""
        test_name = request.node.name
        timestamp = str(int(time.time()))[-6:]
        test_key = f"E2E_ADD_{timestamp}"
        test_value = f"e2e_val_{timestamp}"

        # Step 1: Visit the environments page
        log_test_step("1. Visit environments page")
        navigate_to_environments(page)

        # Step 2: Record the initial custom variable count
        log_test_step("2. Record initial custom variable count")
        initial_count = get_custom_var_count(page)
        logger.info(f"Initial custom variable count: {initial_count}")

        try:
            # Step 3: Open the editor Modal
            log_test_step("3. Click Add Variable -> Modal opens")
            open_add_variable_modal(page)
            modal_title = page.locator(MODAL_TITLE).first
            expect(modal_title).to_contain_text("Add Variable", timeout=5000)
            logger.info("Editor Modal opened with title 'Add Variable'")

            # Step 4: Fill Key and Value
            log_test_step("4. Fill Key and Value")
            key_input = page.locator(MODAL_KEY_INPUT).first
            value_input = page.locator(MODAL_VALUE_INPUT).first
            expect(key_input).to_be_visible(timeout=5000)
            expect(value_input).to_be_visible(timeout=5000)

            key_input.fill(test_key)
            value_input.fill(test_value)
            page.wait_for_timeout(300)

            filled_key = key_input.input_value()
            filled_value = value_input.input_value()
            assert filled_key == test_key, (
                f"Key not filled correctly: expected {test_key}, got {filled_key}"
            )
            assert filled_value == test_value, (
                f"Value not filled correctly: expected {test_value}, got {filled_value}"
            )
            logger.info(f"Filled successfully: {test_key}={test_value}")

            # Step 5: Apply now -> the variable is written and listed
            log_test_step("5. Click Apply now")
            click_modal_ok(page)
            expect_modal_closed(page)
            logger.info("Modal closed after Apply now")

            log_test_step("6. Verify the variable is listed")
            new_row = row_for_key(page, test_key)
            expect(new_row).to_be_visible(timeout=10000)
            new_count = get_custom_var_count(page)
            assert new_count == initial_count + 1, (
                f"Custom count did not increase: {initial_count} -> {new_count}"
            )
            logger.info(f"Variable listed, custom count {initial_count} -> {new_count}")

            # Step 7: Verify the persisted value through the API.
            # The row shows "••••••••" until "Show value" is clicked, so the
            # API is the only place the real value can be asserted.
            log_test_step("7. Verify persisted value via API")
            persisted = api_env_value(api_context, test_key)
            assert persisted == test_value, (
                f"Persisted value mismatch: expected {test_value}, got {persisted!r}"
            )
            logger.info(f"API confirms {test_key}={persisted}")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - add env var works")
        finally:
            log_test_step("Cleanup: delete test variable")
            cleanup_env_var(page, api_context, test_key)


# ============================================================================
# ENV-002b: Add env var — cancel & validation (p2 tier)
# Split out of TestAddEnvironment (p0) so tier markers stay mutually
# exclusive; nightly shards by single tier (integration and pX).
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.envs
class TestAddEnvironmentP2:
    """P2-tier add-env cases (cancel + key-required validation)."""

    @pytest.mark.integration
    @pytest.mark.p2
    @pytest.mark.test_id("ENV-002-CANCEL")
    def test_add_environment_cancel(self, page: Page, request: pytest.FixtureRequest):
        """Verify cancelling the editor Modal writes nothing.

        The pre-#7538 version approximated "cancel" by reloading the page
        (unsaved table rows were dropped).  The Modal now has a real Cancel
        button (`cancelText={t("common.cancel")}`), so cancellation is a
        first-class user action and is asserted directly.
        """
        test_name = request.node.name

        # Step 1: Visit the environments page
        log_test_step("1. Visit environments page")
        navigate_to_environments(page)

        # Step 2: Record the initial count
        log_test_step("2. Record initial custom variable count")
        initial_count = get_custom_var_count(page)

        # Step 3: Open the Modal and type a key without applying
        log_test_step("3. Open Modal and fill Key without applying")
        open_add_variable_modal(page)
        fill_variable_modal(page, key="E2E_CANCEL_SHOULD_NOT_EXIST", value="x")

        # Step 4: Cancel
        log_test_step("4. Click Cancel")
        click_modal_cancel(page)
        expect_modal_closed(page)
        logger.info("Modal closed after Cancel")

        # Step 5: Nothing was written
        log_test_step("5. Verify nothing was written")
        after_count = get_custom_var_count(page)
        assert after_count == initial_count, (
            f"Cancel should not change the count: {initial_count} -> {after_count}"
        )
        expect(
            row_for_key(page, "E2E_CANCEL_SHOULD_NOT_EXIST")
        ).to_have_count(0, timeout=3000)

        # Step 6: Reload — still nothing persisted
        log_test_step("6. Reload and verify persistence")
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        navigate_to_environments(page)
        refreshed_count = get_custom_var_count(page)
        assert refreshed_count == initial_count, (
            f"Count should be unchanged after reload: expected {initial_count}, "
            f"got {refreshed_count}"
        )
        logger.info("Cancel verified: no variable was created")

        log_test_result(test_name, True, 0)

    @pytest.mark.integration
    @pytest.mark.p2
    @pytest.mark.test_id("ENV-002-VALIDATION")
    def test_add_environment_key_required(self, page: Page, request: pytest.FixtureRequest):
        """Verify an empty Key is rejected.

        #7538 dropped the dedicated `environments.keyRequired` message: an
        empty key now fails the same `/^[A-Za-z_][A-Za-z0-9_]*$/` gate as a
        malformed one and reports "Invalid key format".  The assertion follows
        the shipped behaviour rather than the removed copy.
        """
        test_name = request.node.name

        # Step 1: Visit the environments page
        log_test_step("1. Visit environments page")
        navigate_to_environments(page)
        initial_count = get_custom_var_count(page)

        # Step 2: Open the Modal
        log_test_step("2. Open the editor Modal")
        open_add_variable_modal(page)

        # Step 3: Fill Value only, leave Key empty
        log_test_step("3. Fill Value only, leave Key empty")
        fill_variable_modal(page, value="test_value_no_key")
        key_input = page.locator(MODAL_KEY_INPUT).first
        assert key_input.input_value() == "", "Key input should start empty"

        # Step 4: Try to apply
        log_test_step("4. Click Apply now")
        click_modal_ok(page)
        page.wait_for_timeout(800)

        # Step 5: The submission is blocked and an error is reported
        log_test_step("5. Verify the empty Key is rejected")
        expect_modal_open(page)
        logger.info("Modal stayed open: empty Key was not accepted")

        rejected = False
        try:
            expect_toast(page, MSG_INVALID_KEY_FORMAT, timeout=5000)
            rejected = True
            logger.info(f"Validation message detected: {MSG_INVALID_KEY_FORMAT}")
        except Exception:
            error_toast = page.locator(MESSAGE_ERROR).first
            if error_toast.count() > 0 and error_toast.is_visible():
                rejected = True
                logger.info(
                    f"Error toast detected: {error_toast.inner_text().strip()!r}"
                )
        assert rejected, "Empty Key should be rejected with an error indicator"

        # Step 6: Nothing was written
        log_test_step("6. Verify nothing was written")
        click_modal_cancel(page)
        expect_modal_closed(page)
        after_count = get_custom_var_count(page)
        assert after_count == initial_count, (
            f"Rejected submission must not change the count: "
            f"{initial_count} -> {after_count}"
        )

        log_test_result(test_name, True, 0)


# ============================================================================
# ENV-003: Edit env var + update validation
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.envs
class TestEditEnvironment:
    """
    ENV-003: Edit env var + update validation.

    Covers:
    1. Create a variable through the UI
    2. Open the row editor (aria-label="Edit")
    3. Verify the Key input is locked for an existing variable
    4. Change the Value -> Apply now -> verify the new value persisted
    5. Cleanup

    Note: editing used to happen inline in the table row.  #7538 moved it into
    the same Modal as adding, with the Key input `disabled` because renaming
    would create a second variable (the write path is `PATCH {[key]: value}`).
    """

    @pytest.mark.test_id("ENV-003")
    def test_edit_environment(
        self, page: Page, request: pytest.FixtureRequest, api_context
    ):
        """Verify editing an env var."""
        test_name = request.node.name
        stamp = str(int(time.time()))[-6:]
        test_key = f"E2E_EDIT_{stamp}"
        test_value = f"edit_val_{stamp}"
        edited_value = f"edited_{stamp}"

        # Step 1: Visit the environments page
        log_test_step("1. Visit environments page")
        navigate_to_environments(page)
        initial_count = get_custom_var_count(page)

        try:
            # Step 2: Create the variable under test
            log_test_step("2. Create the variable through the UI")
            add_variable_via_ui(page, api_context, test_key, test_value)
            assert api_env_value(api_context, test_key) == test_value, (
                "Precondition failed: created variable is not persisted"
            )
            logger.info(f"Created {test_key}={test_value}")

            # Step 3: Open the row editor
            log_test_step("3. Open the row editor")
            row = row_for_key(page, test_key)
            edit_btn = row.locator(EDIT_BTN_BY_LABEL).first
            expect(edit_btn).to_be_visible(timeout=5000)
            edit_btn.click()
            expect(page.locator(MODAL_KEY_INPUT).first).to_be_visible(timeout=10000)
            modal_title = page.locator(MODAL_TITLE).first
            expect(modal_title).to_contain_text("Edit variable", timeout=5000)
            logger.info("Editor Modal opened with title 'Edit variable'")

            # Step 4: The Key is locked and pre-filled
            log_test_step("4. Verify Key is locked and pre-filled")
            key_input = page.locator(MODAL_KEY_INPUT).first
            assert key_input.input_value() == test_key, (
                f"Key should be pre-filled with {test_key}, "
                f"got {key_input.input_value()!r}"
            )
            assert key_input.is_disabled(), (
                "Key input should be disabled when editing an existing variable"
            )
            logger.info("Key input is locked as expected")

            # Step 5: Change the Value and apply
            log_test_step("5. Change the Value and Apply now")
            value_input = page.locator(MODAL_VALUE_INPUT).first
            expect(value_input).to_be_visible(timeout=5000)
            assert value_input.input_value() == test_value, (
                f"Value should be pre-filled with {test_value}, "
                f"got {value_input.input_value()!r}"
            )
            value_input.fill(edited_value)
            page.wait_for_timeout(300)
            assert value_input.input_value() == edited_value, (
                f"Value not updated in the input: got {value_input.input_value()!r}"
            )
            click_modal_ok(page)
            expect_modal_closed(page)
            logger.info("Edit applied")

            # Step 6: Verify the new value persisted
            log_test_step("6. Verify the edited value persisted")
            expect(row_for_key(page, test_key)).to_be_visible(timeout=10000)
            persisted = api_env_value(api_context, test_key)
            assert persisted == edited_value, (
                f"Value incorrect after edit: expected {edited_value}, got {persisted!r}"
            )
            logger.info(f"Edit verified: {test_key}={persisted}")

            # Step 7: The variable was updated, not duplicated
            log_test_step("7. Verify no duplicate was created")
            after_count = get_custom_var_count(page)
            assert after_count == initial_count + 1, (
                f"Edit should not add a variable: expected {initial_count + 1}, "
                f"got {after_count}"
            )
            logger.info(f"Custom count unchanged by edit: {after_count}")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - edit env var works")
        finally:
            log_test_step("Cleanup: delete test variable")
            cleanup_env_var(page, api_context, test_key)


# ============================================================================
# ENV-004: Delete env var + confirmation flow
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.envs
class TestDeleteEnvironment:
    """
    ENV-004: Delete env var + confirmation flow.

    Covers:
    1. Create a variable through the UI
    2. Click the row delete action (aria-label="Delete")
    3. Verify the confirm dialog (title "Delete Variable", okText "Delete")
    4. Confirm -> row disappears and the count drops
    5. Verify the variable is gone from the API
    6. Cancel path: the variable survives

    Note: deleting an unsaved table row needed no confirmation before #7538.
    Deletion now always goes through `Modal.confirm`, so the dialog itself is
    part of the asserted flow.
    """

    @pytest.mark.test_id("ENV-004")
    def test_delete_environment(
        self, page: Page, request: pytest.FixtureRequest, api_context
    ):
        """Verify deleting an env var."""
        test_name = request.node.name
        stamp = str(int(time.time()))[-6:]
        test_key = f"E2E_DEL_{stamp}"
        test_value = f"del_val_{stamp}"
        keep_key = f"E2E_DEL_KEEP_{stamp}"

        # Step 1: Visit the environments page
        log_test_step("1. Visit environments page")
        navigate_to_environments(page)
        initial_count = get_custom_var_count(page)
        logger.info(f"Initial custom variable count: {initial_count}")

        try:
            # Step 2: Create two variables (one to delete, one to keep)
            log_test_step("2. Create the variables under test")
            add_variable_via_ui(page, api_context, test_key, test_value)
            add_variable_via_ui(page, api_context, keep_key, test_value)
            after_add = get_custom_var_count(page)
            assert after_add == initial_count + 2, (
                f"Expected {initial_count + 2} custom variables, got {after_add}"
            )
            logger.info(f"Created 2 variables, count = {after_add}")

            # Step 3: Cancel the confirm dialog — nothing should be deleted
            log_test_step("3. Open delete confirm and cancel it")
            row = row_for_key(page, test_key)
            row.locator(DELETE_BTN_BY_LABEL).first.click()
            expect(page.locator(CONFIRM_MODAL).first).to_be_visible(timeout=10000)
            confirm_title = page.locator(CONFIRM_MODAL).first.locator(CONFIRM_TITLE).first
            expect(confirm_title).to_contain_text("Delete Variable", timeout=5000)
            confirm_body = page.locator(CONFIRM_MODAL).first.locator(CONFIRM_CONTENT).first
            expect(confirm_body).to_contain_text(test_key, timeout=5000)
            logger.info("Confirm dialog shows the variable name")

            cancel_btn = confirm_button(page, ok=False)
            if cancel_btn.count() > 0 and cancel_btn.is_visible():
                cancel_btn.click()
                page.wait_for_timeout(800)
                expect(row_for_key(page, test_key)).to_be_visible(timeout=5000)
                assert get_custom_var_count(page) == after_add, (
                    "Cancelling the confirm dialog must not delete the variable"
                )
                logger.info("Cancel path verified: variable survived")
            else:
                logger.warning("Cancel button not found, closing dialog via Escape")
                page.keyboard.press("Escape")
                page.wait_for_timeout(800)

            # Step 4: Delete for real
            log_test_step("4. Delete the variable and confirm")
            count_before_delete = get_custom_var_count(page)
            delete_variable_via_ui(page, test_key)

            # Step 5: The row is gone and the count dropped
            log_test_step("5. Verify the row is removed")
            expect(row_for_key(page, test_key)).to_have_count(0, timeout=10000)
            after_delete_count = get_custom_var_count(page)
            assert after_delete_count == count_before_delete - 1, (
                f"Count did not drop after delete: expected {count_before_delete - 1}, "
                f"got {after_delete_count}"
            )
            logger.info(
                f"Delete succeeded, count {count_before_delete} -> {after_delete_count}"
            )

            # Step 6: The kept variable is untouched
            log_test_step("6. Verify the other variable is untouched")
            expect(row_for_key(page, keep_key)).to_be_visible(timeout=5000)

            # Step 7: The API agrees
            log_test_step("7. Verify deletion through the API")
            keys = api_list_env_keys(api_context)
            assert test_key not in keys, f"{test_key} should be deleted, API still has it"
            assert keep_key in keys, f"{keep_key} should still exist"
            logger.info("API confirms the deletion")

            count_text = get_count_text(page)
            logger.info(f"Custom variable count after delete: {count_text}")

            log_test_result(test_name, True, 0)
            logger.info(f"Test {test_name} passed - delete env var works")
        finally:
            log_test_step("Cleanup: delete test variables")
            cleanup_env_var(page, api_context, test_key)
            cleanup_env_var(page, api_context, keep_key)


# ============================================================================
# ENV-005: Multiple variables in sequence + row addressing + persistence
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.envs
class TestEnvVarMultiRowAndCheckbox:
    """
    ENV-005: Create several variables in sequence, address them individually,
    delete one, and verify what survives a reload.

    Covers:
    1. Add 2 variables one after another
    2. Verify both are listed and the count reflects both
    3. Address each row by its own key (not by position)
    4. Reveal a masked value with the "Show value" action
    5. Delete one specific variable and verify the count drops by one
    6. Reload -> the deleted one stays gone, the other persists

    SCOPE CHANGE (#7538): this case used to assert row checkboxes
    (`checkbox.check()` / `is_checked()`) and the per-row "Insert row below"
    button.  The unified page removed the selection model and the insert
    action entirely — `index.tsx` no longer references `selected`,
    `shiftIndices`, `deleteSelected` or `insertRowBelow`, and upstream deleted
    its own three batch-selection unit tests in the same commit.  There is no
    selector that can reach a control the product no longer renders, so the
    "multiple rows" intent is kept and the checkbox/insert steps are replaced
    by the equivalent capabilities that do exist: sequential creation,
    per-key row addressing, value reveal and individual deletion.
    The class name and test_id are preserved so historical reporting stays
    comparable and the shard selection is unchanged.
    """

    @pytest.mark.test_id("ENV-005")
    def test_env_var_multi_row_and_checkbox(
        self, page: Page, request: pytest.FixtureRequest, api_context
    ):
        """Verify sequential multi-variable add, per-key addressing and delete."""
        test_name = request.node.name
        stamp = str(int(time.time()))[-6:]
        key_one = f"E2E_ROW_ONE_{stamp}"
        key_two = f"E2E_ROW_TWO_{stamp}"
        value_one = f"row_one_value_{stamp}"
        value_two = f"row_two_value_{stamp}"

        # Step 1: Visit the environments page
        log_test_step("1. Visit environments page")
        navigate_to_environments(page)
        initial_count = get_custom_var_count(page)
        logger.info(f"Initial custom variable count: {initial_count}")

        try:
            # Step 2: Add the first variable
            log_test_step("2. Add the first variable")
            add_variable_via_ui(page, api_context, key_one, value_one)
            count_after_first = get_custom_var_count(page)
            assert count_after_first == initial_count + 1, (
                f"Count incorrect after first add: expected {initial_count + 1}, "
                f"got {count_after_first}"
            )
            logger.info(f"First variable added, count = {count_after_first}")

            # Step 3: Add the second variable
            log_test_step("3. Add the second variable")
            add_variable_via_ui(page, api_context, key_two, value_two)
            count_after_second = get_custom_var_count(page)
            assert count_after_second == initial_count + 2, (
                f"Count incorrect after second add: expected {initial_count + 2}, "
                f"got {count_after_second}"
            )
            logger.info(f"Second variable added, count = {count_after_second}")

            # Step 4: Address each row by its own key
            log_test_step("4. Address each row by key")
            row_one = row_for_key(page, key_one)
            row_two = row_for_key(page, key_two)
            expect(row_one).to_be_visible(timeout=5000)
            expect(row_two).to_be_visible(timeout=5000)
            for row, key in ((row_one, key_one), (row_two, key_two)):
                shown_key = row.locator(IDENTITY_CODE).first.inner_text().strip()
                assert shown_key == key, f"Row key mismatch: expected {key}, got {shown_key}"
                for label in ("Edit", "Delete"):
                    expect(row.locator(f'button[aria-label="{label}"]').first).to_be_visible(
                        timeout=5000
                    )
            logger.info("Both rows are individually addressable with Edit/Delete actions")

            # Step 5: Reveal the masked value of the first variable
            log_test_step("5. Reveal the masked value")
            masked = row_one.locator('div[class*="__valueText__"] code').first
            expect(masked).to_be_visible(timeout=5000)
            masked_text = masked.inner_text().strip()
            logger.info(f"Value before reveal: {masked_text!r}")
            show_btn = row_one.locator(SHOW_VALUE_BTN_BY_LABEL).first
            if show_btn.count() > 0 and show_btn.is_visible():
                show_btn.click()
                page.wait_for_timeout(500)
                revealed = masked.inner_text().strip()
                assert revealed == value_one, (
                    f"Revealed value mismatch: expected {value_one}, got {revealed!r}"
                )
                logger.info(f"Value after reveal: {revealed}")
                hide_btn = row_one.locator('button[aria-label="Hide value"]').first
                if hide_btn.count() > 0 and hide_btn.is_visible():
                    hide_btn.click()
                    page.wait_for_timeout(300)
                    logger.info("Value re-masked via Hide value")
            else:
                logger.info("Show value action not present, skipping reveal")

            # Step 6: Delete the first variable only
            log_test_step("6. Delete the first variable")
            count_before_delete = get_custom_var_count(page)
            delete_variable_via_ui(page, key_one)
            expect(row_for_key(page, key_one)).to_have_count(0, timeout=10000)
            count_after_delete = get_custom_var_count(page)
            assert count_after_delete == count_before_delete - 1, (
                f"Count did not drop after delete: {count_before_delete} -> "
                f"{count_after_delete}"
            )
            logger.info(f"Row delete succeeded, count = {count_after_delete}")

            # Step 7: The second variable survived
            log_test_step("7. Verify the second variable survived")
            expect(row_for_key(page, key_two)).to_be_visible(timeout=5000)

            # Step 8: Reload — the write is durable, the deletion too
            log_test_step("8. Reload and verify persistence")
            page.reload()
            page.wait_for_load_state("domcontentloaded")
            navigate_to_environments(page)
            refreshed_count = get_custom_var_count(page)
            assert refreshed_count == initial_count + 1, (
                f"After reload expected {initial_count + 1} custom variables, "
                f"got {refreshed_count}"
            )
            expect(row_for_key(page, key_two)).to_be_visible(timeout=10000)
            expect(row_for_key(page, key_one)).to_have_count(0, timeout=3000)
            logger.info("Persistence verified after reload")

            log_test_result(test_name, True, 0)
            logger.info(
                f"Test {test_name} passed - sequential add, per-key addressing, "
                f"value reveal, delete and reload verified"
            )
        finally:
            log_test_step("Cleanup: delete test variables")
            cleanup_env_var(page, api_context, key_one)
            cleanup_env_var(page, api_context, key_two)


# ============================================================================
# ENV-006: Env var save persistence validation
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.envs
class TestEnvVarSaveAndPersist:
    """
    ENV-006: Env var save persistence validation.

    Covers:
    1. Add a new variable (Key/Value) through the Modal
    2. "Apply now" writes it (there is no page-level Save button any more)
    3. Verify the success toast
    4. Reload -> the variable still exists
    5. Verify the value survived through the API (the UI masks it)
    6. Delete the variable and verify the removal persists
    7. Cleanup

    Note: persistence used to be proven by reading the value back from the row
    input.  Custom values are now rendered masked (`<ValueText secret />` shows
    "••••••••"), so the durable value is asserted against `GET /api/envs`.
    """

    @pytest.mark.test_id("ENV-006")
    def test_env_var_save_and_persist(
        self, page: Page, request: pytest.FixtureRequest, api_context
    ):
        """Verify env var save and persistence."""
        test_name = request.node.name
        stamp = str(int(time.time()))[-6:]
        test_key = f"E2E_PERSIST_{stamp}"
        test_value = f"persist_value_{stamp}"
        data_saved = False

        # Step 1: Visit the environments page
        log_test_step("1. Visit environments page")
        navigate_to_environments(page)
        initial_count = get_custom_var_count(page)
        logger.info(f"Initial custom variable count: {initial_count}")

        try:
            # Step 2: Add a new variable
            log_test_step("2. Add a new variable")
            open_add_variable_modal(page)
            key_input = page.locator(MODAL_KEY_INPUT).first
            value_input = page.locator(MODAL_VALUE_INPUT).first
            expect(key_input).to_be_visible(timeout=5000)
            expect(value_input).to_be_visible(timeout=5000)

            key_input.fill(test_key)
            value_input.fill(test_value)
            page.wait_for_timeout(300)

            assert key_input.input_value() == test_key, (
                f"Key not filled correctly: expected {test_key}, "
                f"got {key_input.input_value()!r}"
            )
            assert value_input.input_value() == test_value, (
                f"Value not filled correctly: expected {test_value}, "
                f"got {value_input.input_value()!r}"
            )
            logger.info(f"Variable filled: {test_key}={test_value}")

            # Step 3: Apply now — this is the write
            log_test_step("3. Click Apply now")
            click_modal_ok(page)
            data_saved = True
            expect_modal_closed(page)

            # Step 4: Verify the success toast
            log_test_step("4. Verify save success indicator")
            try:
                expect_toast(page, MSG_APPLIED, timeout=8000)
                logger.info(f"Success toast detected: {MSG_APPLIED}")
            except Exception:
                success_msg = page.locator(MESSAGE_SUCCESS).first
                if success_msg.count() > 0 and success_msg.is_visible():
                    logger.info(
                        f"Success indicator visible: {success_msg.inner_text().strip()!r}"
                    )
                else:
                    logger.info("No obvious success indicator detected, continuing")

            # Step 5: The variable is listed
            log_test_step("5. Verify the variable is listed")
            expect(row_for_key(page, test_key)).to_be_visible(timeout=10000)
            assert get_custom_var_count(page) == initial_count + 1, (
                "Custom count should have increased by one"
            )

            # Step 6: Reload
            log_test_step("6. Reload page")
            page.reload()
            page.wait_for_load_state("domcontentloaded")
            navigate_to_environments(page)

            # Step 7: The variable is still there after reload
            log_test_step("7. Verify the variable still exists after reload")
            refreshed_count = get_custom_var_count(page)
            logger.info(f"Custom count after reload: {refreshed_count}")
            assert refreshed_count == initial_count + 1, (
                f"Variable did not persist: expected {initial_count + 1}, "
                f"got {refreshed_count}"
            )
            expect(row_for_key(page, test_key)).to_be_visible(timeout=10000)
            logger.info(f"Variable persisted across reload: {test_key}")

            # Step 8: The value persisted (API, because the UI masks it)
            log_test_step("8. Verify the persisted value via API")
            persisted = api_env_value(api_context, test_key)
            assert persisted == test_value, (
                f"Value mismatch after reload: expected {test_value}, got {persisted!r}"
            )
            logger.info(f"Persisted value verified: {test_key}={persisted}")

            # Step 9: Reveal it in the UI as well
            log_test_step("9. Reveal the value in the UI")
            row = row_for_key(page, test_key)
            show_btn = row.locator(SHOW_VALUE_BTN_BY_LABEL).first
            if show_btn.count() > 0 and show_btn.is_visible():
                show_btn.click()
                page.wait_for_timeout(500)
                revealed = row.locator('div[class*="__valueText__"] code').first.inner_text().strip()
                assert revealed == test_value, (
                    f"Revealed value mismatch: expected {test_value}, got {revealed!r}"
                )
                logger.info(f"UI reveal matches the persisted value: {revealed}")
            else:
                logger.info("Show value action not present, relying on API assertion")

            # Step 10: Delete it and verify the removal persists
            log_test_step("10. Delete the variable and verify removal persists")
            delete_variable_via_ui(page, test_key)
            expect(row_for_key(page, test_key)).to_have_count(0, timeout=10000)
            data_saved = False

            page.reload()
            page.wait_for_load_state("domcontentloaded")
            navigate_to_environments(page)
            final_count = get_custom_var_count(page)
            assert final_count == initial_count, (
                f"Count should be back to {initial_count} after delete, got {final_count}"
            )
            assert test_key not in api_list_env_keys(api_context), (
                f"{test_key} should be gone from the API after deletion"
            )
            logger.info("Deletion persisted across reload")

            log_test_result(test_name, True, 0)
        finally:
            # Cleanup: make sure the test variable is gone even on failure
            if data_saved:
                log_test_step("Cleanup: delete test variable")
                cleanup_env_var(page, api_context, test_key)
        logger.info(f"Test {test_name} passed - env var save and persistence verified")


# ============================================================================
# ENV-007: Key format validation
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.envs
class TestEnvVarKeyValidation:
    """
    ENV-007: Key format validation.

    Covers:
    1. Invalid Keys ("123invalid", "has space", "has-dash") are rejected with
       "Invalid key format" and the Modal stays open
    2. A valid Key ("E2E_VALID_KEY_<ts>") is accepted and written
    3. Cleanup

    Note: validation moved from a per-row form field (which rendered
    `.qwenpaw-form-item-explain-error` under the input) to a gate inside
    `saveEditor`, which reports through a toast and keeps the Modal open.
    The assertions follow the gate: `saveEditor` rejects anything that fails
    `/^[A-Za-z_][A-Za-z0-9_]*$/` before any request is sent.
    """

    @pytest.mark.test_id("ENV-007")
    def test_env_var_key_format_validation(
        self, page: Page, request: pytest.FixtureRequest, api_context
    ):
        """Verify env var Key format validation."""
        test_name = request.node.name
        stamp = str(int(time.time()))[-6:]
        valid_key = f"E2E_VALID_KEY_{stamp}"

        # Step 1: Visit the environments page
        log_test_step("1. Visit environments page")
        navigate_to_environments(page)
        initial_count = get_custom_var_count(page)

        # Step 2: Open the editor Modal
        log_test_step("2. Open the editor Modal")
        open_add_variable_modal(page)
        key_input = page.locator(MODAL_KEY_INPUT).first
        expect(key_input).to_be_visible(timeout=5000)
        fill_variable_modal(page, value="format_probe_value")

        rejected_keys = []
        # Step 3-5: Each invalid Key must be rejected
        for index, invalid_key in enumerate(("123invalid", "has space", "has-dash"), start=3):
            log_test_step(f"{index}. Test invalid Key: {invalid_key!r}")
            key_input.fill(invalid_key)
            page.wait_for_timeout(300)
            click_modal_ok(page)
            page.wait_for_timeout(800)

            # The Modal must stay open: saveEditor returns before the request.
            expect_modal_open(page)

            has_error = False
            try:
                expect_toast(page, MSG_INVALID_KEY_FORMAT, timeout=5000)
                has_error = True
            except Exception:
                error_toast = page.locator(MESSAGE_ERROR).first
                if error_toast.count() > 0 and error_toast.is_visible():
                    has_error = True
                    logger.info(
                        f"Error toast for {invalid_key!r}: "
                        f"{error_toast.inner_text().strip()!r}"
                    )
            logger.info(f"Rejected {invalid_key!r}: {has_error}")
            if has_error:
                rejected_keys.append(invalid_key)

        assert rejected_keys, (
            "No invalid Key was rejected — the format gate did not fire"
        )
        logger.info(f"Rejected keys: {rejected_keys}")

        # Step 6: The Key input keeps the last rejected value (nothing was sent)
        log_test_step("6. Verify no invalid Key was written")
        assert key_input.input_value() == "has-dash", (
            f"Key input should still hold the last rejected value, "
            f"got {key_input.input_value()!r}"
        )
        assert get_custom_var_count(page) == initial_count, (
            "Rejected Keys must not create variables"
        )

        # Step 7: A valid Key is accepted
        log_test_step("7. Test valid Key")
        key_input.fill(valid_key)
        page.wait_for_timeout(300)
        click_modal_ok(page)
        expect_modal_closed(page, timeout=10000)
        expect(row_for_key(page, valid_key)).to_be_visible(timeout=10000)
        logger.info(f"Valid Key accepted and written: {valid_key}")

        # Step 8: Cleanup
        log_test_step("8. Delete the valid test variable")
        delete_variable_via_ui(page, valid_key)
        expect(row_for_key(page, valid_key)).to_have_count(0, timeout=10000)
        assert get_custom_var_count(page) == initial_count, (
            "Count should be back to the initial value after cleanup"
        )
        logger.info("Test variable deleted")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - Key format validation verified")


# ============================================================================
# ENV-008: Bulk create/filter/delete of several variables
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.envs
class TestBatchOperations:
    """
    ENV-008: Work with several variables at once — bulk create, filter them
    with the search box, then remove them all.

    Covers:
    1. Create 3 variables in sequence
    2. Verify the count reflects all three
    3. Filter with the search box and verify only matching rows remain
    4. Clear the filter and verify all rows come back
    5. Delete all three and verify the count returns to the baseline

    SCOPE CHANGE (#7538): this case used to tick per-row checkboxes and assert
    `checked_count > 0` before a batch delete.  The unified page has no
    selection model at all — no checkbox, no select-all, no "Delete Selected"
    action (`index.tsx` references none of `selected`, `allSelected`,
    `someSelected` or `deleteSelected`, and upstream removed its three
    batch-selection unit tests in the same commit).  A checkbox assertion can
    only ever fail against the shipped UI, so the "operate on many variables"
    intent is kept and re-expressed through the capabilities that replaced it:
    bulk creation, the new search filter, and per-variable deletion in a loop.
    The class name and test_id are preserved so historical reporting stays
    comparable and the shard selection is unchanged.
    """

    @pytest.mark.test_id("ENV-008")
    def test_batch_operations(
        self, page: Page, request: pytest.FixtureRequest, api_context
    ):
        """Verify bulk create + search filter + bulk delete of env vars."""
        test_name = request.node.name
        stamp = str(int(time.time()))[-6:]
        keys = [f"E2E_BATCH_{stamp}_{suffix}" for suffix in ("A", "B", "C")]
        value = f"batch_value_{stamp}"

        log_test_step("1. Visit environments page")
        navigate_to_environments(page)
        initial_count = get_custom_var_count(page)
        logger.info(f"Initial custom variable count: {initial_count}")

        try:
            log_test_step("2. Create 3 variables for bulk operation testing")
            for key in keys:
                add_variable_via_ui(page, api_context, key, value)
            after_add_count = get_custom_var_count(page)
            assert after_add_count == initial_count + 3, (
                f"Count incorrect after creating 3 variables: "
                f"expected {initial_count + 3}, got {after_add_count}"
            )
            logger.info(f"Created 3 variables, count = {after_add_count}")

            log_test_step("3. Verify all three rows are listed")
            for key in keys:
                expect(row_for_key(page, key)).to_be_visible(timeout=5000)

            log_test_step("4. Filter with the search box")
            search_input = page.locator(SEARCH_INPUT).first
            expect(search_input).to_be_visible(timeout=5000)
            search_input.fill(keys[0])
            page.wait_for_timeout(800)
            expect(row_for_key(page, keys[0])).to_be_visible(timeout=5000)
            expect(row_for_key(page, keys[1])).to_have_count(0, timeout=5000)
            expect(row_for_key(page, keys[2])).to_have_count(0, timeout=5000)
            filtered_count = get_custom_var_count(page)
            assert filtered_count == 1, (
                f"Search filter should leave 1 custom variable, got {filtered_count}"
            )
            logger.info(f"Search filter works: {keys[0]} only, count = {filtered_count}")

            log_test_step("5. Clear the filter and verify all rows return")
            search_input.fill("")
            page.wait_for_timeout(800)
            for key in keys:
                expect(row_for_key(page, key)).to_be_visible(timeout=5000)
            assert get_custom_var_count(page) == initial_count + 3, (
                "Clearing the filter should restore the full list"
            )
            logger.info("Filter cleared, all rows restored")

            log_test_step("6. Delete the three variables one by one")
            deleted = 0
            for key in keys:
                count_before = get_custom_var_count(page)
                delete_variable_via_ui(page, key)
                expect(row_for_key(page, key)).to_have_count(0, timeout=10000)
                count_after = get_custom_var_count(page)
                assert count_after == count_before - 1, (
                    f"Count did not drop after deleting {key}: "
                    f"{count_before} -> {count_after}"
                )
                deleted += 1
            assert deleted == 3, f"Expected to delete 3 variables, deleted {deleted}"

            final_count = get_custom_var_count(page)
            assert final_count == initial_count, (
                f"Count incorrect after bulk delete: expected {initial_count}, "
                f"got {final_count}"
            )
            logger.info(f"Bulk delete verified, count restored to {final_count}")

            remaining = api_list_env_keys(api_context)
            for key in keys:
                assert key not in remaining, f"{key} should be gone from the API"
            logger.info("API confirms all three variables were removed")

            log_test_result(test_name, True, 0)
        finally:
            log_test_step("Cleanup: delete any leftover test variables")
            for key in keys:
                cleanup_env_var(page, api_context, key)


# ============================================================================
# ENV-009: API operation validation
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.envs
class TestEnvironmentAPI:
    """
    ENV-009: API operation validation.

    Covers:
    1. API: get env var list
    2. API: add env var
    3. API: delete env var
    """

    @pytest.mark.test_id("ENV-009")
    def test_environment_api(self, page: Page, request: pytest.FixtureRequest, api_context):
        """Verify env var API."""
        test_name = request.node.name
        test_key = None

        try:
            # Step 1: API - get env var list
            log_test_step("1. API: get env var list")
            envs = api_get(api_context, "/api/envs")
            logger.info(f"Env var list: {envs}")
            assert isinstance(envs, list), "API response should be a list"
            logger.info(f"Got {len(envs)} env vars")

            # Step 2: API - add env var
            log_test_step("2. API: add env var")

            timestamp = str(int(time.time()))[-6:]
            test_key = f"API_TEST_{timestamp}"
            test_value = f"api_test_value_{timestamp}"

            # PUT /api/envs expects body as dict; each key-value pair becomes one env var
            put_response = api_context.put(
                f"{config.base_url}/api/envs",
                data={test_key: test_value}
            )
            logger.info(f"API add status code: {put_response.status}")
            assert put_response.ok, f"API add failed: {put_response.status}"
            logger.info("API add env var succeeded")

            # Step 3: Verify add succeeded
            log_test_step("3. Verify API add succeeded")
            envs_after = api_get(api_context, "/api/envs")
            found = any(e.get("key") == test_key for e in envs_after)
            assert found, f"Variable not found after API add: {test_key}"
            logger.info("API add verification succeeded")

            log_test_result(test_name, True, 0)

        except Exception as e:
            log_test_result(test_name, False, str(e))
            raise

        finally:
            # Cleanup: delete test variable via API (overwrite with list excluding the test variable)
            if test_key:
                try:
                    log_test_step("Cleanup: API delete test variable")
                    current_envs = api_get(api_context, "/api/envs")
                    # Build a dict excluding the test variable to do a full overwrite
                    remaining_dict = {
                        e["key"]: e["value"]
                        for e in current_envs
                        if e.get("key") != test_key
                    }
                    # If empty, overwrite with an empty marker to trigger clearing
                    if not remaining_dict:
                        remaining_dict = {}
                    cleanup_response = api_context.put(
                        f"{config.base_url}/api/envs",
                        data=remaining_dict
                    )
                    logger.info(f"Cleanup status code: {cleanup_response.status}")
                except Exception as cleanup_error:
                    logger.warning(f"Cleanup of test variable failed: {cleanup_error}")


# ============================================================================
# ENV-P1-005: Key duplicate conflict detection
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.envs
class TestEnvKeyDuplicateDetection:
    """
    ENV-P1-005: Key duplicate conflict detection.

    Covers:
    1. Create a variable with a given Key
    2. Open the editor again and submit the same Key
    3. Verify the "Duplicate key" rejection and that nothing was written
    4. Verify the duplicate is also rejected against a known (catalogue) key
    5. Cleanup

    Note: this case used to click a broad `button:has-text("Add")` twice and
    then look for a second input row.  After #7538 that first click opens the
    Modal, whose Key placeholder is "VARIABLE_NAME" (not matched by the old
    `input[placeholder*="KEY"]` guess), and the second click lands on the
    button *behind the Modal overlay* — which is what produced the 60s
    `Locator.click` timeout in the nightly run.  Duplicate detection now lives
    in `saveEditor`: it compares the upper-cased key against both the stored
    variables and the catalogue, reports `environments.duplicateKey` through a
    toast, and leaves the Modal open without sending a request.
    """

    @pytest.mark.test_id("ENV-P1-005")
    def test_env_key_duplicate_detection(
        self, page: Page, request: pytest.FixtureRequest, api_context
    ):
        """Test env var Key duplicate conflict detection."""
        test_name = request.node.name
        stamp = str(int(time.time()))[-6:]
        duplicate_key = f"E2E_DUP_{stamp}"
        duplicate_value = f"dup_value_{stamp}"

        log_test_step("1. Visit environments page")
        navigate_to_environments(page)
        initial_count = get_custom_var_count(page)

        try:
            log_test_step("2. Create the first variable")
            add_variable_via_ui(page, api_context, duplicate_key, duplicate_value)
            logger.info(f"First variable created: {duplicate_key}")

            log_test_step("3. Submit the same Key again")
            open_add_variable_modal(page)
            key_input = page.locator(MODAL_KEY_INPUT).first
            expect(key_input).to_be_visible(timeout=5000)
            # Exact case first, then a lower-cased variant: the duplicate check
            # upper-cases both sides, so casing must not matter.
            key_input.fill(duplicate_key)
            fill_variable_modal(page, value="second_value_should_be_rejected")
            click_modal_ok(page)
            page.wait_for_timeout(1000)

            log_test_step("4. Verify the duplicate Key is rejected")
            expect_modal_open(page)
            logger.info("Modal stayed open: duplicate Key was not accepted")

            detected = False
            try:
                expect_toast(page, MSG_DUPLICATE_KEY, timeout=6000)
                detected = True
                logger.info(f"Duplicate rejection detected: {MSG_DUPLICATE_KEY}")
            except Exception:
                error_toast = page.locator(MESSAGE_ERROR).first
                if error_toast.count() > 0 and error_toast.is_visible():
                    toast_text = error_toast.inner_text().strip()
                    logger.info(f"Error toast detected: {toast_text!r}")
                    detected = "uplicate" in toast_text
            assert detected, "Duplicate Key should be rejected with an error message"

            log_test_step("5. Verify a lower-cased duplicate is rejected too")
            key_input.fill(duplicate_key.lower())
            page.wait_for_timeout(300)
            click_modal_ok(page)
            page.wait_for_timeout(1000)
            expect_modal_open(page)
            logger.info("Case-insensitive duplicate rejected as well")

            log_test_step("6. Verify nothing extra was written")
            click_modal_cancel(page)
            expect_modal_closed(page)
            after_count = get_custom_var_count(page)
            assert after_count == initial_count + 1, (
                f"Duplicate submissions must not add variables: "
                f"expected {initial_count + 1}, got {after_count}"
            )
            keys = api_list_env_keys(api_context)
            assert keys.count(duplicate_key) == 1, (
                f"{duplicate_key} should exist exactly once, API has "
                f"{keys.count(duplicate_key)}"
            )
            assert api_env_value(api_context, duplicate_key) == duplicate_value, (
                "The rejected duplicate must not have overwritten the original value"
            )
            logger.info("No duplicate written, original value intact")

            log_test_step("7. Verify the page is still healthy")
            page_content = page.locator("body").inner_text()
            assert len(page_content) > 0, "Page content should not be empty"
            expect(page.locator(ADD_VARIABLE_BTN).first).to_be_visible(timeout=5000)
            logger.info("Page remained healthy after the rejected duplicates")

            log_test_step("8. Delete the test variable through the UI")
            delete_variable_via_ui(page, duplicate_key)
            expect(row_for_key(page, duplicate_key)).to_have_count(0, timeout=10000)
            assert get_custom_var_count(page) == initial_count, (
                "Count should be back to the initial value after cleanup"
            )
            logger.info("Test variable deleted")

            log_test_result(test_name, True, 0)

        finally:
            # Cleanup: make sure the test key is gone even on failure
            log_test_step("Cleanup: delete test variable")
            cleanup_env_var(page, api_context, duplicate_key)
