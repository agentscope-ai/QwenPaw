# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from typing import Any, Optional

import click
import httpx

from ..app.base_path import normalize_base_path
from ..utils.runtime_api import (
    api_client,
    api_url_from_deployment,
    api_url_from_override,
)


DEFAULT_BASE_URL = "http://127.0.0.1:8088"


def client(base_url: str) -> httpx.Client:
    """Create an API client from a legacy explicit base URL."""
    return api_client(api_url_from_override(base_url))


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
    base_path = normalize_base_path(os.environ.get("QWENPAW_BASE_PATH"))
    return f"http://{host}:{port}{base_path}"


def resolve_api_endpoint(ctx: click.Context, base_url: Optional[str]) -> str:
    """Resolve a CLI API endpoint without confusing the mount with /api."""
    if base_url:
        return api_url_from_override(base_url)
    return api_url_from_deployment(resolve_base_url(ctx, None))
