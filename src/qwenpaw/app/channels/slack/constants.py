# -*- coding: utf-8 -*-
"""Slack channel constants."""

# ── Text Length Limits ──

# Maximum text length per Slack message (mrkdown)
SLACK_TEXT_LIMIT: int = 30000

# ── Duplicate Removal ──

# Deduplication window (seconds);
# messages with the same event_id within this window are considered duplicates
SLACK_DEDUP_WINDOW_SECONDS: int = 300

# Maximum number of entries in the deduplication cache
SLACK_DEDUP_MAX_ENTRIES: int = 10000

# ── SSRF Protection ──

# Whitelist of allowed domains for file downloads/uploads
SLACK_SSRF_ALLOWED_SUFFIXES: tuple[str, ...] = (
    ".slack.com",
    ".slack-edge.com",
    ".slack-files.com",
)
# ── Reconnection Backoff ──

# Initial backoff delay (seconds) for Socket Mode reconnection
SLACK_RECONNECT_INITIAL_S: float = 2.0

# Maximum backoff delay (seconds) after repeated failures
SLACK_RECONNECT_MAX_S: float = 30.0

# Exponential backoff multiplier
SLACK_RECONNECT_FACTOR: float = 1.8

# Jitter fraction (0.25 = ±25% randomness to avoid thundering herd)
SLACK_RECONNECT_JITTER: float = 0.25

# Maximum reconnection attempts before giving up
SLACK_RECONNECT_MAX_ATTEMPTS: int = 12

# Socket Mode WebSocket keep-alive ping interval (seconds)
SLACK_SOCKET_PING_INTERVAL_S: int = 10
