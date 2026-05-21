# -*- coding: utf-8 -*-
"""
QwenPaw 智能体管理页面对象

封装智能体管理页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config
from utils.helpers import log_test_step


logger = logging.getLogger(__name__)


class AgentsPage(BasePage):
    """
    智能体管理页面对象
    
    封装智能体管理页面的所有用户操作：
    - 智能体列表查看
    - 创建智能体
    - 编辑智能体
    - 删除智能体
    - 启用/禁用智能体
    - 智能体重排序
    - 智能体文件管理
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/agents"
    
    # ========== 选择器定义 ==========
    
    # 页面标题和面包屑
    PAGE_HEADER = 'button:has-text("Create Agent"), span[class*="breadcrumbCurrent"]:has-text("智能体")'
    BREADCRUMB = 'span[class*="breadcrumbCurrent"]:has-text("智能体")'
    
    # 智能体列表（表格结构）
    AGENT_TABLE = '.qwenpaw-table'
    AGENT_LIST = '.qwenpaw-table-tbody'
    AGENT_ITEM = '.qwenpaw-table-tbody tr.qwenpaw-table-row'
    # 表格列顺序：拖拽手柄(1) | Name(2) | ID(3) | Description(4) | Workspace(5) | Model(6) | Actions(7)
    AGENT_NAME_CELL = 'td.qwenpaw-table-cell:nth-child(2)'
    AGENT_ID_CELL = 'td.qwenpaw-table-cell:nth-child(3)'
    AGENT_DESC_CELL = 'td.qwenpaw-table-cell:nth-child(4)'
    AGENT_WORKSPACE_CELL = 'td.qwenpaw-table-cell:nth-child(5)'
    AGENT_MODEL_CELL = 'td.qwenpaw-table-cell:nth-child(6)'
    AGENT_ACTIONS_CELL = 'td.qwenpaw-table-cell:nth-child(7)'
    AGENT_STATUS = '.qwenpaw-tag'
    
    # 操作按钮
    CREATE_AGENT_BTN = 'button:has-text("创建智能体"), button:has-text("Create Agent"), .qwenpaw-btn-primary'
    # 表格行内操作按钮（3 个图标按钮：编辑、toggle、删除）
    # 使用 Ant Design icon 类名定位（anticon-edit / anticon-delete），fallback 到 nth-child
    EDIT_BTN = 'button:has(.anticon-edit), .qwenpaw-space-item:nth-child(1) button'
    TOGGLE_BTN = '.qwenpaw-space-item:nth-child(2) button'
    DELETE_BTN = 'button.qwenpaw-btn-dangerous, button:has(.anticon-delete)'
    ENABLE_TOGGLE = '.qwenpaw-space-item:nth-child(2) button'
    REFRESH_BTN = 'button:has(.anticon-reload), button:has(.spark-icon-spark-refresh-line)'
    
    # 创建/编辑表单
    FORM_DIALOG = '.qwenpaw-modal, [role="dialog"]'
    FORM_TITLE = '.qwenpaw-modal-header-title, .qwenpaw-spark-title'
    FORM_NAME_INPUT = 'input#name, input[placeholder*="My Agent"]'
    FORM_DESC_INPUT = 'textarea#description, textarea[placeholder*="describe"]'
    FORM_WORKSPACE_INPUT = 'input#workspace_dir'
    FORM_SKILLS_SELECT = '.qwenpaw-form-item:has-text("Skills") .qwenpaw-select-selector'
    FORM_SUBMIT_BTN = '.qwenpaw-modal-footer button.qwenpaw-btn-primary, button:has-text("保存"), button:has-text("Save")'
    FORM_CANCEL_BTN = '.qwenpaw-modal-footer button.qwenpaw-btn-default, button:has-text("取消"), button:has-text("Cancel")'
    
    # 删除确认（Popconfirm 气泡确认框）
    DELETE_CONFIRM_DIALOG = '.qwenpaw-popconfirm'
    DELETE_CONFIRM_BTN = '.qwenpaw-popconfirm-buttons button.qwenpaw-btn-primary'
    DELETE_CANCEL_BTN = '.qwenpaw-popconfirm-buttons button.qwenpaw-btn-default'
    
    # 智能体详情
    AGENT_DETAIL_TAB = '.qwenpaw-tabs-tab-btn'
    AGENT_DETAIL_PANEL = '.qwenpaw-tabs-tabpane-active'
    AGENT_FILES_LIST = '[class*=fileList], .qwenpaw-list'
    AGENT_FILE_ITEM = '[class*=fileItem], .qwenpaw-list-item'
    
    # 空状态
    EMPTY_STATE = '.qwenpaw-empty, [class*=empty]'
    EMPTY_STATE_TEXT = '.qwenpaw-empty-description, .qwenpaw-empty-desc'
    
    # 消息提示（继承自 BasePage，此处无需重复定义）
    
    # ========== 初始化 ==========
    
    def __init__(self, page: Page):
        super().__init__(page)
    
    # ========== 导航和基础操作 ==========
    
    def goto(self) -> "AgentsPage":
        """导航到智能体管理页面"""
        logger.info("Navigating to agents management page")
        self.page.goto(self.PAGE_URL)
        self.wait_for_page_load()
        return self
    
    def wait_for_page_load(self, timeout: int = 10000):
        """等待页面加载完成"""
        try:
            self.page.locator(self.PAGE_HEADER).first.wait_for(state="visible", timeout=timeout)
            logger.info("Agents page loaded successfully")
        except TimeoutError:
            # 尝试其他可能的标题
            self.page.locator(self.BREADCRUMB).first.wait_for(state="visible", timeout=timeout)
            logger.info("Agents page loaded (breadcrumb found)")
        return self
    
    # ========== 智能体列表操作 ==========
    
    def get_agent_list(self) -> List[Dict]:
        """
        获取智能体列表（表格结构）
        
        Returns:
            智能体信息列表
        """
        logger.info("Getting agent list")
        agent_rows = self.page.locator(self.AGENT_ITEM).all()
        
        agents = []
        for row in agent_rows:
            try:
                name_cell = row.locator(self.AGENT_NAME_CELL).first
                name_text = name_cell.inner_text() if name_cell.is_visible() else ""
                # 名称单元格可能包含 "Disabled" 标签，需要去除
                status_tag = name_cell.locator(self.AGENT_STATUS).first
                status = status_tag.inner_text().strip() if status_tag.is_visible() else ""
                # 从名称文本中去除状态标签文本
                clean_name = name_text.replace(status, "").strip() if status else name_text.strip()
                
                id_cell = row.locator(self.AGENT_ID_CELL).first
                agent_id = id_cell.inner_text().strip() if id_cell.is_visible() else ""
                
                desc_cell = row.locator(self.AGENT_DESC_CELL).first
                desc = desc_cell.inner_text().strip() if desc_cell.is_visible() else ""
                
                agents.append({
                    "name": clean_name,
                    "id": agent_id,
                    "description": desc[:200],
                    "status": status,
                    "element": row
                })
            except Exception as e:
                logger.debug(f"Failed to parse agent row: {e}")
                continue
        
        logger.info(f"Found {len(agents)} agents")
        return agents
    
    def get_agent_count(self) -> int:
        """获取智能体数量（等待表格数据加载）"""
        # 等待至少一行出现，避免表格未渲染完就返回 0
        try:
            self.page.locator(self.AGENT_ITEM).first.wait_for(state="visible", timeout=5000)
        except Exception:
            logger.debug("No agent rows found within timeout, table may be empty")
        count = self.page.locator(self.AGENT_ITEM).count()
        logger.info(f"Agent count: {count}")
        return count
    
    def is_agent_exists(self, agent_name: str) -> bool:
        """检查智能体是否存在"""
        agents = self.get_agent_list()
        return any(agent["name"] == agent_name for agent in agents)
    
    def find_agent_by_name(self, agent_name: str) -> Optional[Locator]:
        """根据名称查找智能体"""
        agents = self.get_agent_list()
        for agent in agents:
            if agent["name"] == agent_name:
                return agent["element"]
        return None
    
    def refresh_agent_list(self) -> "AgentsPage":
        """刷新智能体列表"""
        logger.info("Refreshing agent list")
        refresh_btn = self.page.locator(self.REFRESH_BTN).first
        if refresh_btn.is_visible():
            refresh_btn.click()
            self.wait(1000)
        else:
            self.page.reload()
            self.wait_for_page_load()
        return self
    
    # ========== 创建智能体 ==========
    
    def click_create_agent(self) -> "AgentsPage":
        """点击创建智能体按钮"""
        logger.info("Clicking create agent button")
        create_btn = self.page.locator(self.CREATE_AGENT_BTN).first
        expect(create_btn).to_be_visible(timeout=5000)
        create_btn.click()
        self.wait(500)
        return self
    
    def fill_agent_form(self, name: str, description: str = "", language: str = "zh") -> "AgentsPage":
        """
        填写智能体表单
        
        Args:
            name: 智能体名称
            description: 智能体描述
            language: 语言（保留参数兼容性，实际表单无语言选择）
        """
        logger.info(f"Filling agent form: name={name}, description={description}")
        
        # 等待弹窗加载
        self.page.locator(self.FORM_DIALOG).first.wait_for(state="visible", timeout=5000)
        self.wait(500)
        
        # 填写名称
        name_input = self.page.locator(self.FORM_NAME_INPUT).first
        name_input.wait_for(state="visible", timeout=5000)
        name_input.fill(name)
        
        # 填写描述
        if description:
            desc_input = self.page.locator(self.FORM_DESC_INPUT).first
            if desc_input.is_visible():
                desc_input.fill(description)
        
        return self
    
    def submit_agent_form(self) -> "AgentsPage":
        """提交智能体表单"""
        logger.info("Submitting agent form")
        submit_btn = self.page.locator(self.FORM_SUBMIT_BTN).first
        expect(submit_btn).to_be_visible(timeout=5000)
        submit_btn.click()
        self.wait(1000)
        return self
    
    def cancel_agent_form(self) -> "AgentsPage":
        """取消智能体表单"""
        logger.info("Canceling agent form")
        cancel_btn = self.page.locator(self.FORM_CANCEL_BTN).first
        if cancel_btn.is_visible():
            cancel_btn.click()
            self.wait(500)
        return self
    
    def create_agent(self, name: str, description: str = "", language: str = "zh") -> "AgentsPage":
        """
        创建智能体（完整流程）
        
        Args:
            name: 智能体名称
            description: 智能体描述
            language: 语言
        """
        log_test_step(f"创建智能体：{name}")
        self.click_create_agent()
        self.fill_agent_form(name, description, language)
        self.submit_agent_form()
        return self
    
    # ========== 编辑智能体 ==========
    
    def click_edit_agent(self, agent_name: str) -> "AgentsPage":
        """
        点击编辑智能体
        
        Args:
            agent_name: 智能体名称
        """
        logger.info(f"Clicking edit for agent: {agent_name}")
        agent_row = self.find_agent_by_name(agent_name)
        if agent_row:
            actions_cell = agent_row.locator(self.AGENT_ACTIONS_CELL).first
            edit_btn = actions_cell.locator(self.EDIT_BTN).first
            edit_btn.click()
            self.wait(500)
        else:
            raise ValueError(f"Agent not found: {agent_name}")
        return self
    
    def update_agent(self, agent_name: str, new_name: str = None, new_description: str = None) -> "AgentsPage":
        """
        更新智能体信息
        
        Args:
            agent_name: 原智能体名称
            new_name: 新名称（可选）
            new_description: 新描述（可选）
        """
        log_test_step(f"更新智能体：{agent_name}")
        self.click_edit_agent(agent_name)
        
        if new_name:
            name_input = self.page.locator(self.FORM_NAME_INPUT).first
            name_input.fill(new_name)
        
        if new_description:
            desc_input = self.page.locator(self.FORM_DESC_INPUT).first
            desc_input.fill(new_description)
        
        self.submit_agent_form()
        return self
    
    # ========== 删除智能体 ==========
    
    def click_delete_agent(self, agent_name: str) -> "AgentsPage":
        """
        点击删除智能体
        
        Args:
            agent_name: 智能体名称
        """
        logger.info(f"Clicking delete for agent: {agent_name}")
        agent_row = self.find_agent_by_name(agent_name)
        if agent_row:
            actions_cell = agent_row.locator(self.AGENT_ACTIONS_CELL).first
            delete_btn = actions_cell.locator(self.DELETE_BTN).first
            delete_btn.click()
            self.wait(500)
        else:
            raise ValueError(f"Agent not found: {agent_name}")
        return self
    
    def confirm_delete(self) -> "AgentsPage":
        """确认删除（Popconfirm 气泡确认框）"""
        logger.info("Confirming delete")
        # 等待 Popconfirm 出现
        self.page.locator(self.DELETE_CONFIRM_DIALOG).first.wait_for(state="visible", timeout=5000)
        confirm_btn = self.page.locator(self.DELETE_CONFIRM_BTN).first
        confirm_btn.click()
        self.wait(1000)
        return self
    
    def cancel_delete(self) -> "AgentsPage":
        """取消删除（Popconfirm 气泡确认框）"""
        logger.info("Canceling delete")
        popconfirm = self.page.locator(self.DELETE_CONFIRM_DIALOG).first
        if popconfirm.is_visible():
            cancel_btn = self.page.locator(self.DELETE_CANCEL_BTN).first
            cancel_btn.click()
            self.wait(500)
        return self
    
    def delete_agent(self, agent_name: str) -> "AgentsPage":
        """
        删除智能体（完整流程）
        
        Args:
            agent_name: 智能体名称
        """
        log_test_step(f"删除智能体：{agent_name}")
        self.click_delete_agent(agent_name)
        self.confirm_delete()
        return self
    
    # ========== 启用/禁用智能体 ==========
    
    def toggle_agent_status(self, agent_name: str) -> "AgentsPage":
        """
        切换智能体启用状态（点击 Actions 列第二个按钮 + Popconfirm 确认）
        
        Args:
            agent_name: 智能体名称
        """
        logger.info(f"Toggling agent status: {agent_name}")
        agent_row = self.find_agent_by_name(agent_name)
        if agent_row:
            actions_cell = agent_row.locator(self.AGENT_ACTIONS_CELL).first
            toggle_btn = actions_cell.locator(self.TOGGLE_BTN).first
            toggle_btn.click()
            self.wait(500)
            # Toggle 操作会弹出 Popconfirm 确认框，需要点击 Confirm
            popconfirm = self.page.locator(self.DELETE_CONFIRM_DIALOG).first
            if popconfirm.is_visible():
                confirm_btn = self.page.locator(self.DELETE_CONFIRM_BTN).first
                confirm_btn.click()
                logger.info("Toggle popconfirm confirmed")
            self.wait(1000)
        else:
            raise ValueError(f"Agent not found: {agent_name}")
        return self
    
    def enable_agent(self, agent_name: str) -> "AgentsPage":
        """启用智能体"""
        log_test_step(f"启用智能体：{agent_name}")
        return self.toggle_agent_status(agent_name)
    
    def disable_agent(self, agent_name: str) -> "AgentsPage":
        """禁用智能体"""
        log_test_step(f"禁用智能体：{agent_name}")
        return self.toggle_agent_status(agent_name)
    
    def get_agent_status(self, agent_name: str) -> str:
        """
        获取智能体状态
        
        Args:
            agent_name: 智能体名称
            
        Returns:
            状态文本（如 "Disabled" 或空字符串表示启用）
        """
        agent_row = self.find_agent_by_name(agent_name)
        if agent_row:
            name_cell = agent_row.locator(self.AGENT_NAME_CELL).first
            status_tag = name_cell.locator(self.AGENT_STATUS).first
            if status_tag.is_visible():
                return status_tag.inner_text().strip()
        return ""
    
    def is_agent_enabled(self, agent_name: str) -> bool:
        """检查智能体是否已启用（无 Disabled 标签即为启用）"""
        status = self.get_agent_status(agent_name)
        return status == "" or "Enabled" in status or "active" in status.lower()
    
    # ========== 智能体文件管理 ==========
    
    def open_agent_files(self, agent_name: str) -> "AgentsPage":
        """
        打开智能体文件管理
        
        Args:
            agent_name: 智能体名称
        """
        logger.info(f"Opening agent files: {agent_name}")
        agent_item = self.find_agent_by_name(agent_name)
        if agent_item:
            agent_item.click()
            self.wait(1000)
        else:
            raise ValueError(f"Agent not found: {agent_name}")
        return self
    
    def get_agent_files(self) -> List[str]:
        """获取智能体文件列表"""
        logger.info("Getting agent files")
        file_items = self.page.locator(self.AGENT_FILE_ITEM).all()
        files = [item.inner_text().strip() for item in file_items]
        logger.info(f"Found {len(files)} files")
        return files
    
    # ========== 验证和断言 ==========
    
    def verify_agent_created(self, agent_name: str) -> bool:
        """验证智能体创建成功"""
        return self.is_agent_exists(agent_name)
    
    def verify_agent_deleted(self, agent_name: str) -> bool:
        """验证智能体删除成功"""
        return not self.is_agent_exists(agent_name)
    
    def verify_success_message(self, message_contains: str = "") -> bool:
        """验证成功消息"""
        try:
            msg = self.page.locator(self.SUCCESS_MESSAGE).first
            msg.wait_for(state="visible", timeout=3000)
            if message_contains:
                text = msg.inner_text()
                return message_contains in text
            return True
        except TimeoutError:
            return False
    
    def verify_error_message(self, message_contains: str = "") -> bool:
        """验证错误消息"""
        try:
            msg = self.page.locator(self.ERROR_MESSAGE).first
            msg.wait_for(state="visible", timeout=3000)
            if message_contains:
                text = msg.inner_text()
                return message_contains in text
            return True
        except TimeoutError:
            return False
    
    def verify_empty_state(self) -> bool:
        """验证空状态"""
        try:
            empty = self.page.locator(self.EMPTY_STATE).first
            return empty.is_visible()
        except Exception:
            return False
    
    # ========== API 辅助方法 ==========
    
    def api_get_agents(self, api_context) -> List[Dict]:
        """
        通过 API 获取智能体列表
        
        Args:
            api_context: API 请求上下文
            
        Returns:
            智能体列表
        """
        from utils.helpers import api_get
        response = api_get(api_context, "/api/agents")
        return response.get("agents", [])
    
    def api_create_agent(self, api_context, name: str, description: str = "", language: str = "zh") -> Dict:
        """
        通过 API 创建智能体
        
        Args:
            api_context: API 请求上下文
            name: 智能体名称
            description: 智能体描述
            language: 语言
            
        Returns:
            创建结果
        """
        from utils.helpers import api_post
        data = {
            "name": name,
            "description": description,
            "language": language
        }
        return api_post(api_context, "/api/agents", data)
    
    def api_delete_agent(self, api_context, agent_id: str) -> Dict:
        """
        通过 API 删除智能体
        
        Args:
            api_context: API 请求上下文
            agent_id: 智能体 ID
            
        Returns:
            删除结果
        """
        from utils.helpers import api_delete
        return api_delete(api_context, f"/api/agents/{agent_id}")
    
    def api_toggle_agent(self, api_context, agent_id: str, enabled: bool) -> Dict:
        """
        通过 API 切换智能体状态
        
        Args:
            api_context: API 请求上下文
            agent_id: 智能体 ID
            enabled: 是否启用
            
        Returns:
            切换结果
        """
        from utils.helpers import api_post
        return api_post(api_context, f"/api/agents/{agent_id}/toggle", {"enabled": enabled})
