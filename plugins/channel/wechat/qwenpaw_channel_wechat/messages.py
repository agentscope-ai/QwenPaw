# -*- coding: utf-8 -*-
"""iLink native message and quoted-message parsing, without an Agent."""

from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
_FILENAME_EXTENSIONS = (
    ".txt",
    ".doc",
    ".docx",
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".mp4",
    ".avi",
    ".mov",
    ".mp3",
    ".wav",
    ".zip",
    ".rar",
    ".xlsx",
    ".xls",
    ".ppt",
    ".pptx",
)
_MEDIA = {
    2: ("image", "image.jpg", "image_url"),
    4: ("file", "file.bin", "file_url"),
    5: ("video", "video.mp4", "video_url"),
}


class WeChatMessageParser:
    def __init__(self, media_dir: Path):
        self.media_dir = media_dir

    async def parse(self, message, client):
        texts, parts = [], []
        for item in message.get("item_list") or []:
            await self._item(item, client, texts, parts, quoted=False)
            ref = item.get("ref_msg")
            if ref:
                await self._item(
                    ref.get("message_item") or {},
                    client,
                    texts,
                    parts,
                    quoted=True,
                )
        text = "\n".join(texts).strip()
        if text:
            parts.insert(0, {"type": "text", "text": text})
        return parts

    async def _item(self, item, client, texts, parts, *, quoted):
        kind = item.get("type", 0)

        def add(text):
            if quoted:
                texts.insert(0, text)
            else:
                texts.append(text)

        if kind == 1:
            text = (item.get("text_item") or {}).get("text", "").strip()
            if text and (
                quoted or not text.lower().endswith(_FILENAME_EXTENSIONS)
            ):
                add(f"[quoted message: {text}]" if quoted else text)
        elif kind == 3:
            voice = item.get("voice_item") or {}
            transcription = (
                voice["text_item"].get("text", "")
                if isinstance(voice.get("text_item"), dict)
                else voice.get("text", "")
            ).strip()
            if transcription:
                add(
                    f"[quoted voice: {transcription}]"
                    if quoted
                    else transcription,
                )
            else:
                add(
                    "[quoted voice: no transcription]"
                    if quoted
                    else "[voice: no transcription]",
                )
        elif kind in _MEDIA:
            name, default_name, locator = _MEDIA[kind]
            media_item = item.get(name + "_item") or {}
            media = media_item.get("media") or {}
            encrypted = media.get("encrypt_query_param", "")
            key = media.get("aes_key", "")
            if kind == 2 and media_item.get("aeskey"):
                key = base64.b64encode(
                    bytes.fromhex(media_item["aeskey"]),
                ).decode()
            label = ("quoted " if quoted else "") + name
            if not encrypted:
                add(f"[{label}: no url]")
                return
            filename = media_item.get("file_name") or default_name
            path = await self.download(client, "", key, filename, encrypted)
            if path:
                parts.append({"type": name, locator: path})
            else:
                add(f"[{label}: download failed]")
        elif not quoted or kind:
            add(
                f"[quoted message: unsupported type {kind}]"
                if quoted
                else f"[unsupported type: {kind}]",
            )

    async def download(
        self,
        client,
        url,
        aes_key="",
        filename="file.bin",
        encrypted="",
    ):
        try:
            data = await client.download_media(url, aes_key, encrypted)
            self.media_dir.mkdir(parents=True, exist_ok=True)
            safe_name = (
                "".join(c for c in filename if c.isalnum() or c in "-_.")
                or "media"
            )
            digest = hashlib.md5((encrypted or url).encode()).hexdigest()[:8]
            path = self.media_dir / f"wechat_{digest}_{safe_name}"
            path.write_bytes(data)
            return str(path)
        except Exception:
            logger.warning("WeChat media download failed")
            return None
