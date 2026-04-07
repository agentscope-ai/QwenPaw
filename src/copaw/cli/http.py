# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from typing import Any, Optional
from urllib.parse import urlparse

import click
import httpx

from ..app.auth import (
    LOCAL_CLI_TOKEN_HEADER,
    _load_auth_data,
    create_token,
    has_registered_users,
    is_auth_enabled,
)

DEFAULT_BASE_URL = "http://127.0.0.1:8088"
_LOCAL_API_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _build_auth_headers(base_url: str) -> dict[str, str]:
    """Return auth headers for CLI API requests when local auth is enabled."""
    explicit_token = os.environ.get("COPAW_API_TOKEN", "").strip()
    if explicit_token:
        return {"Authorization": f"Bearer {explicit_token}"}

    parsed = urlparse(base_url)
    host = (parsed.hostname or "").strip().lower()
    if (
        host not in _LOCAL_API_HOSTS
        or not is_auth_enabled()
        or not has_registered_users()
    ):
        return {}

    data = _load_auth_data()
    if data.get("_auth_load_error"):
        return {}

    local_cli_token = str(data.get("local_cli_token", "")).strip()
    if local_cli_token:
        # Local CLI calls should authenticate explicitly, not rely on origin.
        return {LOCAL_CLI_TOKEN_HEADER: local_cli_token}

    # Backward compatibility: older auth.json files may not have a dedicated
    # local CLI token until the next successful login or credential rotation.
    username = str((data.get("user") or {}).get("username") or "").strip()
    if data.get("jwt_secret") and username:
        return {"Authorization": f"Bearer {create_token(username)}"}

    return {}


def client(base_url: str) -> httpx.Client:
    """Create HTTP client with /api prefix added to all requests."""
    # Ensure base_url ends with /api
    base = base_url.rstrip("/")
    if not base.endswith("/api"):
        base = f"{base}/api"
    return httpx.Client(
        base_url=base,
        timeout=30.0,
        headers=_build_auth_headers(base_url),
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
