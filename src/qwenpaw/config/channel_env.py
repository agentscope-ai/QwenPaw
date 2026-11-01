# -*- coding: utf-8 -*-
"""SDK-free readers for historical official channel environment entries."""

from collections.abc import Mapping


def read_channel_env(
    channel_key: str,
    environ: Mapping[str, str],
) -> dict | None:
    """Parse the old entry exactly; never construct or import a channel."""
    if channel_key == "telegram":
        return {
            "enabled": environ.get("TELEGRAM_CHANNEL_ENABLED", "0") == "1",
            **{
                key: environ.get("TELEGRAM_" + key.upper(), "")
                for key in (
                    "bot_token",
                    "base_url",
                    "http_proxy",
                    "http_proxy_auth",
                    "bot_prefix",
                    "deny_message",
                )
            },
            "show_typing": environ.get("TELEGRAM_SHOW_TYPING", "1") == "1",
            "require_mention": environ.get("TELEGRAM_REQUIRE_MENTION", "0")
            == "1",
            **{
                key: environ.get("TELEGRAM_" + key.upper(), "open")
                for key in ("dm_policy", "group_policy")
            },
            "allow_from": [
                item.strip()
                for item in environ.get("TELEGRAM_ALLOW_FROM", "").split(",")
                if item.strip()
            ],
        }
    if channel_key == "slack":
        return {
            "enabled": environ.get("SLACK_CHANNEL_ENABLED", "0") == "1",
            **{
                key: environ.get("SLACK_" + key.upper(), "")
                for key in (
                    "bot_token",
                    "app_token",
                    "bot_prefix",
                    "proxy",
                    "deny_message",
                )
            },
            "streaming_enabled": environ.get("SLACK_STREAMING_ENABLED", "0")
            == "1",
            "require_mention": environ.get("SLACK_REQUIRE_MENTION", "1")
            == "1",
            **{
                key: environ.get("SLACK_" + key.upper(), "open")
                for key in ("dm_policy", "group_policy")
            },
            "allow_from": [
                item.strip()
                for item in environ.get("SLACK_ALLOW_FROM", "").split(",")
                if item.strip()
            ],
        }
    if channel_key == "discord":
        return {
            "enabled": environ.get("DISCORD_CHANNEL_ENABLED", "1") == "1",
            **{
                key: environ.get("DISCORD_" + key.upper(), "")
                for key in (
                    "bot_token",
                    "http_proxy",
                    "http_proxy_auth",
                    "bot_prefix",
                    "deny_message",
                    "media_dir",
                )
            },
            **{
                key: environ.get("DISCORD_" + key.upper(), "open")
                for key in ("dm_policy", "group_policy")
            },
            **{
                key: environ.get("DISCORD_" + key.upper(), "0") == "1"
                for key in (
                    "require_mention",
                    "accept_bot_messages",
                    "streaming_enabled",
                )
            },
            "allow_from": [
                item.strip()
                for item in environ.get("DISCORD_ALLOW_FROM", "").split(",")
                if item.strip()
            ],
        }
    if channel_key == "mqtt":
        port = environ.get("MQTT_PORT", "1883")
        qos = environ.get("MQTT_QOS", "2")
        return {
            "enabled": environ.get("MQTT_CHANNEL_ENABLED", "0") == "1",
            "host": environ.get("MQTT_HOST", ""),
            "port": int(port) if port.isdigit() else 1883,
            "qos": int(qos) if qos.isdigit() else 0,
            "transport": environ.get("MQTT_TRANSPORT", "mqtt"),
            "clean_session": environ.get("MQTT_CLEAN_SESSION", "1") == "1",
            "tls_enabled": environ.get("MQTT_TLS_ENABLED", "0") == "1",
            **{
                key: environ.get("MQTT_" + key.upper(), "")
                for key in (
                    "username",
                    "password",
                    "subscribe_topic",
                    "publish_topic",
                    "bot_prefix",
                )
            },
            **{
                key: environ.get("MQTT_" + key.upper())
                for key in (
                    "tls_ca_certs",
                    "tls_certfile",
                    "tls_keyfile",
                )
            },
        }
    if channel_key == "mattermost":
        return {
            "enabled": environ.get("MATTERMOST_CHANNEL_ENABLED", "0") == "1",
            "url": environ.get("MATTERMOST_URL", "").rstrip("/"),
            **{
                key: environ.get("MATTERMOST_" + key.upper(), "")
                for key in (
                    "bot_token",
                    "bot_prefix",
                    "media_dir",
                    "deny_message",
                )
            },
            "show_typing": environ.get("MATTERMOST_SHOW_TYPING", "1") == "1",
            "thread_follow_without_mention": environ.get(
                "MATTERMOST_THREAD_FOLLOW",
                "0",
            )
            == "1",
            "dm_policy": environ.get("MATTERMOST_DM_POLICY", "open"),
            "group_policy": environ.get("MATTERMOST_GROUP_POLICY", "open"),
            "allow_from": [
                item.strip()
                for item in environ.get("MATTERMOST_ALLOW_FROM", "").split(",")
                if item.strip()
            ],
        }
    if channel_key in {"feishu", "dingtalk"}:
        prefix = channel_key.upper() + "_"
        values = {
            "enabled": environ.get(
                prefix + "CHANNEL_ENABLED",
                "1" if channel_key == "dingtalk" else "0",
            )
            == "1",
            **{
                key: environ.get(prefix + key.upper(), "")
                for key in ("bot_prefix", "media_dir", "deny_message")
            },
            **{
                key: environ.get(prefix + key.upper(), "open")
                for key in ("dm_policy", "group_policy")
            },
            "allow_from": [
                item.strip()
                for item in environ.get(prefix + "ALLOW_FROM", "").split(",")
                if item.strip()
            ],
            **{
                key: environ.get(prefix + key.upper(), "0") == "1"
                for key in (
                    "require_mention",
                    "streaming_enabled",
                    "share_session_in_group",
                )
            },
        }
        if channel_key == "feishu":
            values.update(
                {
                    key: environ.get(prefix + key.upper(), "")
                    for key in (
                        "app_id",
                        "app_secret",
                        "encrypt_key",
                        "verification_token",
                    )
                },
            )
            values["domain"] = environ.get("FEISHU_DOMAIN", "feishu")
        else:
            values.update(
                {
                    key: environ.get(prefix + key.upper(), "")
                    for key in (
                        "client_id",
                        "client_secret",
                        "card_template_id",
                        "endpoint",
                    )
                },
            )
            for key in ("message_type", "cron_message_type"):
                values[key] = (
                    (
                        environ.get(prefix + key.upper(), "markdown")
                        or "markdown"
                    )
                    .strip()
                    .lower()
                )
            values["card_template_key"] = (
                environ.get("DINGTALK_CARD_TEMPLATE_KEY", "content")
                or "content"
            )
            values["robot_code"] = environ.get(
                "DINGTALK_ROBOT_CODE",
                "",
            ) or environ.get("DINGTALK_CLIENT_ID", "")
            for key in ("card_auto_layout", "at_sender_on_reply"):
                values[key] = environ.get(prefix + key.upper(), "0") == "1"
        return values
    if channel_key == "qq":
        return {
            "enabled": environ.get("QQ_CHANNEL_ENABLED", "1") == "1",
            "app_id": environ.get("QQ_APP_ID", ""),
            "client_secret": environ.get("QQ_CLIENT_SECRET", ""),
            "bot_prefix": environ.get("QQ_BOT_PREFIX", ""),
            "markdown_enabled": environ.get("QQ_MARKDOWN_ENABLED", "1")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
        }
    if channel_key == "xiaoyi":
        # media_dir was an execution-only constructor input, not a model
        # field. Do not invent WS_URL/TASK_TIMEOUT environment entries.
        return {
            "enabled": environ.get("XIAOYI_CHANNEL_ENABLED", "0") == "1",
            **{
                key: environ.get("XIAOYI_" + key.upper(), "")
                for key in ("ak", "sk", "agent_id", "media_dir")
            },
        }
    if channel_key == "matrix":
        # The old from_env forwarded only these two variables. Its constructor
        # defaults differ from the retained MatrixConfig's public defaults.
        return {
            "enabled": True,
            "vision_enabled": False,
            "homeserver": environ.get("HICLAW_MATRIX_SERVER", "").rstrip("/"),
            "access_token": environ.get("HICLAW_MATRIX_TOKEN", ""),
        }
    if channel_key in {"yuanbao", "wecom", "wechat", "imessage", "onebot"}:
        prefix = channel_key.upper() + "_"
        allow_from = environ.get(prefix + "ALLOW_FROM", "")
        values = {
            "enabled": environ.get(
                prefix + "CHANNEL_ENABLED",
                "1" if channel_key in {"yuanbao", "imessage"} else "0",
            )
            == "1",
            "bot_prefix": environ.get(prefix + "BOT_PREFIX", ""),
            "dm_policy": environ.get(prefix + "DM_POLICY", "open"),
            "group_policy": environ.get(prefix + "GROUP_POLICY", "open"),
            "allow_from": (
                allow_from.split(",")
                if channel_key == "onebot" and allow_from
                else [
                    item.strip()
                    for item in allow_from.split(",")
                    if item.strip()
                ]
            ),
            "deny_message": environ.get(prefix + "DENY_MESSAGE", ""),
        }
        if channel_key != "yuanbao":
            values["media_dir"] = environ.get(prefix + "MEDIA_DIR", "")
        if channel_key == "yuanbao":
            values.update(
                app_id=environ.get("YUANBAO_APP_ID", ""),
                app_secret=environ.get("YUANBAO_APP_SECRET", ""),
                api_domain=environ.get(
                    "YUANBAO_API_DOMAIN",
                    "bot.yuanbao.tencent.com",
                ),
                require_mention=environ.get("YUANBAO_REQUIRE_MENTION", "1")
                == "1",
                accept_bot_messages=environ.get(
                    "YUANBAO_ACCEPT_BOT_MESSAGES",
                    "0",
                )
                == "1",
            )
        elif channel_key == "wecom":
            values.update(
                bot_id=environ.get("WECOM_BOT_ID", ""),
                secret=environ.get("WECOM_SECRET", ""),
                share_session_in_group=environ.get(
                    "WECOM_SHARE_SESSION_IN_GROUP",
                    "1",
                )
                == "1",
                max_reconnect_attempts=int(
                    environ.get("WECOM_MAX_RECONNECT_ATTEMPTS", "-1"),
                ),
                ws_url=environ.get("WECOM_WS_URL", ""),
            )
        elif channel_key == "wechat":
            values.update(
                bot_token=environ.get("WECHAT_BOT_TOKEN", ""),
                bot_token_file=environ.get("WECHAT_BOT_TOKEN_FILE", ""),
                base_url=environ.get("WECHAT_BASE_URL", ""),
            )
        elif channel_key == "imessage":
            values.update(
                db_path=environ.get(
                    "IMESSAGE_DB_PATH",
                    "~/Library/Messages/chat.db",
                ),
                poll_sec=float(environ.get("IMESSAGE_POLL_SEC", "1.0")),
                max_decoded_size=int(
                    environ.get("IMESSAGE_MAX_DECODED_SIZE", "10485760"),
                ),
                require_mention=environ.get("IMESSAGE_REQUIRE_MENTION", "0")
                == "1",
            )
        else:
            values.update(
                ws_host=environ.get("ONEBOT_WS_HOST", "127.0.0.1"),
                ws_port=int(environ.get("ONEBOT_WS_PORT", "6199")),
                access_token=environ.get("ONEBOT_ACCESS_TOKEN", ""),
                require_mention=environ.get("ONEBOT_REQUIRE_MENTION", "0")
                == "1",
                share_session_in_group=environ.get(
                    "ONEBOT_SHARE_SESSION_IN_GROUP",
                    "0",
                )
                == "1",
                media_base64=environ.get("ONEBOT_MEDIA_BASE64", "0") == "1",
                media_base64_max_mb=int(
                    environ.get("ONEBOT_MEDIA_BASE64_MAX_MB", "10"),
                ),
                media_download_max_mb=int(
                    environ.get("ONEBOT_MEDIA_DOWNLOAD_MAX_MB", "50"),
                ),
            )
        return values
    # Voice, SIP and Azure had no historical from_env entrypoint.
    return None
