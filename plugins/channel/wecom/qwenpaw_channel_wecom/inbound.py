# -*- coding: utf-8 -*-
"""Original WeCom message and quoted-media decoding, without host objects."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_QUOTE_MEDIA_MAP = {
    "image": ("image.jpg", dict, {"type": "image"}, "image_url"),
    "file": (None, dict, {"type": "file"}, "file_url"),
    "video": ("video.mp4", dict, {"type": "video"}, "video_url"),
}


def resolve_session_id(sender_id, channel_meta=None):
    meta = channel_meta or {}
    chatid = (meta.get("wecom_chatid") or "").strip()
    chat_type = (meta.get("wecom_chat_type") or "single").strip()
    if chat_type == "group" and chatid:
        return f"wecom:group:{chatid}"
    return f"wecom:{sender_id or chatid or 'unknown'}"


def parse_chatid_from_handle(to_handle):
    handle = (to_handle or "").strip()
    if handle.startswith("wecom:group:"):
        return handle.removeprefix("wecom:group:")
    return handle.removeprefix("wecom:")


class InboundDecoder:
    """Native decoding mixin used solely by the worker platform adapter."""

    async def _on_message(self, frame: Any) -> None:
        """Parse and enqueue one incoming message."""
        epoch = self._epoch
        try:
            body = frame.get("body") or {}
            if frame.get("cmd") != "aibot_msg_callback" or (
                "aibotid" in body
                and body["aibotid"] != self.config.get("bot_id")
            ):
                return False
            msgtype = body.get("msgtype") or ""
            sender_id = (body.get("from") or {}).get("userid", "")
            chatid = body.get("chatid", "")
            chat_type = body.get("chattype", "single")

            msg_id = str(body.get("msgid") or "")
            event_id = (
                "wecom:" + msg_id if msg_id else "wecom:" + uuid.uuid4().hex
            )
            if msg_id and event_id in self._processed_message_ids:
                return True

            content_parts: List[Any] = []
            text_parts: List[str] = []

            if msgtype == "text":
                text = (body.get("text") or {}).get("content", "").strip()
                if text:
                    # In group chat, strip @mention only when it wraps a
                    # slash command, to preserve normal conversation text.
                    if chat_type == "group":
                        text = re.sub(
                            r"^@\S+\s+(?=/)",
                            "",
                            text,
                        ).strip()
                        text = (
                            re.sub(
                                r"@\S+$",
                                "",
                                text,
                            )
                            if text.startswith("/")
                            else text
                        )
                        text = text.strip()
                    text_parts.append(text)

            elif msgtype == "image":
                img_info = body.get("image") or {}
                url = img_info.get("url") or ""
                aes_key = img_info.get("aeskey") or ""
                if url:
                    path = await self._download_media(
                        url,
                        aes_key=aes_key,
                        filename_hint="image.jpg",
                    )
                    if path:
                        content_parts.append(
                            dict(
                                type="image",
                                image_url=path,
                            ),
                        )
                    else:
                        text_parts.append("[image: download failed]")
                else:
                    text_parts.append("[image: no url]")

            elif msgtype == "voice":
                voice_info = body.get("voice") or {}
                # Use ASR text from WeCom; no need to download audio
                asr_text = voice_info.get("content", "").strip()
                if asr_text:
                    text_parts.append(asr_text)
                else:
                    text_parts.append("[voice: no text]")

            elif msgtype == "file":
                file_info = body.get("file") or {}
                url = file_info.get("url") or ""
                aes_key = file_info.get("aeskey") or ""
                filename = file_info.get("filename") or "file.bin"
                if url:
                    path = await self._download_media(
                        url,
                        aes_key=aes_key,
                        filename_hint=filename,
                    )
                    if path:
                        content_parts.append(
                            dict(
                                type="file",
                                file_url=path,
                                filename=filename,
                            ),
                        )
                    else:
                        text_parts.append("[file: download failed]")
                else:
                    text_parts.append("[file: no url]")

            elif msgtype == "video":
                video_info = body.get("video") or {}
                url = video_info.get("url") or ""
                aes_key = video_info.get("aeskey") or ""
                if url:
                    path = await self._download_media(
                        url,
                        aes_key=aes_key,
                        filename_hint="video.mp4",
                    )
                    if path:
                        content_parts.append(
                            dict(
                                type="video",
                                video_url=path,
                            ),
                        )
                    else:
                        text_parts.append("[video: download failed]")
                else:
                    text_parts.append("[video: no url]")

            elif msgtype == "mixed":
                # Mixed: list of items, each has msgtype, text or image
                mixed_items = body.get("mixed", {}).get("msg_item", [])
                for item in mixed_items:
                    itype = item.get("msgtype") or ""
                    if itype == "text":
                        t = item.get("text", {}).get("content", "").strip()
                        if t:
                            text_parts.append(t)
                    elif itype == "image":
                        img = item.get("image") or {}
                        url = img.get("url") or ""
                        aes_key = img.get("aeskey") or ""
                        if url:
                            path = await self._download_media(
                                url,
                                aes_key=aes_key,
                                filename_hint="image.jpg",
                            )
                            if path:
                                content_parts.append(
                                    dict(
                                        type="image",
                                        image_url=path,
                                    ),
                                )
                            else:
                                text_parts.append("[image: download failed]")
                    elif itype == "file":
                        file_info = item.get("file") or {}
                        url = file_info.get("url") or ""
                        aes_key = file_info.get("aeskey") or ""
                        filename = file_info.get("filename") or "file.bin"
                        if url:
                            path = await self._download_media(
                                url,
                                aes_key=aes_key,
                                filename_hint=filename,
                            )
                            if path:
                                content_parts.append(
                                    dict(
                                        type="file",
                                        file_url=path,
                                        filename=filename,
                                    ),
                                )
                            else:
                                text_parts.append("[file: download failed]")
                        else:
                            text_parts.append("[file: no url]")
            else:
                text_parts.append(f"[{msgtype}]")

            # Handle quoted (replied-to) message if present
            quote = body.get("quote")
            if quote:
                quote_type = quote.get("msgtype") or ""
                # Flatten quote into a list of items for unified processing.
                # Single-type quotes become a one-element list; mixed quotes
                # already contain a list of items.
                if quote_type == "mixed":
                    quoted_items = quote.get("mixed", {}).get("msg_item", [])
                elif quote_type:
                    quoted_items = [quote]
                else:
                    quoted_items = []

                for q_item in quoted_items:
                    q_type = q_item.get("msgtype") or ""
                    if q_type == "text":
                        quoted_text = (
                            (q_item.get("text") or {})
                            .get("content", "")
                            .strip()
                        )
                        if quoted_text:
                            text_parts.insert(
                                0,
                                f"[quoted message: {quoted_text}]",
                            )
                    elif q_type in _QUOTE_MEDIA_MAP:
                        (
                            hint_default,
                            content_cls,
                            content_kwargs,
                            url_field,
                        ) = _QUOTE_MEDIA_MAP[q_type]
                        q_data = q_item.get(q_type) or {}
                        q_url = q_data.get("url") or ""
                        q_aes_key = q_data.get("aeskey") or ""
                        hint = (
                            hint_default
                            or q_data.get("filename")
                            or "file.bin"
                        )
                        if q_url:
                            q_path = await self._download_media(
                                q_url,
                                aes_key=q_aes_key,
                                filename_hint=hint,
                            )
                            if q_path:
                                content_parts.append(
                                    content_cls(
                                        **content_kwargs,
                                        **{url_field: q_path},
                                    ),
                                )
                            else:
                                text_parts.insert(
                                    0,
                                    f"[quoted {q_type}: download failed]",
                                )
                    else:
                        text_parts.insert(
                            0,
                            f"[quoted {q_type} message]",
                        )

            text = "\n".join(text_parts).strip()
            if text:
                content_parts.insert(
                    0,
                    dict(type="text", text=text),
                )
            if not content_parts:
                return

            is_group = chat_type == "group"
            meta: Dict[str, Any] = {
                "wecom_sender_id": sender_id,
                "wecom_chatid": chatid,
                "wecom_chat_type": chat_type,
                "is_group": is_group,
                # Group callbacks target this authenticated bot connection.
                "bot_mentioned": is_group,
                "user_name": sender_id,
            }

            session_id = resolve_session_id(sender_id, meta)

            native = {
                "event_id": event_id,
                "frame": frame,
                "sender_id": sender_id,
                "acl_sender_id": sender_id,
                "user_id": (
                    "group"
                    if (is_group and self.share_session_in_group)
                    else sender_id
                ),
                "session_id": session_id,
                "content_parts": content_parts,
                "meta": meta,
            }
            logger.info(
                "wecom recv: sender=%s chatid=%s msgtype=%s text_len=%s",
                sender_id[:20],
                (chatid or "")[:20],
                msgtype,
                len(text),
            )
            self._check_epoch(epoch)
            accepted = await self.on_event(native)
            self._check_epoch(epoch)
            if accepted and msg_id:
                self._processed_message_ids[event_id] = None
                while len(self._processed_message_ids) > 2000:
                    self._processed_message_ids.popitem(last=False)
            return accepted
        except Exception:
            logger.exception("wecom _on_message failed")

    async def _download_media(
        self,
        url: str,
        aes_key: str = "",
        filename_hint: str = "file.bin",
    ) -> Optional[str]:
        """Download (and optionally decrypt) media; return local path."""
        if not self._client:
            return None
        try:
            data, filename = await self._call(
                "download_file",
                url,
                aes_key or None,
                effect=False,
            )
            fn = filename or filename_hint
            # Determine extension from hint if file has none
            hint_ext = Path(filename_hint).suffix
            if hint_ext and Path(fn).suffix in ("", ".bin", ".file"):
                fn = (Path(fn).stem or "file") + hint_ext
            self._media_dir.mkdir(parents=True, exist_ok=True)
            safe_name = (
                "".join(
                    c
                    for c in fn.replace("企业微信截图", "screenshot")
                    if c.isalnum() or c in "-_."
                )
                or "media"
            )
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            path = self._media_dir / f"wecom_{url_hash}_{safe_name}"
            await self._file_work(path.write_bytes, data)
            return str(path)
        except Exception:
            logger.exception("wecom _download_media failed url=%s", url[:60])
            return None
