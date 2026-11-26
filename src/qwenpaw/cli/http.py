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
    from ..config.utils import read_last_api_record
    from ..utils.runtime_api import (
        PROFILE_PROBE_HEADER,
        new_profile_probe,
        read_runtime_api,
    )

    managed = read_runtime_api()
    if managed is None and os.getenv("QWENPAW_RUNTIME_ID"):
        raise click.ClickException("Managed runtime endpoint is unavailable")
    record = read_last_api_record() if managed is None else None
    endpoint = managed or (record and (record.host, record.port))
    if endpoint is None:
        return None
    host, port = endpoint
    target = deployment_url(host, port, record)
    if managed is not None:
        return target

    probe = new_profile_probe()
    nonce = probe.partition(".")[0]
    try:
        with api_client(
            api_url_from_deployment(target),
            timeout=1,
        ) as api, api.stream(
            "GET",
            "/version",
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
