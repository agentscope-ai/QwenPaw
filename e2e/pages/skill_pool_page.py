# -*- coding: utf-8 -*-
"""
QwenPaw Skill Pool 页面对象

封装技能池页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List
from playwright.sync_api import Page, Locator

from pages.base_page import BasePage
from config.settings import config

logger = logging.getLogger(__name__)


class SkillPoolPage(BasePage):
    """
    Skill Pool 页面对象
    
    封装技能池页面的所有用户操作：
    - 页面导航
    - 获取技能卡片
    - 搜索技能
    - 上传和安装技能
    """
    
    PAGE_TITLE = "Skill Pool"
    PAGE_URL = f"{config.base_url}/skill-pool"
    
    # ========== 选择器定义 ==========
    
    # 技能卡片
    SKILL_CARD = ".qwenpaw-card"
    
    # 搜索输入框
    SEARCH_INPUT = 'input[placeholder*="搜索"], input[placeholder*="Search"]'
    
    # 上传按钮
    UPLOAD_BTN = 'button:has-text("上传"), button:has-text("Upload")'
    
    # 安装按钮
    INSTALL_BTN = 'button:has-text("安装"), button:has-text("Install")'
    
    # ========== 初始化 ==========
    
    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("SkillPoolPage initialized")
    
    # ========== 页面导航 ==========
    
    def open(self) -> "SkillPoolPage":
        """打开 Skill Pool 页面"""
        logger.info("Opening Skill Pool page")
        self.goto()
        self.wait_for_loading()
        return self
    
    def wait_for_page_loaded(self) -> bool:
        """
        等待页面加载完成
        
        Returns:
            是否加载成功
        """
        try:
            self.wait_for_element(self.SKILL_CARD, timeout=10000)
            return True
        except Exception as e:
            logger.error(f"Page load failed: {e}")
            return False
    
    # ========== 技能卡片操作 ==========
    
    def get_skill_cards(self) -> List[Locator]:
        """
        获取所有技能卡片
        
        Returns:
            Locator 列表
        """
        logger.info("Getting skill cards")
        return self.find_all(self.SKILL_CARD)
    
    def get_skill_name(self, card: Locator) -> str:
        """
        从技能卡片中获取技能名称
        
        Args:
            card: 技能卡片 Locator
            
        Returns:
            技能名称
        """
        logger.info("Getting skill name from card")
        try:
            # 尝试获取卡片的标题或文本内容
            return card.inner_text().strip().split('\n')[0]
        except Exception as e:
            logger.warning(f"Failed to get skill name: {e}")
            return ""
    
    # ========== 搜索功能 ==========
    
    def search_skills(self, keyword: str) -> "SkillPoolPage":
        """
        搜索技能
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            self
        """
        logger.info(f"Searching skills with keyword: {keyword}")
        search_input = self.find(self.SEARCH_INPUT)
        search_input.fill(keyword)
        self.wait(500)
        return self
    
    # ========== 上传和安装 ==========
    
    def click_upload(self) -> "SkillPoolPage":
        """
        点击上传按钮
        
        Returns:
            self
        """
        logger.info("Clicking upload button")
        upload_btn = self.find(self.UPLOAD_BTN)
        upload_btn.click()
        self.wait(500)
        return self
    
    def click_install(self, card: Locator) -> "SkillPoolPage":
        """
        点击指定技能卡片的安装按钮
        
        Args:
            card: 技能卡片 Locator
            
        Returns:
            self
        """
        logger.info("Clicking install button on skill card")
        # 在卡片范围内查找安装按钮
        install_btn = card.locator(self.INSTALL_BTN).first
        if install_btn.count() > 0:
            install_btn.click()
            self.wait(500)
        else:
            logger.warning("Install button not found in card")
        return self
