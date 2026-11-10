# -*- coding: utf-8 -*-
"""Canonical HTTPS origins for owner-only Hub-to-runtime requests."""

from urllib.parse import urlsplit

HUB_PUBLIC_ORIGIN_HEADER = "X-QwenPaw-Hub-Public-Origin"


def https_origin(value: str, *, allow_path: bool = False) -> str | None:
    """Reject ambiguous URLs instead of trusting a raw forwarded authority."""
    if not value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return None
    if "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (not allow_path and parsed.path not in {"", "/"})
        ):
            return None
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        authority = f"{host}:{port}" if port not in {None, 443} else host
        return f"https://{authority}"
    except ValueError:
        return None
