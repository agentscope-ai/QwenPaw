# -*- coding: utf-8 -*-
"""Vision prepass prompt and normalization helpers.

OpenClaw-aligned: free-form description output instead of rigid JSON schema.
"""

from __future__ import annotations

from typing import Literal

_MAX_DESCRIPTION_CHARS = 500


def build_vlm_prepass_prompt(user_text: str, selected_image_count: int) -> str:
    """Build a simple, free-form image description prompt.

    Mirrors OpenClaw's approach: ask the VLM to describe the image in natural
    language rather than demanding a rigid JSON schema.  This produces richer,
    more reliable output from most VLMs.
    """
    parts = [
        "You are a vision preprocessor. "
        "Describe the provided image(s) concisely and accurately.",
        "Include: visible text (OCR), key objects/entities, layout, and any ambiguities.",
        "Do NOT answer the user's question directly — only describe what you see.",
        "Do NOT claim you cannot view the image.",
        "Do NOT request external tools.",
    ]
    if selected_image_count > 1:
        parts.append(f"Number of images: {selected_image_count}")
    if user_text and user_text.strip():
        parts.append(f"User's task context (for relevance): {user_text.strip()}")
    return "\n".join(parts)


def normalize_vlm_prepass_output(raw: str) -> str:
    """Pass through free-form VLM description, trimming to size limit."""
    text = (raw or "").strip()
    if not text:
        return ""
    if len(text) > _MAX_DESCRIPTION_CHARS:
        text = text[:_MAX_DESCRIPTION_CHARS - 3] + "..."
    return text


def format_vlm_prepass_context(
    capability: Literal["image", "audio", "video"],
    description: str,
    *,
    user_text: str = "",
    include_user_text: bool = True,
) -> str:
    """Render VLM description into OpenClaw-style section text."""
    text = (description or "").strip()
    if not text:
        return ""

    label = {
        "image": "Image",
        "audio": "Audio",
        "video": "Video",
    }.get(capability, "Media")

    content_title = "Transcript" if capability == "audio" else "Description"
    lines: list[str] = [f"[{label}]"]
    cleaned_user_text = (user_text or "").strip()
    if include_user_text and cleaned_user_text:
        lines.append(f"User text:\n{cleaned_user_text}")
    lines.append(f"{content_title}:\n{text}")
    return "\n".join(lines)

