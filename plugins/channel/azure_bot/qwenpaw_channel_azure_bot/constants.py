# -*- coding: utf-8 -*-
"""Bot Framework constants and legacy attachment messages."""

OPENID_URL = (
    "https://login.botframework.com/v1/.well-known/openidconfiguration"
)
ISSUER = "https://api.botframework.com"
UPLOAD_MAX_BYTES = 180_000
DOWNLOAD_MAX_BYTES = 32 * 1024 * 1024
FILE_TOO_LARGE = {
    "zh": "⚠️ 文件「{name}」（{size_kb}KB）超过附件大小限制（180KB），无法发送。",
    "en": '⚠️ File "{name}" ({size_kb}KB) exceeds the attachment size limit (180KB) and cannot be sent.',
    "id": '⚠️ File "{name}" ({size_kb}KB) melebihi batas ukuran lampiran (180KB) dan tidak dapat dikirim.',
    "ru": "⚠️ Файл «{name}» ({size_kb}KB) превышает лимит (180KB).",
}
