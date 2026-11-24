# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from typing import Any, Optional

import click
import httpx

from ..utils.runtime_api import api_client


DEFAULT_BASE_URL = "http://127.0.0.1:8088"


def client(base_url: str) -> httpx.Client:
    """Create HTTP client with /api prefix added to all requests."""
    # Ensure base_url ends with /api
    base = base_url.rstrip("/")
    if not base.endswith("/api"):
        base = f"{base}/api"
    return api_client(base)


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
    return str(httpx.URL(scheme="http", host=host.strip("[]"), port=port))


def explicit_runtime_url(ctx: click.Context | None) -> str | None:
    """Return the App explicitly selected with --host or --port."""
    if ctx is None:
        return None
    root = ctx.find_root()
    explicit = any(
        root.get_parameter_source(option)
        is click.core.ParameterSource.COMMANDLINE
        for option in ("host", "port")
    )
    if explicit:
        return resolve_base_url(root, None)
    return None


def selected_runtime_url(ctx: click.Context | None) -> str | None:
    """Return the explicit or running App that owns CLI mutations."""
    return explicit_runtime_url(ctx) or (local_runtime_url() if ctx else None)


def local_runtime_url() -> str | None:
    """Find the App associated with this local working directory."""
    from ..config.utils import is_qwenpaw_running, read_last_api
    from ..utils.runtime_api import read_runtime_api

    endpoint = read_runtime_api()
    if endpoint is None and os.getenv("QWENPAW_RUNTIME_ID"):
        raise click.ClickException("Managed runtime endpoint is unavailable")
    if endpoint is None and is_qwenpaw_running():
        endpoint = read_last_api()
    if endpoint is None:
        return None
    host, port = endpoint
    return str(httpx.URL(scheme="http", host=host.strip("[]"), port=port))
