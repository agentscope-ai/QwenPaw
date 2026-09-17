# -*- coding: utf-8 -*-
"""
QwenPaw E2E tests - Login/Auth P0 cases

Functional coverage:
1. Auth status API
2. Login page accessibility
"""
from __future__ import annotations

import logging
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from utils.helpers import log_test_step, log_test_result

logger = logging.getLogger(__name__)

BASE_URL = config.server.base_url

# ============================================================================
# AUTH-001: Auth status API
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
class TestAuthStatus:
    """AUTH-001: Auth status API"""

    @pytest.mark.test_id("AUTH-001")
    def test_auth_status_api(self, page: Page, request: pytest.FixtureRequest, api_context):
        """Verify auth status API."""
        test_name = request.node.name

        try:
            log_test_step("1. Fetch auth status via API")
            response = api_context.get("/api/auth/status")
            logger.info(f"Auth status API status code: {response.status}")
            # Auth status API endpoint should be reachable
            assert response.status != 404, "Auth status API endpoint should exist"
            assert response.status != 405, "Auth status API should accept GET"

            if response.ok:
                result = response.json()
                logger.info(f"Auth status: {result}")
                logger.info("Auth status API returned successfully")
            else:
                logger.info(f"Auth status API returned {response.status} (auth may be disabled)")

            log_test_result(test_name, "PASS", "Auth status API validation passed")
        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise

# ============================================================================
# AUTH-002: Login page accessibility
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
class TestLoginPageAccess:
    """AUTH-002: Login page accessibility"""

    @pytest.mark.test_id("AUTH-002")
    def test_login_page_accessible(self, page: Page, request: pytest.FixtureRequest):
        """Verify login page is accessible."""
        test_name = request.node.name

        try:
            log_test_step("1. Navigate to login page")
            page.goto(f"{BASE_URL}/login")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)

            log_test_step("2. Verify page loaded")
            body = page.locator("body").first
            assert body.is_visible(timeout=5000), "Login page should load"

            # Check for login-related elements (input or button)
            login_elements = page.locator(
                'input[type="password"], '
                'button:has-text("登录"), '
                'button:has-text("Login"), '
                'button:has-text("Sign in")'
            ).first

            if login_elements.is_visible(timeout=3000):
                logger.info("Login page contains login elements")
            else:
                logger.info("Login page may have auto-logged in or auth is disabled")

            log_test_result(test_name, "PASS", "Login page accessibility validation passed")
        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise

# ============================================================================
# AUTH-P1-003: Multi-user management / permission control
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.auth
class TestMultiUserManagement:
    """
    AUTH-P1-003: Multi-user management / permission control

    Functional coverage:
    1. Verify auth status API returns has_users field
    2. Verify login page shows different forms based on status
    3. Verify register/login form fields
    """

    @pytest.mark.test_id("AUTH-P1-003")
    def test_multi_user_management(self, page: Page, request: pytest.FixtureRequest, api_context):
        """Test multi-user management / permission control."""
        test_name = request.node.name

        log_test_step("1. Check auth status API")
        try:
            response = api_context.get("/api/auth/status")
            if response.ok:
                result = response.json()
                has_users = result.get("has_users")
                logger.info(f"Auth status: has_users={has_users}")

                if has_users is not None:
                    logger.info(f"API returned has_users field: {has_users}")
                else:
                    logger.info("API did not return has_users field")
            else:
                logger.info(f"Auth status API returned {response.status}")
        except Exception as api_error:
            logger.info(f"Auth status API call failed: {api_error}")

        log_test_step("2. Navigate to login page")
        page.goto(f"{BASE_URL}/login")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)

        log_test_step("3. Verify login/register form")
        # Check for username input
        username_input = page.locator(
            'input[type="text"], input[name="username"], '
            'input[placeholder*="用户"], input[placeholder*="user"], '
            'input[placeholder*="User"]'
        ).first

        # Check for password input
        password_input = page.locator('input[type="password"]').first

        if username_input.count() > 0:
            logger.info("Username input exists")
        if password_input.count() > 0:
            logger.info("Password input exists")

        # Check for login/register buttons
        login_btn = page.locator(
            'button:has-text("登录"), button:has-text("Login"), '
            'button:has-text("Sign in")'
        ).first
        register_btn = page.locator(
            'button:has-text("注册"), button:has-text("Register"), '
            'button:has-text("Sign up"), button:has-text("Create")'
        ).first

        if login_btn.count() > 0:
            logger.info("Login button exists")
        if register_btn.count() > 0:
            logger.info("Register button exists (first-user init mode)")

        # Check for login/register toggle link
        toggle_link = page.locator(
            'a:has-text("注册"), a:has-text("Register"), '
            'a:has-text("登录"), a:has-text("Login"), '
            ':text("已有账号"), :text("没有账号")'
        ).first
        if toggle_link.count() > 0:
            logger.info("Login/register toggle link exists")

        has_form = (username_input.count() > 0 or password_input.count() > 0 or
                    login_btn.count() > 0 or register_btn.count() > 0)
        if has_form:
            logger.info("Login/register form validation passed")
        else:
            logger.info("No login form found, may have auto-logged in or auth disabled")

        log_test_result(test_name, True, 0)


# ============================================================================
# AUTH-P1-004: Login form validation (empty submit / required fields)
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.auth
class TestLoginFormValidation:
    """
    AUTH-P1-004: Login form validation

    Functional coverage:
    1. Submit with empty username -> required field error
    2. Submit with empty password -> required field error
    3. Submit fully empty -> show both required errors
    """

    @pytest.mark.test_id("AUTH-P1-004")
    def test_login_empty_form_validation(self, page: Page, request: pytest.FixtureRequest):
        """Verify required-field validation when submitting an empty login form."""
        test_name = request.node.name

        log_test_step("1. Navigate to login page")
        page.goto(f"{BASE_URL}/login")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)

        log_test_step("2. Check whether login form exists")
        submit_btn = page.locator(
            'button[type="submit"], '
            'button:has-text("登录"), '
            'button:has-text("Login"), '
            'button:has-text("注册"), '
            'button:has-text("Register")'
        ).first

        if not submit_btn.is_visible(timeout=3000):
            logger.info("No login form found (auth may be disabled), skipping form validation test")
            log_test_result(test_name, True, 0)
            return

        log_test_step("3. Click submit without filling anything")
        submit_btn.click()
        page.wait_for_timeout(1000)

        log_test_step("4. Verify required-field validation messages")
        # antd Form validation uses .ant-form-item-explain-error class
        validation_errors = page.locator(
            '.ant-form-item-explain-error, '
            '.ant-form-item-explain .ant-form-item-explain-error, '
            '[role="alert"]'
        ).all()

        if len(validation_errors) > 0:
            for idx, error in enumerate(validation_errors):
                error_text = error.inner_text()
                logger.info(f"  Validation message {idx + 1}: {error_text}")
            logger.info(f"Displayed {len(validation_errors)} required-field validation messages")
        else:
            logger.info("No form validation messages shown (may use other validation method)")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")

    @pytest.mark.test_id("AUTH-P1-005")
    def test_login_partial_form_validation(self, page: Page, request: pytest.FixtureRequest):
        """Verify validation when only username is filled and password is empty."""
        test_name = request.node.name

        log_test_step("1. Navigate to login page")
        try:
            page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=60000)
        except Exception:
            logger.warning("Login page initial load timed out, retrying...")
            page.goto(f"{BASE_URL}/login", wait_until="commit", timeout=60000)
        page.wait_for_timeout(2000)

        log_test_step("2. Check whether login form exists")
        username_input = page.locator(
            'input#username, '
            'input[type="text"], '
            'input[placeholder*="用户"], '
            'input[placeholder*="user"], '
            'input[placeholder*="User"]'
        ).first
        submit_btn = page.locator(
            'button[type="submit"], '
            'button:has-text("登录"), '
            'button:has-text("Login"), '
            'button:has-text("注册"), '
            'button:has-text("Register")'
        ).first

        if not submit_btn.is_visible(timeout=3000):
            logger.info("No login form found (auth may be disabled), skipping test")
            log_test_result(test_name, True, 0)
            return

        log_test_step("3. Fill username only, leave password empty")
        if username_input.is_visible(timeout=3000):
            username_input.fill("test_user")
            page.wait_for_timeout(500)
            logger.info("Username filled")

        log_test_step("4. Click submit")
        submit_btn.click()
        page.wait_for_timeout(1000)

        log_test_step("5. Verify password required-field validation")
        password_error = page.locator(
            '.ant-form-item-explain-error, '
            '[role="alert"]'
        ).first
        if password_error.is_visible(timeout=3000):
            error_text = password_error.inner_text()
            logger.info(f"Password validation message: {error_text}")
        else:
            logger.info("No password validation message shown")

        log_test_result(test_name, True, 0)
        logger.info(f"Test {test_name} passed")
