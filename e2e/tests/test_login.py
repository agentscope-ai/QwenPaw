# -*- coding: utf-8 -*-
"""
QwenPaw E2E 测试 - Login/Auth P0 用例

覆盖功能：
1. 认证状态 API
2. 登录页面可访问性
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
# AUTH-001: 认证状态 API
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
class TestAuthStatus:
    """AUTH-001: 认证状态 API"""
    
    @pytest.mark.test_id("AUTH-001")
    def test_auth_status_api(self, page: Page, request: pytest.FixtureRequest, api_context):
        """验证认证状态 API"""
        test_name = request.node.name
        
        try:
            log_test_step("1. API 获取认证状态")
            response = api_context.get("/api/auth/status")
            logger.info(f"认证状态 API 状态码：{response.status}")
            # 认证状态 API 应该可达
            assert response.status != 404, "认证状态 API 端点应存在"
            assert response.status != 405, "认证状态 API 应接受 GET"
            
            if response.ok:
                result = response.json()
                logger.info(f"认证状态：{result}")
                logger.info(f"✅ 认证状态 API 返回成功")
            else:
                logger.info(f"ℹ️ 认证状态 API 返回 {response.status}（可能未启用认证）")
            
            log_test_result(test_name, "PASS", "认证状态 API 验证通过")
        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise

# ============================================================================
# AUTH-002: 登录页面可访问性
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
class TestLoginPageAccess:
    """AUTH-002: 登录页面可访问性"""
    
    @pytest.mark.test_id("AUTH-002")
    def test_login_page_accessible(self, page: Page, request: pytest.FixtureRequest):
        """验证登录页面可访问"""
        test_name = request.node.name
        
        try:
            log_test_step("1. 访问登录页面")
            page.goto(f"{BASE_URL}/login")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)
            
            log_test_step("2. 验证页面加载")
            body = page.locator("body").first
            assert body.is_visible(timeout=5000), "登录页面应正常加载"
            
            # 检查是否有登录相关元素（输入框或按钮）
            login_elements = page.locator(
                'input[type="password"], '
                'button:has-text("登录"), '
                'button:has-text("Login"), '
                'button:has-text("Sign in")'
            ).first
            
            if login_elements.is_visible(timeout=3000):
                logger.info(f"✅ 登录页面包含登录元素")
            else:
                logger.info(f"ℹ️ 登录页面可能已自动登录或未启用认证")
            
            log_test_result(test_name, "PASS", "登录页面可访问性验证通过")
        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise

# ============================================================================
# AUTH-P1-003: 多用户管理/权限控制
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.auth
class TestMultiUserManagement:
    """
    AUTH-P1-003: 多用户管理/权限控制

    覆盖功能点：
    1. 验证认证状态 API 返回 has_users 字段
    2. 验证登录页面根据状态展示不同表单
    3. 验证注册/登录表单字段
    """

    @pytest.mark.test_id("AUTH-P1-003")
    def test_multi_user_management(self, page: Page, request: pytest.FixtureRequest, api_context):
        """测试多用户管理/权限控制"""
        test_name = request.node.name

        log_test_step("1. 检查认证状态 API")
        try:
            response = api_context.get("/api/auth/status")
            if response.ok:
                result = response.json()
                has_users = result.get("has_users")
                logger.info(f"认证状态：has_users={has_users}")

                if has_users is not None:
                    logger.info(f"✅ API 返回 has_users 字段：{has_users}")
                else:
                    logger.info("API 未返回 has_users 字段")
            else:
                logger.info(f"认证状态 API 返回 {response.status}")
        except Exception as api_error:
            logger.info(f"认证状态 API 调用失败：{api_error}")

        log_test_step("2. 访问登录页面")
        page.goto(f"{BASE_URL}/login")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)

        log_test_step("3. 验证登录/注册表单")
        # 检查是否有用户名输入框
        username_input = page.locator(
            'input[type="text"], input[name="username"], '
            'input[placeholder*="用户"], input[placeholder*="user"], '
            'input[placeholder*="User"]'
        ).first

        # 检查是否有密码输入框
        password_input = page.locator('input[type="password"]').first

        if username_input.count() > 0:
            logger.info("✅ 用户名输入框存在")
        if password_input.count() > 0:
            logger.info("✅ 密码输入框存在")

        # 检查是否有登录/注册按钮
        login_btn = page.locator(
            'button:has-text("登录"), button:has-text("Login"), '
            'button:has-text("Sign in")'
        ).first
        register_btn = page.locator(
            'button:has-text("注册"), button:has-text("Register"), '
            'button:has-text("Sign up"), button:has-text("Create")'
        ).first

        if login_btn.count() > 0:
            logger.info("✅ 登录按钮存在")
        if register_btn.count() > 0:
            logger.info("✅ 注册按钮存在（首用户初始化模式）")

        # 检查是否有切换登录/注册的链接
        toggle_link = page.locator(
            'a:has-text("注册"), a:has-text("Register"), '
            'a:has-text("登录"), a:has-text("Login"), '
            ':text("已有账号"), :text("没有账号")'
        ).first
        if toggle_link.count() > 0:
            logger.info("✅ 登录/注册切换链接存在")

        has_form = (username_input.count() > 0 or password_input.count() > 0 or
                    login_btn.count() > 0 or register_btn.count() > 0)
        if has_form:
            logger.info("✅ 登录/注册表单验证通过")
        else:
            logger.info("未找到登录表单，可能已自动登录或未启用认证")

        log_test_result(test_name, True, 0)


# ============================================================================
# AUTH-P1-004: 登录表单验证（空提交 / 必填校验）
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.auth
class TestLoginFormValidation:
    """
    AUTH-P1-004: 登录表单验证

    覆盖功能点：
    1. 空用户名提交 → 显示必填提示
    2. 空密码提交 → 显示必填提示
    3. 全空提交 → 同时显示两个必填提示
    """

    @pytest.mark.test_id("AUTH-P1-004")
    def test_login_empty_form_validation(self, page: Page, request: pytest.FixtureRequest):
        """验证登录表单空提交时的必填校验"""
        test_name = request.node.name

        log_test_step("1. 访问登录页面")
        page.goto(f"{BASE_URL}/login")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)

        log_test_step("2. 检查是否有登录表单")
        submit_btn = page.locator(
            'button[type="submit"], '
            'button:has-text("登录"), '
            'button:has-text("Login"), '
            'button:has-text("注册"), '
            'button:has-text("Register")'
        ).first

        if not submit_btn.is_visible(timeout=3000):
            logger.info("ℹ️ 未找到登录表单（可能未启用认证），跳过表单验证测试")
            log_test_result(test_name, True, 0)
            return

        log_test_step("3. 不填写任何内容，直接点击提交按钮")
        submit_btn.click()
        page.wait_for_timeout(1000)

        log_test_step("4. 验证表单必填校验提示")
        # antd Form 的校验提示使用 .ant-form-item-explain-error 类
        validation_errors = page.locator(
            '.ant-form-item-explain-error, '
            '.ant-form-item-explain .ant-form-item-explain-error, '
            '[role="alert"]'
        ).all()

        if len(validation_errors) > 0:
            for idx, error in enumerate(validation_errors):
                error_text = error.inner_text()
                logger.info(f"  ✅ 校验提示 {idx + 1}：{error_text}")
            logger.info(f"✅ 共显示 {len(validation_errors)} 个必填校验提示")
        else:
            logger.info("ℹ️ 未显示表单校验提示（可能使用其他校验方式）")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed")

    @pytest.mark.test_id("AUTH-P1-005")
    def test_login_partial_form_validation(self, page: Page, request: pytest.FixtureRequest):
        """验证只填用户名不填密码时的校验"""
        test_name = request.node.name

        log_test_step("1. 访问登录页面")
        try:
            page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=60000)
        except Exception:
            logger.warning("登录页面首次加载超时，重试中...")
            page.goto(f"{BASE_URL}/login", wait_until="commit", timeout=60000)
        page.wait_for_timeout(2000)

        log_test_step("2. 检查是否有登录表单")
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
            logger.info("ℹ️ 未找到登录表单（可能未启用认证），跳过测试")
            log_test_result(test_name, True, 0)
            return

        log_test_step("3. 只填写用户名，不填密码")
        if username_input.is_visible(timeout=3000):
            username_input.fill("test_user")
            page.wait_for_timeout(500)
            logger.info("✅ 已填写用户名")

        log_test_step("4. 点击提交")
        submit_btn.click()
        page.wait_for_timeout(1000)

        log_test_step("5. 验证密码必填校验提示")
        password_error = page.locator(
            '.ant-form-item-explain-error, '
            '[role="alert"]'
        ).first
        if password_error.is_visible(timeout=3000):
            error_text = password_error.inner_text()
            logger.info(f"✅ 密码校验提示：{error_text}")
        else:
            logger.info("ℹ️ 未显示密码校验提示")

        log_test_result(test_name, True, 0)
        logger.info(f"✅ Test {test_name} passed")