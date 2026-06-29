# -*- coding: utf-8 -*-
"""Slack channel utility functions.

Pure helpers with no side effects — string manipulation, session-id
generation, dedup-key construction, and light data extraction.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


# ── Session identifiers ──


def generate_session_id(
    channel_id: str = "",
    thread_ts: str = "",
    user_id: str = "",
    is_dm: bool = False,
) -> str:
    """Build a stable, human-readable session identifier.

    Strategy
    --------
    * Threaded replies → ``slack:thread:<channel>:<thread_ts>``
    * Direct messages   → ``slack:dm:<user_id>``
    * Channel messages  → ``slack:ch:<channel_id>``

    The identifier is used by the processing pipeline to group
    multi-turn conversations.
    """
    if thread_ts:
        return f"slack:thread:{channel_id}:{thread_ts}"
    if is_dm and user_id:
        return f"slack:dm:{user_id}"
    return f"slack:ch:{channel_id}"


# ── Deduplication ──


def build_dedup_key(event: Dict[str, Any]) -> str:
    """Return a deduplication key for a Slack event.

    Prefers ``event_id`` (unique per delivery) and falls back to
    ``(channel, ts)`` for events that lack an id.  Used by
    :class:`SlackEventHandler` to detect Socket Mode redeliveries.
    """
    eid = event.get("event_id")
    if eid:
        return f"event:{eid}"
    ch = event.get("channel") or ""
    ts = event.get("ts") or ""
    return f"msg:{ch}:{ts}"


# ── Text helpers ──


def detect_file_type(filename: str) -> str:
    """Guess the MIME type from *filename* using ``mimetypes``.

    Returns ``"application/octet-stream"`` when no mapping is found.
    """
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


# ── URL parsing ──


def is_slack_host(url: str) -> bool:
    """Return *True* if *url* is hosted on a Slack domain."""
    from .constants import SLACK_SSRF_ALLOWED_SUFFIXES

    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(
        host == s[1:] or host.endswith(s) for s in SLACK_SSRF_ALLOWED_SUFFIXES
    )


# ── Retry helpers ──


async def with_retry(func, *args, retries=3, backoff=1.5, **kwargs):
    """Call *func* with exponential backoff retry on transient failures.

    Retryable errors are determined by :func:`_is_retryable_error`.
    Non-retryable errors are raised immediately.

    Parameters
    ----------
    func:
        Async callable to retry.
    retries:
        Maximum number of attempts (including the first).  Default 3.
    backoff:
        Base delay multiplier in seconds.  Delay for attempt *n* is
        ``backoff * n``.  Default 1.5.
    """
    last_exc = None
    for attempt in range(retries):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt == retries - 1:
                raise
            if not _is_retryable_error(exc):
                raise

            # Prefer Slack's Retry-After header
            retry_after = _extract_retry_after(exc)
            if retry_after is not None:
                await asyncio.sleep(retry_after)
            else:
                await asyncio.sleep(backoff * (attempt + 1))
    raise last_exc


def _extract_retry_after(exc: Exception) -> Optional[float]:
    """Extract Retry-After seconds from a Slack API error response."""
    try:
        # slack_sdk.errors.SlackApiError 携带 response
        headers = exc.response.headers
        value = headers.get("Retry-After") or headers.get("retry-after")
        if value:
            return float(value)
    except (AttributeError, ValueError, TypeError):
        pass
    return None


def _is_retryable_error(exc: Exception) -> bool:
    """Return *True* if *exc* represents a transient failure worth retrying.

    Covers HTTP 429 (rate-limit), 5xx (server errors), and common
    network-layer failures (timeout, connection reset).
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (429, 500, 502, 503, 504):
        return True
    msg = str(exc).lower()
    return any(
        key in msg
        for key in (
            "rate_limited",
            "timeout",
            "connection reset",
            "ratelimited",
        )
    )


# ── Proxy helpers ──

# Slack API hosts that may be excluded from proxying via NO_PROXY.
_SLACK_PROXY_HOSTS: Tuple[str, ...] = (
    "slack.com",
    "files.slack.com",
    "wss-primary.slack.com",
)


def _resolve_slack_proxy_url(
    proxy: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve the proxy URL to use for Slack connections.

    Resolution order:
    1. Explicit *proxy* argument.
    2. ``HTTP_PROXY`` / ``HTTPS_PROXY`` environment variables.

    Returns *None* when ``NO_PROXY`` excludes Slack's API hosts.
    """
    proxy_url = proxy or os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY")
    if not proxy_url:
        return None, None

    proxy_url = proxy_url.strip()
    if not proxy_url.lower().startswith(("http://", "https://")):
        return None, "unsupported_proxy_scheme"

    no_proxy = os.getenv("NO_PROXY") or ""
    if no_proxy:
        patterns = [
            p.strip().lower() for p in no_proxy.split(",") if p.strip()
        ]
        if any(
            _host_matches_no_proxy(host, patterns)
            for host in _SLACK_PROXY_HOSTS
        ):
            return None, "no_proxy_bypass"

    return proxy_url, None


def _host_matches_no_proxy(hostname: str, patterns: List[str]) -> bool:
    """Return *True* if *hostname* (or its parent domains)
    matches any pattern.
    """
    hostname = hostname.lower().strip()
    for pat in patterns:
        pat = pat.strip()
        if pat == "*":
            return True
        if pat == hostname:
            return True
        if pat.startswith(".") and hostname.endswith(pat):
            return True
        if hostname.endswith("." + pat):
            return True
    return False


def _apply_slack_proxy(client: Any, proxy_url: Optional[str]) -> None:
    """Apply a proxy URL to a Slack SDK client or clear it explicitly."""
    if hasattr(client, "proxy"):
        client.proxy = proxy_url
