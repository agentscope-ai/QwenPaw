# -*- coding: utf-8 -*-
"""Additional guardrails for backup-related API endpoints.

Backup endpoints accept only bearer-token style authentication from the
existing middleware (Authorization header or token query parameter). They do
not rely on cookies; keeping that invariant is part of the CSRF defense.

When auth is disabled, backup routes are still sensitive because they can
export secrets, import archives, or replace local config during restore. This
module keeps that policy isolated from the general auth middleware so the
backup-specific restrictions do not affect unrelated APIs.
"""
from __future__ import annotations

import ipaddress
import json
import threading
from typing import Any

from fastapi import Request
from starlette.responses import Response

from ..constant import CONFIG_FILE, WORKING_DIR

_ALLOW_HOSTS_ENDPOINT = "/api/config/security/allow-no-auth-hosts"
_BACKUP_PATH = "/api/backups"
_CONFIG_LOCK = threading.Lock()
_cached_config: Any | None = None
_cached_config_mtime_ns: int | None = None


def apply(request: Request, *, skip_auth: bool) -> Response | bool:
    """Return a rejection response or the final ``skip_auth`` decision.

    ``skip_auth`` is the existing middleware decision. For backup routes we
    may tighten it: auth-enabled deployments must still present bearer-style
    credentials, while auth-disabled deployments are limited to same-origin
    requests from allow-listed hosts.
    """
    if not _matches_protected(request) or request.method == "OPTIONS":
        return skip_auth

    if not _is_same_origin(request):
        return _json_response(
            403,
            "sec_fetch_site_rejected",
            "Cross-site backup requests are not allowed.",
        )

    from .auth import has_registered_users, is_auth_enabled

    auth_active = is_auth_enabled() and has_registered_users()
    if auth_active:
        return False

    rejected = _check_unauth_remote(request)
    return rejected if rejected is not None else skip_auth


def _matches_protected(request: Request) -> bool:
    """Return True for endpoints that can read or mutate backup state."""
    path = request.url.path
    if path == _BACKUP_PATH or path.startswith(f"{_BACKUP_PATH}/"):
        return True
    return request.method == "PUT" and path == _ALLOW_HOSTS_ENDPOINT


def _json_response(status_code: int, code: str, message: str) -> Response:
    return Response(
        content=json.dumps({"detail": {"code": code, "message": message}}),
        status_code=status_code,
        media_type="application/json",
    )


def _is_same_origin(request: Request) -> bool:
    """Reject browser cross-site backup calls before they reach handlers."""
    sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if sec_fetch_site in {"same-origin", "none"}:
        return True
    if sec_fetch_site in {"cross-site", "same-site"}:
        return False

    origin = request.headers.get("origin")
    if not origin:
        return True
    if origin == "null":
        return False

    target = f"{request.url.scheme}://{request.url.netloc}"
    return origin.rstrip("/").lower() == target.lower()


def _check_unauth_remote(request: Request) -> Response | None:
    """Reject auth-off backup calls from hosts outside the allow list."""
    client_host = request.client.host if request.client else ""
    config = _get_cached_config()
    allowed_hosts = config.security.allow_no_auth_hosts
    if _ip_in_allow_list(client_host, allowed_hosts):
        return None
    return _json_response(
        403,
        "backup_host_not_allowlisted",
        "Backup endpoints are available only from allow-listed hosts.",
    )


def _get_cached_config() -> Any:
    """Load config with mtime caching for the auth-off host allow list."""
    global _cached_config, _cached_config_mtime_ns

    config_path = WORKING_DIR / CONFIG_FILE
    try:
        mtime_ns: int | None = config_path.stat().st_mtime_ns
    except FileNotFoundError:
        mtime_ns = None

    if _cached_config is not None and _cached_config_mtime_ns == mtime_ns:
        return _cached_config

    with _CONFIG_LOCK:
        try:
            current_mtime_ns: int | None = config_path.stat().st_mtime_ns
        except FileNotFoundError:
            current_mtime_ns = None

        if (
            _cached_config is not None
            and _cached_config_mtime_ns == current_mtime_ns
        ):
            return _cached_config

        from ..config import load_config

        _cached_config = load_config()
        _cached_config_mtime_ns = current_mtime_ns
        return _cached_config


def _canonicalize_ip(value: str) -> str:
    """Normalize IP text so IPv4-mapped loopback forms compare correctly."""
    host = value.strip().strip("[]")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return str(ip.ipv4_mapped)
    return str(ip)


def _ip_in_allow_list(client_host: str, allowed_hosts: list[str]) -> bool:
    """Return True when *client_host* matches the configured allow list."""
    canonical_client = _canonicalize_ip(client_host)
    canonical_allowed = {_canonicalize_ip(host) for host in allowed_hosts}
    return canonical_client in canonical_allowed
