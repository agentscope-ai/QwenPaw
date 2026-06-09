# -*- coding: utf-8 -*-
"""Yuanbao channel constants."""

# Default WebSocket gateway URL (binary protobuf protocol)
DEFAULT_WS_URL = "wss://bot-wss.yuanbao.tencent.com/wss/connection"

# Default API domain (REST endpoints for sign-token, media upload, etc.)
DEFAULT_API_DOMAIN = "bot.yuanbao.tencent.com"

# Sign-token API path
SIGN_TOKEN_PATH = "/api/v5/robotLogic/sign-token"

# Retryable sign-token error code
RETRYABLE_SIGN_CODE = 10099
SIGN_MAX_RETRIES = 3
SIGN_RETRY_DELAY_S = 1.0

# Token cache refresh margin (seconds before expiry to refresh)
TOKEN_REFRESH_MARGIN_S = 300  # 5 minutes

# Heartbeat interval (seconds) — server may override via PingRsp
HEARTBEAT_INTERVAL = 5

# Reconnect delays (seconds) — exponential backoff
RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]
MAX_RECONNECT_ATTEMPTS = 100

# Close codes that should NOT trigger reconnection
NO_RECONNECT_CLOSE_CODES = {
    4012,  # Version ban
    4013,  # User ban
    4014,  # Same-user connection conflict
    4018,  # Account ban
    4019,  # Account deleted
    4021,  # Device removed
}

# Auth error codes that require token refresh
AUTH_FAILED_CODES = {41103, 41104, 41108}
AUTH_ALREADY_CODE = 41101

# Consecutive heartbeat timeouts before triggering reconnect
HEARTBEAT_TIMEOUT_THRESHOLD = 2

# Connection timeout (seconds)
CONNECTION_TIMEOUT = 15

# Send timeout (seconds)
SEND_TIMEOUT = 30

# Maximum text chunk size (characters)
TEXT_CHUNK_LIMIT = 2800

# Maximum media upload size (bytes) — 20 MB
MEDIA_MAX_BYTES = 20 * 1024 * 1024

# Session ID suffix length (last N chars of raw account id)
SESSION_ID_SUFFIX_LEN = 8

# Typing indicator heartbeat values (EnumHeartbeat in biz.proto)
HEARTBEAT_RUNNING = 1  # Bot is processing / typing
HEARTBEAT_FINISH = 2  # Bot finished processing

# Interval (seconds) between typing heartbeat keepalive pings
TYPING_KEEPALIVE_INTERVAL = 3
