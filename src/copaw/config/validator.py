# -*- coding: utf-8 -*-
"""Configuration validation for CoPaw."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .config import Config, ChannelConfig, MCPClientConfig

logger = logging.getLogger(__name__)


class ValidationLevel(str, Enum):
    """Validation severity levels."""
    ERROR = "error"      # Blocks execution
    WARNING = "warning"  # May cause issues
    INFO = "info"        # Informational


@dataclass
class ValidationIssue:
    """Single validation issue."""
    level: ValidationLevel
    path: str  # Config path like "channels.dingtalk.client_id"
    message: str
    suggestion: str  # Fix suggestion
    code: str  # Error code like "CHANNEL_MISSING_CREDENTIALS"


@dataclass
class ValidationResult:
    """Validation result container."""
    valid: bool
    issues: list[ValidationIssue]

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == ValidationLevel.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == ValidationLevel.WARNING]

    @property
    def infos(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == ValidationLevel.INFO]


class ConfigValidator:
    """Validates config.json structure and semantics."""

    def __init__(self, config: Optional[Config] = None):
        from .utils import load_config
        self.config = config or load_config()
        self.issues: list[ValidationIssue] = []

    def validate_all(self) -> ValidationResult:
        """Run all validation checks."""
        self.issues = []

        self._validate_channels()
        self._validate_mcp()
        self._validate_agents()
        self._validate_heartbeat()

        has_errors = any(i.level == ValidationLevel.ERROR for i in self.issues)
        return ValidationResult(valid=not has_errors, issues=self.issues)

    def _add_issue(
        self,
        level: ValidationLevel,
        path: str,
        message: str,
        suggestion: str,
        code: str,
    ) -> None:
        self.issues.append(
            ValidationIssue(
                level=level,
                path=path,
                message=message,
                suggestion=suggestion,
                code=code,
            )
        )

    # --- Channel Validation ---

    def _validate_channels(self) -> None:
        """Validate all channel configurations."""
        channels = self.config.channels

        # Check if at least one channel is enabled
        enabled_channels = self._get_enabled_channels(channels)
        if not enabled_channels:
            self._add_issue(
                ValidationLevel.WARNING,
                "channels",
                "No channels are enabled",
                "Enable at least one channel (console, dingtalk, feishu, etc.) "
                "in config.json or run 'copaw init' to configure channels.",
                "NO_CHANNELS_ENABLED",
            )

        # Validate individual channels
        if channels.dingtalk.enabled:
            self._validate_dingtalk(channels.dingtalk)
        if channels.feishu.enabled:
            self._validate_feishu(channels.feishu)
        if channels.qq.enabled:
            self._validate_qq(channels.qq)
        if channels.discord.enabled:
            self._validate_discord(channels.discord)
        if channels.telegram.enabled:
            self._validate_telegram(channels.telegram)

    def _get_enabled_channels(self, channels: ChannelConfig) -> list[str]:
        """Get list of enabled channel names."""
        enabled = []
        for name in ["console", "dingtalk", "feishu", "qq", "discord",
                     "telegram", "imessage"]:
            channel = getattr(channels, name, None)
            if channel and getattr(channel, "enabled", False):
                enabled.append(name)
        return enabled

    def _validate_dingtalk(self, config) -> None:
        """Validate DingTalk channel configuration."""
        if not config.client_id or not config.client_secret:
            self._add_issue(
                ValidationLevel.ERROR,
                "channels.dingtalk",
                "DingTalk is enabled but missing credentials",
                "Set 'client_id' and 'client_secret' in config.json under "
                "channels.dingtalk, or run 'copaw channels config'.",
                "DINGTALK_MISSING_CREDENTIALS",
            )

    def _validate_feishu(self, config) -> None:
        """Validate Feishu channel configuration."""
        if not config.app_id or not config.app_secret:
            self._add_issue(
                ValidationLevel.ERROR,
                "channels.feishu",
                "Feishu is enabled but missing credentials",
                "Set 'app_id' and 'app_secret' in config.json under "
                "channels.feishu, or run 'copaw channels config'.",
                "FEISHU_MISSING_CREDENTIALS",
            )

    def _validate_qq(self, config) -> None:
        """Validate QQ channel configuration."""
        if not config.app_id or not config.client_secret:
            self._add_issue(
                ValidationLevel.ERROR,
                "channels.qq",
                "QQ is enabled but missing credentials",
                "Set 'app_id' and 'client_secret' in config.json under "
                "channels.qq, or run 'copaw channels config'.",
                "QQ_MISSING_CREDENTIALS",
            )

    def _validate_discord(self, config) -> None:
        """Validate Discord channel configuration."""
        if not config.bot_token:
            self._add_issue(
                ValidationLevel.ERROR,
                "channels.discord",
                "Discord is enabled but missing bot_token",
                "Set 'bot_token' in config.json under channels.discord, "
                "or run 'copaw channels config'.",
                "DISCORD_MISSING_TOKEN",
            )

    def _validate_telegram(self, config) -> None:
        """Validate Telegram channel configuration."""
        if not config.bot_token:
            self._add_issue(
                ValidationLevel.ERROR,
                "channels.telegram",
                "Telegram is enabled but missing bot_token",
                "Set 'bot_token' in config.json under channels.telegram, "
                "or run 'copaw channels config'.",
                "TELEGRAM_MISSING_TOKEN",
            )

    # --- MCP Validation ---

    def _validate_mcp(self) -> None:
        """Validate MCP client configurations."""
        for client_id, client in self.config.mcp.clients.items():
            if not client.enabled:
                continue

            self._validate_mcp_client(client_id, client)

    def _validate_mcp_client(self, client_id: str, client: MCPClientConfig) -> None:
        """Validate single MCP client."""
        path_prefix = f"mcp.clients.{client_id}"

        # Transport-specific validation
        if client.transport == "stdio":
            if not client.command:
                self._add_issue(
                    ValidationLevel.ERROR,
                    f"{path_prefix}.command",
                    f"MCP client '{client_id}' uses stdio but command is empty",
                    "Set 'command' field for stdio transport.",
                    "MCP_STDIO_NO_COMMAND",
                )
        else:  # streamable_http or sse
            if not client.url:
                self._add_issue(
                    ValidationLevel.ERROR,
                    f"{path_prefix}.url",
                    f"MCP client '{client_id}' uses {client.transport} but url is empty",
                    "Set 'url' field for HTTP-based transport.",
                    "MCP_HTTP_NO_URL",
                )

    # --- Agents Validation ---

    def _validate_agents(self) -> None:
        """Validate agents configuration."""
        agents = self.config.agents

        # Validate max_iters
        if agents.running.max_iters < 1:
            self._add_issue(
                ValidationLevel.ERROR,
                "agents.running.max_iters",
                f"max_iters must be >= 1, got {agents.running.max_iters}",
                "Set agents.running.max_iters to a positive integer (default: 50).",
                "AGENTS_INVALID_MAX_ITERS",
            )

        # Validate max_input_length
        if agents.running.max_input_length < 1000:
            self._add_issue(
                ValidationLevel.WARNING,
                "agents.running.max_input_length",
                f"max_input_length is very small: {agents.running.max_input_length}",
                "Consider increasing to at least 4096 tokens for better context.",
                "AGENTS_SMALL_INPUT_LENGTH",
            )

    # --- Heartbeat Validation ---

    def _validate_heartbeat(self) -> None:
        """Validate heartbeat configuration."""
        hb = self.config.agents.defaults.heartbeat
        if not hb or not hb.enabled:
            return

        # Validate every format
        if not self._is_valid_interval(hb.every):
            self._add_issue(
                ValidationLevel.ERROR,
                "agents.defaults.heartbeat.every",
                f"Invalid interval format: {hb.every}",
                "Use format like '30m', '1h', '2h30m'.",
                "HEARTBEAT_INVALID_INTERVAL",
            )

    @staticmethod
    def _is_valid_interval(interval: str) -> bool:
        """Check if interval string is valid (e.g., '30m', '1h')."""
        pattern = r"^\d+[smhd](\d+[smhd])*$"
        return bool(re.match(pattern, interval))
