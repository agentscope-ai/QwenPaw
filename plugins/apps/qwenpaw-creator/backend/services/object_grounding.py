# -*- coding: utf-8 -*-
"""VLM-backed object localization with normalized and pixel bounding boxes."""

from __future__ import annotations

import io
import json
import math
import re
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from models import config as model_config
from models import vlm_model
from models.media_transport import validate_reference_image_bytes

OBJECT_GROUNDING_SYSTEM_PROMPT = (
    "You are an object-localization node for QwenPaw Creator. "
    "Detect only the objects requested by the user. Return strict JSON only "
    "as an array of objects with this schema: "
    '[{"label":"name","bbox_2d":[x1,y1,x2,y2]}]. '
    "bbox_2d coordinates are normalized integers from 0 to 1000. "
    "Do not include prose, markdown, confidence, or unrequested objects."
)

_REF_RE = re.compile(r"<ref>(.*?)</ref>", re.DOTALL)
_BOX_RE = re.compile(
    r"<box>\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)"
    r"\s*,\s*\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)</box>",
)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
MAX_OBJECT_GROUNDING_PIXELS = 50_000_000


def object_grounding_image_suffix(content: bytes) -> str:
    """Return a safe extension derived from decoded image bytes."""
    _image_size(content)
    with Image.open(io.BytesIO(content)) as image:
        image_format = str(image.format or "").upper()
    return {
        "JPEG": ".jpg",
        "PNG": ".png",
        "WEBP": ".webp",
        "GIF": ".gif",
        "BMP": ".bmp",
    }.get(image_format, ".png")


def _image_size(content: bytes) -> tuple[int, int]:
    validate_reference_image_bytes(content)
    with Image.open(io.BytesIO(content)) as image:
        width, height = image.size
    if width * height > MAX_OBJECT_GROUNDING_PIXELS:
        raise ValueError(
            "object grounding image exceeds the 50 megapixel limit",
        )
    return width, height


def _normalized_bbox(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        numbers = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(item) for item in numbers):
        return None
    bbox = [round(item) for item in numbers]
    if not all(0 <= item <= 1000 for item in bbox):
        return None
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return None
    return bbox


def _pixel_bbox(
    bbox: list[int],
    width: int,
    height: int,
) -> list[int]:
    x1, y1, x2, y2 = bbox
    return [
        round(x1 / 1000 * width),
        round(y1 / 1000 * height),
        round(x2 / 1000 * width),
        round(y2 / 1000 * height),
    ]


def _detection(
    label: Any,
    bbox_value: Any,
    width: int,
    height: int,
) -> dict[str, Any] | None:
    bbox = _normalized_bbox(bbox_value)
    if bbox is None:
        return None
    return {
        "label": str(label or "").strip()[:160],
        "bbox_normalized": bbox,
        "bbox_pixel": _pixel_bbox(bbox, width, height),
    }


def _parse_json_detections(
    text: str,
    width: int,
    height: int,
) -> list[dict[str, Any]] | None:
    match = _CODE_FENCE_RE.search(text)
    raw = match.group(1).strip() if match else text.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        payload = (
            payload.get("detections")
            or payload.get("objects")
            or payload.get("results")
            or []
        )
    if not isinstance(payload, list):
        return None
    detections: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        detection = _detection(
            item.get("label") or item.get("name") or item.get("object") or "",
            item.get("bbox_2d")
            or item.get("bbox")
            or item.get("box")
            or item.get("bounding_box"),
            width,
            height,
        )
        if detection is not None:
            detections.append(detection)
    return detections or None


def _parse_ref_box_detections(
    text: str,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []
    refs = list(_REF_RE.finditer(text))
    for index, ref_match in enumerate(refs):
        start = ref_match.end()
        end = refs[index + 1].start() if index + 1 < len(refs) else len(text)
        for box_match in _BOX_RE.finditer(text[start:end]):
            detection = _detection(
                ref_match.group(1),
                [box_match.group(item) for item in range(1, 5)],
                width,
                height,
            )
            if detection is not None:
                detections.append(detection)
    return detections


def parse_object_grounding(
    text: str,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    """Parse JSON first and retain the upstream ref/box compatibility form."""
    detections = _parse_json_detections(text, width, height)
    if detections is None:
        detections = _parse_ref_box_detections(text, width, height)
    seen: set[tuple[str, tuple[int, ...]]] = set()
    deduped: list[dict[str, Any]] = []
    for detection in detections:
        key = (
            str(detection["label"]).casefold(),
            tuple(detection["bbox_normalized"]),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(detection)
    return deduped


async def ground_image_objects(
    content: bytes,
    image_url: str,
    prompt: str,
) -> dict[str, Any]:
    """Locate requested objects in one validated image with Creator's VLM."""
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ValueError("object grounding prompt is required")
    if len(clean_prompt) > 1000:
        raise ValueError("object grounding prompt exceeds 1000 characters")
    width, height = _image_size(content)
    raw_response = await vlm_model.chat_completion(
        [
            vlm_model.multimodal_media_part(image_url, "image"),
            {
                "type": "text",
                "text": (
                    f"Detect and locate: {clean_prompt}. "
                    "Return only the requested JSON array."
                ),
            },
        ],
        system_prompt=OBJECT_GROUNDING_SYSTEM_PROMPT,
        temperature=0.0,
        max_tokens=2048,
        timeout=float(model_config.get_vlm_timeout_seconds()),
    )
    return {
        "imageSize": {"width": width, "height": height},
        "detections": parse_object_grounding(
            raw_response,
            width,
            height,
        ),
        "rawResponse": raw_response,
        "model": model_config.get_vlm_model_name(),
    }


def render_object_grounding_annotation(
    content: bytes,
    detections: list[dict[str, Any]],
) -> bytes:
    """Draw bounding boxes into a PNG without changing the source image."""
    _image_size(content)
    with Image.open(io.BytesIO(content)) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    line_width = max(2, min(image.size) // 200)
    font = ImageFont.load_default()
    colors = (
        (239, 68, 68),
        (34, 197, 94),
        (59, 130, 246),
        (234, 179, 8),
        (168, 85, 247),
        (6, 182, 212),
    )
    for index, detection in enumerate(detections):
        bbox = detection.get("bbox_pixel")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        color = colors[index % len(colors)]
        draw.rectangle(tuple(bbox), outline=color, width=line_width)
        label = str(detection.get("label") or "").strip()
        if not label:
            continue
        try:
            bounds = draw.textbbox((0, 0), label, font=font)
            text_width = bounds[2] - bounds[0]
            text_height = bounds[3] - bounds[1]
            label_y = max(0, int(bbox[1]) - text_height - 6)
            draw.rectangle(
                (
                    int(bbox[0]),
                    label_y,
                    int(bbox[0]) + text_width + 6,
                    label_y + text_height + 6,
                ),
                fill=color,
            )
            draw.text(
                (int(bbox[0]) + 3, label_y + 2),
                label,
                fill=(255, 255, 255),
                font=font,
            )
        except UnicodeEncodeError:
            # The box remains useful when the default Pillow font cannot
            # encode a provider-returned label on a minimal installation.
            continue
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


__all__ = [
    "ground_image_objects",
    "object_grounding_image_suffix",
    "parse_object_grounding",
    "render_object_grounding_annotation",
]
