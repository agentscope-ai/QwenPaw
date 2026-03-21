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
