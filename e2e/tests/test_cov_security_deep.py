# -*- coding: utf-8 -*-
"""
Deep security/governance flows for coverage boost (Plan B).

Targets: Governance & Security (~5,243 uncovered lines) — tool guard,
file guard, rule configuration, save/enable/disable flows.

Run: pytest tests/test_cov_security_deep.py -v
"""
from __future__ import annotations

import logging

import pytest

from pages.security_page import SecurityPage
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)


@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.security
class TestSecurityGuardsDeep:
    """
    COV-SEC-001: Tool guard + file guard deep configuration flows.

    Coverage: governance/policy engine, security config, sandbox rules.
    """

    @pytest.mark.test_id("COV-SEC-001")
    def test_tool_and_file_guard_deep(
        self, security_page: SecurityPage, request: pytest.FixtureRequest
    ):
        test_name = request.node.name

        log_test_step("1. Open security page")
        security_page.open()
        security_page.wait_for_page_loaded()

        log_test_step("2. Switch to tool guard tab")
        security_page.switch_to_tab("toolGuard")
        security_page.page.wait_for_timeout(1500)

        log_test_step("3. Read current guard state")
        initial_enabled = security_page.is_guard_enabled()
        logger.info(f"Tool guard initially enabled={initial_enabled}")

        log_test_step("4. Toggle guard and save")
        security_page.toggle_guard()
        security_page.click_save()
        security_page.page.wait_for_timeout(2000)

        log_test_step("5. Verify state persisted after reload")
        security_page.page.reload()
        security_page.wait_for_page_loaded()
        security_page.switch_to_tab("toolGuard")
        toggled = security_page.is_guard_enabled()
        assert toggled != initial_enabled, "Guard state did not persist"

        log_test_step("6. Restore original state")
        security_page.toggle_guard()
        security_page.click_save()
        security_page.page.wait_for_timeout(1500)

        log_test_step("7. Switch to file guard tab and repeat")
        security_page.switch_to_tab("fileGuard")
        security_page.page.wait_for_timeout(1500)
        file_initial = security_page.is_guard_enabled()
        security_page.toggle_guard()
        security_page.click_save()
        security_page.page.wait_for_timeout(1500)
        security_page.page.reload()
        security_page.wait_for_page_loaded()
        security_page.switch_to_tab("fileGuard")
        file_toggled = security_page.is_guard_enabled()
        assert file_toggled != file_initial, "File guard state did not persist"
        # restore
        security_page.toggle_guard()
        security_page.click_save()
        security_page.page.wait_for_timeout(1000)

        log_test_step("8. Inspect protected tools select and path input")
        security_page.switch_to_tab("toolGuard")
        select = security_page.get_protected_tools_select()
        if select.count() > 0:
            logger.info("Protected tools select present")
        path_input = security_page.get_path_input()
        if path_input.count() > 0:
            logger.info("Path input present")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
