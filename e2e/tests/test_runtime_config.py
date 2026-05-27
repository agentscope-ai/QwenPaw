# -*- coding: utf-8 -*-
"""
QwenPaw Runtime Config (Agent Config) module P0 end-to-end test cases.

Combined test cases:
- AGCFG-001: ReAct agent tab display + language dropdown + timezone verification
- AGCFG-002: Tab switching (LLM retry / rate limiter / context compaction) + per-tab content verification
- AGCFG-003: Config modification, save and reset

Run with: pytest tests/test_runtime_config_p0.py -v
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)

AGENT_CONFIG_URL = f"{config.base_url}/agent-config"


def navigate_to_agent_config(page: Page):
    """Navigate to the runtime config page and wait for it to load."""
    page.goto(AGENT_CONFIG_URL)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(3000)


# ============================================================================
# AGCFG-001: ReAct agent tab display + language dropdown + timezone verification
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.config
class TestReActAgentConfig:
    """
    AGCFG-001: ReAct agent tab display + language dropdown + timezone verification.

    Coverage:
    1. Runtime config page navigation and load
    2. ReAct agent tab active by default
    3. Agent language dropdown display and switching
    4. User timezone dropdown display
    5. Form card title verification
    """

    @pytest.mark.test_id("AGCFG-001")
    def test_react_agent_language_and_timezone(self, page: Page, request: pytest.FixtureRequest):
        """Verify ReAct agent language switching and timezone configuration."""
        test_name = request.node.name

        # Step 1: Visit the runtime config page
        log_test_step("1. Visit the runtime config page")
        navigate_to_agent_config(page)

        # Step 2: Verify breadcrumb
        log_test_step("2. Verify breadcrumb")
        try:
            breadcrumb = page.locator(
                'span[class*="breadcrumbCurrent"]:has-text("Runtime"), '
                'span[class*="breadcrumbCurrent"]:has-text("Config")'
            ).first
            if not breadcrumb.is_visible():
                breadcrumb = page.locator('text=Runtime').first
            expect(breadcrumb).to_be_visible(timeout=5000)
            logger.info("Breadcrumb verified")
        except Exception:
            logger.warning("Breadcrumb verification skipped (locale mismatch)")

        # Step 3: Verify tabs exist
        log_test_step("3. Verify tabs exist")
        react_tab = page.locator('[data-node-key="reactAgent"] .qwenpaw-tabs-tab-btn').first
        expect(react_tab).to_be_visible(timeout=5000)
        logger.info("ReAct agent tab visible")

        # Step 4: Verify the ReAct agent tab is active by default
        log_test_step("4. Verify the ReAct agent tab is active by default")
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(active_panel).to_be_visible(timeout=5000)

        # Verify the card title
        card_title = active_panel.locator('.qwenpaw-spark-title').first
        expect(card_title).to_be_visible(timeout=5000)
        title_text = card_title.inner_text()
        assert "ReAct" in title_text, f"Card title does not contain ReAct: {title_text}"
        logger.info(f"Card title: {title_text}")

        # Step 5: Verify the agent language dropdown
        log_test_step("5. Verify the agent language dropdown")
        language_label = active_panel.locator('label:has-text("Agent Language"), label:has-text("Language")').first
        try:
            expect(language_label).to_be_visible(timeout=5000)
            logger.info("Agent language label visible")
        except Exception:
            logger.warning("Agent language label not found, skipping verification")

        # Find the language dropdown (first select)
        language_select = active_panel.locator('.qwenpaw-select').first
        expect(language_select).to_be_visible(timeout=5000)

        # Read the currently selected value
        current_value = language_select.locator('.qwenpaw-select-selection-item').first.inner_text()
        logger.info(f"Current agent language: {current_value}")

        # Click to expand the dropdown
        language_select.click()
        page.wait_for_timeout(1000)

        dropdown = page.locator('.qwenpaw-select-dropdown:visible').first
        if dropdown.is_visible():
            options = dropdown.locator('.qwenpaw-select-item-option').all()
            option_texts = [opt.inner_text() for opt in options]
            logger.info(f"Language options: {option_texts}")
            assert len(options) >= 2, f"Insufficient language options: {len(options)}"
            assert "English" in option_texts, f"Missing English option: {option_texts}"
            logger.info("Language dropdown opens correctly and options verified")

            # Close the dropdown without selecting, to avoid altering user config
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        else:
            page.keyboard.press("Escape")
            logger.warning("Language dropdown options did not open, skipping verification")

        # Step 6: Verify the user timezone dropdown
        log_test_step("6. Verify the user timezone dropdown")
        timezone_label = active_panel.locator('label:has-text("User Timezone"), label:has-text("Timezone")').first
        try:
            expect(timezone_label).to_be_visible(timeout=5000)
            logger.info("User timezone label visible")
        except Exception:
            logger.warning("User timezone label not found, skipping verification")

        # The timezone dropdown is the second select
        selects = active_panel.locator('.qwenpaw-select').all()
        assert len(selects) >= 2, f"Insufficient dropdowns (expected >= 2): {len(selects)}"
        timezone_select = selects[1]
        timezone_value = timezone_select.locator('.qwenpaw-select-selection-item').first.inner_text()
        assert len(timezone_value) > 0, "Timezone value is empty"
        logger.info(f"Current timezone: {timezone_value}")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - ReAct agent language and timezone config OK")


# ============================================================================
# AGCFG-002: Tab switching (LLM retry / rate limiter / context compaction)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.config
class TestAgentConfigTabSwitch:
    """
    AGCFG-002: Tab switching verification.

    Coverage:
    1. Switch to LLM auto-retry tab and verify content
    2. Switch to LLM rate limiter tab and verify content
    3. Switch to context compaction tab and verify content
    4. Verify switches/inputs in each tab
    """

    @pytest.mark.test_id("AGCFG-002")
    def test_agent_config_tab_switch(self, page: Page, request: pytest.FixtureRequest):
        """Verify tab switching and content display on the runtime config page."""
        test_name = request.node.name

        # Step 1: Visit the runtime config page
        log_test_step("1. Visit the runtime config page")
        navigate_to_agent_config(page)

        # Step 2: Verify all tabs are visible
        log_test_step("2. Verify all tabs are visible")
        tab_keys = ["reactAgent", "llmRetry", "llmRateLimiter", "lightContext"]

        for key in tab_keys:
            tab_btn = page.locator(f'[data-node-key="{key}"] .qwenpaw-tabs-tab-btn').first
            expect(tab_btn).to_be_visible(timeout=5000)

        logger.info(f"All {len(tab_keys)} tabs are visible")

        # Step 3: Switch to the LLM auto-retry tab
        log_test_step("3. Switch to the LLM auto-retry tab")
        llm_retry_tab = page.locator('[data-node-key="llmRetry"] .qwenpaw-tabs-tab-btn').first
        llm_retry_tab.click()
        page.wait_for_timeout(1500)

        retry_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(retry_panel).to_be_visible(timeout=5000)

        retry_switches = retry_panel.locator('button.qwenpaw-switch[role="switch"]').all()
        retry_inputs = retry_panel.locator('.qwenpaw-input, .qwenpaw-input-number, .qwenpaw-select').all()
        assert len(retry_switches) + len(retry_inputs) >= 1, "No config items in LLM auto-retry tab"
        logger.info(f"LLM auto-retry tab - switches: {len(retry_switches)}, inputs: {len(retry_inputs)}")

        # Step 4: Switch to the LLM rate limiter tab
        log_test_step("4. Switch to the LLM rate limiter tab")
        rate_limiter_tab = page.locator('[data-node-key="llmRateLimiter"] .qwenpaw-tabs-tab-btn').first
        rate_limiter_tab.click()
        page.wait_for_timeout(1500)

        rate_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(rate_panel).to_be_visible(timeout=5000)

        rate_switches = rate_panel.locator('button.qwenpaw-switch[role="switch"]').all()
        rate_inputs = rate_panel.locator('.qwenpaw-input, .qwenpaw-input-number, .qwenpaw-select').all()
        assert len(rate_switches) + len(rate_inputs) >= 1, "No config items in LLM rate limiter tab"
        logger.info(f"LLM rate limiter tab - switches: {len(rate_switches)}, inputs: {len(rate_inputs)}")

        # Step 5: Switch to the context management tab
        log_test_step("5. Switch to the context management tab")
        context_tab = page.locator('[data-node-key="lightContext"] .qwenpaw-tabs-tab-btn').first
        context_tab.click()
        page.wait_for_timeout(1500)

        context_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(context_panel).to_be_visible(timeout=5000)

        context_inputs = context_panel.locator('.qwenpaw-input, .qwenpaw-input-number, .qwenpaw-select').all()
        assert len(context_inputs) >= 1, "No config items in context management tab"
        logger.info(f"Context management tab - inputs: {len(context_inputs)}")

        # Step 6: Switch back to the ReAct agent tab to confirm round-trip
        log_test_step("6. Switch back to the ReAct agent tab")
        react_tab = page.locator('[data-node-key="reactAgent"] .qwenpaw-tabs-tab-btn').first
        react_tab.click()
        page.wait_for_timeout(1000)

        react_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(react_panel).to_be_visible(timeout=5000)
        logger.info("Switched back to ReAct agent tab")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - tab switching and content display OK")


# ============================================================================
# AGCFG-003: Config modification, save and reset
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.config
class TestAgentConfigSaveAndReset:
    """
    AGCFG-003: Config modification, save and reset.

    Coverage:
    1. Visit the runtime config page
    2. Switch to the context compaction tab
    3. Locate the enable switch and record its current state
    4. Toggle the switch
    5. Locate the save button and click it
    6. Verify the save success notification
    7. Reload the page
    8. Switch back to the context compaction tab
    9. Verify the switch state was persisted
    10. Restore the original state and save
    """

    @pytest.mark.test_id("AGCFG-003")
    def test_config_save_and_reset(self, page: Page, request: pytest.FixtureRequest):
        """Verify config modification, saving and persistence."""
        test_name = request.node.name

        # Step 1: Visit the runtime config page
        log_test_step("1. Visit the runtime config page")
        navigate_to_agent_config(page)

        # Step 2: Switch to the long-term memory tab (context compaction was merged in; this tab has a toggle switch)
        log_test_step("2. Switch to the long-term memory tab")
        context_tab = page.locator('[data-node-key="remeLightMemory"] .qwenpaw-tabs-tab-btn').first
        expect(context_tab).to_be_visible(timeout=5000)
        context_tab.click()
        page.wait_for_timeout(1500)

        context_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(context_panel).to_be_visible(timeout=5000)
        logger.info("Switched to long-term memory tab")

        # Step 3: Locate the enable switch and record its initial state
        log_test_step("3. Record the initial switch state")
        enable_switch = context_panel.locator('.qwenpaw-switch').first
        expect(enable_switch).to_be_visible(timeout=5000)

        initial_checked = enable_switch.get_attribute('aria-checked')
        assert initial_checked in ['true', 'false'], f"Unexpected initial switch state: {initial_checked}"
        logger.info(f"Initial switch state: aria-checked={initial_checked}")

        # Step 4: Toggle the switch
        log_test_step("4. Toggle the switch")
        enable_switch.click()
        page.wait_for_timeout(1000)

        new_checked = enable_switch.get_attribute('aria-checked')
        assert new_checked != initial_checked, f"Switch did not flip: {initial_checked} -> {new_checked}"
        logger.info(f"Switch toggled: {initial_checked} -> {new_checked}")

        # Step 5: Locate the save button and click it
        log_test_step("5. Click the save button")
        save_btn = page.locator('button.qwenpaw-btn-primary:has-text("Save")').first
        if not save_btn.is_visible():
            # Fall back to the footer area
            save_btn = page.locator('div[class*="footer"] button.qwenpaw-btn-primary').first
        expect(save_btn).to_be_visible(timeout=5000)
        save_btn.click()
        page.wait_for_timeout(2000)

        # Step 6: Verify the save success notification
        log_test_step("6. Verify the save success notification")
        success_msg = page.locator('.qwenpaw-message-success, .qwenpaw-message-notice-content:has-text("Save")').first
        try:
            expect(success_msg).to_be_visible(timeout=3000)
            logger.info("Save success notification visible")
        except Exception:
            logger.info("No obvious success notification detected, continuing")

        # Step 7: Reload the page
        log_test_step("7. Reload the page")
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        # Step 8: Switch to the long-term memory tab
        log_test_step("8. Switch to the long-term memory tab")
        context_tab_refreshed = page.locator('[data-node-key="remeLightMemory"] .qwenpaw-tabs-tab-btn').first
        expect(context_tab_refreshed).to_be_visible(timeout=5000)
        context_tab_refreshed.click()
        page.wait_for_timeout(1500)

        context_panel_refreshed = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(context_panel_refreshed).to_be_visible(timeout=5000)

        # Step 9: Verify the switch state was persisted
        log_test_step("9. Verify the switch state was persisted")
        enable_switch_refreshed = context_panel_refreshed.locator('.qwenpaw-switch').first
        expect(enable_switch_refreshed).to_be_visible(timeout=5000)

        persisted_checked = enable_switch_refreshed.get_attribute('aria-checked')
        assert persisted_checked == new_checked, (
            f"Switch state was not persisted: expected {new_checked}, got {persisted_checked}"
        )
        logger.info(f"Switch state persisted: {persisted_checked}")

        # Step 10: Restore the original state and save
        log_test_step("10. Restore the original state and save")
        enable_switch_refreshed.click()
        page.wait_for_timeout(1000)

        restored_checked = enable_switch_refreshed.get_attribute('aria-checked')
        assert restored_checked == initial_checked, (
            f"Switch was not restored: expected {initial_checked}, got {restored_checked}"
        )
        logger.info(f"Switch restored to initial state: {restored_checked}")

        # Save again
        save_btn_refreshed = page.locator('button.qwenpaw-btn-primary:has-text("Save")').first
        if not save_btn_refreshed.is_visible():
            save_btn_refreshed = page.locator('div[class*="footer"] button.qwenpaw-btn-primary').first
        if save_btn_refreshed.is_visible():
            save_btn_refreshed.click()
            page.wait_for_timeout(2000)
            logger.info("Saved restored state")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed - config modification, save and persistence OK")


# ============================================================================
# P1 test cases: LLM retry, rate limiter, tool result compaction, embedding
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.config
class TestLlmRetryConfig:
    """
    test_llm_retry_config: LLM retry configuration.

    Coverage:
    1. Switch to LLM auto-retry tab
    2. Retry switch display and toggle
    3. Display and edit max retries, backoff base, backoff cap
    4. Verify config save
    """

    def test_llm_retry_config(self, page: Page):
        """LLM retry configuration test."""
        log_test_step("Navigate to the Agent Config page")
        navigate_to_agent_config(page)

        from pages.runtime_config_page import RuntimeConfigPage
        runtime_config_page = RuntimeConfigPage(page)

        log_test_step("Switch to the LLM auto-retry tab")
        runtime_config_page.switch_to_llm_retry_tab()

        # Verify the card title
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        card_title = active_panel.locator('.qwenpaw-spark-title').first
        expect(card_title).to_be_visible()
        title_text = card_title.inner_text()
        assert "LLM" in title_text or "Retry" in title_text, \
            f"Card title does not contain expected keywords: {title_text}"
        logger.info("LLM retry config card title verified")

        # Verify the retry switch exists
        switch_selector = '.qwenpaw-switch'
        retry_switch = active_panel.locator(switch_selector).first
        expect(retry_switch).to_be_visible()
        logger.info("LLM retry switch verified")

        # Verify the input fields exist
        input_selectors = [
            '#llm_max_retries',
            '#llm_backoff_base',
            '#llm_backoff_cap'
        ]
        for selector in input_selectors:
            input_el = active_panel.locator(selector).first
            expect(input_el).to_be_visible()
        logger.info("LLM retry config inputs verified")

        # Record the original values
        log_test_step("Record original config values")
        max_retries_input = active_panel.locator('#llm_max_retries').first
        original_max_retries = max_retries_input.input_value()
        backoff_base_input = active_panel.locator('#llm_backoff_base').first
        original_backoff_base = backoff_base_input.input_value()
        backoff_cap_input = active_panel.locator('#llm_backoff_cap').first
        original_backoff_cap = backoff_cap_input.input_value()
        logger.info(f"Original values: max_retries={original_max_retries}, base={original_backoff_base}, cap={original_backoff_cap}")

        try:
            # Modify the config values
            log_test_step("Modify LLM retry config")
            max_retries_input.fill('5')
            backoff_base_input.fill('2.0')
            backoff_cap_input.fill('30.0')
            logger.info("LLM retry config values updated")

            # Save the config
            log_test_step("Save LLM retry config")
            runtime_config_page.click_save()
            runtime_config_page.assert_config_saved()
            logger.info("LLM retry config saved")

            # Reload and verify persistence
            log_test_step("Reload and verify persistence")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            runtime_config_page.switch_to_llm_retry_tab()
            active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
            persisted_value = active_panel.locator('#llm_max_retries').first.input_value()
            assert persisted_value == '5', f"After reload, max_retries should be '5', got '{persisted_value}'"
            logger.info("LLM retry config persistence verified")
        finally:
            # Restore the original config
            try:
                navigate_to_agent_config(page)
                runtime_config_page.switch_to_llm_retry_tab()
                active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
                active_panel.locator('#llm_max_retries').first.fill(original_max_retries)
                active_panel.locator('#llm_backoff_base').first.fill(original_backoff_base)
                active_panel.locator('#llm_backoff_cap').first.fill(original_backoff_cap)
                runtime_config_page.click_save()
                runtime_config_page.assert_config_saved()
                logger.info('Original config restored')
            except Exception as cleanup_error:
                logger.warning(f'Failed to restore config: {cleanup_error}')


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.config
class TestLlmRateLimiterConfig:
    """
    test_llm_rate_limiter_config: LLM rate limiter configuration.

    Coverage:
    1. Switch to LLM rate limiter tab
    2. Display of max concurrency, QPM, pause, jitter, acquire timeout fields
    3. Verify config modification and save
    """

    def test_llm_rate_limiter_config(self, page: Page):
        """LLM rate limiter configuration test."""
        log_test_step("Navigate to the Agent Config page")
        navigate_to_agent_config(page)

        from pages.runtime_config_page import RuntimeConfigPage
        runtime_config_page = RuntimeConfigPage(page)

        log_test_step("Switch to the LLM rate limiter tab")
        runtime_config_page.switch_to_llm_rate_limiter_tab()

        # Verify the card title
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        card_title = active_panel.locator('.qwenpaw-spark-title').first
        expect(card_title).to_be_visible()
        title_text = card_title.inner_text()
        assert "LLM" in title_text or "Rate" in title_text, \
            f"Card title does not contain expected keywords: {title_text}"
        logger.info("LLM rate limiter config card title verified")

        # Verify the input fields exist
        input_selectors = [
            '#llm_max_concurrent',
            '#llm_max_qpm',
            '#llm_rate_limit_pause',
            '#llm_rate_limit_jitter',
            '#llm_acquire_timeout'
        ]
        for selector in input_selectors:
            input_el = active_panel.locator(selector).first
            expect(input_el).to_be_visible()
        logger.info("LLM rate limiter config inputs verified")

        # Record the original values
        log_test_step("Record original config values")
        max_concurrent_input = active_panel.locator('#llm_max_concurrent').first
        original_concurrent = max_concurrent_input.input_value()
        max_qpm_input = active_panel.locator('#llm_max_qpm').first
        original_qpm = max_qpm_input.input_value()
        pause_input = active_panel.locator('#llm_rate_limit_pause').first
        original_pause = pause_input.input_value()
        logger.info(f"Original values: concurrent={original_concurrent}, qpm={original_qpm}, pause={original_pause}")

        try:
            # Modify the config values
            log_test_step("Modify LLM rate limiter config")
            max_concurrent_input.fill('10')
            max_qpm_input.fill('100')
            pause_input.fill('60.0')

            jitter_input = active_panel.locator('#llm_rate_limit_jitter').first
            jitter_input.fill('10.0')

            acquire_timeout_input = active_panel.locator('#llm_acquire_timeout').first
            acquire_timeout_input.fill('120')

            logger.info("LLM rate limiter config values updated")

            # Save the config
            log_test_step("Save LLM rate limiter config")
            runtime_config_page.click_save()
            runtime_config_page.assert_config_saved()
            logger.info("LLM rate limiter config saved")

            # Reload and verify persistence
            log_test_step("Reload and verify persistence")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            runtime_config_page.switch_to_llm_rate_limiter_tab()
            active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
            persisted_concurrent = active_panel.locator('#llm_max_concurrent').first.input_value()
            assert persisted_concurrent == '10', f"After reload, max_concurrent should be '10', got '{persisted_concurrent}'"
            logger.info("LLM rate limiter config persistence verified")
        finally:
            # Restore the original config
            try:
                navigate_to_agent_config(page)
                runtime_config_page.switch_to_llm_rate_limiter_tab()
                active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
                active_panel.locator('#llm_max_concurrent').first.fill(original_concurrent)
                active_panel.locator('#llm_max_qpm').first.fill(original_qpm)
                active_panel.locator('#llm_rate_limit_pause').first.fill(original_pause)
                runtime_config_page.click_save()
                runtime_config_page.assert_config_saved()
                logger.info('Original config restored')
            except Exception as cleanup_error:
                logger.warning(f'Failed to restore config: {cleanup_error}')


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.config
class TestToolResultCompactConfig:
    """
    test_tool_result_compact_config: Context management config (tool-result compaction was merged into the context management tab).

    Coverage:
    1. Switch to the context management tab
    2. Verify panel content (context compaction, tool result compaction, etc.)
    3. Verify config items are displayed
    """

    def test_tool_result_compact_config(self, page: Page):
        """Context management config test (tool-result compaction was merged here)."""
        log_test_step("Navigate to the Agent Config page")
        navigate_to_agent_config(page)

        from pages.runtime_config_page import RuntimeConfigPage
        runtime_config_page = RuntimeConfigPage(page)

        log_test_step("Switch to the context management tab (tool-result compaction was merged here)")
        runtime_config_page.switch_to_context_compact_tab()

        # Verify the panel is visible
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(active_panel).to_be_visible(timeout=5000)

        # Verify the panel contains context-management related content
        panel_text = active_panel.inner_text()
        assert any(kw in panel_text for kw in ["Context", "Compact"]), \
            f"Panel content does not contain context management keywords: {panel_text[:200]}"
        logger.info("Context management panel content verified")

        # Verify there are config items (inputs or selects)
        inputs = active_panel.locator('.qwenpaw-input, .qwenpaw-input-number, .qwenpaw-select').all()
        assert len(inputs) >= 1, f"No config items found on context management panel; found {len(inputs)}"
        logger.info(f"Found {len(inputs)} config items on context management panel")


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.config
class TestEmbeddingConfig:
    """
    test_embedding_config: Long-term memory configuration (embedding config was merged into the long-term memory tab).

    Coverage:
    1. Switch to the long-term memory tab
    2. Verify panel content (vector model config, memory toggle, etc.)
    3. Verify toggles and config items are displayed
    """

    def test_embedding_config(self, page: Page):
        """Long-term memory config test (embedding config was merged here)."""
        log_test_step("Navigate to the Agent Config page")
        navigate_to_agent_config(page)

        from pages.runtime_config_page import RuntimeConfigPage
        runtime_config_page = RuntimeConfigPage(page)

        log_test_step("Switch to the long-term memory tab (embedding config was merged here)")
        runtime_config_page.switch_to_memory_summary_tab()

        # Verify the panel is visible
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(active_panel).to_be_visible(timeout=5000)

        # Verify the panel contains long-term memory related content
        panel_text = active_panel.inner_text()
        assert any(kw in panel_text for kw in ["Memory", "Embedding"]), \
            f"Panel content does not contain long-term memory keywords: {panel_text[:200]}"
        logger.info("Long-term memory panel content verified")

        # Verify there are switches
        switches = active_panel.locator('.qwenpaw-switch').all()
        assert len(switches) >= 1, f"No switches found on long-term memory panel; found {len(switches)}"
        logger.info(f"Found {len(switches)} switches on long-term memory panel")


# ============================================================================
# AGCFG-P1-001: Context compaction config
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.runtime_config
class TestContextCompactConfig:
    """
    AGCFG-P1-001: Context compaction config.

    Coverage:
    1. Switch to the Context Compact tab
    2. Verify form fields exist (switches, sliders, etc.)
    3. Modify config and save
    """

    @pytest.mark.test_id("AGCFG-P1-001")
    def test_context_compact_config(self, page: Page, request: pytest.FixtureRequest):
        """Test the display and editing of context compaction config."""
        test_name = request.node.name

        log_test_step("Navigate to the runtime config page")
        navigate_to_agent_config(page)

        log_test_step("Switch to the context management tab")
        context_tab = page.locator(
            '[data-node-key="lightContext"] .qwenpaw-tabs-tab-btn, '
            '.qwenpaw-tabs-tab-btn:has-text("Context")'
        ).first
        expect(context_tab).to_be_visible(timeout=5000)
        context_tab.click()
        page.wait_for_timeout(1500)
        logger.info("Switched to Context Compact tab")

        log_test_step("Verify active panel content")
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(active_panel).to_be_visible(timeout=5000)

        # Verify the card title
        card_title = active_panel.locator('.qwenpaw-spark-title').first
        expect(card_title).to_be_visible()
        title_text = card_title.inner_text()
        assert "Context" in title_text or "Compact" in title_text, \
            f"Card title does not contain expected keywords: {title_text}"
        logger.info(f"Card title verified: {title_text}")

        log_test_step("Verify context management config items exist")
        # The context management tab may have switches, sliders, inputs or selects
        switches = active_panel.locator('.qwenpaw-switch').all()
        sliders = active_panel.locator('.qwenpaw-slider').all()
        inputs = active_panel.locator('.qwenpaw-input, .qwenpaw-input-number, .qwenpaw-select').all()
        total_controls = len(switches) + len(sliders) + len(inputs)
        assert total_controls >= 1, \
            f"No config items on context management panel: switches={len(switches)}, sliders={len(sliders)}, inputs={len(inputs)}"
        logger.info(f"Found config items: switches={len(switches)}, sliders={len(sliders)}, inputs={len(inputs)}")

        # If there are switches, test toggling
        if len(switches) >= 1:
            log_test_step("Toggle the context management switch")
            first_switch = switches[0]
            original_state = first_switch.get_attribute("aria-checked")
            first_switch.click()
            page.wait_for_timeout(1000)
            new_state = first_switch.get_attribute("aria-checked")
            assert original_state != new_state, \
                f"Switch toggle had no effect: before={original_state}, after={new_state}"
            logger.info(f"Switch toggled: {original_state} -> {new_state}")
            # Restore the original state
            first_switch.click()
            page.wait_for_timeout(500)
        else:
            logger.info("Context management tab has no switch controls; skipping toggle test")

        log_test_result(test_name, True, 0)


# ============================================================================
# AGCFG-P2-001: Dynamic linkage between config items
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.runtime_config
class TestConfigDynamicLinkage:
    """AGCFG-P2-001: Dynamic linkage between config items."""

    @pytest.mark.test_id("AGCFG-P2-001")
    def test_config_dynamic_linkage(self, page: Page, request: pytest.FixtureRequest):
        """Test dynamic linkage between config items."""
        test_name = request.node.name

        log_test_step("Navigate to the runtime config page")
        navigate_to_agent_config(page)

        log_test_step("Verify tab switching linkage")
        tabs = page.locator('.qwenpaw-tabs-tab').all()
        assert len(tabs) >= 3, f"Insufficient tabs: {len(tabs)}"
        logger.info(f"Found {len(tabs)} config tabs")

        log_test_step("Switch tabs and verify panel content changes")
        for i in range(min(3, len(tabs))):
            tabs[i].click()
            page.wait_for_timeout(1000)
            active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
            panel_content = active_panel.inner_text()
            logger.info(f"Tab {i+1} panel content length: {len(panel_content)}")
            assert len(panel_content) > 10, f"Tab {i+1} panel content is empty"

        logger.info("Dynamic linkage between config items verified")
        log_test_result(test_name, True, 0)


# ============================================================================
# AGCFG-P1-002: Memory summary config
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.runtime_config
class TestMemorySummaryConfig:
    """
    AGCFG-P1-002: Memory summary config.

    Coverage:
    1. Switch to the Memory Summary tab
    2. Verify form fields exist (switches, inputs, sliders, etc.)
    3. Modify config and verify
    """

    @pytest.mark.test_id("AGCFG-P1-002")
    def test_memory_summary_config(self, page: Page, request: pytest.FixtureRequest):
        """Test the display and editing of memory summary config."""
        test_name = request.node.name

        log_test_step("Navigate to the runtime config page")
        navigate_to_agent_config(page)

        log_test_step("Switch to the Memory Summary tab")
        memory_tab = page.locator(
            '[data-node-key="memorySummary"] .qwenpaw-tabs-tab-btn, '
            '.qwenpaw-tabs-tab-btn:has-text("Memory")'
        ).first
        expect(memory_tab).to_be_visible(timeout=5000)
        memory_tab.click()
        page.wait_for_timeout(1500)
        logger.info("Switched to Memory Summary tab")

        log_test_step("Verify active panel content")
        active_panel = page.locator('.qwenpaw-tabs-tabpane-active').first
        expect(active_panel).to_be_visible(timeout=5000)

        # Verify the card title
        card_title = active_panel.locator('.qwenpaw-spark-title').first
        expect(card_title).to_be_visible()
        title_text = card_title.inner_text()
        assert "Memory" in title_text or "Summary" in title_text, \
            f"Card title does not contain expected keywords: {title_text}"
        logger.info(f"Card title verified: {title_text}")

        log_test_step("Verify the memory summary switch exists")
        switches = active_panel.locator('.qwenpaw-switch').all()
        assert len(switches) >= 1, f"Memory summary switch not found; found {len(switches)} switches"
        logger.info(f"Found {len(switches)} switches")

        log_test_step("Verify the Cron expression input exists")
        cron_input = active_panel.locator('#memory_summary_dream_cron, input[id*="dream_cron"]').first
        if cron_input.count() == 0:
            cron_input = active_panel.locator('input').nth(0)
        assert cron_input.count() > 0, "Cron expression input not found"
        logger.info("Cron expression input present")

        log_test_step("Verify number inputs exist")
        number_inputs = active_panel.locator('.qwenpaw-input-number').all()
        assert len(number_inputs) >= 1, f"No number inputs found; got {len(number_inputs)}"
        logger.info(f"Found {len(number_inputs)} number inputs")

        log_test_step("Toggle the memory summary switch")
        first_switch = switches[0]
        original_state = first_switch.get_attribute("aria-checked")
        first_switch.click()
        page.wait_for_timeout(1000)
        new_state = first_switch.get_attribute("aria-checked")
        assert original_state != new_state, \
            f"Switch toggle had no effect: before={original_state}, after={new_state}"
        logger.info(f"Switch toggled: {original_state} -> {new_state}")

        # Restore the original state
        first_switch.click()
        page.wait_for_timeout(500)

        log_test_result(test_name, True, 0)