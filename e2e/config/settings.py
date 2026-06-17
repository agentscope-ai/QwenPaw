# -*- coding: utf-8 -*-
"""
QwenPaw E2E Test Framework Configuration Module

Provides unified configuration management with environment variable overrides.
"""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BrowserConfig:
    """Browser configuration"""
    browser_type: str = "chromium"  # chromium, firefox, webkit
    headless: bool = True
    viewport_width: int = 1920
    viewport_height: int = 1080
    slow_mo: int = 0  # Slow motion mode (milliseconds), used for debugging
    timeout: int = 30000  # Default timeout (milliseconds)
    args: list = field(default_factory=lambda: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        # Disable Chrome translation popup (the system under test has English UI;
        # if Chrome detects a locale mismatch it pops up "Translate this page?",
        # which obscures elements / hijacks focus)
        "--disable-features=TranslateUI",
        "--disable-translate",
        # Disable other potentially interfering popups
        "--disable-notifications",
        "--disable-popup-blocking",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
    ])


@dataclass
class ServerConfig:
    """Server configuration"""
    base_url: str = "http://localhost:8088"
    api_base_url: str = ""  # Leave empty to use base_url + /api

    model_key: str = ""     # Key for Model connection tests
    timeout: int = 30000
    retry_count: int = 3
    retry_delay: float = 1.0


@dataclass
class TestConfig:
    """Test configuration"""
    user_id: str = "default"
    channel: str = "console"
    screenshot_on_fail: bool = True
    video_on_fail: bool = False
    log_level: str = "INFO"
    parallel_workers: int = 1


@dataclass
class PathConfig:
    """Path configuration"""
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
    Unified configuration manager.

    Uses the singleton pattern and supports environment variable overrides.

    Environment variables:
    - QWENPAW_BASE_URL: Server URL
    - QWENPAW_HEADLESS: Headless mode (true/false)
    - QWENPAW_TIMEOUT: Timeout (milliseconds)
    - QWENPAW_USER_ID: User ID
    - QWENPAW_CHANNEL: Channel name
    - PLAYWRIGHT_SLOW_MO: Slow motion delay (milliseconds)
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
        """Load configuration from environment variables"""
        # Server configuration
        if os.getenv("QWENPAW_BASE_URL"):
            self.server.base_url = os.getenv("QWENPAW_BASE_URL")

        # Browser configuration
        headless_env = os.getenv("QWENPAW_HEADLESS", "true").lower()
        self.browser.headless = headless_env in ("true", "1", "yes")

        if os.getenv("QWENPAW_TIMEOUT"):
            try:
                timeout = int(os.getenv("QWENPAW_TIMEOUT"))
                self.browser.timeout = timeout
                self.server.timeout = timeout
            except ValueError:
                import warnings
                warnings.warn(f"Invalid QWENPAW_TIMEOUT value: '{os.getenv('QWENPAW_TIMEOUT')}', using default")

        if os.getenv("PLAYWRIGHT_SLOW_MO"):
            self.browser.slow_mo = int(os.getenv("PLAYWRIGHT_SLOW_MO"))

        # Test configuration
        if os.getenv("QWENPAW_USER_ID"):
            self.test.user_id = os.getenv("QWENPAW_USER_ID")

        if os.getenv("QWENPAW_CHANNEL"):
            self.test.channel = os.getenv("QWENPAW_CHANNEL")

        if os.getenv("QWENPAW_DASHSCOPE_API_KEY"):
            self.server.model_key = os.getenv("QWENPAW_DASHSCOPE_API_KEY")

        # Set API base URL
        if not self.server.api_base_url:
            self.server.api_base_url = f"{self.server.base_url}/api"

    def _ensure_directories(self):
        """Ensure all required directories exist"""
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


# Global configuration instance
config = Config()


def get_config() -> Config:
    """Get the configuration instance"""
    return config
