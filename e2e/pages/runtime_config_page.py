# -*- coding: utf-8 -*-
"""
QwenPaw Runtime Config page object.

Wraps all interactions on the Runtime Config (Agent Config) page and exposes business-level methods.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class RuntimeConfigPage(BasePage):
    """
    Runtime Config page object.

    Wraps all user interactions on the runtime config page:
    - ReAct agent tab
    - Language dropdown
    - Timezone display
    - Save configuration
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/agent-config"

    # ========== Selector definitions ==========

    # Page-loaded indicator
    PAGE_LOAD_INDICATOR = '.qwenpaw-tabs-tab-btn'

    # Tabs
    REACT_TAB = '[data-node-key="reactAgent"] .qwenpaw-tabs-tab-btn'
    LLM_RETRY_TAB = '[data-node-key="llmRetry"] .qwenpaw-tabs-tab-btn'
    LLM_RATE_LIMITER_TAB = '[data-node-key="llmRateLimiter"] .qwenpaw-tabs-tab-btn'
    CONTEXT_COMPACT_TAB = '[data-node-key="lightContext"] .qwenpaw-tabs-tab-btn'
    TOOL_RESULT_COMPACT_TAB = '[data-node-key="lightContext"] .qwenpaw-tabs-tab-btn'  # Merged into the Context Management tab
    MEMORY_SUMMARY_TAB = '[data-node-key="remeLightMemory"] .qwenpaw-tabs-tab-btn'
    EMBEDDING_CONFIG_TAB = '[data-node-key="remeLightMemory"] .qwenpaw-tabs-tab-btn'  # Embedding model config merged into the Long-term Memory tab
    TOOL_EXECUTION_LEVEL_TAB = '[data-node-key="toolExecutionLevel"] .qwenpaw-tabs-tab-btn'

    # Active panel
    ACTIVE_PANEL = '.qwenpaw-tabs-tabpane-active'

    # Language dropdown
    LANGUAGE_SELECT = '.qwenpaw-select'

    # Timezone display
    TIMEZONE_DISPLAY = '.qwenpaw-select-selection-item'

    # ReAct tab form fields
    MAX_ITERS_INPUT = '#max_iters'
    AUTO_CONTINUE_SWITCH = '#auto_continue_on_text_only'
    MEMORY_BACKEND_SELECT = '#memory_manager_backend'
    MAX_INPUT_LENGTH_INPUT = '#max_input_length'

    # Save button
    SAVE_BTN = 'button.qwenpaw-btn-primary:has-text("保存"), button:has-text("保 存")'
    RESET_BTN = 'button:has-text("重置"), button:has-text("重 置")'

    # Card title
    CARD_TITLE = '.qwenpaw-spark-title'

    # Generic form elements
    SWITCH = '.qwenpaw-switch'
    INPUT_NUMBER = '.qwenpaw-input-number-input'
    SLIDER = '.qwenpaw-slider'

    # ========== Navigation methods ==========

    def open(self) -> "RuntimeConfigPage":
        """Open the Runtime Config page."""
        logger.info("Opening Runtime Config page")
        self.goto()
        self.wait_for_page_loaded()
        return self

    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "RuntimeConfigPage":
        """Wait for the page to finish loading."""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self

    # ========== Tab operation methods ==========

    def get_react_tab(self) -> Locator:
        """Get the ReAct Agent tab."""
        return self.page.locator(self.REACT_TAB).first

    def switch_to_react_tab(self) -> "RuntimeConfigPage":
        """Switch to the ReAct Agent tab."""
        tab = self.get_react_tab()
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)

        # Verify the panel is active
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)

        logger.info("Switched to ReAct Agent tab")
        return self

    def switch_to_llm_retry_tab(self) -> "RuntimeConfigPage":
        """Switch to the LLM Auto-retry tab."""
        tab = self.page.locator(self.LLM_RETRY_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)

        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)

        logger.info("Switched to LLM Auto-retry tab")
        return self

    def switch_to_llm_rate_limiter_tab(self) -> "RuntimeConfigPage":
        """Switch to the LLM Rate Limiter tab."""
        tab = self.page.locator(self.LLM_RATE_LIMITER_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)

        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)

        logger.info("Switched to LLM Rate Limiter tab")
        return self

    def switch_to_context_compact_tab(self) -> "RuntimeConfigPage":
        """Switch to the Context Compaction tab."""
        tab = self.page.locator(self.CONTEXT_COMPACT_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)

        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)

        logger.info("Switched to Context Compaction tab")
        return self

    def switch_to_tool_result_compact_tab(self) -> "RuntimeConfigPage":
        """Switch to the Tool Result Compaction Config tab."""
        tab = self.page.locator(self.TOOL_RESULT_COMPACT_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)

        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)

        logger.info("Switched to Tool Result Compaction Config tab")
        return self

    def switch_to_memory_summary_tab(self) -> "RuntimeConfigPage":
        """Switch to the Long-term Memory Config tab."""
        tab = self.page.locator(self.MEMORY_SUMMARY_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)

        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)

        logger.info("Switched to Long-term Memory Config tab")
        return self

    def switch_to_embedding_config_tab(self) -> "RuntimeConfigPage":
        """Switch to the Embedding Model Config tab."""
        tab = self.page.locator(self.EMBEDDING_CONFIG_TAB).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)

        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)

        logger.info("Switched to Embedding Model Config tab")
        return self

    def switch_to_tab(self, tab_key: str) -> "RuntimeConfigPage":
        """
        Generic tab-switch method.

        Args:
            tab_key: the tab's data-node-key value, e.g. "reactAgent", "llmRetry", etc.
        """
        tab_selector = f'[data-node-key="{tab_key}"] .qwenpaw-tabs-tab-btn'
        tab = self.page.locator(tab_selector).first
        expect(tab).to_be_visible(timeout=self.timeout)
        tab.click()
        self.page.wait_for_timeout(1500)

        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        expect(active_panel).to_be_visible(timeout=self.timeout)

        logger.info(f"Switched to tab: {tab_key}")
        return self

    # ========== ReAct tab field operations ==========

    def get_max_iters(self) -> str:
        """Get the max iterations."""
        input_el = self.page.locator(self.MAX_ITERS_INPUT).first
        return input_el.input_value() if input_el.is_visible() else ""

    def set_max_iters(self, value: int) -> "RuntimeConfigPage":
        """Set the max iterations."""
        input_el = self.page.locator(self.MAX_ITERS_INPUT).first
        expect(input_el).to_be_visible(timeout=self.timeout)
        input_el.fill(str(value))
        logger.info(f"Set max iterations: {value}")
        return self

    def is_auto_continue_enabled(self) -> bool:
        """Check whether 'auto-continue on text-only steps' is enabled."""
        switch = self.page.locator(self.AUTO_CONTINUE_SWITCH).first
        if switch.count() > 0:
            return switch.get_attribute("aria-checked") == "true"
        return False

    def toggle_auto_continue(self) -> "RuntimeConfigPage":
        """Toggle the 'auto-continue on text-only steps' switch."""
        switch = self.page.locator(self.AUTO_CONTINUE_SWITCH).first
        expect(switch).to_be_visible(timeout=self.timeout)
        switch.click()
        self.page.wait_for_timeout(500)
        logger.info("Toggled auto-continue switch")
        return self

    def get_memory_backend(self) -> str:
        """Get the current memory manager backend."""
        select = self.page.locator(self.MEMORY_BACKEND_SELECT).first
        if select.is_visible():
            selection = select.locator('.qwenpaw-select-selection-item').first
            return selection.inner_text() if selection.is_visible() else ""
        return ""

    def get_max_input_length(self) -> str:
        """Get the max context length."""
        input_el = self.page.locator(self.MAX_INPUT_LENGTH_INPUT).first
        return input_el.input_value() if input_el.is_visible() else ""

    def set_max_input_length(self, value: int) -> "RuntimeConfigPage":
        """Set the max context length."""
        input_el = self.page.locator(self.MAX_INPUT_LENGTH_INPUT).first
        expect(input_el).to_be_visible(timeout=self.timeout)
        input_el.fill(str(value))
        logger.info(f"Set max context length: {value}")
        return self

    # ========== Generic panel operations ==========

    def get_active_panel_switches(self) -> List[Locator]:
        """Get all switches in the currently active panel."""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.SWITCH).all()

    def get_active_panel_inputs(self) -> List[Locator]:
        """Get all number inputs in the currently active panel."""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.INPUT_NUMBER).all()

    def get_active_panel_sliders(self) -> List[Locator]:
        """Get all sliders in the currently active panel."""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.SLIDER).all()

    def click_reset(self) -> "RuntimeConfigPage":
        """Click the reset button."""
        reset_btn = self.page.locator(self.RESET_BTN).first
        expect(reset_btn).to_be_visible(timeout=self.timeout)
        reset_btn.click()
        self.page.wait_for_timeout(2000)
        logger.info("Clicked reset button")
        return self

    # ========== Language selection operations ==========

    def get_language_select(self) -> Locator:
        """Get the language dropdown."""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        return active_panel.locator(self.LANGUAGE_SELECT).first

    def select_language(self, language: str) -> "RuntimeConfigPage":
        """
        Select a language.

        Args:
            language: language name, e.g. "English", "中文"

        Returns:
            self
        """
        language_select = self.get_language_select()
        expect(language_select).to_be_visible(timeout=self.timeout)

        # Click to expand the dropdown
        language_select.click()
        self.page.wait_for_timeout(1000)

        # Pick the option
        dropdown = self.page.locator('.qwenpaw-select-dropdown:visible').first
        if dropdown.is_visible():
            option = dropdown.locator(f'.qwenpaw-select-item-option:has-text("{language}")').first
            expect(option).to_be_visible(timeout=self.timeout)
            option.click()
            self.page.wait_for_timeout(500)
            logger.info(f"Selected language: {language}")
        else:
            logger.warning("Language dropdown did not expand")
            self.page.keyboard.press("Escape")

        return self

    def get_current_language(self) -> str:
        """Get the currently selected language."""
        language_select = self.get_language_select()
        selection_item = language_select.locator('.qwenpaw-select-selection-item').first
        return selection_item.inner_text()

    # ========== Timezone operations ==========

    def get_timezone_display(self) -> Locator:
        """Get the timezone display element."""
        active_panel = self.page.locator(self.ACTIVE_PANEL).first
        selects = active_panel.locator(self.LANGUAGE_SELECT).all()
        # Timezone is the second select
        if len(selects) >= 2:
            return selects[1]
        return selects[0] if len(selects) > 0 else self.page.locator('.qwenpaw-select').last

    def get_current_timezone(self) -> str:
        """Get the current timezone."""
        timezone_select = self.get_timezone_display()
        selection_item = timezone_select.locator(self.TIMEZONE_DISPLAY).first
        return selection_item.inner_text()

    # ========== Save operation ==========

    def get_save_button(self) -> Locator:
        """Get the save button."""
        return self.page.locator(self.SAVE_BTN).first

    def click_save(self) -> "RuntimeConfigPage":
        """Click the save button."""
        save_btn = self.get_save_button()
        if not save_btn.is_visible():
            # Try locating it inside the footer
            save_btn = self.page.locator('div[class*="footer"] button.qwenpaw-btn-primary').first

        expect(save_btn).to_be_visible(timeout=self.timeout)
        save_btn.click()
        self.page.wait_for_timeout(2000)
        logger.info("Clicked save button")
        return self

    # ========== Assertion methods ==========

    def assert_react_tab_active(self) -> "RuntimeConfigPage":
        """Assert the ReAct Agent tab is active."""
        card_title = self.page.locator(self.ACTIVE_PANEL).locator(self.CARD_TITLE).first
        expect(card_title).to_be_visible(timeout=self.timeout)
        title_text = card_title.inner_text()
        assert "ReAct" in title_text, f"Card title does not contain ReAct: {title_text}"
        return self

    def assert_config_saved(self) -> "RuntimeConfigPage":
        """Assert the configuration was saved successfully."""
        error_msg = self.page.locator('.qwenpaw-message-error')
        assert error_msg.count() == 0, "An error message appeared after saving"
        return self
