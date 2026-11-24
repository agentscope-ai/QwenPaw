# -*- coding: utf-8 -*-
"""SDK-free compatibility for historical official from_config inputs.

HTTP configuration APIs still validate their schema before invoking factories.
Environment readers deliberately do not apply these input conversions.
"""

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path


def absolute_execution_paths(
    values: Mapping,
    *,
    path_fields: tuple[str, ...],
    working_dir: Path,
) -> dict:
    """Detach path fields, preserving symlinks and lexical ``..``."""
    result = deepcopy(dict(values))
    for key in path_fields:
        if result.get(key):
            path = Path(result[key]).expanduser()
            result[key] = str(
                path if path.is_absolute() else working_dir / path,
            )
    return result


def normalize_channel_config(
    channel_key: str,
    config: Mapping,
    *,
    dictionary: bool = True,
) -> dict:
    """Read legacy config input into a detached, schema-valid value mapping."""
    values = deepcopy(dict(config))
    if channel_key == "telegram":
        for key in (
            "bot_token",
            "base_url",
            "http_proxy",
            "http_proxy_auth",
            "bot_prefix",
        ):
            values[key] = (values.get(key) or "").strip()
        values["base_url"] = values["base_url"].rstrip("/")
        if values.get("show_typing") is None:
            values["show_typing"] = True
        for key, default in (
            ("enabled", False),
            ("streaming_enabled", False),
            ("access_control_dm", False),
            ("access_control_group", False),
            ("require_mention", False),
        ):
            values[key] = bool(values.get(key, default))
        for key in ("dm_policy", "group_policy"):
            values[key] = values.get(key) or "open"
        values["allow_from"] = values.get("allow_from") or []
        values["deny_message"] = values.get("deny_message") or ""
    elif channel_key == "slack":
        values["allow_from"] = values.get("allow_from") or []
        for key in ("bot_token", "app_token", "bot_prefix", "deny_message"):
            values[key] = values.get(key) or ""
        for key in ("dm_policy", "group_policy"):
            values[key] = values.get(key) or "open"
        for key in ("access_control_dm", "access_control_group"):
            values[key] = bool(values.get(key, False))
    elif channel_key == "discord":
        if values.get("http_proxy") is None:
            values["http_proxy"] = ""
        for key in (
            "bot_token",
            "http_proxy_auth",
            "bot_prefix",
            "deny_message",
        ):
            values[key] = values.get(key) or ""
        for key in ("dm_policy", "group_policy"):
            values[key] = values.get(key) or "open"
        values["allow_from"] = values.get("allow_from") or []
        if not isinstance(values.get("media_dir"), str):
            values["media_dir"] = ""
        for key in ("access_control_dm", "access_control_group"):
            values[key] = bool(values.get(key, False))
    elif channel_key == "mqtt":
        values["enabled"] = bool(values.get("enabled", False))
        if dictionary:
            for key, default, fallback in (
                ("port", 1883, 1883),
                ("qos", 2, 0),
            ):
                raw = values.get(key, default)
                values[key] = (
                    int(raw)
                    if isinstance(raw, (str, int)) and str(raw).isdigit()
                    else fallback
                )
            for key in (
                "host",
                "username",
                "password",
                "subscribe_topic",
                "publish_topic",
                "bot_prefix",
            ):
                values[key] = (values.get(key) or "").strip()
            values.setdefault("transport", "tcp")
            for key, default in (
                ("clean_session", True),
                ("tls_enabled", False),
                ("access_control_dm", False),
                ("access_control_group", False),
            ):
                values[key] = bool(values.get(key, default))
        else:
            values["port"] = (
                int(values["port"]) if values.get("port") else 1883
            )
            for key in (
                "host",
                "username",
                "password",
                "subscribe_topic",
                "publish_topic",
                "bot_prefix",
            ):
                values[key] = values.get(key) or ""
    elif channel_key == "mattermost":
        values["enabled"] = bool(values.get("enabled", False))
        for key in ("url", "bot_token", "bot_prefix", "media_dir"):
            values[key] = (values.get(key) or "").strip()
        values["url"] = values["url"].rstrip("/")
        for key in ("dm_policy", "group_policy"):
            values[key] = values.get(key) or "open"
        values["allow_from"] = values.get("allow_from") or []
        values["deny_message"] = values.get("deny_message") or ""
        for key in (
            "thread_follow_without_mention",
            "access_control_dm",
            "access_control_group",
        ):
            values[key] = bool(values.get(key, False))
        if not values["url"] or not values["bot_token"]:
            values["enabled"] = False
    elif channel_key == "wecom":
        for key in (
            "bot_id",
            "secret",
            "bot_prefix",
            "media_dir",
            "welcome_text",
            "deny_message",
            "ws_url",
        ):
            values[key] = values.get(key) or ""
        for key in ("dm_policy", "group_policy"):
            values[key] = values.get(key) or "open"
        values["allow_from"] = values.get("allow_from") or []
        for key, default in (
            ("share_session_in_group", True),
            ("streaming_enabled", False),
            ("access_control_dm", False),
            ("access_control_group", False),
        ):
            values[key] = bool(values.get(key, default))
        reconnect = values.get("max_reconnect_attempts")
        values["max_reconnect_attempts"] = (
            -1 if reconnect is None else int(reconnect)
        )
    elif channel_key == "wechat":
        for key in (
            "bot_token",
            "bot_token_file",
            "base_url",
            "bot_prefix",
            "media_dir",
            "deny_message",
        ):
            values[key] = values.get(key) or ""
        for key in ("dm_policy", "group_policy"):
            values[key] = values.get(key) or "open"
        values["allow_from"] = values.get("allow_from") or []
        values["message_merge_delay_ms"] = (
            values.get("message_merge_delay_ms", 0) or 0
        )
        for key in ("access_control_dm", "access_control_group"):
            values[key] = bool(values.get(key, False))
    return values
