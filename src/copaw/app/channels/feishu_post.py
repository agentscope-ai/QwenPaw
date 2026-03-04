# -*- coding: utf-8 -*-
"""Helpers for parsing Feishu rich-text (post) message content."""

from __future__ import annotations

import json
from typing import Any, Optional


def _get_key(node: dict[str, Any], *keys: str) -> Optional[str]:
    """Return the first non-empty string value for the given keys."""
    for key in keys:
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _get_text(node: dict[str, Any], *keys: str) -> str:
    """Return first non-empty text value without stripping spaces."""
    for key in keys:
        value = node.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _text_from_post_node(node: dict[str, Any], tag: str) -> str:
    """Extract visible text from a post node when available."""
    if tag in ("text", "a", "md"):
        return _get_text(node, "text")
    if tag == "at":
        return _get_text(node, "user_name", "name", "text")
    return ""


def _collect_post_fallback(
    node: Any,
    texts: list[str],
    image_keys: list[str],
    seen_images: set[str],
) -> None:
    """Recursively walk unknown post payload shapes."""
    if isinstance(node, list):
        for item in node:
            _collect_post_fallback(item, texts, image_keys, seen_images)
        return

    if not isinstance(node, dict):
        return

    tag = str(node.get("tag", "") or "").strip().lower()
    text = _text_from_post_node(node, tag).strip()
    if text:
        texts.append(text)

    image_key = _get_key(node, "image_key", "imageKey", "file_key", "fileKey")
    if tag in ("img", "image") and image_key and image_key not in seen_images:
        image_keys.append(image_key)
        seen_images.add(image_key)

    for value in node.values():
        _collect_post_fallback(value, texts, image_keys, seen_images)


def parse_feishu_post_content(
    content: Optional[str],
) -> tuple[list[str], list[str]]:
    """Parse Feishu post JSON into visible text rows and image keys."""
    if not content:
        return [], []

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return [], []

    texts: list[str] = []
    image_keys: list[str] = []
    seen_images: set[str] = set()

    locale_blocks: list[dict[str, Any]] = []
    if isinstance(data, dict):
        if isinstance(data.get("content"), list):
            locale_blocks.append(data)
        for value in data.values():
            if isinstance(value, dict) and isinstance(
                value.get("content"),
                list,
            ):
                locale_blocks.append(value)

    for block in locale_blocks:
        title = block.get("title")
        if isinstance(title, str) and title.strip():
            texts.append(title.strip())

        rows = block.get("content")
        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, list):
                continue
            row_text_parts: list[str] = []
            for item in row:
                if not isinstance(item, dict):
                    continue
                tag = str(item.get("tag", "") or "").strip().lower()
                text = _text_from_post_node(item, tag)
                if text:
                    row_text_parts.append(text)
                image_key = _get_key(
                    item,
                    "image_key",
                    "imageKey",
                    "file_key",
                    "fileKey",
                )
                if (
                    tag in ("img", "image")
                    and image_key
                    and image_key not in seen_images
                ):
                    image_keys.append(image_key)
                    seen_images.add(image_key)
            row_text = "".join(row_text_parts).strip()
            if row_text:
                texts.append(row_text)

    if texts or image_keys:
        return texts, image_keys

    _collect_post_fallback(data, texts, image_keys, seen_images)
    return texts, image_keys
