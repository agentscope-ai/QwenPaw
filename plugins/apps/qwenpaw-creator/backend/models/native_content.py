# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""AgentScope-native message blocks for Creator text and media parts."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
import mimetypes
from typing import Any

from agentscope.message import Base64Source, DataBlock, TextBlock, URLSource

from domain.errors import ValidationError

from .dashscope_multimodal import DashScopeNativeDataBlock


def _media_type(url: str, payload: Mapping[str, Any], fallback: str) -> str:
    explicit = payload.get("mediaType") or payload.get("media_type")
    if explicit:
        return str(explicit)
    guessed, _ = mimetypes.guess_type(url)
    return guessed or fallback


def _data_block(
    url: str,
    *,
    media_type: str,
    video_options: Mapping[str, Any] | None = None,
) -> DataBlock:
    options = dict(video_options or {})
    native_options = {
        field: options.get(field, options.get(camel))
        for field, camel in (
            ("fps", "fps"),
            ("min_pixels", "minPixels"),
            ("max_pixels", "maxPixels"),
            ("total_pixels", "totalPixels"),
        )
        if options.get(field, options.get(camel)) is not None
    }
    if url.startswith("data:"):
        try:
            header, encoded = url.split(",", 1)
            declared = header[5:].split(";", 1)[0] or media_type
            if ";base64" not in header:
                raise ValueError("not base64")
            base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValidationError("非法 media data URL") from exc
        source = Base64Source(data=encoded, media_type=declared)
    else:
        source = URLSource(url=url, media_type=media_type)
    if media_type.startswith("video/"):
        return DashScopeNativeDataBlock(source=source, **native_options)
    return DataBlock(source=source)


def native_content_blocks(
    parts: Sequence[Mapping[str, Any]],
    *,
    seen_media: set[tuple[str, str]] | None = None,
) -> list[TextBlock | DataBlock]:
    blocks: list[TextBlock | DataBlock] = []
    observed_media = seen_media if seen_media is not None else set()
    for part in parts:
        part_type = part.get("type")
        if part_type == "text":
            blocks.append(TextBlock(text=str(part.get("text") or "")))
            continue
        if part_type in {"image_url", "video_url"}:
            key = str(part_type)
            payload = part.get(key)
            if not isinstance(payload, Mapping) or not payload.get("url"):
                raise ValidationError(f"{key} content part 缺少 URL")
            url = str(payload["url"])
            attachment = part.get("attachment")
            attachment_ref = (
                str(attachment.get("assetVersionRef") or "")
                if isinstance(attachment, Mapping)
                else ""
            )
            if attachment_ref.startswith("asset-version:"):
                attachment_ref = attachment_ref[len("asset-version:") :]
            identity = str(payload.get("versionId") or attachment_ref)
            media_identity = (key, identity or f"url:{url}")
            if media_identity in observed_media:
                continue
            observed_media.add(media_identity)
            fallback = "image/png" if part_type == "image_url" else "video/mp4"
            video_options = dict(payload) if part_type == "video_url" else None
            if video_options is not None:
                video_options.setdefault("fps", 0.1)
            blocks.append(
                _data_block(
                    url,
                    media_type=_media_type(url, payload, fallback),
                    video_options=video_options,
                ),
            )
            continue
        if part_type in {"audio", "document"}:
            attachment = part.get("attachment")
            if not isinstance(attachment, Mapping):
                raise ValidationError(
                    f"{part_type} content part 缺少 attachment",
                )
            canonical_text = attachment.get("canonicalText") or attachment.get(
                "text",
            )
            if part_type == "document" and canonical_text is not None:
                provenance = (
                    attachment.get("versionId")
                    or attachment.get("url")
                    or "document"
                )
                blocks.append(
                    TextBlock(
                        text=f"[规范文档提取物 provenance={provenance}]\n{canonical_text}",
                    ),
                )
                continue
            if part_type == "document":
                raise ValidationError("当前模型只接受带 provenance 的规范文档提取物")
            url = str(attachment.get("url") or "")
            if not url:
                raise ValidationError("audio attachment 缺少 URL")
            blocks.append(
                _data_block(
                    url,
                    media_type=_media_type(url, attachment, "audio/wav"),
                ),
            )
            continue
        raise ValidationError(f"未知 Creator content part: {part_type!r}")
    return blocks


__all__ = ["native_content_blocks"]
