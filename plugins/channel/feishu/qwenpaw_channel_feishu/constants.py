# -*- coding: utf-8 -*-
"""Feishu channel constants."""

# Token cache: refresh 1 min before expire
FEISHU_TOKEN_REFRESH_BEFORE_SECONDS = 60

# Max size for Feishu file upload (30MB)
FEISHU_FILE_MAX_BYTES = 30 * 1024 * 1024

# Dedup cache max size
FEISHU_PROCESSED_IDS_MAX = 1000

# Nickname cache max size (open_id -> name from Contact API)
FEISHU_NICKNAME_CACHE_MAX = 500

# Short suffix length for session_id (from chat_id or open_id)
FEISHU_SESSION_ID_SUFFIX_LEN = 8

# Timeout for Contact API when fetching user name by open_id (seconds)
FEISHU_USER_NAME_FETCH_TIMEOUT = 2

# Stale message threshold: drop Feishu retry deliveries older than this (ms)
FEISHU_STALE_MSG_THRESHOLD_MS = 20 * 1000

# WebSocket reconnection backoff settings
FEISHU_WS_INITIAL_RETRY_DELAY = 1.0  # seconds
FEISHU_WS_MAX_RETRY_DELAY = 60.0  # seconds
FEISHU_WS_BACKOFF_FACTOR = 2

# If no data (including pong) received for this many seconds, force reconnect.
# SDK pings every ~120s, so 240s ≈ 2 missed cycles.
FEISHU_WS_RECV_TIMEOUT = 240

# ---- CardKit streaming card constants ----

# Minimum interval (seconds) between streaming update API calls.
# CardKit allows 10 QPS per card entity; we use a conservative interval.
FEISHU_STREAM_MIN_INTERVAL_S = 0.15

# Element ID for the markdown component inside the streaming card.
FEISHU_STREAM_ELEMENT_ID = "streaming_content"

# Element ID for the collapsible panel wrapping the reasoning markdown.
# CardKit requires <= 20 chars, starting with a letter.
FEISHU_REASONING_PANEL_ELEMENT_ID = "reasoning_panel"

# Header label of the reasoning panel. Deliberately English: QwenPaw ships
# internationally, and the collapsed state is conveyed by the arrow icon
# instead of by state-dependent copy.
FEISHU_REASONING_PANEL_TITLE = "Thinking"

# Standard icon used as the panel's expand/collapse arrow. Paired with
# ``icon_expanded_angle: 180`` it points up while expanded and down after
# the panel is collapsed.
FEISHU_REASONING_PANEL_ICON_TOKEN = "down-small-ccm_outlined"
