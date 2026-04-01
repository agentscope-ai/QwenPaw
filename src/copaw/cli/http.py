# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import click
import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8088"

_BASE_PATH_ENV = "COPAW_BASE_PATH"


def _normalize_base_path(base_path: str) -> str:
    base_path = (base_path or "").strip()
    if not base_path:
        return ""
    if not base_path.startswith("/"):
        base_path = f"/{base_path}"
    base_path = base_path.rstrip("/")
    if base_path == "/":
        return ""
    return base_path


def normalize_api_base_url(base_url: str) -> str:
    """Normalize a service base URL to the API base URL.

    - Adds COPAW_BASE_PATH (if present) to the URL path when missing.
    - Ensures the result ends with /api (without double-appending).
    """
    base_url = (base_url or "").rstrip("/")
    if not base_url:
        base_url = DEFAULT_BASE_URL

    base_path = _normalize_base_path(os.getenv(_BASE_PATH_ENV, ""))
    parts = urlsplit(base_url)

    path = parts.path or ""
    if base_path and not (
        path == base_path or path.startswith(f"{base_path}/")
    ):
        if not path or path == "/":
            path = base_path
        else:
            path = f"{base_path}{path if path.startswith('/') else '/' + path}"

    path = path.rstrip("/")
    if not path.endswith("/api"):
        path = f"{path}/api" if path else "/api"

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            path,
            parts.query,
            parts.fragment,
        ),
    )


def client(base_url: str) -> httpx.Client:
    """Create HTTP client with /api prefix added to all requests."""
    return httpx.Client(
        base_url=normalize_api_base_url(base_url),
        timeout=30.0,
    )


def print_json(data: Any) -> None:
    click.echo(json.dumps(data, ensure_ascii=False, indent=2))


def resolve_base_url(ctx: click.Context, base_url: Optional[str]) -> str:
    """Resolve base_url with priority:
    1) command --base-url
    2) global --host/--port (from ctx.obj)

    Args:
        ctx: Click context containing global options
        base_url: Optional base_url override from command option

    Returns:
        Resolved base URL string
    """
    if base_url:
        return base_url.rstrip("/")
    host = (ctx.obj or {}).get("host", "127.0.0.1")
    port = (ctx.obj or {}).get("port", 8088)
    return f"http://{host}:{port}"
