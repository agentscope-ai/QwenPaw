# -*- coding: utf-8 -*-
"""Generic HTTP Webhook channel plugin for QwenPaw.

A generic inbound/outbound HTTP webhook channel. Accepts arbitrary
JSON payloads via POST, verifies an optional HMAC-SHA256 signature,
enforces per-client-IP rate limiting, and posts agent replies back to
a configured outbound URL.

Installable as an opt-in plugin from the QwenPaw Plugin Marketplace
(``plugins/channel/webhook``).
"""

from .channel import (
    DEFAULT_BIND_ADDRESS,
    DEFAULT_PORT,
    DEFAULT_RATE_LIMIT_BURST,
    DEFAULT_RATE_LIMIT_RPS,
    GenericWebhookEvent,
    WebhookChannel,
    WebhookChannelConfig,
)
from .sender import send_webhook_reply, send_webhook_reply_sync
from .server import (
    MAX_BODY_BYTES,
    create_webhook_app,
    start_webhook_server,
)
from .signature import (
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
    verify_signature,
)

__all__ = [
    "DEFAULT_BIND_ADDRESS",
    "DEFAULT_PORT",
    "DEFAULT_RATE_LIMIT_BURST",
    "DEFAULT_RATE_LIMIT_RPS",
    "GenericWebhookEvent",
    "MAX_BODY_BYTES",
    "SIGNATURE_HEADER",
    "SIGNATURE_PREFIX",
    "WebhookChannel",
    "WebhookChannelConfig",
    "create_webhook_app",
    "send_webhook_reply",
    "send_webhook_reply_sync",
    "start_webhook_server",
    "verify_signature",
]
