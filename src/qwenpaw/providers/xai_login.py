# -*- coding: utf-8 -*-
"""xAI OAuth PKCE loopback login flow.

Self-contained port of hermes-agent's xAI loopback login (the 8
functions described in ``agent/credential_sources.py`` and
``hermes_cli/auth.py``).  No hermes_cli dependency — talks directly
to xAI's well-known OpenID discovery + token endpoints, runs a
single-shot HTTP server on loopback :56121 to capture the
authorization code, and writes the resulting tokens to
``~/.xai/auth.json`` (or ``$XAI_HOME/auth.json``).

The flow:
    1. Fetch ``.well-known/openid-configuration`` from auth.x.ai.
    2. Generate PKCE verifier/challenge + state/nonce.
    3. Open the browser to the authorize URL (or print it).
    4. Wait for the user's browser to hit ``/callback`` with ``code``.
    5. Exchange the code at the token_endpoint.
    6. Atomically write tokens + discovery to ``auth.json``.

xAI server gates on (client_id, redirect_uri, scope) — we reuse the
Grok-CLI client_id since that's the only public identifier the OAuth
server accepts for loopback redirects.  Same setup hermes-agent uses.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import os
import secrets
import socket
import socketserver
import threading
import time
import urllib.parse
import uuid
import webbrowser
from pathlib import Path
from typing import Any

import httpx

from .xai_auth import (
    DEFAULT_XAI_BASE_URL,
    XAI_OAUTH_CLIENT_ID,
    XAI_OAUTH_ISSUER,
    _resolve_auth_path,
)

logger = logging.getLogger(__name__)

# Fixed loopback port matches the redirect_uri registered with xAI for
# the Grok-CLI client.  Falling back to a different port would 400 at
# the authorize step because xAI compares ``redirect_uri`` byte-for-
# byte to the one bound to ``client_id``.
LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 56121
LOOPBACK_REDIRECT_URI = f"http://{LOOPBACK_HOST}:{LOOPBACK_PORT}/callback"

# Hermes ships a generic scope set covering chat + image + video + TTS.
# ``offline_access`` is what gets us the refresh_token.
XAI_OAUTH_SCOPE = (
    "openid profile email offline_access grok-cli:access api:access"
)

# Default callback wait window — the user has 5 minutes to complete
# the consent screen before we give up and the local server shuts down.
CALLBACK_TIMEOUT_S = 300


def _pkce_verifier() -> str:
    return (
        base64.urlsafe_b64encode(secrets.token_bytes(96))
        .rstrip(b"=")
        .decode("ascii")
    )


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def _discover(timeout: float = 15.0) -> dict[str, str]:
    url = f"{XAI_OAUTH_ISSUER}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        body = resp.json()
    authorize = body.get("authorization_endpoint")
    token = body.get("token_endpoint")
    if not authorize or not token:
        raise RuntimeError(
            f"xAI OIDC discovery returned no endpoints: {body!r}",
        )
    # Defense-in-depth — only trust endpoints on auth.x.ai.  A
    # compromised DNS or MITM that redirected discovery elsewhere
    # would otherwise steer the user's browser to a phishing host.
    for label, ep in (("authorization", authorize), ("token", token)):
        parsed = urllib.parse.urlparse(ep)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".x.ai")
        ):
            raise RuntimeError(
                f"xAI OIDC {label}_endpoint refused: "
                f"not https on .x.ai ({ep})",
            )
    return {"authorization_endpoint": authorize, "token_endpoint": token}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Single-shot handler — captures the first /callback hit and quits."""

    # Class-level slots populated by the parent before serve_forever().
    result_holder: dict[str, Any] = {}
    expected_state: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        # Suppress default stderr access logs — they'd leak the auth
        # code (which is in the query string) to journalctl.
        logger.debug("xai-loopback: " + fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        code = (params.get("code") or [""])[0] or None
        state = (params.get("state") or [""])[0] or None
        error = (params.get("error") or [""])[0] or None

        body = (
            b"<html><body><h1>xAI login complete</h1>"
            b"<p>You can close this tab.</p></body></html>"
        )
        if error:
            self.result_holder["error"] = f"xAI returned error: {error}"
            body = (
                b"<html><body><h1>xAI login failed</h1>"
                b"<p>See terminal for details.</p></body></html>"
            )
        elif not code:
            self.result_holder["error"] = "Callback missing ?code= param"
        elif state != self.expected_state:
            # CSRF defense — never trust a code that arrives without
            # the state value we issued, even if the user appears to
            # be the only person hitting loopback.
            self.result_holder["error"] = (
                f"State mismatch (got {state!r}, "
                f"expected {self.expected_state!r})"
            )
        else:
            self.result_holder["code"] = code

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_callback_server(
    state: str,
) -> tuple[socketserver.TCPServer, dict[str, Any]]:
    result_holder: dict[str, Any] = {}

    class _Handler(_CallbackHandler):
        pass

    _Handler.result_holder = result_holder
    _Handler.expected_state = state

    # Set SO_REUSEADDR on the *class* before instantiation: TCPServer's
    # __init__ binds the socket immediately, so an instance-level
    # ``server.allow_reuse_address = True`` set afterwards is too late —
    # the bind has already happened without the flag, and a TIME_WAIT
    # socket from a previous login attempt would still block this one.
    class _ReusableServer(socketserver.TCPServer):
        allow_reuse_address = True

    try:
        server = _ReusableServer(
            (LOOPBACK_HOST, LOOPBACK_PORT),
            _Handler,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Could not bind {LOOPBACK_HOST}:{LOOPBACK_PORT} for xAI loopback "
            f"({exc}). The xAI OAuth client is registered against this exact "
            f"port — close whatever else is using it and retry.",
        ) from exc
    return server, result_holder


def _wait_for_code(
    server: socketserver.TCPServer,
    result_holder: dict[str, Any],
    timeout: float,
) -> str:
    thread = threading.Thread(
        target=server.serve_forever,
        name="xai-loopback",
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if "code" in result_holder:
                return result_holder["code"]
            if "error" in result_holder:
                raise RuntimeError(result_holder["error"])
            time.sleep(0.25)
        raise TimeoutError(
            f"Timed out after {timeout:.0f}s waiting for xAI callback. "
            "Did the browser tab finish loading?",
        )
    finally:
        server.shutdown()
        server.server_close()


async def _exchange_code(
    *,
    token_endpoint: str,
    code: str,
    code_verifier: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "client_id": XAI_OAUTH_CLIENT_ID,
                "code": code,
                "redirect_uri": LOOPBACK_REDIRECT_URI,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"xAI token exchange failed: HTTP {resp.status_code} — "
            f"{resp.text[:300]}",
        )
    body = resp.json()
    if not body.get("access_token") or not body.get("refresh_token"):
        raise RuntimeError(
            "xAI token exchange returned no access_token / refresh_token; "
            "the OAuth scope may not include offline_access. Body keys: "
            f"{list(body.keys())}",
        )
    return body


def _save_auth(
    *,
    auth_path: Path,
    tokens: dict[str, Any],
    discovery: dict[str, str],
) -> None:
    auth_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "auth_mode": "oauth_pkce",
        "tokens": {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "id_token": tokens.get("id_token"),
        },
        "discovery": discovery,
        "redirect_uri": LOOPBACK_REDIRECT_URI,
        "issuer": XAI_OAUTH_ISSUER,
        "base_url": DEFAULT_XAI_BASE_URL,
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp = auth_path.with_suffix(auth_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, auth_path)


async def run_loopback_login(
    *,
    open_browser: bool = True,
    timeout: float = CALLBACK_TIMEOUT_S,
) -> Path:
    """Run the full PKCE loopback flow and persist tokens.

    Returns the auth_path that was written.  Raises ``RuntimeError`` /
    ``TimeoutError`` on any failure.  Safe to call repeatedly — each
    run replaces the previous auth.json atomically.
    """
    auth_path = _resolve_auth_path()
    discovery = await _discover()
    code_verifier = _pkce_verifier()
    state = uuid.uuid4().hex
    nonce = uuid.uuid4().hex

    server, result_holder = _start_callback_server(state)

    params = {
        "client_id": XAI_OAUTH_CLIENT_ID,
        "response_type": "code",
        "scope": XAI_OAUTH_SCOPE,
        "redirect_uri": LOOPBACK_REDIRECT_URI,
        "code_challenge": _pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
        "state": state,
        "nonce": nonce,
        # ``plan=generic`` is what unlocks loopback redirects on the
        # xAI OAuth tier; without it the authorize endpoint 400s for
        # any redirect_uri that isn't a registered web callback.
        "plan": "generic",
        "referrer": "qwenpaw",
    }
    authorize_url = (
        discovery["authorization_endpoint"]
        + "?"
        + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    )

    print(
        f"\nOpen this URL in your browser to sign in to xAI:\n\n  "
        f"{authorize_url}\n",
    )
    if open_browser:
        try:
            webbrowser.open(authorize_url)
        except Exception:
            pass

    # serve_forever runs on a background thread — we block here until
    # the handler captures the code or the timeout fires.
    code = await _to_thread(_wait_for_code, server, result_holder, timeout)

    tokens = await _exchange_code(
        token_endpoint=discovery["token_endpoint"],
        code=code,
        code_verifier=code_verifier,
    )
    _save_auth(auth_path=auth_path, tokens=tokens, discovery=discovery)
    return auth_path


async def _to_thread(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Tiny shim — asyncio.to_thread back-compat for older Pythons.

    qwenpaw runs on 3.10+ but this file is intentionally dep-free so
    it can be unit-tested in isolation without importing the rest of
    the package.  to_thread was added in 3.9, so this is a safety
    net rather than a back-compat shim — kept for clarity.
    """
    import asyncio

    return await asyncio.to_thread(fn, *args, **kwargs)


def is_port_free(host: str = LOOPBACK_HOST, port: int = LOOPBACK_PORT) -> bool:
    """Probe whether the loopback port we need is currently free.

    Used by the CLI to give a clearer pre-flight error than the bind
    failure inside ``_start_callback_server``.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()
