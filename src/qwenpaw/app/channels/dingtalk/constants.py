# -*- coding: utf-8 -*-
"""DingTalk channel constants."""

# When consumer sends all messages via sessionWebhook, process() skips reply
SENT_VIA_WEBHOOK = "__SENT_VIA_WEBHOOK__"
SENT_VIA_AI_CARD = "__SENT_VIA_AI_CARD__"

# Token cache TTL (1 hour)
DINGTALK_TOKEN_TTL_SECONDS = 3600

# Minimum interval between non-final AI Card updates.
AI_CARD_STREAM_MIN_INTERVAL_SECONDS = 0.6

# Time debounce (300ms)
DINGTALK_DEBOUNCE_SECONDS = 0.3

# DingTalk message type to runtime content type
DINGTALK_TYPE_MAPPING = {
    "picture": "image",
    "voice": "audio",
}

AI_CARD_TOKEN_PREEMPTIVE_REFRESH_SECONDS = 90 * 60
AI_CARD_PROCESSING_TEXT = "处理中..."
AI_CARD_RECOVERY_FINAL_TEXT = "⚠️ 上一次回复处理中断，已自动结束。请重新发送你的问题。"

# Safety margin (ms) before sessionWebhook expiry to consider it expired.
# Treat webhook as expired 5 minutes before actual expiry time.
SESSION_WEBHOOK_EXPIRY_SAFETY_MARGIN_MS = 5 * 60 * 1000
