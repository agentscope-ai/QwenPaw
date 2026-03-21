# -*- coding: utf-8 -*-
"""DingTalk channel constants."""

# When consumer sends all messages via sessionWebhook, process() skips reply
SENT_VIA_WEBHOOK = "__SENT_VIA_WEBHOOK__"

# Token cache TTL (1 hour)
DINGTALK_TOKEN_TTL_SECONDS = 3600

# Time debounce (300ms)
DINGTALK_DEBOUNCE_SECONDS = 0.3

# Short suffix length for session_id from conversation_id
DINGTALK_SESSION_ID_SUFFIX_LEN = 8

# DingTalk message type to runtime content type
DINGTALK_TYPE_MAPPING = {
    "picture": "image",
}
