# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,too-many-branches,too-many-statements
"""Provider search aggregation, fallback, and result deduplication."""

from __future__ import annotations

import asyncio
import io
import math
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from models import media_transport as _media_transport
from services.runtime_files.safe_remote_download import (
    safe_download_bytes as _safe_download_bytes,
)
from services.runtime_files.safe_remote_download import (
    validate_public_remote_url as _validate_public_remote_url,
)
from services.storage_root import require_creator_data_root
from utils.logger import setup_logger
from utils.paths import local_path_from_file_url as _local_path_from_file_url
from utils.paths import media_path_from_url as _media_path_from_url

from ..staging import sniff_image_media_type as _sniff_image_media_type
from ..staging import validate_raster_image as _validate_raster_image
from ..staging import visual_download_max_bytes as _visual_download_max_bytes
from ..triage import _clean_query
from .adapters import _search_dashscope_web_search_image_visuals
from .adapters import _search_dashscope_web
from .adapters import _extract_serper_pages
from .adapters import _search_serper
from .adapters import _search_serper_lens
from .adapters import _search_serper_visuals
from .adapters import _search_tavily
from .adapters import _search_tavily_visuals
from .config import dashscope_api_key as _dashscope_web_search_image_api_key
from .config import (
    dashscope_web_search_api_key as _dashscope_web_search_api_key,
)
from .config import (
    is_retryable_visual_search_error as _is_retryable_visual_search_error,
)
from .config import (
    dashscope_native_search_unavailable_reason as _dashscope_native_search_unavailable_reason,
)
from .config import serper_api_key as _serper_api_key
from .config import tavily_api_key as _tavily_api_key
from .config import (
    visual_search_min_results_for_fallback as _visual_search_min_results_for_fallback,
)
from .config import (
    visual_search_provider_order as _visual_search_provider_order,
)

DEFAULT_MAX_SOURCES = 6
DEFAULT_TIMEOUT = 60.0
DEFAULT_TEXT_SEARCH_TIMEOUT = 60.0
DEFAULT_TEXT_SEARCH_RETRIES = 1
DEFAULT_VISUAL_SEARCH_TIMEOUT = 120.0
DEFAULT_VISUAL_SEARCH_RETRIES = 1
USER_AGENT = "QwenPaw-Creator/0.1 web-grounding"
logger = setup_logger("services.web_grounding.providers.search")


def _dedupe_sources(
    sources: list[dict[str, Any]],
    max_sources: int,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for source in sources:
        url = str(source.get("url") or "").strip()
        if url:
            key = f"url:{url.casefold()}"
        else:
            metadata = (
                str(source.get(field) or "").strip().casefold()
                for field in ("title", "query", "provider", "snippet")
            )
            key = "metadata:" + "\x1f".join(metadata)
            if key == "metadata:\x1f\x1f\x1f":
                continue
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(source)
        if len(deduped) >= max_sources:
            break
    return deduped


def _dedupe_visual_sources(
    sources: list[dict[str, Any]],
    max_sources: int,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for source in sources:
        url = str(source.get("url") or "").strip()
        key = url.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(source)
        if len(deduped) >= max_sources:
            break
    for index, source in enumerate(deduped, start=1):
        source["index"] = index
    return deduped


def _dedupe_visual_sources_with_query_coverage(
    sources: list[dict[str, Any]],
    *,
    query_order: list[str],
    max_sources: int,
) -> list[dict[str, Any]]:
    """Prefer one candidate per visual query before filling globally."""
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []

    def add(source: dict[str, Any]) -> bool:
        url = str(source.get("url") or "").strip()
        key = url.lower()
        if not key or key in seen:
            return False
        seen.add(key)
        selected.append(source)
        return len(selected) >= max_sources

    for query in query_order:
        clean_query = _clean_query(query)
        if not clean_query:
            continue
        for source in sources:
            if _clean_query(source.get("query")) != clean_query:
                continue
            if add(source):
                break
        if len(selected) >= max_sources:
            break
    if len(selected) < max_sources:
        for source in sources:
            if add(source):
                break
    for index, source in enumerate(selected, start=1):
        source["index"] = index
    return selected


async def search_web(
    query: str,
    *,
    max_sources: int = DEFAULT_MAX_SOURCES,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Run Tavily, then Serper, then DashScope/Qwen web search."""
    query = _clean_query(query)
    if not query:
        return {
            "query": query,
            "sources": [],
            "issues": ["empty_query"],
            "provider": "",
            "providers": [],
            "providers_attempted": [],
        }
    logger.info(
        "Web grounding search started query=%r max_sources=%d timeout=%s",
        query,
        max_sources,
        timeout,
    )
    headers = {"User-Agent": USER_AGENT}
    issues: list[str] = []
    providers: list[str] = []
    providers_attempted: list[str] = []
    sources: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        if _tavily_api_key():
            providers_attempted.append("tavily")
            try:
                sources = await _search_tavily(client, query, max_sources)
            except Exception as exc:
                issues.append(f"tavily:{exc.__class__.__name__}: {exc}")
                logger.warning(
                    "Web grounding provider failed query=%r provider=tavily error=%s",
                    query,
                    exc,
                )
            if sources:
                providers.append("tavily")
            else:
                issues.append("tavily:no_text_sources")
        else:
            issues.append("tavily_api_key_missing")
            logger.info(
                "Web grounding provider skipped query=%r provider=tavily reason=api_key_missing",
                query,
            )

        if not sources:
            if _serper_api_key():
                providers_attempted.append("serper")
                serper_sources: list[dict[str, Any]] = []
                try:
                    serper_sources = await _search_serper(
                        client,
                        query,
                        max_sources,
                    )
                except Exception as exc:
                    issues.append(f"serper:{exc.__class__.__name__}: {exc}")
                    logger.warning(
                        "Web grounding provider failed query=%r provider=serper error=%s",
                        query,
                        exc,
                    )
                if serper_sources:
                    sources = serper_sources
                    providers.append("serper")
                else:
                    issues.append("serper:no_text_sources")
            else:
                issues.append("serper_api_key_missing")
                logger.info(
                    "Web grounding provider skipped query=%r provider=serper reason=api_key_missing",
                    query,
                )

        if not sources:
            native_search_key = _dashscope_web_search_api_key()
            native_search_issue = _dashscope_native_search_unavailable_reason(
                api_key_override=native_search_key,
            )
            if native_search_key and not native_search_issue:
                providers_attempted.append("dashscope_web_search")
                effective_timeout = max(
                    float(timeout),
                    DEFAULT_TEXT_SEARCH_TIMEOUT,
                )
                last_exc: Exception | None = None
                async with httpx.AsyncClient(
                    timeout=effective_timeout,
                    follow_redirects=True,
                    headers=headers,
                ) as dashscope_client:
                    for attempt in range(DEFAULT_TEXT_SEARCH_RETRIES + 1):
                        try:
                            sources = await _search_dashscope_web(
                                dashscope_client,
                                query,
                                max_sources,
                            )
                            if sources and attempt:
                                issues.append(
                                    f"dashscope_web_search:retry_succeeded:{attempt + 1}",
                                )
                            break
                        except Exception as exc:
                            last_exc = exc
                            retryable = _is_retryable_visual_search_error(exc)
                            logger.warning(
                                "Web grounding provider failed query=%r provider=dashscope_web_search attempt=%d/%d retryable=%s error=%s",
                                query,
                                attempt + 1,
                                DEFAULT_TEXT_SEARCH_RETRIES + 1,
                                retryable,
                                exc,
                            )
                            if (
                                not retryable
                                or attempt >= DEFAULT_TEXT_SEARCH_RETRIES
                            ):
                                break
                            await asyncio.sleep(0.25 * (attempt + 1))
                if last_exc is not None and not sources:
                    issues.append(
                        f"dashscope_web_search:{last_exc.__class__.__name__}: {last_exc}",
                    )
                    if _is_retryable_visual_search_error(last_exc):
                        issues.append("dashscope_web_search:retry_exhausted")
                if sources:
                    providers.append("dashscope_web_search")
                else:
                    issues.append("dashscope_web_search:no_text_sources")
            else:
                issues.append(
                    (
                        "dashscope_web_search_api_key_missing"
                        if not native_search_key
                        else f"dashscope_web_search:{native_search_issue}"
                    ),
                )
                logger.info(
                    "Web grounding provider skipped query=%r provider=dashscope_web_search reason=%s",
                    query,
                    native_search_issue or "api_key_missing",
                )
    sources = _dedupe_sources(sources, max_sources=max_sources)
    logger.info(
        "Web grounding search completed query=%r providers=%s sources=%d issues=%d",
        query,
        ",".join(providers),
        len(sources),
        len(issues),
    )
    return {
        "query": query,
        "sources": sources,
        "issues": issues,
        "provider": providers[-1] if providers else "",
        "providers": providers,
        "providers_attempted": providers_attempted,
    }


async def extract_web_pages(
    urls: list[str],
    *,
    goal: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Extract public pages through Serper without letting one URL abort all."""
    normalized_urls = list(
        dict.fromkeys(
            str(url or "").strip() for url in urls if str(url or "").strip()
        ),
    )
    result: dict[str, Any] = {
        "goal": _clean_query(goal),
        "sources": [],
        "issues": [],
        "provider": "",
        "providers": [],
        "providers_attempted": [],
    }
    if not normalized_urls:
        result["issues"].append("serper_scrape:empty_urls")
        return result
    if not _serper_api_key():
        result["issues"].append("serper_api_key_missing")
        return result
    result["providers_attempted"].append("serper_scrape")
    async with httpx.AsyncClient(
        timeout=max(float(timeout), DEFAULT_TEXT_SEARCH_TIMEOUT),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for raw_url in normalized_urls:
            try:
                public_url = await asyncio.to_thread(
                    _validate_public_remote_url,
                    raw_url,
                )
                pages = await _extract_serper_pages(
                    client,
                    [public_url],
                    goal=result["goal"],
                )
                if pages:
                    result["sources"].extend(pages)
                else:
                    result["issues"].append(
                        f"serper_scrape:no_content:{public_url}",
                    )
            except Exception as exc:
                result["issues"].append(
                    f"serper_scrape:{exc.__class__.__name__}: {exc}",
                )
    if result["sources"]:
        result["provider"] = "serper_scrape"
        result["providers"].append("serper_scrape")
    return result


async def search_visual_refs(
    query: str,
    *,
    max_sources: int = DEFAULT_MAX_SOURCES,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Run configured image/reference search providers for one query."""
    query = _clean_query(query)
    if not query:
        return {
            "query": query,
            "visual_sources": [],
            "issues": ["empty_query"],
            "provider": "",
            "providers": [],
        }
    providers = _visual_search_provider_order()
    min_results = _visual_search_min_results_for_fallback()
    effective_timeout = max(float(timeout), DEFAULT_VISUAL_SEARCH_TIMEOUT)
    logger.info(
        "Visual grounding search started query=%r providers=%s max_sources=%d timeout=%s",
        query,
        ",".join(providers),
        max_sources,
        effective_timeout,
    )
    headers = {"User-Agent": USER_AGENT}
    issues: list[str] = []
    collected: list[dict[str, Any]] = []
    used_providers: list[str] = []
    attempted_providers: list[str] = []
    if not providers:
        if not _tavily_api_key():
            issues.append("tavily_api_key_missing")
        if not _serper_api_key():
            issues.append("serper_api_key_missing")
        native_search_key = _dashscope_web_search_image_api_key()
        native_search_issue = _dashscope_native_search_unavailable_reason(
            api_key_override=native_search_key,
        )
        issues.append(
            (
                "dashscope_web_search_image_api_key_missing"
                if not native_search_key
                else f"dashscope_web_search_image:{native_search_issue}"
            ),
        )
    async with httpx.AsyncClient(
        timeout=effective_timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        for provider in providers:
            remaining = max_sources - len(
                _dedupe_visual_sources(collected, max_sources=max_sources),
            )
            if remaining <= 0:
                break
            provider_sources: list[dict[str, Any]]
            if provider == "tavily":
                if not _tavily_api_key():
                    issues.append("tavily_api_key_missing")
                    logger.info(
                        "Visual grounding provider skipped query=%r provider=tavily reason=api_key_missing",
                        query,
                    )
                    continue
                attempted_providers.append(provider)
                try:
                    provider_sources = await _search_tavily_visuals(
                        client,
                        query,
                        remaining,
                    )
                except Exception as exc:
                    provider_sources = []
                    issues.append(
                        f"tavily_images:{exc.__class__.__name__}: {exc}",
                    )
                    logger.warning(
                        "Visual grounding provider failed query=%r provider=tavily error=%s",
                        query,
                        exc,
                    )
            elif provider == "serper":
                if not _serper_api_key():
                    issues.append("serper_api_key_missing")
                    logger.info(
                        "Visual grounding provider skipped query=%r provider=serper reason=api_key_missing",
                        query,
                    )
                    continue
                attempted_providers.append(provider)
                try:
                    provider_sources = await _search_serper_visuals(
                        client,
                        query,
                        remaining,
                    )
                except Exception as exc:
                    provider_sources = []
                    issues.append(
                        f"serper_images:{exc.__class__.__name__}: {exc}",
                    )
                    logger.warning(
                        "Visual grounding provider failed query=%r provider=serper error=%s",
                        query,
                        exc,
                    )
            elif provider == "dashscope_web_search_image":
                native_search_key = _dashscope_web_search_image_api_key()
                native_search_issue = (
                    _dashscope_native_search_unavailable_reason(
                        api_key_override=native_search_key,
                    )
                )
                if not native_search_key or native_search_issue:
                    issues.append(
                        (
                            "dashscope_web_search_image_api_key_missing"
                            if not native_search_key
                            else f"dashscope_web_search_image:{native_search_issue}"
                        ),
                    )
                    logger.info(
                        "Visual grounding provider skipped query=%r provider=dashscope_web_search_image reason=%s",
                        query,
                        native_search_issue or "api_key_missing",
                    )
                    continue
                attempted_providers.append(provider)
                last_exc: BaseException | None = None
                provider_sources = []
                for attempt in range(DEFAULT_VISUAL_SEARCH_RETRIES + 1):
                    try:
                        provider_sources = (
                            await _search_dashscope_web_search_image_visuals(
                                client,
                                query,
                                remaining,
                            )
                        )
                        if attempt:
                            issues.append(
                                f"dashscope_web_search_image:retry_succeeded:{attempt + 1}",
                            )
                        break
                    except Exception as exc:
                        last_exc = exc
                        retryable = _is_retryable_visual_search_error(exc)
                        final_attempt = (
                            attempt >= DEFAULT_VISUAL_SEARCH_RETRIES
                        )
                        logger.warning(
                            "Visual grounding provider failed query=%r provider=dashscope_web_search_image attempt=%d/%d retryable=%s error=%s",
                            query,
                            attempt + 1,
                            DEFAULT_VISUAL_SEARCH_RETRIES + 1,
                            retryable,
                            exc,
                        )
                        if final_attempt or not retryable:
                            break
                        await asyncio.sleep(1.0)
                if last_exc is not None and (not provider_sources):
                    issues.append(
                        f"dashscope_web_search_image:{last_exc.__class__.__name__}: {last_exc}",
                    )
                    if _is_retryable_visual_search_error(last_exc):
                        issues.append(
                            "dashscope_web_search_image:retry_exhausted",
                        )
            else:
                issues.append(f"unknown_visual_provider:{provider}")
                continue
            if provider_sources:
                used_providers.append(provider)
                collected.extend(provider_sources)
                deduped_count = len(
                    _dedupe_visual_sources(collected, max_sources=max_sources),
                )
                if deduped_count >= min_results:
                    break
            else:
                issues.append(f"{provider}:no_visual_sources")
    visual_sources = _dedupe_visual_sources(collected, max_sources=max_sources)
    logger.info(
        "Visual grounding search completed query=%r providers=%s visual_sources=%d issues=%d",
        query,
        ",".join(used_providers),
        len(visual_sources),
        len(issues),
    )
    return {
        "query": query,
        "visual_sources": visual_sources,
        "issues": issues,
        "provider": used_providers[-1] if used_providers else "",
        "providers": used_providers,
        "providers_attempted": attempted_providers,
    }


def _lens_local_media_path(ref: str) -> Path:
    """Resolve a local ref and confine it to the Creator data root.

    The grounding context is model-controlled, so an arbitrary filesystem
    path here would let a prompt-injected run exfiltrate any readable file
    through the presigned-URL round trip. Symlinks are resolved before the
    containment check.
    """
    if ref.startswith("file://"):
        candidate = _local_path_from_file_url(ref)
    elif ref.startswith("/generated/"):
        candidate = _media_path_from_url(ref)
    else:
        candidate = Path(ref)
    resolved = candidate.expanduser().resolve()
    root = require_creator_data_root(create=False).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(
            "local reference images must be Creator media files inside "
            "CREATOR_DATA_ROOT",
        )
    return resolved


def _lens_local_image_payload(ref: str) -> tuple[bytes, str]:
    """Read and validate a confined local image for the Lens round trip."""
    path = _lens_local_media_path(ref)
    if not path.is_file():
        raise ValueError(f"image not found: {path}")
    max_bytes = _visual_download_max_bytes()
    if path.stat().st_size > max_bytes:
        raise ValueError(
            f"image exceeds the {max_bytes} byte visual reference limit",
        )
    payload = path.read_bytes()
    _sniff_image_media_type(payload)
    _validate_raster_image(payload)
    return payload, path.name


def _normalized_lens_bbox(
    bbox: list[float] | None,
) -> tuple[float, ...] | None:
    if bbox is None:
        return None
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError("bbox must contain [x1, y1, x2, y2]")
    values = tuple(float(value) for value in bbox)
    if any(not math.isfinite(value) for value in values):
        raise ValueError("bbox coordinates must be finite")
    x1, y1, x2, y2 = values
    if not all(0.0 <= value <= 1000.0 for value in values):
        raise ValueError("bbox coordinates must be between 0 and 1000")
    if x2 <= x1 or y2 <= y1:
        raise ValueError("bbox must have positive width and height")
    if values == (0.0, 0.0, 1000.0, 1000.0):
        return None
    return values


def _crop_lens_image_payload(
    payload: bytes,
    filename: str,
    bbox: list[float] | None,
) -> tuple[bytes, str]:
    normalized = _normalized_lens_bbox(bbox)
    if normalized is None:
        return payload, filename
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            x1, y1, x2, y2 = normalized
            left = max(0, min(image.width - 1, int(x1 * image.width / 1000)))
            top = max(0, min(image.height - 1, int(y1 * image.height / 1000)))
            right = max(
                left + 1,
                min(image.width, math.ceil(x2 * image.width / 1000)),
            )
            bottom = max(
                top + 1,
                min(image.height, math.ceil(y2 * image.height / 1000)),
            )
            cropped = image.crop((left, top, right, bottom)).convert("RGB")
            output = io.BytesIO()
            cropped.save(output, format="JPEG", quality=90)
    except Exception as exc:
        raise ValueError(f"bbox crop failed: {exc}") from exc
    return output.getvalue(), f"{Path(filename).stem or 'reference'}-crop.jpg"


async def _lens_host_image_payload(
    payload: bytes,
    filename: str,
) -> tuple[str, list[str], str]:
    """Host a validated image via configured OSS or automatic Uguu fallback."""
    readiness = _media_transport.creator_oss_readiness()
    status = str(readiness.get("status") or "invalid")
    issues: list[str] = []
    if status == "ready":
        try:
            signed_url = (
                await _media_transport.upload_image_for_temporary_public_url(
                    payload,
                    filename,
                )
            )
            return signed_url, issues, "creator_oss"
        except Exception as exc:
            issues.append(
                f"serper_lens:creator_oss_upload_failed:{exc.__class__.__name__}: {exc}",
            )
    elif status != "absent":
        blockers = "; ".join(readiness.get("blockers") or [])
        issues.append(
            f"serper_lens:creator_oss_invalid: {blockers or 'invalid OSS configuration'}",
        )
    try:
        public_url = await _media_transport.upload_image_to_uguu_for_temporary_public_url(
            payload,
            filename,
        )
        validated_url = await asyncio.to_thread(
            _validate_public_remote_url,
            public_url,
        )
        return validated_url, issues, "uguu"
    except Exception as exc:
        issues.append(
            f"serper_lens:uguu_upload_failed:{exc.__class__.__name__}: {exc}",
        )
        return "", issues, "uguu"


async def _lens_local_image_url(
    ref: str,
    bbox: list[float] | None,
) -> tuple[str, list[str], str]:
    try:
        payload, filename = _lens_local_image_payload(ref)
        payload, filename = _crop_lens_image_payload(payload, filename, bbox)
    except Exception as exc:
        return (
            "",
            [f"serper_lens:invalid_local_image_reference: {exc}"],
            "",
        )
    return await _lens_host_image_payload(payload, filename)


async def _lens_public_image_url(
    image_ref: str,
    bbox: list[float] | None = None,
) -> tuple[str, list[str], str]:
    """Resolve *image_ref* into a public URL Serper Lens can fetch.

    Returns ``(url, issues, transport)``. Lens only
    accepts a public http(s) ``{"url"}`` payload (no base64/upload form);
    http(s) inputs must pass the SSRF public-address policy, DashScope
    temporary ``oss://`` URLs are not public. Local media prefers configured
    Creator OSS and falls back to the Uguu temporary host when OSS is absent,
    incomplete, or fails during upload/signing.
    """
    ref = str(image_ref or "").strip()
    if not ref:
        return "", ["serper_lens:empty_image_reference"], ""
    if ref.startswith(("http://", "https://")):
        try:
            public_url = await asyncio.to_thread(
                _validate_public_remote_url,
                ref,
            )
            if _normalized_lens_bbox(bbox) is None:
                return public_url, [], "direct_url"
            payload = await asyncio.to_thread(
                _safe_download_bytes,
                public_url,
                max_bytes=_visual_download_max_bytes(),
                timeout=DEFAULT_VISUAL_SEARCH_TIMEOUT,
            )
            _sniff_image_media_type(payload)
            _validate_raster_image(payload)
            filename = Path(httpx.URL(public_url).path).name or "reference.jpg"
            payload, filename = _crop_lens_image_payload(
                payload,
                filename,
                bbox,
            )
            return await _lens_host_image_payload(payload, filename)
        except Exception as exc:
            return "", [f"serper_lens:non_public_image_url: {exc}"], ""
    if ref.startswith("oss://"):
        return (
            "",
            [
                "serper_lens:oss_url_not_public: DashScope temporary oss:// "
                "URLs resolve only inside DashScope and cannot be fetched by "
                "Serper Lens",
            ],
            "",
        )
    return await _lens_local_image_url(ref, bbox)


async def search_visual_refs_by_image(
    image_ref: str,
    *,
    query: str = "",
    bbox: list[float] | None = None,
    max_sources: int = DEFAULT_MAX_SOURCES,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Reverse image search for one reference image via Serper Lens.

    *image_ref* may be a public http(s) URL or a local image (plain path,
    ``file://`` URL, or canonical ``/generated/...`` media URL). Local/cropped
    media prefers configured Creator OSS and uses the free Uguu temporary host
    whenever OSS is absent, invalid, or fails during upload/signing.
    """
    label = _clean_query(query) or str(image_ref or "").strip()
    result: dict[str, Any] = {
        "query": label,
        "image_reference": (
            str(image_ref or "").strip()
            if str(image_ref or "").startswith(("http://", "https://"))
            else ""
        ),
        "image_reference_kind": (
            "public_url"
            if str(image_ref or "").startswith(("http://", "https://"))
            else "local_media"
        ),
        "image_transport": "",
        "bbox": list(bbox) if bbox is not None else None,
        "visual_sources": [],
        "issues": [],
        "provider": "",
        "providers": [],
        "providers_attempted": [],
    }
    if not _serper_api_key():
        result["issues"].append("serper_api_key_missing")
        logger.info(
            "Visual grounding by image skipped provider=serper_lens reason=api_key_missing",
        )
        return result
    image_url, resolution_issues, transport = await _lens_public_image_url(
        image_ref,
        bbox,
    )
    result["image_transport"] = transport
    result["issues"].extend(resolution_issues)
    if not image_url:
        logger.info(
            "Visual grounding by image skipped issues=%s",
            resolution_issues,
        )
        return result
    effective_timeout = max(float(timeout), DEFAULT_VISUAL_SEARCH_TIMEOUT)
    logger.info(
        "Visual grounding by image started provider=serper_lens max_sources=%d timeout=%s",
        max_sources,
        effective_timeout,
    )
    result["providers_attempted"].append("serper_lens")
    visual_sources: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=effective_timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        try:
            visual_sources = await _search_serper_lens(
                client,
                image_url,
                max_sources,
                query=label,
            )
        except Exception as exc:
            visual_sources = []
            result["issues"].append(
                f"serper_lens:{exc.__class__.__name__}: {exc}",
            )
            logger.warning(
                "Visual grounding by image failed provider=serper_lens error=%s",
                exc,
            )
    visual_sources = _dedupe_visual_sources(
        visual_sources,
        max_sources=max_sources,
    )
    if visual_sources:
        result["providers"].append("serper_lens")
        result["provider"] = "serper_lens"
    else:
        result["issues"].append("serper_lens:no_visual_sources")
    result["visual_sources"] = visual_sources
    logger.info(
        "Visual grounding by image completed provider=serper_lens visual_sources=%d issues=%d",
        len(visual_sources),
        len(result["issues"]),
    )
    return result
