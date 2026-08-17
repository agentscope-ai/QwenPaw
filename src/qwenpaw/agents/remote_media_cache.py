# -*- coding: utf-8 -*-
"""Client-side localization of remote media URLs.

When a conversation history contains media blocks referencing remote
HTTP(S) URLs (e.g. images returned by web tools), the URL is forwarded
to the model backend verbatim.  Backends then fetch the URL
*server-side*, which fails for hotlink-protected hosts (HTTP 403) or
unreachable networks.  Worse, several backends (e.g. vLLM) reject the
whole request when any media URL cannot be fetched — a single dead URL
poisons every subsequent turn of the session.

This module downloads such URLs *client-side* (with per-host ``Referer``
fix-ups for known hotlink-protected sites), caches them on disk, and
returns a local file path that can be embedded safely.  Failures degrade
gracefully: a negative-cache entry prevents repeated attempts within
``NEGATIVE_CACHE_TTL`` and the caller replaces the media block with a
text placeholder instead of poisoning the request.
"""

import hashlib
import json
import logging
import mimetypes
import os
import tempfile
import time
from typing import Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# Seconds a failed download stays cached before we retry it.
NEGATIVE_CACHE_TTL = 24 * 60 * 60

# Maximum media size pulled into the cache (bytes).
MAX_MEDIA_BYTES = 30 * 1024 * 1024

# Download timeout (seconds).
FETCH_TIMEOUT = 10

# Environment variable that disables client-side localization entirely
# (remote URLs are then passed through untouched, legacy behavior).
KILL_SWITCH_ENV = "QWENPAW_DISABLE_REMOTE_MEDIA_CACHE"

# Environment variable overriding the on-disk cache location.
CACHE_DIR_ENV = "QWENPAW_REMOTE_MEDIA_CACHE_DIR"

# Known hotlink-protected hosts mapped to the ``Referer`` their CDN
# expects.  Matched against the URL netloc (exact, or any subdomain).
_HOTLINK_REFERER_MAP = {
    "i.pximg.net": "https://app.pixiv.net/",
}

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class MediaFetchError(Exception):
    """Raised when a remote media URL cannot be downloaded."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def remote_media_cache_enabled() -> bool:
    """Return True unless the kill-switch env var is set."""
    return os.environ.get(KILL_SWITCH_ENV, "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    )


def remote_media_cache_dir() -> str:
    """Return the cache directory, creating it if necessary."""
    cache_dir = os.environ.get(CACHE_DIR_ENV) or os.path.join(
        os.path.expanduser("~"),
        ".qwenpaw",
        "media_cache",
    )
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _hotlink_referer(url: str) -> Optional[str]:
    """Return the expected ``Referer`` for hotlink-protected hosts."""
    netloc = urlparse(url).netloc.lower()
    for host, referer in _HOTLINK_REFERER_MAP.items():
        if netloc == host or netloc.endswith("." + host):
            return referer
    return None


def _download(url: str) -> Tuple[bytes, str]:
    """Fetch ``url`` and return ``(payload, content_type)``.

    Raises :class:`MediaFetchError` with a human-readable reason on
    failure.  Split out from :func:`localize_remote_url` so tests can
    monkeypatch it and stay offline.
    """
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    referer = _hotlink_referer(url)
    if referer:
        request.add_header("Referer", referer)
    try:
        with urlopen(request, timeout=FETCH_TIMEOUT) as response:
            content_type = response.headers.get("Content-Type", "")
            payload = response.read(MAX_MEDIA_BYTES + 1)
    except HTTPError as exc:
        raise MediaFetchError(f"HTTP {exc.code}") from exc
    except (URLError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise MediaFetchError(str(reason)) from exc
    if len(payload) > MAX_MEDIA_BYTES:
        raise MediaFetchError(f"payload exceeds {MAX_MEDIA_BYTES} bytes")
    return payload, content_type


def _cache_key(url: str) -> str:
    """Return a stable cache filename for ``url``.

    SHA-1 is sufficient here: the key only maps URLs to cache entries,
    it is not used for any cryptographic purpose.
    """
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _positive_cache_path(cache_dir: str, key: str) -> Optional[str]:
    """Return the cached media file for ``key`` if one exists."""
    prefix = key + "."
    try:
        for name in os.listdir(cache_dir):
            if (
                name.startswith(prefix)
                and not name.endswith(".failed.json")
                and not name.endswith(".part")
            ):
                return os.path.join(cache_dir, name)
    except OSError:
        return None
    return None


def _write_negative_entry(
    cache_dir: str,
    key: str,
    url: str,
    reason: str,
) -> None:
    try:
        with open(
            os.path.join(cache_dir, key + ".failed.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump({"url": url, "reason": reason}, fh)
    except OSError:
        logger.debug("Could not write negative cache entry", exc_info=True)


def _negative_cache_reason(
    cache_dir: str,
    key: str,
) -> Optional[str]:
    """Return the cached failure reason if still fresh, else None."""
    path = os.path.join(cache_dir, key + ".failed.json")
    try:
        if time.time() - os.path.getmtime(path) > NEGATIVE_CACHE_TTL:
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get("reason")
    except (OSError, ValueError):
        return None


def localize_remote_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Download ``url`` into the cache and return a local path.

    Returns ``(local_path, None)`` on success or ``(None, reason)`` on
    failure (network error, non-media content type, unwritable cache).
    Failures are negative-cached for :data:`NEGATIVE_CACHE_TTL` so a
    dead URL is not retried on every request.
    """
    key = _cache_key(url)
    try:
        cache_dir = remote_media_cache_dir()
    except OSError as exc:
        return None, f"cache dir unavailable: {exc}"

    cached_reason = _negative_cache_reason(cache_dir, key)
    if cached_reason:
        return None, cached_reason

    cached_path = _positive_cache_path(cache_dir, key)
    if cached_path:
        return cached_path, None

    try:
        payload, content_type = _download(url)
    except MediaFetchError as exc:
        _write_negative_entry(cache_dir, key, url, exc.reason)
        return None, exc.reason

    media_type = content_type.split(";")[0].strip().lower()
    if not media_type.startswith(("image/", "audio/", "video/")):
        reason = f"non-media content type: {media_type or 'unknown'}"
        _write_negative_entry(cache_dir, key, url, reason)
        return None, reason

    ext = mimetypes.guess_extension(media_type) or ".bin"
    dest = os.path.join(cache_dir, key + ext)
    try:
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".part")
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp_path, dest)
    except OSError as exc:
        return None, f"cache write failed: {exc}"

    logger.debug("Localized remote media %s -> %s", url, dest)
    return dest, None
