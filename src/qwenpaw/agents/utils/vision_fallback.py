# -*- coding: utf-8 -*-
"""Vision fallback: describe images via a vision model for text-only agents.

When the active model does not support multimodal input but the conversation
contains image blocks, this module calls a vision-capable model to generate
text descriptions and replaces image blocks in-place with TextBlocks
containing the descriptions.  This allows the primary text-only model to
reason about image content through natural language descriptions.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import unicodedata
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from agentscope.message import DataBlock, Msg, TextBlock, URLSource

logger = logging.getLogger(__name__)

# Prefix/suffix used to mark injected image descriptions so downstream
# logic (and the model itself) knows this is derived content.
_DESC_PREFIX = "[Image Description: "
_DESC_SUFFIX = "]"

# Block types considered as image media
_IMAGE_BLOCK_TYPES = {"image"}
_IMAGE_MIME_PREFIXES = ("image/",)


# ---------------------------------------------------------------------------
# Session-level description cache (keyed by image URL/path hash)
# ---------------------------------------------------------------------------
# The cache is module-level and intentionally short-lived: it avoids
# re-describing the same image if it appears multiple times within the
# current reasoning pass / conversation.  It is not persisted to disk.
# When the caller supplies a session_id and it changes, the cache is
# cleared so that a new conversation does not inherit stale descriptions.
# For long-running processes, clear_description_cache() can also be called
# explicitly (e.g., on agent reload or chat reset).
#
# Concurrency: an ``asyncio.Lock`` protects the cache, the in-flight
# deduplication table, and the counters.  Vision model API calls happen
# OUTSIDE the lock and are limited by a semaphore so that concurrent
# requests can describe different images in parallel.  When two requests
# race for the same image, the first creates an ``asyncio.Future`` in the
# in-flight table; subsequent requests await that future, avoiding the
# "thundering herd" problem.
# ---------------------------------------------------------------------------

# Maximum number of cached descriptions kept in memory.  200 is a
# conservative bound for a single session; long-running agents that
# process many images will evict stale entries via LRU.
_MAX_CACHE_SIZE = 200

_description_cache: OrderedDict[str, str] = OrderedDict()
_in_flight: Dict[str, asyncio.Future[str]] = {}
_last_cleared_session_id: Optional[str] = None
_cache_lock: Optional[asyncio.Lock] = None

# Limit concurrent vision model calls to avoid overwhelming the provider.
_MAX_CONCURRENT_VISION_CALLS = 3
_vision_semaphore: Optional[asyncio.Semaphore] = None


def _get_cache_lock() -> asyncio.Lock:
    """Return the module-level cache lock, lazily creating it.

    Lazy initialisation avoids creating ``asyncio.Lock`` at import time,
    which can raise ``RuntimeError`` or emit deprecation warnings on
    Python versions that require a running event loop to construct the
    primitive.
    """
    global _cache_lock
    if _cache_lock is None:
        _cache_lock = asyncio.Lock()
    return _cache_lock


def _get_vision_semaphore() -> asyncio.Semaphore:
    """Return the module-level vision-call semaphore, lazily creating it."""
    global _vision_semaphore
    if _vision_semaphore is None:
        _vision_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_VISION_CALLS)
    return _vision_semaphore


# Simple observability counters.  These are intentionally module-level so
# that long-running processes can inspect them without adding a heavy
# metrics dependency.  Callers may also read them via get_metrics().
_success_count: int = 0
_failure_count: int = 0


def clear_description_cache() -> None:
    """Clear the session-level image description cache."""
    global _last_cleared_session_id
    _description_cache.clear()
    _in_flight.clear()
    _last_cleared_session_id = None


def _ensure_cache_for_session(session_id: Optional[str]) -> None:
    """Clear the cache when the active session changes."""
    global _last_cleared_session_id
    if session_id is None:
        return
    if _last_cleared_session_id != session_id:
        _description_cache.clear()
        # Any in-flight work for the previous session is no longer useful;
        # clear it to avoid stale results contaminating the new session.
        _in_flight.clear()
        _last_cleared_session_id = session_id


def _set_cache_entry(key: str, value: str) -> None:
    """Store a description in the cache, evicting the oldest if needed."""
    _description_cache[key] = value
    _description_cache.move_to_end(key)
    if len(_description_cache) > _MAX_CACHE_SIZE:
        _description_cache.popitem(last=False)


def get_metrics() -> Dict[str, int]:
    """Return current vision fallback success/failure counters.

    Ops/monitoring: this returns a snapshot dict with ``success``,
    ``failure`` and ``cache_size``.  The same numbers are emitted as a
    structured INFO log line ("Vision fallback: described=... metrics=...")
    at the end of every ``describe_images_in_messages`` call, so operators
    can track the vision-fallback success/failure rate by scraping logs or
    by periodically polling this function from a health/metrics endpoint.
    Counters are process-lifetime cumulative (reset only via
    ``_reset_metrics`` in tests or a process restart).
    """
    return {
        "success": _success_count,
        "failure": _failure_count,
        "cache_size": len(_description_cache),
    }


def _reset_metrics() -> None:
    """Reset vision fallback counters (intended for tests)."""
    global _success_count, _failure_count
    _success_count = 0
    _failure_count = 0


# Patterns that may indicate prompt-injection attempts embedded in a
# vision model description.  These are heuristic and intentionally loose:
# the goal is to flag obviously suspicious content, not to perfectly
# classify adversarial text.
_SUSPICIOUS_DESCRIPTION_PATTERNS = (
    r"(?i)ignore\s+(previous|above|prior)\s+(instruction|instructions|prompt)",
    r"(?i)^\s*(system|assistant|user)\s*[:：]",
    r"(?i)^\s*you\s+are\s+(now|from\s+now\s+on)\s+",
)


def _sanitize_description_text(text: str) -> str:
    """Normalize and defang a vision-model description before injection.

    Removes control characters, collapses whitespace to a single line,
    and logs a warning if the description contains suspicious
    instruction-like patterns.  This is a defence-in-depth step against
    prompt-injection attacks where an adversarial image tricks the vision
    model into emitting system-level instructions.
    """
    # Drop control characters (Cc category) except common whitespace that
    # we will normalize next.
    cleaned = "".join(
        ch for ch in text if unicodedata.category(ch) != "Cc" or ch in "\t\n\r"
    )
    # Collapse all whitespace runs to a single space so multi-line
    # injection payloads cannot masquerade as formatting.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    for pattern in _SUSPICIOUS_DESCRIPTION_PATTERNS:
        if re.search(pattern, cleaned):
            logger.warning(
                "Vision fallback description contains a suspicious "
                "pattern and will be treated as untrusted user content.",
            )
            break

    return cleaned


def _canonical_url_for_key(url: str) -> str:
    """Strip query/fragment from a URL for stable cache keying.

    Presigned URLs for the same underlying image often differ only in
    their query parameters (tokens, expiry).  By hashing the URL without
    query/fragment we ensure semantically identical images share a cache
    entry, reducing redundant vision-model calls and cost.
    """
    if url.startswith("file://"):
        return url
    try:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return url


def _get_image_key(block: Any) -> str | None:
    """Extract a stable cache key from an image block.

    Returns a hash of the *canonical* image URL/path (with query
    parameters and fragments stripped), or None if no URL can be
    extracted.

    Limitation: image blocks without an extractable URL (e.g. inline
    base64 ``data:`` sources) return ``None`` and are therefore never
    cached — each occurrence is re-described.  This is acceptable because
    QwenPaw persists uploads to disk and references them by URL/path;
    inline base64 images are rare on this path.  If they become common,
    add a content-hash key here (hashing the decoded bytes).
    """
    url = _extract_image_url(block)
    if not url:
        return None
    canonical = _canonical_url_for_key(url)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _extract_image_url(block: Any) -> str | None:
    """Extract URL/path string from an image block (dict or DataBlock)."""
    if isinstance(block, dict):
        btype = block.get("type")
        if btype == "image":
            # dict-style: {"type": "image", "image_url": {"url": "..."}}
            # or {"type": "image", "url": "..."}
            image_url = block.get("image_url")
            if isinstance(image_url, dict):
                return image_url.get("url")
            return block.get("url")
    else:
        btype = getattr(block, "type", None)
        if btype == "image":
            image_url = getattr(block, "image_url", None)
            if isinstance(image_url, dict):
                return image_url.get("url")
            return getattr(block, "url", None)
        # 2.0 DataBlock with image media type
        if btype == "data":
            source = getattr(block, "source", None)
            mt = getattr(source, "media_type", "") or ""
            if mt.startswith(_IMAGE_MIME_PREFIXES):
                url = getattr(source, "url", None)
                return str(url) if url is not None else None
    return None


def _is_image_block(block: Any) -> bool:
    """Check if a block is an image block."""
    if isinstance(block, dict):
        return block.get("type") in _IMAGE_BLOCK_TYPES
    btype = getattr(block, "type", None)
    if btype in _IMAGE_BLOCK_TYPES:
        return True
    # 2.0 DataBlock: type="data", media type starts with "image/"
    if btype == "data":
        source = getattr(block, "source", None)
        mt = getattr(source, "media_type", "") or ""
        return mt.startswith(_IMAGE_MIME_PREFIXES)
    return False


def _build_image_data_block(url: str) -> DataBlock:
    """Build a DataBlock for an image URL."""
    import mimetypes

    media_type, _ = mimetypes.guess_type(url)
    if not media_type:
        media_type = "image/*"
    return DataBlock(source=URLSource(url=url, media_type=media_type))


# ---------------------------------------------------------------------------
# Core: collect images, call vision model, replace in-place
# ---------------------------------------------------------------------------


def _collect_image_blocks(
    msgs: List[Msg],
    max_images: int,
) -> List[Tuple[int, int, Any, str]]:
    """Collect image blocks from messages with their positions.

    Returns a list of (msg_index, block_index, block, image_url) tuples,
    limited to max_images entries.  Skips images that are already cached.
    """
    results: List[Tuple[int, int, Any, str]] = []
    for msg_idx, msg in enumerate(msgs):
        if not isinstance(msg.content, list):
            continue
        for blk_idx, block in enumerate(msg.content):
            if not _is_image_block(block):
                continue
            url = _extract_image_url(block)
            if not url:
                continue
            # Skip already-cached images (will be replaced from cache later)
            key = _get_image_key(block)
            if key and key in _description_cache:
                continue
            results.append((msg_idx, blk_idx, block, url))
            if len(results) >= max_images:
                return results
    return results


def _ensure_provider_credentials(provider: Any, provider_id: str) -> None:
    """Validate that the vision provider has usable credentials.

    Many vision models (e.g. DashScope ``qwen-vl-max``) are paid and
    require an API key.  If the selected provider requires a key but none
    is configured, calling the model would incur a wasted network round
    trip before failing.  We fail fast here with a clear message so the
    caller can log it and gracefully fall back to media stripping.
    """
    # Local providers (e.g. Ollama) and providers that explicitly do not
    # require a key are always considered usable.
    if getattr(provider, "is_local", False):
        return
    if getattr(provider, "require_api_key", True) is False:
        return
    api_key = (getattr(provider, "api_key", "") or "").strip()
    if not api_key:
        raise ValueError(
            f"Vision fallback provider '{provider_id}' has no API key "
            f"configured. Set the API key in provider settings or choose "
            f"a provider that does not require one.",
        )


async def _call_vision_model(
    vision_provider_id: str,
    vision_model: str,
    image_url: str,
    system_prompt: str,
    max_tokens: int,
) -> str:
    """Call the vision model to describe a single image.

    Returns the description text, or raises on failure.
    """
    from ...providers.provider_manager import ProviderManager

    manager = ProviderManager.get_instance()
    provider = manager.get_provider(vision_provider_id)
    if provider is None:
        raise ValueError(
            f"Vision fallback provider '{vision_provider_id}' not found.",
        )

    _ensure_provider_credentials(provider, vision_provider_id)

    model = provider.get_chat_model_instance(vision_model)

    # Build request messages: system prompt + user message with image
    messages = [
        Msg(
            name="system",
            role="system",
            content=[TextBlock(type="text", text=system_prompt)],
        ),
        Msg(
            name="user",
            role="user",
            content=[
                _build_image_data_block(image_url),
                TextBlock(
                    type="text",
                    text="Please describe this image concisely.",
                ),
            ],
        ),
    ]

    # Call the vision model.  Forward the per-call token limit via the
    # documented ``**kwargs`` contract (agentscope passes these straight
    # to the underlying API), instead of mutating the shared model
    # instance's parameters.
    call_kwargs = {"max_tokens": max_tokens} if max_tokens > 0 else {}
    response = await model(messages, **call_kwargs)

    # Handle streaming or non-streaming response
    if hasattr(response, "__aiter__"):
        accumulated = ""
        async for chunk in response:
            text = _extract_text(chunk)
            if text:
                accumulated += text
        return accumulated

    return _extract_text(response)


def _extract_text(response: Any) -> str:
    """Extract text from a ChatResponse-like object."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response

    # Try .text attribute
    text = (
        response.get("text")
        if isinstance(response, dict)
        else getattr(response, "text", None)
    )
    if isinstance(text, str) and text:
        return text

    # Try .content attribute
    content = (
        response.get("content")
        if isinstance(response, dict)
        else getattr(response, "content", None)
    )
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for item in content:
            item_text = (
                item.get("text")
                if isinstance(item, dict)
                else getattr(item, "text", None)
            )
            if isinstance(item_text, str) and item_text:
                return item_text

    return ""


def _sanitize_source_url(image_url: str) -> str:
    """Return a safe, short reference to the image source.

    Strips query parameters and fragments (which may contain tokens) and
    masks local file paths so that sensitive URLs or filesystem layout do
    not leak into the conversation context or logs.
    """
    if image_url.startswith("file://"):
        return "local file"

    try:
        parts = urlsplit(image_url)
        # Keep only scheme, netloc and path; drop query/fragment to avoid
        # leaking presigned tokens or other credentials.
        sanitized = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, "", ""),
        )
    except ValueError:
        sanitized = image_url
    if len(sanitized) <= 80:
        return sanitized
    return sanitized[:77] + "..."


def _make_description_block(description: str, image_url: str) -> TextBlock:
    """Wrap a description string into a TextBlock with markers."""
    short_url = _sanitize_source_url(image_url)
    text = f"{_DESC_PREFIX}{description} (source: {short_url}){_DESC_SUFFIX}"
    return TextBlock(type="text", text=text)


async def _reserve_or_get_cached(
    key: Optional[str],
) -> Tuple[Optional[str], Optional["asyncio.Future[str]"], bool]:
    """Reserve an in-flight slot or return a cached description.

    Returns ``(cached, future, is_owner)``:
    - ``cached``: the cached description if present (caller returns it);
    - ``future``: the in-flight future to settle (owner) or await;
    - ``is_owner``: True when this caller must perform the vision call.
    """
    if key is None:
        return None, None, True
    async with _get_cache_lock():
        if key in _description_cache:
            return _description_cache[key], None, False
        if key in _in_flight:
            return None, _in_flight[key], False
        future: asyncio.Future[str] = asyncio.Future()
        _in_flight[key] = future
        return None, future, True


async def _settle_future(
    key: Optional[str],
    future: Optional["asyncio.Future[str]"],
    result: str,
) -> None:
    """Cache a non-empty result and resolve the shared in-flight future.

    Failure is signalled by an empty ``result`` string.  We deliberately
    resolve the future with a value (never ``set_exception``) so that a
    future which no waiter retrieves does not raise the noisy
    "Future exception was never retrieved" warning at garbage collection.
    """
    if key is None or future is None:
        return
    async with _get_cache_lock():
        _in_flight.pop(key, None)
        if result:
            _set_cache_entry(key, result)
        if not future.done():
            future.set_result(result)


async def _perform_vision_call(
    key: Optional[str],
    url: str,
    future: Optional["asyncio.Future[str]"],
    *,
    vision_provider_id: str,
    vision_model: str,
    max_tokens: int,
    system_prompt: str,
) -> Optional[str]:
    """Invoke the vision model, sanitize, cache, and settle the future."""
    async with _get_vision_semaphore():
        try:
            raw = await _call_vision_model(
                vision_provider_id=vision_provider_id,
                vision_model=vision_model,
                image_url=url,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            logger.warning(
                "Vision fallback failed for image %s: %s",
                _sanitize_source_url(url),
                exc,
                exc_info=True,
            )
            await _settle_future(key, future, "")
            return None

    description = _sanitize_description_text(raw)
    if not description.strip():
        logger.warning(
            "Vision fallback returned empty description for image %s",
            _sanitize_source_url(url),
        )
        await _settle_future(key, future, "")
        return None

    await _settle_future(key, future, description)
    return description


async def _get_or_describe_image(
    key: Optional[str],
    url: str,
    *,
    vision_provider_id: str,
    vision_model: str,
    max_tokens: int,
    system_prompt: str,
) -> Optional[str]:
    """Return a sanitized description for ``url``.

    If ``key`` is provided the result is read from cache when available,
    or stored in cache after a successful vision-model call.  Concurrent
    callers requesting the same key share a single in-flight
    ``asyncio.Future`` so that the vision model is only invoked once.

    Returns ``None`` when the call fails or produces empty text.
    """
    cached, future, is_owner = await _reserve_or_get_cached(key)
    if cached is not None:
        return cached

    if not is_owner:
        # Another request is already describing this image; await it.
        # An empty result signals that the owner's call failed.
        try:
            result = await future  # type: ignore[misc]
        except Exception:
            return None
        return result or None

    return await _perform_vision_call(
        key,
        url,
        future,
        vision_provider_id=vision_provider_id,
        vision_model=vision_model,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
    )


async def describe_images_in_messages(
    msgs: List[Msg],
    *,
    vision_provider_id: str,
    vision_model: str,
    max_images: int = 5,
    max_tokens: int = 300,
    system_prompt: str = "",
    session_id: Optional[str] = None,
) -> int:
    """Replace image blocks with text descriptions in-place.

    Calls the specified vision model for each image block found in the
    message list.  Already-described images (in cache) are replaced from
    cache without an API call.

    Security note: the description text produced by the vision model is
    injected into the main model's context as plain text.  An adversarial
    image crafted to make the vision model emit instructions can therefore
    act as a prompt-injection vector.  Keep the vision model choice
    trustworthy and consider the description as untrusted user content.

    Args:
        msgs: Message list (will be mutated in-place).
        vision_provider_id: Provider ID for the vision model.
        vision_model: Model name for the vision model.
        max_images: Maximum number of new images to describe per call.
        max_tokens: Max tokens for each description.
        system_prompt: System prompt for the vision model.
        session_id: Optional session identifier.  When provided and it
            differs from the previous call, the in-memory description
            cache is cleared to avoid cross-session description reuse.

    Returns:
        Total number of image blocks replaced with descriptions.
    """
    global _success_count, _failure_count

    # Phase 1: under lock, replace cached images and collect uncached ones.
    async with _get_cache_lock():
        _ensure_cache_for_session(session_id)

        total_replaced = 0

        # First pass: replace cached images.
        for msg in msgs:
            if not isinstance(msg.content, list):
                continue
            new_content = []
            for block in msg.content:
                if _is_image_block(block):
                    key = _get_image_key(block)
                    if key and key in _description_cache:
                        url = _extract_image_url(block) or ""
                        new_content.append(
                            _make_description_block(
                                _description_cache[key],
                                url,
                            ),
                        )
                        total_replaced += 1
                        continue
                new_content.append(block)
            msg.content = new_content

        # Second pass: collect uncached images to describe.
        uncached = _collect_image_blocks(msgs, max_images)

    # Phase 2: outside the lock, describe uncached images concurrently.
    # The semaphore limits provider load; in-flight futures deduplicate
    # concurrent requests for the same image key.
    async def _describe_item(
        item: Tuple[int, int, Any, str],
    ) -> Optional[str]:
        _msg_idx, _blk_idx, block, url = item
        key = _get_image_key(block)
        return await _get_or_describe_image(
            key,
            url,
            vision_provider_id=vision_provider_id,
            vision_model=vision_model,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )

    descriptions = await asyncio.gather(
        *[_describe_item(item) for item in uncached],
    )

    # Phase 3: under lock, apply descriptions and update counters.
    async with _get_cache_lock():
        for (msg_idx, blk_idx, block, url), description in zip(
            uncached,
            descriptions,
        ):
            if description is None or not description.strip():
                _failure_count += 1
                continue

            # The description is already sanitized and cached when a key
            # exists; re-cache here only for blocks without a usable key.
            key = _get_image_key(block)
            if key:
                _set_cache_entry(key, description)

            msg = msgs[msg_idx]
            if isinstance(msg.content, list) and blk_idx < len(
                msg.content,
            ):
                msg.content[blk_idx] = _make_description_block(
                    description,
                    url,
                )
                total_replaced += 1
                _success_count += 1

        logger.info(
            "Vision fallback: described=%d attempted=%d metrics=%s",
            total_replaced,
            len(uncached),
            get_metrics(),
        )

        return total_replaced


__all__ = [
    "describe_images_in_messages",
    "clear_description_cache",
    "get_metrics",
]
