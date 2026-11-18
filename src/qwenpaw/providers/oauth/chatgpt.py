# -*- coding: utf-8 -*-
"""Local ChatGPT registration, encrypted sessions, and token renewal."""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
from filelock import FileLock

from ...constant import SECRET_DIR
from ...security.secret_store import decrypt_dict_fields, encrypt_dict_fields
from ...utils.oauth_callback import oauth_error_html, oauth_success_html
from ..provider_persistence import write_snapshot_payload
from .base import generate_code_challenge, generate_code_verifier

ISSUER = f"https://auth.openai.com"
RESOURCE = f"https://api.openai.com/v1"
PLAN_SCOPE = f"chatgpt.tokens.use.direct"
logger = logging.getLogger(__name__)


@dataclass
class SignInAttempt:
    """Keep untrusted browser callbacks separate from the active account."""

    state: str
    verifier: str
    nonce: str
    redirect: str
    client_id: str | None
    deadline: float
    status: str = f"pending"


class ChatGPTAccounts:
    """Own account registrations without exposing tokens to the console."""

    def __init__(self, directory: Path = SECRET_DIR / f"chatgpt"):
        self.directory = directory
        self.path = directory / f"accounts.json"
        self.attempt: SignInAttempt | None = None
        self._guard = threading.RLock()

    def _lock(self) -> FileLock:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return FileLock(self.directory / f"accounts.lock", timeout=35)

    def _read(self) -> dict:
        if not self.path.exists():
            return {
                f"host": uuid.uuid4().urn,
                f"active": None,
                f"accounts": {},
            }
        payload = decrypt_dict_fields(
            json.loads(self.path.read_text(encoding=f"utf-8")),
            frozenset({f"payload"}),
        )
        return json.loads(payload[f"payload"])

    def _save(self, data: dict) -> None:
        payload = encrypt_dict_fields(
            {f"payload": json.dumps(data)},
            frozenset({f"payload"}),
        )
        write_snapshot_payload(payload, self.path)

    def status(self) -> dict:
        with self._lock():
            data = self._read()
        current = data[f"accounts"].get(data[f"active"], {})
        connected = bool(current.get(f"refresh_token"))
        return {
            f"active": data[f"active"],
            f"connected": connected,
            f"sharing": connected and PLAN_SCOPE in current.get(f"scopes", []),
            f"accounts": [
                {f"id": key, f"email": value.get(f"email", f"")}
                for key, value in data[f"accounts"].items()
            ],
        }

    @staticmethod
    def _discovery() -> dict:
        response = httpx.get(
            f"{ISSUER}/.well-known/openid-configuration",
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _token(form: dict) -> dict:
        response = httpx.post(
            f"{ISSUER}/api/accounts/oauth/token",
            data={**form, f"resource": RESOURCE},
            timeout=30,
        )
        if not response.is_success:
            raise ValueError(f"ChatGPT authorization expired. Sign in again.")
        return response.json()

    def _identity(self, token: str, client_id: str, nonce: str) -> dict:
        keys = jwt.PyJWKClient(self._discovery()[f"jwks_uri"])
        claims = jwt.decode(
            token,
            keys.get_signing_key_from_jwt(token).key,
            algorithms=[f"RS256"],
            audience=client_id,
            issuer=ISSUER,
            options={f"require": [f"exp", f"sub", f"iss", f"aud", f"nonce"]},
        )
        if not secrets.compare_digest(claims[f"nonce"], nonce):
            raise ValueError(f"Invalid sign-in nonce.")
        return claims

    @staticmethod
    def _credentials(token: dict, previous: dict) -> dict:
        return {
            **previous,
            f"access_token": token[f"access_token"],
            f"refresh_token": token.get(
                f"refresh_token",
                previous.get(f"refresh_token"),
            ),
            f"id_token": token.get(f"id_token", previous.get(f"id_token")),
            f"expires_at": time.time() + token[f"expires_in"],
            f"scopes": (
                token[f"scope"].split()
                if f"scope" in token
                else previous.get(f"scopes", [])
            ),
        }

    def start(self, account_id: str | None = None) -> dict:
        with self._guard, self._lock():
            if self.attempt and self.attempt.status == f"pending":
                if time.monotonic() < self.attempt.deadline:
                    raise ValueError(f"A ChatGPT sign-in is already pending.")
            data = self._read()
            if account_id and account_id not in data[f"accounts"]:
                raise ValueError(f"Select a saved ChatGPT account.")
            account = data[f"accounts"].get(account_id, {})
            self._save(data)
            owner = self

            class Callback(BaseHTTPRequestHandler):
                def log_message(self, *_args):
                    """Do not log callback URLs or authorization codes."""

                def do_GET(self):  # pylint: disable=invalid-name
                    parsed = urlsplit(self.path)
                    query = {
                        k: v[0] for k, v in parse_qs(parsed.query).items()
                    }
                    ok = parsed.path == f"/auth/callback" and owner.complete(
                        attempt,
                        query,
                    )
                    body = (
                        oauth_success_html(f"openai-chatgpt")
                        if ok
                        else oauth_error_html(
                            f"Authorization failed. Please retry in QwenPaw.",
                        )
                    ).encode()
                    self.send_response(200 if ok else 400)
                    self.send_header(
                        f"Content-Type",
                        f"text/html; charset=utf-8",
                    )
                    self.send_header(f"Cache-Control", f"no-store")
                    self.send_header(f"Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            server = HTTPServer((f"127.0.0.1", 0), Callback)
            server.timeout = 0.5
            attempt = SignInAttempt(
                state=secrets.token_urlsafe(32),
                verifier=generate_code_verifier(),
                nonce=secrets.token_urlsafe(32),
                redirect=(
                    f"http://127.0.0.1:{server.server_port}" f"/auth/callback"
                ),
                client_id=account_id,
                deadline=time.monotonic() + 300,
            )
            self.attempt = attempt

            def listen():
                try:
                    while attempt.status == f"pending":
                        if time.monotonic() >= attempt.deadline:
                            attempt.status = f"failed"
                            break
                        server.handle_request()
                finally:
                    server.server_close()

            threading.Thread(target=listen, daemon=True).start()
            params = {
                f"client_id": account_id or f"dynamic_agent_client",
                f"ext_agent_host_id": data[f"host"],
                f"response_type": f"code",
                f"redirect_uri": attempt.redirect,
                f"scope": f"openid profile email offline_access "
                f"resource.invoke {PLAN_SCOPE}",
                f"resource": RESOURCE,
                f"state": attempt.state,
                f"nonce": attempt.nonce,
                f"code_challenge_method": f"S256",
                f"code_challenge": generate_code_challenge(attempt.verifier),
            }
            if not account_id:
                params[f"agent_name_hint"] = f"QwenPaw"
            for hint, key in (
                (f"id_token_hint", f"id_token"),
                (f"login_hint", f"email"),
            ):
                if account.get(key):
                    params[hint] = account[key]
            return {
                f"state": attempt.state,
                f"authorize_url": f"{ISSUER}/api/accounts/authorize?"
                f"{urlencode(params)}",
            }

    def complete(self, attempt: SignInAttempt, query: dict) -> bool:
        with self._guard:
            if (
                attempt is not self.attempt
                or attempt.status != f"pending"
                or time.monotonic() >= attempt.deadline
                or not secrets.compare_digest(
                    query.get(f"state", f""),
                    attempt.state,
                )
            ):
                return False
            attempt.status = f"exchanging"
            try:
                if query.get(f"error") or not query.get(f"code"):
                    raise ValueError(f"Authorization declined.")
                client_id = query.get(f"client_id") or attempt.client_id
                if (
                    not client_id
                    or client_id == f"dynamic_agent_client"
                    or attempt.client_id
                    and client_id != attempt.client_id
                ):
                    raise ValueError(f"Invalid account registration.")
                with self._lock():
                    data = self._read()
                    data[f"accounts"].setdefault(client_id, {})
                    self._save(data)
                token = self._token(
                    {
                        f"grant_type": f"authorization_code",
                        f"client_id": client_id,
                        f"code": query[f"code"],
                        f"code_verifier": attempt.verifier,
                        f"redirect_uri": attempt.redirect,
                    },
                )
                claims = self._identity(
                    token[f"id_token"],
                    client_id,
                    attempt.nonce,
                )
                with self._lock():
                    data = self._read()
                    previous = data[f"accounts"].get(client_id, {})
                    if previous.get(f"sub", claims[f"sub"]) != claims[f"sub"]:
                        raise ValueError(f"The ChatGPT account changed.")
                    data[f"accounts"][client_id] = self._credentials(
                        token,
                        {
                            f"sub": claims[f"sub"],
                            f"email": claims.get(f"email", f""),
                        },
                    )
                    data[f"active"] = client_id
                    self._save(data)
                attempt.status = f"completed"
                return True
            except Exception as exc:
                logger.warning(f"ChatGPT sign-in failed: {type(exc).__name__}")
                attempt.status = f"failed"
                return False

    def cancel(self, state: str) -> None:
        with self._guard:
            if self.attempt and self.attempt.state == state:
                if self.attempt.status == f"pending":
                    self.attempt.status = f"cancelled"

    def select(self, account_id: str) -> None:
        with self._guard, self._lock():
            if self.attempt and self.attempt.status == f"pending":
                self.attempt.status = f"cancelled"
            data = self._read()
            if account_id not in data[f"accounts"]:
                raise ValueError(f"Unknown ChatGPT account.")
            data[f"active"] = account_id
            self._save(data)

    def access_token(self) -> str:
        with self._lock():
            data = self._read()
            client_id = data[f"active"]
            account = data[f"accounts"].get(client_id, {})
            if not account.get(f"refresh_token"):
                raise ValueError(f"Sign in to ChatGPT first.")
            if account.get(f"expires_at", 0) < time.time() + 60:
                token = self._token(
                    {
                        f"grant_type": f"refresh_token",
                        f"client_id": client_id,
                        f"refresh_token": account[f"refresh_token"],
                    },
                )
                account = self._credentials(token, account)
                data[f"accounts"][client_id] = account
                self._save(data)
            if PLAN_SCOPE not in account.get(f"scopes", []):
                raise ValueError(
                    f"Allow ChatGPT plan usage and sign in again.",
                )
            return account[f"access_token"]

    def sign_out(self) -> bool:
        with self._guard:
            if self.attempt and self.attempt.status == f"pending":
                self.attempt.status = f"cancelled"
            with self._lock():
                data = self._read()
                client_id = data[f"active"]
                account = data[f"accounts"].get(client_id, {})
                refresh_token = account.get(f"refresh_token")
                for key in (f"access_token", f"refresh_token", f"id_token"):
                    account.pop(key, None)
                self._save(data)
            revoked = True
            if refresh_token:
                try:
                    endpoint = self._discovery()[f"revocation_endpoint"]
                    for delay in (0, 0.5, 1):
                        if delay:
                            time.sleep(delay)
                        response = httpx.post(
                            endpoint,
                            data={
                                f"token": refresh_token,
                                f"token_type_hint": f"refresh_token",
                                f"client_id": client_id,
                            },
                            timeout=10,
                        )
                        if response.status_code < 500:
                            break
                    revoked = response.status_code == 200
                except httpx.HTTPError:
                    revoked = False
            return revoked


chatgpt_accounts = ChatGPTAccounts()
