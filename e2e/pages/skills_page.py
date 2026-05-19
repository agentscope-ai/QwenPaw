# -*- coding: utf-8 -*-
"""
QwenPaw Skills 页面对象

封装 Skills 页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class SkillsPage(BasePage):
    """
    Skills 页面对象
    
    封装 Skills 页面的所有用户操作：
    - 打开技能页面
    - 获取技能卡片列表
    - 获取技能名称
    - 切换技能开关
    - 检查技能启用状态
    - 搜索技能
    """
    
    PAGE_TITLE = "QwenPaw Console"
    SKILLS_URL = f"{config.base_url}/skills"
    PAGE_URL = SKILLS_URL
    
    # ========== 选择器定义 ==========
    
    # 页面加载标志
    SKILL_PAGE_CONTAINER = "div[class*=skillsPage]"
    PAGE_LOAD_INDICATOR = SKILL_PAGE_CONTAINER
    
    # 技能卡片相关选择器
    SKILL_CARD_SELECTOR = ".qwenpaw-card"
    SWITCH_SELECTOR = '.qwenpaw-switch'
    
    # 搜索框
    SEARCH_INPUT = 'input[placeholder*="搜索"], input[placeholder*="Search"], .ant-input-search input, .qwenpaw-input-search input'
    
    # ========== 导航方法 ==========
    
    def open(self) -> "SkillsPage":
        """打开 Skills 页面"""
        logger.info("打开 Skills 页面")
        self.goto()
        self.wait_for_page_loaded()
        return self
    
    def wait_for_page_loaded(self, timeout: Optional[int] = None) -> "SkillsPage":
        """等待页面加载完成"""
        timeout = timeout or self.timeout
        expect(self.page.locator(self.PAGE_LOAD_INDICATOR).first).to_be_visible(timeout=timeout)
        return self
    
    # ========== 技能列表操作方法 ==========
    
    def get_skill_cards(self) -> List[Locator]:
        """获取所有技能卡片"""
        cards = self.page.locator(self.SKILL_CARD_SELECTOR).all()
        logger.info(f"找到 {len(cards)} 个技能卡片")
        return cards
    
    def get_skill_name(self, card: Locator) -> str:
        """获取技能名称"""
        # 尝试从卡片标题中获取技能名称
        title_element = card.locator('.ant-card-meta-title, .qwenpaw-card-meta-title, h3, h4, [class*="title"]').first
        if title_element.count() > 0:
            return title_element.inner_text()
        
        # 如果找不到标题，返回卡片的文本内容
        return card.inner_text().strip()[:50]
    
    def toggle_skill(self, card: Locator) -> "SkillsPage":
        """切换技能开关"""
        switch = card.locator(self.SWITCH_SELECTOR).first
        if switch.count() > 0:
            switch.click()
            logger.info("切换技能开关")
        return self
    
    def is_skill_enabled(self, card: Locator) -> bool:
        """检查技能是否启用"""
        switch = card.locator(self.SWITCH_SELECTOR).first
        if switch.count() > 0:
            return switch.evaluate(
                "el => el.classList.contains('qwenpaw-switch-checked') || "
                "el.classList.contains('ant-switch-checked') || "
                "el.getAttribute('aria-checked') === 'true'"
            )
        return False
    
    def search_skills(self, keyword: str) -> "SkillsPage":
        """搜索技能"""
        search_input = self.page.locator(self.SEARCH_INPUT).first
        if search_input.count() > 0:
            search_input.fill(keyword)
            logger.info(f"搜索技能: {keyword}")
            # 等待搜索结果加载
            self.page.wait_for_timeout(500)
        return self
    
    # ========== 断言方法 ==========
    
    def assert_skill_count(self, expected_count: int, timeout: Optional[int] = None) -> "SkillsPage":
        """断言技能卡片数量"""
        expect(self.page.locator(self.SKILL_CARD_SELECTOR)).to_have_count(
            expected_count, timeout=timeout or self.timeout
        )
        return self
    
    def assert_skill_exists(self, skill_name: str, timeout: Optional[int] = None) -> "SkillsPage":
        """断言技能存在"""
        skill_card = self.page.locator(self.SKILL_CARD_SELECTOR).filter(
            has_text=skill_name
        ).first
        expect(skill_card).to_be_visible(timeout=timeout or self.timeout)
        return self
