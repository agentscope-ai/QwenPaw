"""配置模式。外部桥默认关闭。"""

from __future__ import annotations

from dataclasses import dataclass


CONFIG_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class ExternalSmsBridge:
    """外部 SMS DB 桥。默认关闭。"""

    enabled: bool = False


@dataclass(frozen=True)
class AppConfig:
    """应用配置。"""

    schema_version: str = CONFIG_SCHEMA_VERSION
    external_sms_bridge: ExternalSmsBridge = ExternalSmsBridge()
    auth_required: bool = True


def default_config() -> AppConfig:
    """返回冻结默认配置。"""
    return AppConfig()


__all__ = [
    "AppConfig",
    "CONFIG_SCHEMA_VERSION",
    "ExternalSmsBridge",
    "default_config",
]
