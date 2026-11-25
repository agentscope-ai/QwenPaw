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


def local_runtime_url(require_verified: bool = False) -> str | None:
    """Find the profile's App; destructive local operations require a known owner."""
    from ..config.utils import read_last_api
    from ..utils.runtime_api import (
        PROFILE_PROBE_HEADER,
        new_profile_probe,
        read_runtime_api,
    )

    managed = read_runtime_api()
    if managed is None and os.getenv("QWENPAW_RUNTIME_ID"):
        raise click.ClickException("Managed runtime endpoint is unavailable")
    endpoint = managed or read_last_api()
    if endpoint is None:
        return None
    host, port = endpoint
    target = str(httpx.URL(scheme="http", host=host.strip("[]"), port=port))
    if managed is not None:
        return target

    probe = new_profile_probe()
    nonce = probe.partition(".")[0]
    try:
        with api_client(target, timeout=1) as api, api.stream(
            "GET",
            "/api/version",
            headers={PROFILE_PROBE_HEADER: probe},
        ) as response:
            if (
                response.is_success
                and response.headers.get(PROFILE_PROBE_HEADER) == nonce
            ):
                return target
    except httpx.ConnectError:
        return None
    except httpx.HTTPError:
        pass
    if require_verified:
        raise click.ClickException(
            f"Cannot verify which profile owns the App at {target}. "
            "Stop or upgrade that App before continuing.",
        )
    return None
