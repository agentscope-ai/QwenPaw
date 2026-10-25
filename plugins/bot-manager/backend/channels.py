"""
Channel adapters — extensible registry for supported bot channels.

To add a new channel: sub-class ChannelAdapter, implement the required
methods, and call register_channel(). No other code changes needed.
"""

import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ── Registry ────────────────────────────────────────────

_CHANNEL_REGISTRY: Dict[str, "ChannelAdapter"] = {}


def register_channel(adapter: "ChannelAdapter") -> None:
    _CHANNEL_REGISTRY[adapter.channel_key] = adapter
    logger.info(f"[bot-manager] Registered channel: {adapter.channel_key}")


def get_channel(channel_key: str) -> Optional["ChannelAdapter"]:
    return _CHANNEL_REGISTRY.get(channel_key)


def list_channels() -> List[str]:
    return sorted(_CHANNEL_REGISTRY.keys())


# ── Base adapter ───────────────────────────────────────


class ChannelAdapter:
    """Base adapter — sub-class and override for each channel."""

    channel_key: str = ""
    display_name: str = ""
    binding_method: str = "manual"  # "manual" | "qrcode"
    credential_fields: List[str] = []  # fields wiped on "clear credentials"

    # ── core read/write ──

    def get_config(self, agent_config: Dict) -> Dict:
        """Extract this channel's config from agent.json."""
        return agent_config.get("channels", {}).get(self.channel_key, {})

    def update_config(self, agent_config: Dict, update: Dict) -> Dict:
        """Merge *update* into this channel's config inside agent.json."""
        if "channels" not in agent_config:
            agent_config["channels"] = {}
        ch = agent_config["channels"].setdefault(self.channel_key, {})
        for k, v in update.items():
            ch[k] = v
        return agent_config

    # ── credentials ──

    def has_credentials(self, config: Dict) -> bool:
        """Whether the agent has valid credentials for this channel."""
        raise NotImplementedError

    def clear_credentials(self, agent_config: Dict) -> Dict:
        """Wipe credential fields."""
        wipe = {f: "" for f in self.credential_fields}
        return self.update_config(agent_config, wipe)

    # ── status ──

    def get_status_fields(self, config: Dict) -> Dict:
        """Extra fields returned in ``GET /agents`` for the table."""
        return {}

    def get_status(self, agents_config: List[Dict]) -> Dict:
        """Aggregate stats across all agents."""
        total = len(agents_config)
        enabled = 0
        with_creds = 0
        for cfg in agents_config:
            ch = self.get_config(cfg)
            if ch.get("enabled"):
                enabled += 1
            if self.has_credentials(ch):
                with_creds += 1
        return {
            "channel": self.channel_key,
            "total_agents": total,
            "enabled_agents": enabled,
            "agents_with_credentials": with_creds,
        }


# ── Built-in adapters ──────────────────────────────────


class WechatChannel(ChannelAdapter):
    channel_key = "wechat"
    display_name = "微信"
    binding_method = "qrcode"
    credential_fields = ["bot_token"]

    def has_credentials(self, config: Dict) -> bool:
        return bool(config.get("bot_token"))

    def get_status_fields(self, config: Dict) -> Dict:
        return {
            "bot_prefix": config.get("bot_prefix", ""),
            "dm_policy": config.get("dm_policy", "open"),
            "group_policy": config.get("group_policy", "open"),
            "has_native_config": bool(config),
        }


class DingtalkChannel(ChannelAdapter):
    channel_key = "dingtalk"
    display_name = "钉钉"
    binding_method = "manual"
    credential_fields = ["client_id", "client_secret", "robot_code"]

    def has_credentials(self, config: Dict) -> bool:
        return bool(config.get("client_id") and config.get("client_secret"))

    def get_status_fields(self, config: Dict) -> Dict:
        return {
            "message_type": config.get("message_type", "markdown"),
            "bot_prefix": config.get("bot_prefix", ""),
            "streaming_enabled": config.get("streaming_enabled", False),
            "share_session_in_group": config.get("share_session_in_group", False),
            "at_sender_on_reply": config.get("at_sender_on_reply", False),
            "robot_code": config.get("robot_code", ""),
        }


# ── Register built-in channels ─────────────────────────

register_channel(WechatChannel())
register_channel(DingtalkChannel())