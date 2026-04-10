# -*- coding: utf-8 -*-
"""XiaoYi channel constants."""

# Default WebSocket URL
DEFAULT_WS_URL = "wss://hag.cloud.huawei.com/openclaw/v1/ws/link"

# Heartbeat interval (seconds)
HEARTBEAT_INTERVAL = 30

# Reconnect delays (seconds)
RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]
MAX_RECONNECT_ATTEMPTS = 50

# Connection timeout (seconds)
CONNECTION_TIMEOUT = 30

# Task timeout (milliseconds)
DEFAULT_TASK_TIMEOUT_MS = 3600000  # 1 hour

# Maximum text chunk size (characters)
# Larger messages will be split to avoid WebSocket disconnection
TEXT_CHUNK_LIMIT = 4000
