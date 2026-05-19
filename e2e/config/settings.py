# -*- coding: utf-8 -*-
"""
QwenPaw E2E 测试框架配置模块

提供统一的配置管理，支持环境变量覆盖。
"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BrowserConfig:
    """浏览器配置"""
    browser_type: str = "chromium"  # chromium, firefox, webkit
    headless: bool = True
    viewport_width: int = 1920
    viewport_height: int = 1080
    slow_mo: int = 0  # 慢动作模式（毫秒），调试时使用
    timeout: int = 30000  # 默认超时（毫秒）
    args: list = field(default_factory=lambda: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        # 禁用 Chrome 翻译弹窗（被测系统 UI 是英文，Chrome 检测到
        # locale 不匹配会弹"是否翻译此页面"，遮挡元素 / 劫持焦点）
        "--disable-features=TranslateUI",
        "--disable-translate",
        # 禁用其他可能的干扰弹窗
        "--disable-notifications",
        "--disable-popup-blocking",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
    ])


@dataclass
class ServerConfig:
    """服务器配置"""
    base_url: str = "http://localhost:8088"
    api_base_url: str = ""  # 留空则使用 base_url + /api
    api_key: str = ""       # 集成测试用 API Key
    model_key: str = ""     # Model 连接测试用 Key
    timeout: int = 30000
    retry_count: int = 3
    retry_delay: float = 1.0


@dataclass
class TestConfig:
    """测试配置"""
    user_id: str = "default"
    channel: str = "console"
    screenshot_on_fail: bool = True
    video_on_fail: bool = False
    log_level: str = "INFO"
    parallel_workers: int = 1


@dataclass
class PathConfig:
    """路径配置"""
    base_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    tests_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    data_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data")
    reports_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "reports")
    screenshots_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "reports" / "screenshots")
    videos_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "reports" / "videos")
    logs_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "reports" / "logs")
    allure_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "reports" / "allure-results")


class Config:
    """
    统一配置管理类
    
    使用单例模式，支持环境变量覆盖。
    
    环境变量列表：
    - QWENPAW_BASE_URL: 服务器地址
    - QWENPAW_HEADLESS: 是否无头模式 (true/false)
    - QWENPAW_TIMEOUT: 超时时间（毫秒）
    - QWENPAW_USER_ID: 用户 ID
    - QWENPAW_CHANNEL: 频道名称
    - PLAYWRIGHT_SLOW_MO: 慢动作时间（毫秒）
    """
    
    _instance: Optional["Config"] = None
    
    def __new__(cls) -> "Config":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.browser = BrowserConfig()
        self.server = ServerConfig()
        self.test = TestConfig()
        self.paths = PathConfig()
        
        self._load_from_env()
        self._ensure_directories()
        self._initialized = True
    
    def _load_from_env(self):
        """从环境变量加载配置"""
        # 服务器配置
        if os.getenv("QWENPAW_BASE_URL"):
            self.server.base_url = os.getenv("QWENPAW_BASE_URL")
        
        # 浏览器配置
        headless_env = os.getenv("QWENPAW_HEADLESS", "true").lower()
        self.browser.headless = headless_env in ("true", "1", "yes")
        
        if os.getenv("QWENPAW_TIMEOUT"):
            try:
                timeout = int(os.getenv("QWENPAW_TIMEOUT"))
                self.browser.timeout = timeout
                self.server.timeout = timeout
            except ValueError:
                import warnings
                warnings.warn(f"QWENPAW_TIMEOUT 值无效: '{os.getenv('QWENPAW_TIMEOUT')}'，使用默认值")
        
        if os.getenv("PLAYWRIGHT_SLOW_MO"):
            self.browser.slow_mo = int(os.getenv("PLAYWRIGHT_SLOW_MO"))
        
        # 测试配置
        if os.getenv("QWENPAW_USER_ID"):
            self.test.user_id = os.getenv("QWENPAW_USER_ID")
        
        if os.getenv("QWENPAW_CHANNEL"):
            self.test.channel = os.getenv("QWENPAW_CHANNEL")

        # API Key 配置
        if os.getenv("QWENPAW_API_KEY"):
            self.server.api_key = os.getenv("QWENPAW_API_KEY")

        if os.getenv("QWENPAW_MODEL_KEY"):
            self.server.model_key = os.getenv("QWENPAW_MODEL_KEY")

        # 设置 API 基础 URL
        if not self.server.api_base_url:
            self.server.api_base_url = f"{self.server.base_url}/api"
    
    def _ensure_directories(self):
        """确保所有需要的目录存在"""
        for dir_path in [
            self.paths.reports_dir,
            self.paths.screenshots_dir,
            self.paths.videos_dir,
            self.paths.logs_dir,
            self.paths.allure_dir,
            self.paths.data_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    @property
    def base_url(self) -> str:
        return self.server.base_url
    
    @property
    def api_url(self) -> str:
        return self.server.api_base_url


# 全局配置实例
config = Config()


def get_config() -> Config:
    """获取配置实例"""
    return config
