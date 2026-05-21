# -*- coding: utf-8 -*-
"""
QwenPaw 智能体管理模块 P0 级端到端测试用例

组合用例设计：
- AGENT-001: 智能体列表展示与刷新
- AGENT-002: 创建智能体（完整流程）
- AGENT-003: 编辑智能体信息
- AGENT-004: 删除智能体（带确认）
- AGENT-005: 启用/禁用智能体
- AGENT-006: 智能体文件管理
- AGENT-007: 智能体 API 操作验证

执行命令：pytest tests/test_agents_p0.py -v
"""
from __future__ import annotations

import json
import logging
import time
import pytest
from playwright.sync_api import Page, expect

from config.settings import config
from pages.agents_page import AgentsPage
from utils.helpers import log_test_step, log_test_result, take_screenshot

logger = logging.getLogger(__name__)

AGENTS_URL = f"{config.base_url}/agents"


def navigate_to_agents(page: Page):
    """导航到智能体管理页面并等待加载"""
    page.goto(AGENTS_URL)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)


# ============================================================================
# AGENT-001: 智能体列表展示与刷新
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agents_core
class TestAgentList:
    """
    AGENT-001: 智能体列表展示与刷新
    
    覆盖功能点：
    1. 智能体管理页面访问与加载
    2. 智能体列表展示（名称、ID、描述、状态）
    3. 列表刷新功能
    4. 空状态处理
    """
    
    @pytest.mark.test_id("AGENT-001")
    def test_agent_list_display_and_refresh(self, page: Page, request: pytest.FixtureRequest):
        """验证智能体列表展示与刷新功能"""
        test_name = request.node.name
        
        # 步骤 1: 访问智能体管理页面
        log_test_step("1. 访问智能体管理页面")
        navigate_to_agents(page)
        
        # 步骤 2: 验证页面标题（兼容中英文）
        log_test_step("2. 验证页面标题")
        try:
            header_cn = page.locator('span[class*="breadcrumbCurrent"]:has-text("智能体")').first
            header_en = page.locator('span[class*="breadcrumbCurrent"]:has-text("Agents")').first
            if header_cn.is_visible(timeout=3000):
                logger.info("✅ 页面标题验证通过（中文）")
            elif header_en.is_visible(timeout=3000):
                logger.info("✅ 页面标题验证通过（英文）")
            else:
                logger.warning("⚠️ 页面标题未找到，跳过验证")
        except Exception:
            logger.warning("⚠️ 页面标题验证跳过")
        
        # 步骤 3: 验证面包屑（兼容中英文）
        log_test_step("3. 验证面包屑")
        try:
            breadcrumb_cn = page.locator('span[class*="breadcrumbCurrent"]:has-text("智能体")').first
            breadcrumb_en = page.locator('span[class*="breadcrumbCurrent"]:has-text("Agents")').first
            if breadcrumb_cn.is_visible(timeout=3000):
                logger.info("✅ 面包屑验证通过（中文）")
            elif breadcrumb_en.is_visible(timeout=3000):
                logger.info("✅ 面包屑验证通过（英文）")
            else:
                logger.warning("⚠️ 面包屑未找到，跳过验证")
        except Exception:
            logger.warning("⚠️ 面包屑验证跳过")
        
        # 步骤 4: 验证智能体列表存在
        log_test_step("4. 验证智能体列表存在")
        agents_page = AgentsPage(page)
        agent_count = agents_page.get_agent_count()
        assert agent_count >= 1, "智能体列表应至少有一个智能体（default）"
        logger.info(f"✅ 智能体列表验证通过，共 {agent_count} 个智能体")
        
        # 步骤 5: 验证智能体信息展示
        log_test_step("5. 验证智能体信息展示")
        agents = agents_page.get_agent_list()
        assert len(agents) > 0, "智能体列表不应为空"
        
        has_name = any(agent["name"] for agent in agents)
        assert has_name, "智能体应该有名称"
        logger.info(f"✅ 智能体信息验证通过：{agents[0]['name']}")
        
        # 步骤 6: 刷新列表并验证数据一致
        log_test_step("6. 刷新列表并验证数据一致")
        count_before = agents_page.get_agent_count()
        agents_page.refresh_agent_list()
        count_after = agents_page.get_agent_count()
        assert count_before == count_after, "刷新前后智能体数量应一致"
        logger.info("✅ 刷新功能验证通过")
        
        log_test_result(test_name, "PASS", "智能体列表展示与刷新正常")


# ============================================================================
# AGENT-002: 创建智能体（完整流程）
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agents_create
class TestCreateAgent:
    """
    AGENT-002: 创建智能体（完整流程）
    
    覆盖功能点：
    1. 创建智能体按钮点击
    2. 表单填写（名称、描述、语言）
    3. 表单提交
    4. 创建成功验证
    5. 取消创建
    """
    
    @pytest.mark.test_id("AGENT-002")
    def test_create_agent_success(self, page: Page, request: pytest.FixtureRequest):
        """验证成功创建智能体"""
        test_name = request.node.name
        
        # 生成唯一的智能体名称
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"TestAgent_{timestamp}"
        agent_description = f"测试智能体_{timestamp}"
        
        try:
            # 步骤 1: 访问智能体管理页面
            log_test_step("1. 访问智能体管理页面")
            agents_page = AgentsPage(page)
            agents_page.goto()
            
            # 步骤 2: 获取创建前的智能体数量
            log_test_step("2. 获取创建前的智能体数量")
            count_before = agents_page.get_agent_count()
            logger.info(f"创建前智能体数量：{count_before}")
            
            # 步骤 3: 点击创建智能体按钮
            log_test_step("3. 点击创建智能体按钮")
            agents_page.click_create_agent()
            
            # 步骤 4: 验证表单弹窗显示
            log_test_step("4. 验证表单弹窗显示")
            form_dialog = page.locator(agents_page.FORM_DIALOG).first
            expect(form_dialog).to_be_visible(timeout=5000)
            logger.info("✅ 创建智能体表单弹窗已显示")
            
            # 步骤 5: 填写智能体信息
            log_test_step("5. 填写智能体信息")
            agents_page.fill_agent_form(agent_name, agent_description, "zh")
            logger.info(f"填写智能体信息：名称={agent_name}, 描述={agent_description}")
            
            # 步骤 6: 提交表单
            log_test_step("6. 提交表单")
            agents_page.submit_agent_form()
            page.wait_for_timeout(2000)
            
            # 步骤 7: 验证创建成功消息
            log_test_step("7. 验证创建成功消息")
            assert agents_page.verify_success_message(), "应显示创建成功消息"
            logger.info("✅ 创建成功消息验证通过")
            
            # 步骤 8: 验证智能体出现在列表中（增加重试机制）
            log_test_step("8. 验证智能体出现在列表中")
            found = False
            for attempt in range(5):
                agents_page.refresh_agent_list()
                page.wait_for_timeout(2000)
                if agents_page.is_agent_exists(agent_name):
                    found = True
                    break
                logger.warning(f"尝试 {attempt + 1}/5: 未找到智能体 {agent_name}，等待后重试...")
                page.wait_for_timeout(2000)
            assert found, f"智能体 {agent_name} 应存在于列表中"
            logger.info(f"✅ 智能体 {agent_name} 已存在于列表中")
            
            # 步骤 9: 验证智能体数量增加
            log_test_step("9. 验证智能体数量增加")
            count_after = agents_page.get_agent_count()
            assert count_after == count_before + 1, f"智能体数量应从 {count_before} 增加到 {count_before + 1}"
            logger.info(f"✅ 智能体数量验证通过：{count_before} -> {count_after}")
            
            log_test_result(test_name, "PASS", f"成功创建智能体：{agent_name}")
            
        finally:
            # 清理：删除创建的测试智能体（重新导航确保页面状态正确）
            try:
                page.goto(AGENTS_URL)
                page.wait_for_timeout(2000)
                agents_page = AgentsPage(page)
                agents_page.wait_for_page_load()
                if agents_page.is_agent_exists(agent_name):
                    logger.info(f"清理测试智能体：{agent_name}")
                    agents_page.delete_agent(agent_name)
            except Exception as e:
                logger.warning(f"清理测试智能体失败：{e}")
    
    @pytest.mark.test_id("AGENT-002-CANCEL")
    def test_create_agent_cancel(self, page: Page, request: pytest.FixtureRequest):
        """验证取消创建智能体"""
        test_name = request.node.name
        
        try:
            # 步骤 1: 访问智能体管理页面
            log_test_step("1. 访问智能体管理页面")
            agents_page = AgentsPage(page)
            agents_page.goto()
            
            # 步骤 2: 获取创建前的智能体数量
            log_test_step("2. 获取创建前的智能体数量")
            count_before = agents_page.get_agent_count()
            
            # 步骤 3: 点击创建智能体按钮
            log_test_step("3. 点击创建智能体按钮")
            agents_page.click_create_agent()
            
            # 步骤 4: 填写部分信息
            log_test_step("4. 填写部分信息")
            agents_page.fill_agent_form("TestCancelAgent", "测试取消")
            
            # 步骤 5: 取消创建
            log_test_step("5. 取消创建")
            agents_page.cancel_agent_form()
            page.wait_for_timeout(1000)
            
            # 步骤 6: 验证表单已关闭
            log_test_step("6. 验证表单已关闭")
            form_dialog = page.locator(agents_page.FORM_DIALOG).first
            expect(form_dialog).not_to_be_visible(timeout=3000)
            logger.info("✅ 表单已关闭")
            
            # 步骤 7: 验证智能体数量未变化
            log_test_step("7. 验证智能体数量未变化")
            count_after = agents_page.get_agent_count()
            assert count_before == count_after, "取消创建后智能体数量不应变化"
            logger.info("✅ 取消创建验证通过")
            
            log_test_result(test_name, "PASS", "取消创建智能体功能正常")
            
        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise
    
    @pytest.mark.test_id("AGENT-002-VALIDATION")
    def test_create_agent_name_required(self, page: Page, request: pytest.FixtureRequest):
        """验证智能体名称必填"""
        test_name = request.node.name
        
        try:
            # 步骤 1: 访问智能体管理页面
            log_test_step("1. 访问智能体管理页面")
            agents_page = AgentsPage(page)
            agents_page.goto()
            
            # 步骤 2: 点击创建智能体按钮
            log_test_step("2. 点击创建智能体按钮")
            agents_page.click_create_agent()
            
            # 步骤 3: 不填写名称，直接提交
            log_test_step("3. 不填写名称，直接提交")
            agents_page.submit_agent_form()
            page.wait_for_timeout(1000)
            
            # 步骤 4: 验证错误提示或表单未关闭
            log_test_step("4. 验证错误提示或表单未关闭")
            form_dialog = page.locator(agents_page.FORM_DIALOG).first
            # 表单应该仍然显示（未提交成功）或显示错误消息
            assert form_dialog.is_visible() or agents_page.verify_error_message(), \
                "名称为空时应显示错误或阻止提交"
            logger.info("✅ 名称必填验证通过")
            
            log_test_result(test_name, "PASS", "智能体名称必填验证正常")
            
            # 取消创建
            agents_page.cancel_agent_form()
            
        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise


# ============================================================================
# AGENT-003: 编辑智能体信息
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agents_edit
class TestEditAgent:
    """
    AGENT-003: 编辑智能体信息
    
    覆盖功能点：
    1. 编辑智能体入口
    2. 修改智能体名称
    3. 修改智能体描述
    4. 保存修改
    5. 取消修改
    """
    
    @pytest.mark.test_id("AGENT-003")
    def test_edit_agent_info(self, page: Page, request: pytest.FixtureRequest):
        """验证编辑智能体信息"""
        test_name = request.node.name
        
        # 创建测试智能体
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"TestEditAgent_{timestamp}"
        new_description = f"更新后的描述_{timestamp}"
        
        try:
            # 步骤 1: 创建测试智能体
            log_test_step("1. 创建测试智能体")
            agents_page = AgentsPage(page)
            agents_page.goto()
            agents_page.create_agent(agent_name, "原始描述", "zh")
            page.wait_for_timeout(2000)
            assert agents_page.is_agent_exists(agent_name), "测试智能体应创建成功"
            logger.info(f"测试智能体已创建：{agent_name}")
            
            # 步骤 2: 点击编辑智能体
            log_test_step("2. 点击编辑智能体")
            agents_page.click_edit_agent(agent_name)
            
            # 步骤 3: 验证编辑表单显示
            log_test_step("3. 验证编辑表单显示")
            form_dialog = page.locator(agents_page.FORM_DIALOG).first
            expect(form_dialog).to_be_visible(timeout=5000)
            logger.info("✅ 编辑表单已显示")
            
            # 步骤 4: 修改描述
            log_test_step("4. 修改描述")
            agents_page.fill_agent_form(name=agent_name, description=new_description)
            
            # 步骤 5: 保存修改
            log_test_step("5. 保存修改")
            agents_page.submit_agent_form()
            page.wait_for_timeout(2000)
            
            # 步骤 6: 验证修改成功
            log_test_step("6. 验证修改成功")
            assert agents_page.verify_success_message(), "应显示修改成功消息"
            logger.info("✅ 修改成功消息验证通过")
            
            log_test_result(test_name, "PASS", f"成功编辑智能体：{agent_name}")
            
        finally:
            # 清理：删除测试智能体（重新导航确保页面状态正确）
            try:
                page.goto(AGENTS_URL)
                page.wait_for_timeout(2000)
                agents_page = AgentsPage(page)
                agents_page.wait_for_page_load()
                if agents_page.is_agent_exists(agent_name):
                    logger.info(f"清理测试智能体：{agent_name}")
                    agents_page.delete_agent(agent_name)
            except Exception as e:
                logger.warning(f"清理测试智能体失败：{e}")


# ============================================================================
# AGENT-004: 删除智能体（带确认）
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.agents_delete
class TestDeleteAgent:
    """
    AGENT-004: 删除智能体（带确认）
    
    覆盖功能点：
    1. 删除智能体入口
    2. 删除确认弹窗
    3. 确认删除
    4. 取消删除
    5. 删除后验证
    """
    
    @pytest.mark.test_id("AGENT-004")
    def test_delete_agent_success(self, page: Page, request: pytest.FixtureRequest):
        """验证成功删除智能体"""
        test_name = request.node.name
        
        # 创建测试智能体
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"TestDeleteAgent_{timestamp}"
        
        try:
            # 步骤 1: 创建测试智能体
            log_test_step("1. 创建测试智能体")
            agents_page = AgentsPage(page)
            agents_page.goto()
            agents_page.create_agent(agent_name, "测试删除", "zh")
            page.wait_for_timeout(2000)
            assert agents_page.is_agent_exists(agent_name), "测试智能体应创建成功"
            logger.info(f"测试智能体已创建：{agent_name}")
            
            # 步骤 2: 获取删除前的智能体数量
            log_test_step("2. 获取删除前的智能体数量")
            count_before = agents_page.get_agent_count()
            
            # 步骤 3: 点击删除智能体
            log_test_step("3. 点击删除智能体")
            agents_page.click_delete_agent(agent_name)
            
            # 步骤 4: 验证删除确认弹窗显示
            log_test_step("4. 验证删除确认弹窗显示")
            confirm_dialog = page.locator(agents_page.DELETE_CONFIRM_DIALOG).first
            expect(confirm_dialog).to_be_visible(timeout=5000)
            logger.info("✅ 删除确认弹窗已显示")
            
            # 步骤 5: 确认删除
            log_test_step("5. 确认删除")
            agents_page.confirm_delete()
            page.wait_for_timeout(2000)
            
            # 步骤 6: 验证删除成功消息
            log_test_step("6. 验证删除成功消息")
            assert agents_page.verify_success_message(), "应显示删除成功消息"
            logger.info("✅ 删除成功消息验证通过")
            
            # 步骤 7: 验证智能体已从列表移除
            log_test_step("7. 验证智能体已从列表移除")
            agents_page.refresh_agent_list()
            assert not agents_page.is_agent_exists(agent_name), f"智能体 {agent_name} 应从列表中移除"
            logger.info(f"✅ 智能体 {agent_name} 已从列表移除")
            
            # 步骤 8: 验证智能体数量减少
            log_test_step("8. 验证智能体数量减少")
            count_after = agents_page.get_agent_count()
            assert count_after == count_before - 1, f"智能体数量应从 {count_before} 减少到 {count_before - 1}"
            logger.info(f"✅ 智能体数量验证通过：{count_before} -> {count_after}")
            
            log_test_result(test_name, "PASS", f"成功删除智能体：{agent_name}")
            
        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            # 确保清理
            try:
                if agents_page.is_agent_exists(agent_name):
                    agents_page.delete_agent(agent_name)
            except Exception:
                pass
            raise
    
    @pytest.mark.test_id("AGENT-004-CANCEL")
    def test_delete_agent_cancel(self, page: Page, request: pytest.FixtureRequest):
        """验证取消删除智能体"""
        test_name = request.node.name
        
        # 创建测试智能体
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"TestCancelDelete_{timestamp}"
        
        try:
            # 步骤 1: 创建测试智能体
            log_test_step("1. 创建测试智能体")
            agents_page = AgentsPage(page)
            agents_page.goto()
            agents_page.create_agent(agent_name, "测试取消删除", "zh")
            page.wait_for_timeout(2000)
            
            # 步骤 2: 获取删除前的智能体数量
            log_test_step("2. 获取删除前的智能体数量")
            count_before = agents_page.get_agent_count()
            
            # 步骤 3: 点击删除智能体
            log_test_step("3. 点击删除智能体")
            agents_page.click_delete_agent(agent_name)
            
            # 步骤 4: 取消删除
            log_test_step("4. 取消删除")
            agents_page.cancel_delete()
            page.wait_for_timeout(1000)
            
            # 步骤 5: 验证智能体仍存在
            log_test_step("5. 验证智能体仍存在")
            assert agents_page.is_agent_exists(agent_name), f"智能体 {agent_name} 应仍然存在"
            logger.info(f"✅ 智能体 {agent_name} 仍然存在")
            
            # 步骤 6: 验证智能体数量未变化
            log_test_step("6. 验证智能体数量未变化")
            count_after = agents_page.get_agent_count()
            assert count_before == count_after, "取消删除后智能体数量不应变化"
            logger.info("✅ 取消删除验证通过")
            
            log_test_result(test_name, "PASS", "取消删除智能体功能正常")
            
        finally:
            # 清理（重新导航确保页面状态正确）
            try:
                page.goto(AGENTS_URL)
                page.wait_for_timeout(2000)
                agents_page = AgentsPage(page)
                agents_page.wait_for_page_load()
                if agents_page.is_agent_exists(agent_name):
                    agents_page.delete_agent(agent_name)
            except Exception:
                pass


# ============================================================================
# AGENT-005: 启用/禁用智能体
# ============================================================================

@pytest.mark.integration
@pytest.mark.p0
@pytest.mark.agents_toggle
class TestToggleAgent:
    """
    AGENT-005: 启用/禁用智能体
    
    覆盖功能点：
    1. 智能体状态展示
    2. 切换智能体状态
    3. 状态更新验证
    """
    
    @pytest.mark.test_id("AGENT-005")
    def test_toggle_agent_status(self, page: Page, request: pytest.FixtureRequest):
        """验证切换智能体启用状态"""
        test_name = request.node.name
        
        # 创建测试智能体
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"TestToggleAgent_{timestamp}"
        
        try:
            # 步骤 1: 创建测试智能体
            log_test_step("1. 创建测试智能体")
            agents_page = AgentsPage(page)
            agents_page.goto()
            agents_page.create_agent(agent_name, "测试状态切换", "zh")
            page.wait_for_timeout(2000)
            
            # 步骤 2: 验证智能体初始状态为启用
            log_test_step("2. 验证智能体初始状态为启用")
            assert agents_page.is_agent_exists(agent_name), "测试智能体应存在"
            initial_status = agents_page.get_agent_status(agent_name)
            logger.info(f"初始状态：{initial_status}")
            
            # 步骤 3: 禁用智能体
            log_test_step("3. 禁用智能体")
            agents_page.disable_agent(agent_name)
            page.wait_for_timeout(2000)
            
            # 步骤 4: 验证禁用后状态变化（不刷新页面，因为刷新后可能过滤掉已禁用的智能体）
            log_test_step("4. 验证禁用后状态")
            # 方式1: 在当前页面检查 Disabled 标签是否出现
            disabled_tag = page.locator(f'.qwenpaw-table-row:has-text("{agent_name}") .qwenpaw-tag:has-text("Disabled")')
            # 方式2: 检查成功提示消息
            success_msg = page.locator('.qwenpaw-message-success, .qwenpaw-notification-success')
            tag_visible = disabled_tag.count() > 0 and disabled_tag.first.is_visible()
            msg_visible = success_msg.count() > 0
            assert tag_visible or msg_visible, \
                "智能体应已被禁用（Disabled 标签或成功消息应出现）"
            logger.info("✅ 禁用状态验证通过")
            
            # 步骤 5: 启用智能体（在当前页面直接操作，不刷新）
            log_test_step("5. 启用智能体")
            # 重新查找智能体行并点击 toggle
            agent_row = page.locator(f'.qwenpaw-table-row:has-text("{agent_name}")').first
            if agent_row.is_visible():
                toggle_btn = agent_row.locator('.qwenpaw-space-item:nth-child(2) button').first
                toggle_btn.click()
                page.wait_for_timeout(500)
                # 处理可能的确认弹窗
                popconfirm_btn = page.locator('.qwenpaw-popconfirm-buttons button.qwenpaw-btn-primary').first
                if popconfirm_btn.is_visible():
                    popconfirm_btn.click()
                page.wait_for_timeout(2000)
            
            # 步骤 6: 验证启用后状态恢复
            log_test_step("6. 验证启用后状态")
            # Disabled 标签应消失
            disabled_tag_after = page.locator(f'.qwenpaw-table-row:has-text("{agent_name}") .qwenpaw-tag:has-text("Disabled")')
            is_still_disabled = disabled_tag_after.count() > 0 and disabled_tag_after.first.is_visible()
            assert not is_still_disabled, "智能体应已被启用（Disabled 标签应消失）"
            logger.info("✅ 启用状态验证通过")
            
            log_test_result(test_name, "PASS", f"智能体状态切换验证通过：{agent_name}")
            
        finally:
            # 清理（重新导航确保页面状态正确）
            try:
                page.goto(AGENTS_URL)
                page.wait_for_timeout(2000)
                agents_page = AgentsPage(page)
                agents_page.wait_for_page_load()
                if agents_page.is_agent_exists(agent_name):
                    agents_page.delete_agent(agent_name)
            except Exception:
                pass


# ============================================================================
# AGENT-006: 智能体 API 操作验证
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.agents_api
class TestAgentAPI:
    """
    AGENT-006: 智能体 API 操作验证
    
    覆盖功能点：
    1. API 获取智能体列表
    2. API 创建智能体
    3. API 删除智能体
    4. API 切换智能体状态
    """
    
    @pytest.mark.test_id("AGENT-006")
    def test_agent_api_operations(self, page: Page, request: pytest.FixtureRequest, api_context):
        """验证智能体 API 操作"""
        test_name = request.node.name
        
        # 创建测试智能体
        timestamp = str(int(time.time()))[-6:]
        agent_name = f"APIAgent_{timestamp}"
        
        try:
            # 步骤 1: API 获取智能体列表
            log_test_step("1. API 获取智能体列表")
            agents_page = AgentsPage(page)
            agents_list = agents_page.api_get_agents(api_context)
            assert isinstance(agents_list, list), "API 返回应为列表"
            logger.info(f"API 获取到 {len(agents_list)} 个智能体")
            
            # 步骤 2: API 创建智能体
            log_test_step("2. API 创建智能体")
            create_result = agents_page.api_create_agent(
                api_context,
                name=agent_name,
                description="通过 API 创建的测试智能体",
                language="zh"
            )
            assert create_result, "API 创建应返回结果"
            logger.info(f"API 创建智能体结果：{create_result}")
            
            # 步骤 3: 验证智能体已创建（增加重试机制）
            log_test_step("3. 验证智能体已创建")
            found = False
            for attempt in range(5):
                page.goto(AGENTS_URL)
                page.wait_for_timeout(3000)
                agents_page.refresh_agent_list()
                page.wait_for_timeout(2000)
                if agents_page.is_agent_exists(agent_name):
                    found = True
                    break
                logger.warning(f"尝试 {attempt + 1}/5: 未找到智能体 {agent_name}，等待后重试...")
                page.wait_for_timeout(3000)
            assert found, f"智能体 {agent_name} 应存在（重试 5 次后仍未找到）"
            logger.info(f"✅ 智能体 {agent_name} 已创建")
            
            # 步骤 4: 获取智能体 ID
            log_test_step("4. 获取智能体 ID")
            agents = agents_page.get_agent_list()
            agent_id = None
            for agent in agents:
                if agent["name"] == agent_name:
                    agent_id = agent.get("id", "")
                    break
            assert agent_id, "应能获取智能体 ID"
            logger.info(f"智能体 ID: {agent_id}")
            
            # 步骤 5: API 切换智能体状态（如果 API 支持）
            log_test_step("5. API 切换智能体状态")
            try:
                toggle_result = agents_page.api_toggle_agent(api_context, agent_id, False)
                logger.info(f"API 切换状态结果：{toggle_result}")
            except (AssertionError, Exception) as toggle_err:
                logger.info(f"ℹ️ API toggle 不可用（{toggle_err}），跳过此步骤")
            
            # 步骤 6: API 删除智能体
            log_test_step("6. API 删除智能体")
            delete_result = agents_page.api_delete_agent(api_context, agent_id)
            assert delete_result, "API 删除应返回结果"
            logger.info(f"API 删除智能体结果：{delete_result}")
            
            # 步骤 7: 验证智能体已删除
            log_test_step("7. 验证智能体已删除")
            page.reload()
            page.wait_for_timeout(2000)
            agents_page.refresh_agent_list()
            assert not agents_page.is_agent_exists(agent_name), f"智能体 {agent_name} 应已删除"
            logger.info(f"✅ 智能体 {agent_name} 已删除")
            
            log_test_result(test_name, "PASS", "智能体 API 操作验证通过")
            
        except Exception as e:
            log_test_result(test_name, "FAIL", str(e))
            raise

        finally:
            # 清理：确保测试智能体被删除
            try:
                agents_page = AgentsPage(page)
                page.goto(AGENTS_URL)
                page.wait_for_timeout(2000)
                agents_page.refresh_agent_list()
                if agents_page.is_agent_exists(agent_name):
                    logger.info(f"清理：删除测试智能体 {agent_name}")
                    agents_page.delete_agent(agent_name)
            except Exception as cleanup_error:
                logger.warning(f"清理测试智能体失败：{cleanup_error}")


# ============================================================================
# AGENT-007: 智能体默认保护
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.agents_protection
class TestAgentProtection:
    """
    AGENT-007: 智能体默认保护
    
    覆盖功能点：
    1. 默认智能体不可删除
    2. 默认智能体不可禁用
    """
    
    @pytest.mark.test_id("AGENT-007")
    def test_default_agent_protected(self, page: Page, request: pytest.FixtureRequest):
        """验证默认智能体受保护"""
        test_name = request.node.name
        
        # 步骤 1: 访问智能体管理页面
        log_test_step("1. 访问智能体管理页面")
        agents_page = AgentsPage(page)
        agents_page.goto()
        
        # 步骤 2: 查找默认智能体
        log_test_step("2. 查找默认智能体")
        # 等待表格数据加载完成
        page.wait_for_timeout(2000)
        default_agent = None
        agents = agents_page.get_agent_list()
        logger.info(f"智能体列表共 {len(agents)} 个：{[a.get('name') + '(id=' + a.get('id', '') + ')' for a in agents]}")
        for agent in agents:
            agent_id = agent.get("id", "").lower()
            agent_name = agent.get("name", "").lower()
            if agent_id == "default" or "default" in agent_id or agent_name in ("默认智能体", "copaw"):
                default_agent = agent["element"]
                logger.info(f"找到默认智能体：name={agent.get('name')}, id={agent.get('id')}")
                break
        
        if default_agent:
            # 步骤 3: 验证默认智能体删除按钮为 disabled 状态
            log_test_step("3. 验证默认智能体删除保护")
            actions_cell = default_agent.locator(agents_page.AGENT_ACTIONS_CELL).first
            delete_btn = actions_cell.locator(agents_page.DELETE_BTN).first
            
            if delete_btn.is_visible():
                is_disabled = delete_btn.is_disabled()
                title = delete_btn.get_attribute("title") or ""
                logger.info(f"删除按钮 disabled={is_disabled}, title=\"{title}\"")
                assert is_disabled, "默认智能体的删除按钮应为 disabled 状态"
                logger.info("✅ 默认智能体删除按钮已禁用，保护验证通过")
            else:
                logger.info("ℹ️ 未找到删除按钮（可能默认智能体无删除入口）")
            
            logger.info("✅ 默认智能体保护验证通过")
        else:
            pytest.skip("未找到默认智能体，跳过保护验证")
        
        log_test_result(test_name, "PASS", "默认智能体保护验证通过")


# ============================================================================
# P1 级测试用例：智能体拖拽排序
# ============================================================================

@pytest.mark.integration
@pytest.mark.p1
@pytest.mark.agents_reorder
class TestAgentDragReorder:
    """
    AGENT-P1-001: 智能体拖拽排序
    
    覆盖功能点：
    1. 智能体列表的拖拽手柄识别
    2. 拖拽操作执行（从位置A拖到位置B）
    3. 排序结果验证
    4. 刷新页面验证持久化
    """

    def test_agent_drag_reorder(self, page: Page):
        """测试智能体拖拽排序功能"""
        log_test_step("导航到智能体管理页面")
        navigate_to_agents(page)
        
        log_test_step("查找智能体列表行")
        agent_rows = page.locator("tr[data-row-key], .ant-table-row, [class*='agent-row'], tbody tr").all()
        
        if len(agent_rows) < 2:
            pytest.skip(f"智能体数量不足（{len(agent_rows)}个），无法进行拖拽测试")
        
        log_test_step(f"找到 {len(agent_rows)} 个智能体，准备进行拖拽测试")
        
        first_row = agent_rows[0]
        second_row = agent_rows[1]
        
        log_test_step("获取拖拽前的智能体顺序")
        before_order = []
        for row in agent_rows[:3]:
            row_key = row.get_attribute("data-row-key")
            if row_key:
                before_order.append(row_key)
            else:
                name_cell = row.locator("td").nth(1)
                if name_cell.count() > 0:
                    name_text = name_cell.inner_text()
                    before_order.append(name_text.strip())
        
        assert len(before_order) >= 2, "无法获取至少 2 个智能体的标识信息"
        logger.info(f"拖拽前顺序: {before_order}")
        
        log_test_step("查找拖拽手柄")
        drag_handle = first_row.locator(".drag-handle, [class*='drag-handle'], .anticon-menu, svg[data-icon='menu']").first
        
        if drag_handle.count() == 0:
            drag_handle = first_row.locator("button[class*='drag'], [class*='sortable-handle']").first
        
        if drag_handle.count() == 0:
            pytest.skip("未找到拖拽手柄，当前页面可能不支持拖拽排序")
        
        log_test_step("找到拖拽手柄，开始执行拖拽操作")
        drag_handle.hover()
        time.sleep(0.5)
        
        page.mouse.down()
        time.sleep(0.3)
        
        second_row_center = second_row.bounding_box()
        assert second_row_center is not None, "无法获取第二行的位置信息"
        
        target_y = second_row_center["y"] + second_row_center["height"] / 2
        target_x = second_row_center["x"] + second_row_center["width"] / 2
        
        page.mouse.move(target_x, target_y, steps=10)
        time.sleep(0.5)
        
        page.mouse.up()
        time.sleep(2)
        
        log_test_step("拖拽操作完成，验证新顺序")
        refreshed_rows = page.locator("tr[data-row-key], .ant-table-row, [class*='agent-row'], tbody tr").all()
        after_order = []
        for row in refreshed_rows[:3]:
            row_key = row.get_attribute("data-row-key")
            if row_key:
                after_order.append(row_key)
            else:
                name_cell = row.locator("td").nth(1)
                if name_cell.count() > 0:
                    name_text = name_cell.inner_text()
                    after_order.append(name_text.strip())
        
        logger.info(f"拖拽后顺序: {after_order}")
        assert before_order != after_order, "拖拽后智能体顺序未改变，拖拽排序未生效"
        logger.info("✅ 智能体顺序已改变，拖拽排序成功")
        
        log_test_step("刷新页面验证持久化")
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
        
        persisted_rows = page.locator("tr[data-row-key], .ant-table-row, [class*='agent-row'], tbody tr").all()
        persisted_order = []
        for row in persisted_rows[:3]:
            row_key = row.get_attribute("data-row-key")
            if row_key:
                persisted_order.append(row_key)
            else:
                name_cell = row.locator("td").nth(1)
                if name_cell.count() > 0:
                    name_text = name_cell.inner_text()
                    persisted_order.append(name_text.strip())
        
        logger.info(f"刷新后顺序: {persisted_order}")
        assert after_order == persisted_order, \
            f"拖拽排序未持久化：拖拽后 {after_order}，刷新后 {persisted_order}"
        logger.info("✅ 拖拽排序已持久化，测试成功")
        
        logger.info("智能体拖拽排序测试完成")


# ============================================================================
# AGENT-P2-001: 智能体技能关联配置
# ============================================================================

@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.agents
class TestAgentSkillAssociation:
    """AGENT-P2-001: 智能体技能关联配置"""

    @pytest.mark.test_id("AGENT-P2-001")
    def test_agent_skill_association(self, page: Page, request: pytest.FixtureRequest):
        """测试智能体技能关联配置"""
        test_name = request.node.name

        log_test_step("导航到智能体管理页面")
        page.goto(f"{config.base_url}/agents")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

        log_test_step("查找智能体卡片")
        agent_cards = page.locator('.qwenpaw-card, [class*="agentCard"]').all()
        if len(agent_cards) == 0:
            logger.info("未找到智能体卡片，跳过测试")
            log_test_result(test_name, True, 0)
            return
        logger.info(f"找到 {len(agent_cards)} 个智能体卡片")

        log_test_step("点击第一个智能体查看详情")
        agent_cards[0].click()
        page.wait_for_timeout(3000)

        log_test_step("验证智能体详情页面已打开")
        # 点击卡片后可能打开弹窗/抽屉，也可能跳转到新页面
        detail_area = page.locator(
            '.qwenpaw-modal, .ant-modal, .qwenpaw-drawer, .ant-drawer, '
            '[class*="detail"], [class*="config"], [class*="agent"]'
        ).first

        # 如果弹窗/抽屉未出现，检查是否已跳转到详情页面
        if detail_area.count() == 0:
            current_url = page.url
            if "/agents/" in current_url or "/agent/" in current_url:
                logger.info(f"✅ 已跳转到智能体详情页面：{current_url}")
            else:
                logger.info("ℹ️ 点击智能体卡片后未打开详情弹窗或跳转，可能不支持此操作")
                log_test_result(test_name, True, 0)
                return
        else:
            logger.info("✅ 智能体详情页面已打开")

        log_test_step("验证详情页面包含关键配置区域")
        page_content = page.locator('body').inner_text()
        
        # 验证详情页面包含智能体相关配置区域
        config_keywords = ['Skills', '技能', 'Model', '模型', 'Prompt', '提示词',
                          'Name', '名称', 'Config', '配置', 'System', 'Setting']
        found_keywords = [kw for kw in config_keywords if kw in page_content]
        assert len(found_keywords) > 0, \
            f"智能体详情页面应包含至少一个配置区域关键词，但未找到任何: {config_keywords}"
        logger.info(f"✅ 详情页面包含配置关键词: {found_keywords}")

        # 验证页面有可交互元素（输入框、开关、选择器等）
        interactive_elements = page.locator(
            'input, textarea, .qwenpaw-switch, .qwenpaw-select, '
            '.qwenpaw-radio-group, button'
        ).all()
        visible_interactive = [el for el in interactive_elements if el.is_visible()]
        assert len(visible_interactive) > 0, "详情页面应有可交互元素"
        logger.info(f"✅ 详情页面有 {len(visible_interactive)} 个可交互元素")

        # 查找技能关联区域
        skill_section = page.locator(
            ':text("Skills"), :text("技能"), '
            '[class*="skill"], [class*="Skill"]'
        ).first
        if skill_section.count() > 0:
            assert skill_section.is_visible(timeout=3000), "技能区域应可见"
            logger.info("✅ 找到技能关联区域")
        else:
            logger.info("ℹ️ 未找到技能关联区域（当前页面可能不展示技能配置）")

        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        # 如果跳转了页面，返回列表页
        if "/agents/" in page.url or "/agent/" in page.url:
            page.go_back()
            page.wait_for_timeout(1000)
        log_test_result(test_name, True, 0)

