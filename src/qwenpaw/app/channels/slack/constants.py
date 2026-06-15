# -*- coding: utf-8 -*-
"""Slack channel constants."""

# ── Text Length Limits ──

# Maximum text length per Slack message (mrkdown)
SLACK_TEXT_LIMIT: int = 30000

# ── Streaming Output ──

# AsyncChatStream local buffer size (characters);
# messages are automatically flushed when this limit is exceeded
SLACK_STREAM_BUFFER_SIZE: int = 256

# Minimum interval (seconds) for fallback to chat_update for streaming editing
SLACK_STREAM_EDIT_MIN_INTERVAL: float = 0.4

# ── Duplicate Removal ──

# Deduplication window (seconds);
# messages with the same event_id within this window are considered duplicates
SLACK_DEDUP_WINDOW_SECONDS: int = 300

# Maximum number of entries in the deduplication cache
SLACK_DEDUP_MAX_ENTRIES: int = 10000

# ── Thread Participation Tracking ──

# Thread participation cache TTL (seconds);
# after this time, the thread will no longer be automatically replied to
SLACK_THREAD_CACHE_TTL_SECONDS: int = 86400  # 24 hours

# Maximum number of entries in the thread participation cache
SLACK_THREAD_CACHE_MAX: int = 5000

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
