# -*- coding: utf-8 -*-
"""Helpers for Codex-backed OpenAI browser auth."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from .auth_helper_base import BaseAuthHelper
from .auth_helper_registry import AUTH_HELPER_REGISTRY
from .provider import Provider, ProviderAuth

logger = logging.getLogger(__name__)

CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_AUTH_ISSUER = "https://auth.openai.com"
TOKEN_REFRESH_INTERVAL = timedelta(minutes=7)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso8601(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _format_iso8601(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    if not token or token.count(".") < 2:
        return {}
    _, payload, _ = token.split(".", 2)
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode()))
    except Exception:
        return {}


def _derive_identity(id_token: str) -> str:
    payload = _decode_jwt_payload(id_token)
    email = payload.get("email")
    if isinstance(email, str) and email:
        return email
    profile = payload.get("https://api.openai.com/profile") or {}
    if isinstance(profile, dict):
        email = profile.get("email")
        if isinstance(email, str) and email:
            return email
    return ""


def _derive_account_id(id_token: str, fallback: str = "") -> str:
    payload = _decode_jwt_payload(id_token)
    auth = payload.get("https://api.openai.com/auth") or {}
    if isinstance(auth, dict):
        account_id = auth.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return fallback


def _derive_expires_at(access_token: str) -> str:
    payload = _decode_jwt_payload(access_token)
    exp = payload.get("exp")
    if isinstance(exp, (int, float)):
        return _format_iso8601(datetime.fromtimestamp(exp, tz=timezone.utc))
    return ""


def is_oauth_authorized(provider: Provider) -> bool:
    auth = provider.auth
    return (
        auth.mode == "oauth_browser"
        and auth.status == "authorized"
        and bool(auth.access_token)
        and bool(auth.account_id)
    )


def get_chatgpt_headers(provider: Provider) -> dict[str, str]:
    auth = provider.auth
    return {
        "Authorization": f"Bearer {auth.access_token}",
        "ChatGPT-Account-Id": auth.account_id,
        "User-Agent": "codex-cli",
        "Accept": "application/json",
    }


def needs_token_refresh(auth: ProviderAuth) -> bool:
    if auth.mode != "oauth_browser" or not auth.refresh_token:
        return False

    expires_at = _parse_iso8601(auth.expires_at)
    if expires_at is not None and expires_at <= _utcnow() + timedelta(
        minutes=1,
    ):
        return True

    last_refresh = _parse_iso8601(auth.last_refresh)
    return (
        last_refresh is None
        or (_utcnow() - last_refresh) >= TOKEN_REFRESH_INTERVAL
    )


async def refresh_openai_provider_auth(
    provider: Provider,
    persist: Callable[[Provider], None],
) -> ProviderAuth:
    """Refresh OAuth credentials in-place when needed."""
    auth = provider.auth
    if auth.mode != "oauth_browser":
        return auth
    if not auth.refresh_token:
        auth.status = "expired"
        auth.error = "Missing refresh token"
        persist(provider)
        raise RuntimeError("Missing refresh token")
    if not needs_token_refresh(auth):
        return auth

    payload = {
        "client_id": CODEX_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": auth.refresh_token,
    }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{CODEX_AUTH_ISSUER}/oauth/token",
            headers={"Content-Type": "application/json"},
            json=payload,
        )

    if response.status_code >= 400:
        auth.status = "expired" if response.status_code == 401 else "error"
        auth.error = response.text[:300]
        persist(provider)
        raise RuntimeError(f"Failed to refresh token: {response.status_code}")

    data = response.json()
    auth.id_token = str(data.get("id_token") or auth.id_token or "")
    auth.access_token = str(
        data.get("access_token") or auth.access_token or "",
    )
    auth.refresh_token = str(
        data.get("refresh_token") or auth.refresh_token or "",
    )
    auth.identity = _derive_identity(auth.id_token) or auth.identity
    auth.account_id = _derive_account_id(auth.id_token, auth.account_id)
    auth.expires_at = _derive_expires_at(auth.access_token) or auth.expires_at
    auth.last_refresh = _format_iso8601(_utcnow())
    auth.status = "authorized"
    auth.error = ""
    persist(provider)
    return auth


async def refresh_provider_auth(
    provider: Provider,
    persist: Callable[[Provider], None],
) -> ProviderAuth:
    """Backward-compatible wrapper around the OpenAI refresh flow."""
    return await refresh_openai_provider_auth(provider, persist)


def load_provider_auth_from_codex_home(codex_home: Path) -> ProviderAuth:
    """Load a ProviderAuth instance from a Codex auth.json file."""
    auth_file = codex_home / "auth.json"
    if not auth_file.exists():
        raise FileNotFoundError(f"Codex auth file not found: {auth_file}")
    data = json.loads(auth_file.read_text(encoding="utf-8"))
    tokens = data.get("tokens") or {}
    id_token = str(tokens.get("id_token") or "")
    access_token = str(tokens.get("access_token") or "")
    refresh_token = str(tokens.get("refresh_token") or "")
    account_id = str(tokens.get("account_id") or "")
    return ProviderAuth(
        mode="oauth_browser",
        status="authorized" if access_token and account_id else "error",
        identity=_derive_identity(id_token),
        account_id=_derive_account_id(id_token, account_id),
        access_token=access_token,
        refresh_token=refresh_token,
        id_token=id_token,
        expires_at=_derive_expires_at(access_token),
        last_refresh=str(data.get("last_refresh") or "")
        or _format_iso8601(_utcnow()),
        error="",
    )


@dataclass
class LoginSession:
    session_id: str
    provider_id: str
    codex_home: Path
    process: asyncio.subprocess.Process
    previous_auth: ProviderAuth
    status: str = "authorizing"
    auth_url: str = ""
    error: str = ""
    created_at: str = field(default_factory=lambda: _format_iso8601(_utcnow()))
    stdout_lines: list[str] = field(default_factory=list)
    wait_task: asyncio.Task[None] | None = None

    def to_dict(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "provider_id": self.provider_id,
            "status": self.status,
            "auth_url": self.auth_url,
            "error": self.error,
            "created_at": self.created_at,
        }


class OpenAIAuthHelper(BaseAuthHelper):
    """Manage browser login sessions via the official Codex CLI."""

    helper_id = "openai"

    def supports(self, provider: Provider) -> bool:
        return "oauth_browser" in provider.auth_modes and (
            provider.auth_helper == self.helper_id
            or (provider.id == "openai" and not provider.auth_helper)
        )

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, LoginSession] = {}

    def is_available(self) -> bool:
        return shutil.which("codex") is not None

    def unavailable_reason(self) -> str:
        return (
            "Codex CLI is required for ChatGPT browser sign-in. "
            "Install the codex command and make sure it is available in PATH."
        )

    async def refresh_auth(
        self,
        provider: Provider,
        persist: Callable[[Provider], None],
    ) -> ProviderAuth:
        return await refresh_openai_provider_auth(provider, persist)

    async def start_browser_login(
        self,
        provider: Provider,
        auth_root: Path,
        persist: Callable[[Provider], None],
    ) -> LoginSession:
        if not self.supports(provider):
            raise ValueError(
                "Browser sign-in is not supported for provider "
                f"'{provider.id}'",
            )

        session_id = str(uuid.uuid4())
        codex_home = auth_root / session_id
        codex_home.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["CODEX_HOME"] = str(codex_home)

        process = await asyncio.create_subprocess_exec(
            "codex",
            "login",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        session = LoginSession(
            session_id=session_id,
            provider_id=provider.id,
            codex_home=codex_home,
            process=process,
            previous_auth=provider.auth.model_copy(deep=True),
        )
        async with self._lock:
            self._sessions[session_id] = session

        session.wait_task = asyncio.create_task(
            self._watch_session(session, provider, persist),
        )
        await self._wait_for_auth_url(session)
        provider.auth = session.previous_auth.model_copy(
            update={
                "mode": "oauth_browser",
                "status": "authorizing",
                "error": "",
            },
        )
        persist(provider)
        return session

    async def _wait_for_auth_url(self, session: LoginSession) -> None:
        deadline = asyncio.get_running_loop().time() + 5
        while asyncio.get_running_loop().time() < deadline:
            if session.auth_url or session.error:
                return
            await asyncio.sleep(0.1)

    async def _watch_session(
        self,
        session: LoginSession,
        provider: Provider,
        persist: Callable[[Provider], None],
    ) -> None:
        assert session.process.stdout is not None
        try:
            while True:
                line = await session.process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", "ignore").strip()
                session.stdout_lines.append(text)
                if text.startswith("https://auth.openai.com/oauth/authorize?"):
                    session.auth_url = text

            return_code = await session.process.wait()
            if return_code == 0:
                provider.auth = load_provider_auth_from_codex_home(
                    session.codex_home,
                )
                provider.auth.mode = "oauth_browser"
                provider.auth.status = "authorized"
                try:
                    oauth_models = await provider.fetch_models()
                    if hasattr(provider, "oauth_models"):
                        setattr(provider, "oauth_models", oauth_models)
                    if not oauth_models:
                        logger.warning(
                            "OpenAI OAuth login succeeded but no models "
                            "were fetched. The model list may be empty "
                            "due to network issues or "
                            "authentication problems.",
                        )
                    else:
                        logger.info(
                            "OpenAI OAuth login succeeded, fetched %d models",
                            len(oauth_models),
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to discover OpenAI oauth models "
                        "after login: %s",
                        exc,
                        exc_info=True,
                    )
                persist(provider)
                session.status = "authorized"
            else:
                session.status = "error"
                session.error = self._extract_error(session)
                provider.auth = session.previous_auth.model_copy()
                persist(provider)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("OpenAI login session failed: %s", exc)
            session.status = "error"
            session.error = str(exc)
            provider.auth = session.previous_auth.model_copy()
            persist(provider)
        finally:
            shutil.rmtree(session.codex_home, ignore_errors=True)

    @staticmethod
    def _extract_error(session: LoginSession) -> str:
        for line in reversed(session.stdout_lines):
            if line and not line.startswith("https://"):
                return line
        return "Login failed"

    async def get_session(self, session_id: str) -> LoginSession | None:
        async with self._lock:
            return self._sessions.get(session_id)


OPENAI_AUTH_HELPER = OpenAIAuthHelper()
AUTH_HELPER_REGISTRY.register(OPENAI_AUTH_HELPER)


def is_codex_cli_available() -> bool:
    """Return whether the Codex CLI is available in PATH."""
    return OPENAI_AUTH_HELPER.is_available()
