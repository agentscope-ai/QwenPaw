# -*- coding: utf-8 -*-
"""Meeting module data models - Types."""

from enum import Enum


class MeetingType(str, Enum):
    """会议类型枚举."""

    REGULAR = "REGULAR"  # 例会：周期性召开，固定议题
    TEMPORARY = "TEMPORARY"  # 临时会议：一次性，针对特定议题


class RoleType(str, Enum):
    """角色类型枚举."""

    HOST = "HOST"  # 主持人
    REPORTER = "REPORTER"  # 汇报人
    DECIDER = "DECIDER"  # 决策人


class MeetingStatus(str, Enum):
    """会议状态枚举."""

    CREATED = "CREATED"  # 已创建
    INITIALIZED = "INITIALIZED"  # 已初始化（配置已解析，文档路径已生成）
    RUNNING = "RUNNING"  # 进行中
    COMPLETED = "COMPLETED"  # 已完成
    STOPPED = "STOPPED"  # 已停止
    FAILED = "FAILED"  # 失败


class PhaseType(str, Enum):
    """会议阶段枚举."""

    BACKGROUND = "BACKGROUND"  # 生成背景
    OPENING = "OPENING"  # 开场
    ROUND = "ROUND"  # 轮次发言 (动态轮次)
    DECISION = "DECISION"  # 决策阶段
    SUMMARY = "SUMMARY"  # 生成纪要
