# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Optional

import click
import httpx

from ..app.base_path import normalize_base_path
from ..utils.runtime_api import (
    api_client,
    api_url_from_deployment,
    api_url_from_override,
)

if TYPE_CHECKING:
    from ..config.utils import LastApiEndpoint


DEFAULT_BASE_URL = "http://127.0.0.1:8088"


def client(base_url: str) -> httpx.Client:
    """Create an API client from a legacy explicit base URL."""
    return api_client(api_url_from_override(base_url))


def print_json(data: Any) -> None:
    click.echo(json.dumps(data, ensure_ascii=False, indent=2))


def deployment_url(
    host: str,
    port: int,
    record: LastApiEndpoint | None = None,
) -> str:
    """Use a recorded mount only for its own HTTP address."""
    host = host.strip().strip("[]")
    mount = None
    if (
        record is not None
        and host.lower() == record.host.strip().strip("[]").lower()
        and port == record.port
    ):
        mount = record.base_path
    if mount is None:
        mount = os.environ.get("QWENPAW_BASE_PATH")
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}{normalize_base_path(mount)}"


def resolve_base_url(ctx: click.Context, base_url: Optional[str]) -> str:
    """Prefer an explicit URL; otherwise resolve the selected HTTP address."""
    if base_url:
        return base_url.rstrip("/")
    options = ctx.obj or {}
    return deployment_url(
        options.get("host", "127.0.0.1"),
        options.get("port", 8088),
        options.get("last_api"),
    )


def resolve_api_endpoint(ctx: click.Context, base_url: Optional[str]) -> str:
    """Resolve a CLI API endpoint without confusing the mount with /api."""
    if base_url:
        return api_url_from_override(base_url)
    return api_url_from_deployment(resolve_base_url(ctx, None))
