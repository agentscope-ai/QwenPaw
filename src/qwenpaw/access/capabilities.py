# -*- coding: utf-8 -*-
"""平台级 capability 的最小稳定集合。"""

from enum import StrEnum


class Capability(StrEnum):
    """平台与 Agent 入口使用的稳定能力集合。"""

    PLATFORM_USE = "platform.use"
    AGENT_USE = "agent.use"
    USERS_MANAGE = "users.manage"
    PLATFORM_SETTINGS_MANAGE = "platform.settings.manage"
    MODELS_MANAGE = "models.manage"
    SKILLS_MANAGE = "skills.manage"
    PLUGINS_MANAGE = "plugins.manage"
    PUBLICATIONS_REVIEW = "publications.review"
