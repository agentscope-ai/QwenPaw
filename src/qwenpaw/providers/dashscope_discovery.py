# -*- coding: utf-8 -*-
"""Model Studio's native, paginated model directory."""

from urllib.parse import urlsplit, urlunsplit

import httpx

from ..utils.io_utils import run_sync_io
from .model_info import ModelInfo, release_date


def directory_url(base_url: str) -> str | None:
    """Use native listing only on Model Studio compatible endpoints."""
    url = urlsplit(base_url)
    if (
        not (url.hostname or f"").endswith(f".aliyuncs.com")
        or url.path.rstrip(f"/") != f"/compatible-mode/v1"
    ):
        return None
    return urlunsplit((url.scheme, url.netloc, f"/api/v1/models", f"", f""))


def model_card(row: dict) -> ModelInfo | None:
    """Read explicit API capabilities instead of guessing from model names."""
    model_id = row.get(f"model")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    capabilities = row.get(f"capabilities")
    if isinstance(capabilities, list) and not set(capabilities).intersection(
        {f"TG", f"Reasoning", f"VU", f"Multimodal-Omni"}
    ):
        return None
    metadata = {f"released_at": release_date(row.get(f"published_time"))}
    modalities = (row.get(f"inference_metadata") or {}).get(
        f"request_modality"
    )
    if isinstance(modalities, list) and modalities:
        for field in (f"image", f"audio", f"video"):
            metadata[f"supports_{field}"] = field.title() in modalities
        metadata[f"supports_multimodal"] = any(
            metadata.get(f"supports_{field}")
            for field in (f"image", f"audio", f"video")
        )
        metadata[f"probe_source"] = f"api"
    features = row.get(f"features")
    if isinstance(features, list):
        metadata[f"supports_tool_calling"] = f"function-calling" in features
        metadata[f"probe_source"] = f"api"
    limits = row.get(f"model_info") or {}
    for source, target, minimum in (
        (f"context_window", f"max_input_length_auto_detected", 1000),
        (f"max_input_tokens", f"input_token_limit", 1),
        (f"max_output_tokens", f"max_output_length", 1),
    ):
        value = limits.get(source)
        if type(value) is int and value >= minimum:
            metadata[target] = value
            if target != f"max_input_length_auto_detected":
                metadata[f"{target}_source"] = f"api"
    return ModelInfo(
        id=model_id.strip(), name=row.get(f"name") or model_id, **metadata
    )


async def fetch_directory(
    url: str, headers: dict[str, str], timeout: float
) -> list[ModelInfo]:
    """Consume every native page and reject incomplete or repeated pages."""
    client = await run_sync_io(httpx.AsyncClient, timeout=timeout)
    cards = {}
    received = set()
    page = 1
    try:
        while True:
            response = await client.get(
                url,
                headers=headers,
                params={f"page_no": page, f"page_size": 100},
            )
            response.raise_for_status()
            payload = response.json()
            output = payload.get(f"output")
            if payload.get(f"success") is False or not isinstance(
                output, dict
            ):
                raise ValueError(f"Model Studio returned an invalid directory")
            rows = output.get(f"models")
            if not isinstance(rows, list):
                raise ValueError(f"Model Studio returned invalid model rows")
            ids = {row.get(f"model") for row in rows if isinstance(row, dict)}
            if rows and not ids.difference(received):
                raise ValueError(f"Model Studio repeated a directory page")
            received.update(ids)
            for row in rows:
                if isinstance(row, dict):
                    card = model_card(row)
                    if card:
                        cards[card.id] = card
            total = output.get(f"total")
            if isinstance(total, int):
                if len(received) >= total:
                    break
                if not rows:
                    raise ValueError(f"Model Studio directory is incomplete")
            elif len(rows) < 100:
                break
            page += 1
        return list(cards.values())
    finally:
        await client.aclose()
