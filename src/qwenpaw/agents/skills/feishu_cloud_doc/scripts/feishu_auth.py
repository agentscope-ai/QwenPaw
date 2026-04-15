"""Feishu/Lark authentication helper.

Provides tenant_access_token retrieval for scripts that call
Feishu Open API.  Credentials are read from environment variables
(FEISHU_APP_ID / FEISHU_APP_SECRET) or from the QwenPaw config file
(~/.qwenpaw/config.json  →  channels.feishu.app_id / app_secret).

Usage:
    from feishu_auth import get_tenant_token, get_base_url
    token = get_tenant_token()
    base = get_base_url()          # https://open.feishu.cn or larksuite
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

import httpx

_TOKEN_CACHE: dict[str, str] = {}


def _read_config_credentials() -> Tuple[str, str, str]:
    """Read app_id, app_secret, domain from QwenPaw config file."""
    config_candidates = [
        Path.home() / ".qwenpaw" / "config.json",
        Path.home() / ".config" / "qwenpaw" / "config.json",
    ]
    for config_path in config_candidates:
        if not config_path.exists():
            continue
        try:
            with open(config_path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            feishu_cfg = (cfg.get("channels") or {}).get("feishu") or {}
            app_id = feishu_cfg.get("app_id") or ""
            app_secret = feishu_cfg.get("app_secret") or ""
            domain = feishu_cfg.get("domain") or "feishu"
            if app_id and app_secret:
                return app_id, app_secret, domain
        except (json.JSONDecodeError, OSError):
            continue
    return "", "", "feishu"


def get_credentials() -> Tuple[str, str, str]:
    """Return (app_id, app_secret, domain).

    Priority: environment variables > config file.
    """
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    domain = os.environ.get("FEISHU_DOMAIN", "")

    if not app_id or not app_secret:
        cfg_id, cfg_secret, cfg_domain = _read_config_credentials()
        app_id = app_id or cfg_id
        app_secret = app_secret or cfg_secret
        domain = domain or cfg_domain

    domain = domain or "feishu"
    return app_id, app_secret, domain


def get_base_url(domain: str = "") -> str:
    """Return the Open API base URL for the given domain."""
    if not domain:
        _, _, domain = get_credentials()
    if domain == "lark":
        return "https://open.larksuite.com"
    return "https://open.feishu.cn"


def get_tenant_token(force_refresh: bool = False) -> str:
    """Obtain a tenant_access_token via the internal auth endpoint.

    The token is cached in-process for the lifetime of the script.
    """
    app_id, app_secret, domain = get_credentials()
    if not app_id or not app_secret:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": (
                        "Feishu credentials not found. Set FEISHU_APP_ID and "
                        "FEISHU_APP_SECRET environment variables, or configure "
                        "them in ~/.qwenpaw/config.json under channels.feishu."
                    ),
                }
            )
        )
        sys.exit(1)

    cache_key = f"{app_id}:{domain}"
    if not force_refresh and cache_key in _TOKEN_CACHE:
        return _TOKEN_CACHE[cache_key]

    base_url = get_base_url(domain)
    url = f"{base_url}/open-apis/auth/v3/tenant_access_token/internal"
    resp = httpx.post(
        url,
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=15,
    )
    data = resp.json()
    if data.get("code") != 0:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"Failed to get tenant_access_token: {data.get('msg', 'unknown error')}",
                    "code": data.get("code"),
                }
            )
        )
        sys.exit(1)

    token = data["tenant_access_token"]
    _TOKEN_CACHE[cache_key] = token
    return token


def auth_headers() -> dict[str, str]:
    """Return standard Authorization + Content-Type headers."""
    return {
        "Authorization": f"Bearer {get_tenant_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }
