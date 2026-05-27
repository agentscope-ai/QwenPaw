# -*- coding: utf-8 -*-
"""
QwenPaw E2E test framework - Pages module.

Exports all page object classes.
"""
from pages.base_page import BasePage
from pages.chat_page import ChatPage
from pages.channels_page import ChannelsPage
from pages.sessions_page import SessionsPage
from pages.cronjobs_page import CronJobsPage
from pages.heartbeat_page import HeartbeatPage
from pages.agents_page import AgentsPage
from pages.files_page import FilesPage
from pages.skills_page import SkillsPage
from pages.models_page import ModelsPage
from pages.mcp_page import McpPage
from pages.voice_page import VoicePage
from pages.security_page import SecurityPage
from pages.runtime_config_page import RuntimeConfigPage
from pages.tools_page import ToolsPage
from pages.environments_page import EnvironmentsPage
from pages.token_usage_page import TokenUsagePage
from pages.skill_pool_page import SkillPoolPage

__all__ = [
    "BasePage",
    "ChatPage",
    "ChannelsPage",
    "SessionsPage",
    "CronJobsPage",
    "HeartbeatPage",
    "AgentsPage",
    "FilesPage",
    "SkillsPage",
    "ModelsPage",
    "McpPage",
    "VoicePage",
    "SecurityPage",
    "RuntimeConfigPage",
    "ToolsPage",
    "EnvironmentsPage",
    "TokenUsagePage",
    "SkillPoolPage",
]