# -*- coding: utf-8 -*-
"""Webhook channel package.

A generic inbound/outbound HTTP webhook channel. Accepts arbitrary JSON
payloads via POST, optionally verifies an HMAC-SHA256 signature, and
posts agent replies back to a configured outbound URL.
"""
from .channel import WebhookChannel
from .sender import send_webhook_reply, send_webhook_reply_sync
from .server import create_webhook_app, start_webhook_server
from .signature import verify_signature

__all__ = [
    "WebhookChannel",
    "create_webhook_app",
    "send_webhook_reply",
    "send_webhook_reply_sync",
    "start_webhook_server",
    "verify_signature",
]
