# -*- coding: utf-8 -*-
"""QQ native media and JSON parts, preserving the original support matrix."""

from __future__ import annotations

import base64
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from qwenpaw.app.channels.utils import (
    file_url_to_local_path,
    parse_data_url,
)

from .errors import QQDeliveryError
from .formatting import _media_path, _resolve_send_path

_EXT_TYPE_MAP = {
    **dict.fromkeys(
        (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"),
        "image",
    ),
    **dict.fromkeys(
        (".mp4", ".avi", ".mov", ".mkv", ".webm", ".mpeg"),
        "video",
    ),
    **dict.fromkeys((".mp3", ".wav", ".ogg", ".m4a", ".aac", ".wma"), "audio"),
}


def _resolve_attachment_type(att_type, file_name):
    if not att_type:
        return _EXT_TYPE_MAP.get(Path(file_name).suffix.lower(), "file")
    if att_type == "voice":
        return "audio"
    if att_type in ("image", "video", "audio", "file"):
        return att_type
    mime = att_type.split(";")[0].strip().lower()
    for prefix in ("image/", "video/", "audio/"):
        if mime.startswith(prefix):
            return prefix.rstrip("/")
    return "file"


def _content_type_to_media_type(content_type, source_path=""):
    content_type = getattr(content_type, "value", content_type)
    if source_path and Path(source_path).suffix.lower() in {
        ".amr",
        ".silk",
        ".slk",
    }:
        return 3
    return {"image": 1, "video": 2, "audio": 4, "file": 4}.get(content_type)


def _value(part, key):
    return (
        part.get(key) if isinstance(part, dict) else getattr(part, key, None)
    )


def _resolve_media_url_and_path(part):
    kind = _value(part, "type")
    kind = getattr(kind, "value", kind)
    key = "data" if kind == "audio" else str(kind) + "_url"
    raw = _value(part, key) or ""
    if kind not in {"image", "video", "audio", "file"} or not raw:
        return None, None
    if raw.startswith("file://"):
        local = file_url_to_local_path(raw) or raw
        return None, local if os.path.isfile(local) else None
    if raw.startswith(("http://", "https://")):
        return raw, None
    return (None, raw) if os.path.isfile(raw) else (raw, None)


def _make_content_part(resolved_type, local_path, file_name):
    if resolved_type not in {"image", "video", "audio", "file"}:
        return None
    key = "data" if resolved_type == "audio" else resolved_type + "_url"
    part = {"type": resolved_type, key: local_path}
    if resolved_type == "file":
        part["filename"] = file_name
    return part


class QQMedia:
    def __init__(self, platform, config):
        self.platform = platform
        workspace = config.get("workspace_dir")
        working = workspace or os.getenv("QWENPAW_WORKING_DIR") or os.getcwd()
        default = (
            Path(working) / "media"
            if workspace
            else Path(working) / "media/qq"
        )
        self.directory = Path(config.get("media_dir") or default).expanduser()
        self.root = (
            Path(workspace).expanduser().resolve()
            if workspace
            else self.directory.resolve()
        )

    def _safe_path(self, value, *, exists=True):
        path = Path(value).expanduser().resolve()
        if not path.is_relative_to(self.root):
            raise QQDeliveryError("MEDIA_PATH_UNAUTHORIZED")
        if exists and not path.is_file():
            raise QQDeliveryError("MEDIA_FILE_NOT_FOUND")
        return path

    def _read_file(self, value):
        """Recheck authorization in the I/O thread; refuse replaced symlinks."""
        path = self._safe_path(value)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        directory = None
        try:
            if os.open in os.supports_dir_fd:
                directory = os.open(
                    self.root,
                    flags | getattr(os, "O_DIRECTORY", 0),
                )
                relative = path.relative_to(self.root)
                for name in relative.parts[:-1]:
                    child = os.open(
                        name,
                        flags | getattr(os, "O_DIRECTORY", 0),
                        dir_fd=directory,
                    )
                    os.close(directory)
                    directory = child
                descriptor = os.open(
                    relative.parts[-1],
                    flags,
                    dir_fd=directory,
                )
            else:
                descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as source:
                return source.read()
        finally:
            if directory is not None:
                os.close(directory)

    async def _download(self, url, filename):
        if not filename:
            return None
        name = Path(filename.replace("\\", "/")).name
        if name in {"", ".", ".."}:
            return None
        try:
            directory = self._safe_path(self.directory, exists=False)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / name
            # Reject an existing escaped symlink instead of reading or replacing it.
            self._safe_path(target, exists=False)
            response = await self.platform._request("GET", url)
            if response.status_code != 200:
                return None
            self._safe_path(directory, exists=False)
            self._safe_path(target, exists=False)
            fd, temporary = tempfile.mkstemp(
                prefix=".qq-download-",
                dir=directory,
            )
            os.close(fd)
            try:
                await self.platform._file_io(
                    Path(temporary).write_bytes,
                    response.content,
                )
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return str(target)
        except QQDeliveryError:
            return None
        except Exception:
            return None

    async def parse_attachments(self, attachments):
        parts = []
        for attachment in attachments or ():
            if not isinstance(attachment, dict):
                continue
            url = attachment.get("url", "")
            filename = attachment.get("filename", "")
            kind = attachment.get("content_type", attachment.get("type", ""))
            voice = kind == "voice" or Path(filename).suffix.lower() in {
                ".amr",
                ".silk",
                ".slk",
            }
            if voice and attachment.get("asr_refer_text"):
                parts.append(
                    {"type": "text", "text": attachment["asr_refer_text"]},
                )
                continue
            if voice and attachment.get("voice_wav_url"):
                url = attachment["voice_wav_url"]
                filename = filename.rsplit(".", 1)[0] + ".wav"
            if not url:
                continue
            path = await self._download(url, filename)
            if path:
                part = _make_content_part(
                    _resolve_attachment_type(kind, filename),
                    path,
                    filename,
                )
                if part:
                    parts.append(part)
        return parts

    async def send(self, route, part, *, reply=False, inline=False):
        kind = part.get("type")
        if kind not in {"image", "video", "audio", "file"}:
            raise QQDeliveryError("MEDIA_TYPE_UNSUPPORTED")
        url, local = _resolve_media_url_and_path(part)
        if not url and not local:
            raise QQDeliveryError("MEDIA_FILE_NOT_FOUND")
        if local:
            local = str(self._safe_path(local))
        if url and not url.startswith("data:"):
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise QQDeliveryError("MEDIA_FILE_NOT_FOUND")
        message_type = route["message_type"]
        msg_id = route.get("message_id") if reply else None
        if message_type in {"c2c", "group"}:
            return await self._send_rich(
                route,
                kind,
                url,
                local,
                msg_id,
                inline=inline,
            )
        if message_type not in {"guild", "dm"} or kind not in {
            "image",
            "video",
        }:
            raise QQDeliveryError("MEDIA_TYPE_UNSUPPORTED")
        path, _, _ = _resolve_send_path(
            message_type,
            route.get("sender_id"),
            route.get("channel_id"),
            route.get("group_openid"),
            route.get("guild_id"),
        )
        if url and not url.startswith("data:"):
            body = {"image": url}
            if msg_id:
                body["msg_id"] = msg_id
            return await self.platform._api_request_async("POST", path, body)
        temporary = None
        try:
            if url:
                data = await self.platform._file_io(parse_data_url, url)
                if data is None:
                    raise QQDeliveryError("MEDIA_DATA_INVALID")
                directory = self._safe_path(self.directory, exists=False)
                directory.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(
                    prefix="qq-media-",
                    suffix=data.suffix,
                    dir=directory,
                )
                os.close(fd)
                await self.platform._file_io(
                    Path(temporary).write_bytes,
                    data.data,
                )
                local, filename = temporary, "image" + data.suffix
            else:
                filename = Path(local).name
            content = await self.platform._file_io(self._read_file, local)
            return await self.platform._api_request_async(
                "POST",
                path,
                None,
                data={"msg_id": msg_id} if msg_id else {},
                files={"file_image": (filename, content)},
            )
        except (ValueError, OSError) as exc:
            raise QQDeliveryError("MEDIA_DATA_INVALID") from exc
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    async def _send_rich(
        self,
        route,
        kind,
        url,
        local,
        msg_id,
        *,
        inline=False,
    ):
        media_type = _content_type_to_media_type(kind, url or local or "")
        message_type = route["message_type"]
        if message_type == "group" and media_type == 4:
            raise QQDeliveryError("MEDIA_TYPE_UNSUPPORTED")
        target = (
            route.get("sender_id")
            if message_type == "c2c"
            else route.get("group_openid")
        )
        if not target or target == "unknown":
            raise QQDeliveryError("OUTBOUND_TARGET_UNKNOWN")
        body = {"file_type": media_type, "srv_send_msg": False}
        try:
            if local:
                content = await self.platform._file_io(self._read_file, local)
                filename = Path(local).name
                body.update(
                    file_data=base64.b64encode(content).decode("ascii"),
                    file_name=filename,
                )
            elif url.startswith("data:"):
                data = await self.platform._file_io(parse_data_url, url)
                if data is None:
                    raise QQDeliveryError("MEDIA_DATA_INVALID")
                filename = "file" + data.suffix
                body.update(
                    file_data=base64.b64encode(data.data).decode("ascii"),
                    file_name=filename,
                )
            else:
                filename = Path(url.split("?")[0]).name
                body["url"] = url
        except (ValueError, OSError) as exc:
            raise QQDeliveryError("MEDIA_DATA_INVALID") from exc
        uploaded = await self.platform._api_request_async(
            "POST",
            _media_path(message_type, target, "files"),
            body,
        )
        file_info = uploaded.get("file_info")
        if not isinstance(file_info, str) or not file_info:
            raise QQDeliveryError(
                "MEDIA_UPLOAD_INVALID_RECEIPT",
                side_effect_possible=True,
            )
        outgoing = {
            "msg_type": 7,
            "media": {"file_info": file_info},
            "msg_seq": self.platform._next_seq(
                route,
                msg_id,
                message_type + "_media",
            ),
        }
        if filename and not inline:
            outgoing["content"] = filename
        if msg_id:
            outgoing["msg_id"] = msg_id
        return await self.platform._api_request_async(
            "POST",
            _media_path(message_type, target, "messages"),
            outgoing,
        )
