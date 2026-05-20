# -*- coding: utf-8 -*-
"""xAI OAuth credential loader + refresher.

Reads ``~/.xai/auth.json`` written by ``qwenpaw xai login`` (a PKCE
loopback flow against ``auth.x.ai``) and keeps the ``access_token``
fresh by calling the discovered ``token_endpoint`` when the JWT is
near expiry.

The file layout::

    {
      "auth_mode": "oauth_pkce",
      "tokens": {
        "access_token":  "eyJ...",
        "refresh_token": "...",
        "id_token":      "eyJ..."          # optional
      },
      "discovery": {
        "authorization_endpoint": "https://...",
        "token_endpoint":         "https://..."
      },
      "redirect_uri":  "http://127.0.0.1:56121/callback",
      "last_refresh":  "2026-05-16T12:00:00Z"
    }

Exposes the same minimal surface as other OAuth credential managers
(``ensure_fresh``, ``auth_headers``, ``base_url``) so callers can swap
providers without learning two auth surfaces.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Same client_id Grok-CLI ships with — Hermes reuses it; we do too.
# Reuse is intentional: the xAI OAuth server gates on this string and
# the loopback redirect_uri together, and rolling our own client_id
# would require an entitlement application from xAI.
XAI_OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_OAUTH_ISSUER = "https://auth.x.ai"

# Default xAI OpenAI-compatible base URL — same surface used for chat,
# image, video, TTS, STT.
DEFAULT_XAI_BASE_URL = "https://api.x.ai/v1"

# Refresh the access_token this many seconds BEFORE its JWT ``exp`` so
# an in-flight request never races the expiry edge.  120s mirrors the
# Hermes default; xAI tokens are usually ~1h.
REFRESH_SAFETY_MARGIN_S = 120


def _decode_jwt_claims(jwt: str) -> dict | None:
    """Best-effort base64url-decode the payload segment of a JWT.

    Returns ``None`` when the token isn't a parseable JWT — refresh
    paths fall back to a fixed 1h expiry in that case.
    """
    try:
        payload_b64 = jwt.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(
            base64.urlsafe_b64decode(payload_b64.encode("ascii")),
        )
    except Exception:
        return None


def _decode_jwt_exp_ms(jwt: str) -> int | None:
    claims = _decode_jwt_claims(jwt)
    if claims is None:
        return None
    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        return int(exp * 1000)
    return None


def _resolve_auth_path() -> Path:
    home = os.environ.get("XAI_HOME") or "~/.xai"
    return Path(os.path.expanduser(home)) / "auth.json"


@dataclass
class XaiCredential:
    access_token: str
    refresh_token: str
    id_token: str | None
    expires_at_ms: int
    token_endpoint: str
    auth_path: Path
    auth_mode: str = "oauth_pkce"

    @property
    def seconds_until_expiry(self) -> int:
        return max(0, int((self.expires_at_ms - time.time() * 1000) / 1000))

    @property
    def needs_refresh(self) -> bool:
        return self.seconds_until_expiry <= REFRESH_SAFETY_MARGIN_S


class XaiAuth:
    """Stateful manager for ``~/.xai/auth.json``.

    Usage::

        auth = XaiAuth()  # raises FileNotFoundError if not logged in
        headers = await auth.auth_headers()  # refreshes on demand
    """

    def __init__(self, auth_path: Path | None = None) -> None:
        self._auth_path = auth_path or _resolve_auth_path()
        self._lock = threading.Lock()
        # Single-flight gate around ensure_fresh's refresh path.  Lazy-
        # created on first use so XaiAuth can be constructed outside an
        # event loop (the chat-model construction path is sync).
        self._refresh_lock: asyncio.Lock | None = None
        self._creds: XaiCredential | None = None
        # Out-of-band reload mechanic — lets a fresh ``qwenpaw xai
        # login`` complete while CoPaw is running and the daemon picks
        # up the new tokens without a restart.
        self._loaded_mtime_ns: int = 0
        self._load()

    # ------------------------------------------------------------- #
    # Disk I/O                                                       #
    # ------------------------------------------------------------- #

    def _load(self) -> None:
        if not self._auth_path.exists():
            raise FileNotFoundError(
                f"xAI auth file not found: {self._auth_path}. "
                "Run `qwenpaw xai login` once to populate it.",
            )
        stat = self._auth_path.stat()
        raw = json.loads(self._auth_path.read_text())
        tokens = raw.get("tokens") or {}
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if not access_token or not refresh_token:
            raise ValueError(
                f"xAI auth file {self._auth_path} missing access_token "
                "or refresh_token (did the login flow complete?).",
            )
        discovery = raw.get("discovery") or {}
        token_endpoint = discovery.get("token_endpoint")
        if not token_endpoint:
            raise ValueError(
                f"xAI auth file {self._auth_path} missing "
                "discovery.token_endpoint. Re-run `qwenpaw xai login`.",
            )

        exp_ms = _decode_jwt_exp_ms(access_token)
        if exp_ms is None:
            exp_ms = int(stat.st_mtime * 1000) + 60 * 60 * 1000

        self._creds = XaiCredential(
            access_token=access_token,
            refresh_token=refresh_token,
            id_token=tokens.get("id_token"),
            expires_at_ms=exp_ms,
            token_endpoint=token_endpoint,
            auth_path=self._auth_path,
            auth_mode=str(raw.get("auth_mode") or "oauth_pkce"),
        )
        self._loaded_mtime_ns = stat.st_mtime_ns

    def _save(self, *, tokens: dict[str, Any]) -> None:
        raw = json.loads(self._auth_path.read_text())
        raw.setdefault("tokens", {})
        raw["tokens"].update(tokens)
        raw["last_refresh"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(),
        )
        tmp = self._auth_path.with_suffix(self._auth_path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._auth_path)
        self._loaded_mtime_ns = self._auth_path.stat().st_mtime_ns

    # ------------------------------------------------------------- #
    # Refresh                                                        #
    # ------------------------------------------------------------- #

    async def _refresh(self) -> None:
        assert self._creds is not None
        logger.info(
            "[XaiAuth] refreshing access_token (expires in %ds)",
            self._creds.seconds_until_expiry,
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self._creds.token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "client_id": XAI_OAUTH_CLIENT_ID,
                    "refresh_token": self._creds.refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code in (400, 401, 403):
            # xAI returns 400/401 when the refresh_token is revoked or
            # expired; 403 typically means the X Premium+ subscription
            # lapsed.  All three require the user to re-login — we
            # surface that intent explicitly instead of silently retrying.
            raise XaiAuthError(
                f"xAI refresh failed with HTTP {resp.status_code}: "
                f"{resp.text[:200]}",
                relogin_required=True,
            )
        resp.raise_for_status()
        body = resp.json()

        new_access = body.get("access_token")
        new_refresh = body.get("refresh_token") or self._creds.refresh_token
        new_id = body.get("id_token") or self._creds.id_token
        if not new_access:
            raise RuntimeError(
                "xAI token refresh succeeded but no access_token in response",
            )

        exp_ms = _decode_jwt_exp_ms(new_access) or (
            int(time.time() * 1000) + 3600 * 1000
        )
        tokens_to_save: dict[str, Any] = {
            "access_token": new_access,
            "refresh_token": new_refresh,
        }
        if new_id:
            tokens_to_save["id_token"] = new_id

        with self._lock:
            self._save(tokens=tokens_to_save)
            self._creds = XaiCredential(
                access_token=new_access,
                refresh_token=new_refresh,
                id_token=new_id,
                expires_at_ms=exp_ms,
                token_endpoint=self._creds.token_endpoint,
                auth_path=self._auth_path,
                auth_mode=self._creds.auth_mode,
            )
        logger.info(
            "[XaiAuth] refreshed — new expiry in %ds",
            self._creds.seconds_until_expiry,
        )

    # ------------------------------------------------------------- #
    # Public API                                                     #
    # ------------------------------------------------------------- #

    async def ensure_fresh(self) -> XaiCredential:
        if self._creds is None:
            self._load()
        else:
            try:
                disk_mtime_ns = self._auth_path.stat().st_mtime_ns
            except OSError:
                disk_mtime_ns = self._loaded_mtime_ns
            if disk_mtime_ns > self._loaded_mtime_ns:
                logger.info(
                    "[XaiAuth] auth.json changed on disk — reloading",
                )
                self._load()
        assert self._creds is not None
        if not self._creds.needs_refresh:
            return self._creds
        # Single-flight refresh.  Without this gate, two coroutines that
        # both notice the token is near expiry would both POST a refresh
        # — xAI's refresh_token rotates per call, so the second response
        # would invalidate the first, leaving auth.json desynced with
        # whatever bearer the in-flight requests were issued under.
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        async with self._refresh_lock:
            # Re-check under the lock: the coroutine that held it before
            # us may have already rotated the bearer, in which case our
            # cached creds are now stale and this refresh would be the
            # second (losing) caller.
            if self._creds.needs_refresh:
                await self._refresh()
        return self._creds

    def reload(self) -> XaiCredential:
        """Force-reread ``auth.json`` from disk.  Synchronous —
        the next request will lazily refresh the token if needed."""
        with self._lock:
            self._load()
        assert self._creds is not None
        return self._creds

    async def auth_headers(self) -> dict[str, str]:
        creds = await self.ensure_fresh()
        return {
            "Authorization": f"Bearer {creds.access_token}",
        }

    @property
    def base_url(self) -> str:
        return os.environ.get("QWENPAW_XAI_BASE_URL", DEFAULT_XAI_BASE_URL)


class XaiAuthError(RuntimeError):
    """Raised when xAI auth cannot be refreshed.

    ``relogin_required=True`` signals callers (UI, CLI) to prompt the
    user to re-run ``qwenpaw xai login`` instead of silently retrying.
    """

    def __init__(
        self,
        message: str,
        *,
        relogin_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.relogin_required = relogin_required


# -------------------------------------------------------------------------
# CLI smoke test — `python -m qwenpaw.providers.xai_auth`
# -------------------------------------------------------------------------


async def _smoke() -> None:
    auth = XaiAuth()
    creds = await auth.ensure_fresh()
    headers = await auth.auth_headers()
    masked = {
        k: (v[:12] + "..." + v[-6:] if k == "Authorization" else v)
        for k, v in headers.items()
    }
    print(f"auth_path:  {creds.auth_path}")
    print(f"auth_mode:  {creds.auth_mode}")
    print(f"expires_in: {creds.seconds_until_expiry}s")
    print(f"base_url:   {auth.base_url}")
    print(f"headers:    {masked}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_smoke())
