# -*- coding: utf-8 -*-
"""Generic Webhook channel plugin entry point."""

import logging

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class WebhookChannelPlugin:
    """Generic HTTP Webhook channel plugin.

    Register via :func:`api.register_channel` so the channel is only
    available to deployments that explicitly install it from the
    Plugin Marketplace. This keeps the inbound-listener attack
    surface opt-in.
    """

    def register(self, api: PluginApi):
        """Register the Webhook channel."""
        from .channel import WebhookChannel

        api.register_channel(
            channel_class=WebhookChannel,
            label="Webhook",
            description=(
                "Generic HTTP webhook receiver + sender (HMAC-SHA256 "
                "signed, per-client-IP rate limited)"
            ),
            icon=(
                "https://img.alicdn.com/imgextra/i4/"
                "O1CN01S2dWM41uMPblaTUEP_!!6000000006024-2-tps-3000-3000.png"
            ),
            doc_url={
                "zh": (
                    "https://qwenpaw.agentscope.io/docs/channels/"
                    "?lang=zh#Webhook通用-HTTP"
                ),
                "en": (
                    "https://qwenpaw.agentscope.io/docs/channels/"
                    "?lang=en#Webhook-generic-HTTP"
                ),
            },
            config_fields=[
                {
                    "name": "channel_id",
                    "label": {
                        "zh-CN": "入站 URL 段",
                        "en-US": "Inbound URL slug",
                    },
                    "type": "text",
                    "required": True,
                    "placeholder": "default",
                    "default": "default",
                    "help": {
                        "zh-CN": (
                            "接收端监听的 URL 段，例如 " "`default`、`homeassistant`、`ci`"
                        ),
                        "en-US": (
                            "Inbound URL slug the receiver listens on; "
                            "e.g. `default`, `homeassistant`, `ci`"
                        ),
                    },
                },
                {
                    "name": "bind_address",
                    "label": {
                        "zh-CN": "绑定地址",
                        "en-US": "Bind address",
                    },
                    "type": "text",
                    "required": False,
                    "placeholder": "127.0.0.1",
                    "default": "127.0.0.1",
                    "help": {
                        "zh-CN": ("入站监听地址；公开部署时请改用反向代理，" "不要直接绑定到 0.0.0.0"),
                        "en-US": (
                            "Inbound listener address. For public "
                            "deployments use a reverse proxy rather "
                            "than binding directly to 0.0.0.0"
                        ),
                    },
                },
                {
                    "name": "port",
                    "label": {
                        "zh-CN": "入站端口",
                        "en-US": "Inbound port",
                    },
                    "type": "number",
                    "required": False,
                    "placeholder": "9070",
                    "default": 9070,
                },
                {
                    "name": "outbound_url",
                    "label": {
                        "zh-CN": "出站 URL",
                        "en-US": "Outbound URL",
                    },
                    "type": "text",
                    "required": False,
                    "placeholder": "https://my-service/hook",
                    "default": "",
                    "help": {
                        "zh-CN": (
                            "Agent 回复 POST 到的地址；入站请求"
                            "未指定 to_handle 时使用此默认 URL"
                        ),
                        "en-US": (
                            "Where agent replies are POSTed; used as "
                            "the default when the inbound request "
                            "does not specify a `to_handle`"
                        ),
                    },
                },
                {
                    "name": "secret",
                    "label": {
                        "zh-CN": "HMAC-SHA256 共享密钥",
                        "en-US": "HMAC-SHA256 shared secret",
                    },
                    "type": "password",
                    "required": False,
                    "placeholder": "",
                    "default": "",
                    "help": {
                        "zh-CN": (
                            "配置后任何不带正确 X-QwenPaw-Signature "
                            "签名的请求都会被 401 拒绝；公开部署"
                            "时强烈建议配置"
                        ),
                        "en-US": (
                            "When set, any request without a valid "
                            "X-QwenPaw-Signature header is rejected "
                            "with 401. Strongly recommended for "
                            "public deployments"
                        ),
                    },
                },
                {
                    "name": "rate_limit_rps",
                    "label": {
                        "zh-CN": "限流 (RPS)",
                        "en-US": "Rate limit (RPS)",
                    },
                    "type": "number",
                    "required": False,
                    "placeholder": "5",
                    "default": 5,
                    "help": {
                        "zh-CN": ("每个客户端 IP 的平均请求速率上限"),
                        "en-US": (
                            "Per-client-IP sustained request rate "
                            "limit (requests / second)"
                        ),
                    },
                },
                {
                    "name": "rate_limit_burst",
                    "label": {
                        "zh-CN": "限流 (突发)",
                        "en-US": "Rate limit (burst)",
                    },
                    "type": "number",
                    "required": False,
                    "placeholder": "10",
                    "default": 10,
                    "help": {
                        "zh-CN": ("每个客户端 IP 允许的最大突发请求数"),
                        "en-US": (
                            "Maximum per-client-IP burst size before "
                            "the rate limit kicks in"
                        ),
                    },
                },
            ],
        )
        logger.info("✓ Webhook channel registered")


# Export plugin instance
plugin = WebhookChannelPlugin()
