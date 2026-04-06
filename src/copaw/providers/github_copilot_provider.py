# -*- coding: utf-8 -*-
"""GitHub Copilot provider with GitHub device authorization."""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from typing import Any

import httpx
from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, Field, PrivateAttr

try:
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError
except ImportError:  # pragma: no cover - exercised via JSON fallback
    keyring = None  # type: ignore[assignment]
    KeyringError = Exception  # type: ignore[misc,assignment]
    PasswordDeleteError = Exception  # type: ignore[misc,assignment]

from .openai_provider import OpenAIProvider
from .openai_responses_chat_model_compat import OpenAIResponsesChatModelCompat
from .provider import ModelInfo, ProviderInfo


logger = logging.getLogger(__name__)

GITHUB_COPILOT_OAUTH_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
GITHUB_COPILOT_API_URL = "https://api.individual.githubcopilot.com"
DEFAULT_COPILOT_TOKEN_TTL = 25 * 60
COPILOT_TOKEN_REFRESH_SKEW = 60
RESPONSES_API_MIN_MAX_OUTPUT_TOKENS = 16
GITHUB_AUTH_STORAGE_KEYCHAIN = "keychain"
GITHUB_AUTH_STORAGE_JSON = "json"
GITHUB_AUTH_STORAGE_NONE = "none"
GITHUB_AUTH_PERSIST_FIELDS = (
    "github_oauth_token",
    "github_token_type",
    "github_scope",
    "github_user_login",
    "github_user_id",
)


class DeviceAuthorizationSession(BaseModel):
    session_id: str
    device_code: str
    user_code: str
    verification_uri: str
    expires_at: int
    interval: int = 5
    status: str = "pending"
    last_message: str = ""


class DeviceAuthorizationPollResult(BaseModel):
    status: str
    message: str = ""
    interval: int | None = None
    slow_down: bool = False


class GitHubCopilotProvider(OpenAIProvider):
    """OpenAI-compatible provider backed by GitHub Copilot."""

    supports_oauth_login: bool = True
    auth_method: str | None = "github-device"
    is_authenticated: bool = False
    auth_account_label: str | None = None
    auth_expires_at: int | None = None
    github_oauth_token: str = ""
    github_token_type: str = "bearer"
    github_scope: str = ""
    github_user_login: str = ""
    github_user_id: int | None = None
    github_auth_storage: str | None = None
    copilot_access_token: str = ""
    copilot_token_expires_at: int | None = None

    _device_sessions: dict[str, DeviceAuthorizationSession] = PrivateAttr(
        default_factory=dict,
    )

    _PERSIST_EXCLUDES = {
        "api_key",
        "supports_oauth_login",
        "is_authenticated",
        "auth_method",
        "auth_account_label",
        "auth_expires_at",
        "copilot_access_token",
        "copilot_token_expires_at",
    }

    def model_post_init(self, __context: Any) -> None:
        self._clear_runtime_copilot_state()
        storage = (self.github_auth_storage or "").strip().lower()
        if storage == GITHUB_AUTH_STORAGE_NONE:
            self._clear_github_oauth_state()
            return
        if storage == GITHUB_AUTH_STORAGE_KEYCHAIN:
            payload = self._load_keyring_auth_payload()
            if payload:
                self._apply_github_auth_payload(payload)
            else:
                self._clear_github_oauth_state()
                self.github_auth_storage = GITHUB_AUTH_STORAGE_NONE
            return
        if storage != GITHUB_AUTH_STORAGE_JSON:
            payload = self._load_keyring_auth_payload()
            if payload:
                self._apply_github_auth_payload(payload)
                self.github_auth_storage = GITHUB_AUTH_STORAGE_KEYCHAIN
        self.auth_account_label = self.github_user_login or None
        self.is_authenticated = bool(self.github_oauth_token)

    def _keyring_service_name(self) -> str:
        return f"io.agentscope.copaw.provider.{self.id}"

    def _clear_runtime_copilot_state(self) -> None:
        self.copilot_access_token = ""
        self.copilot_token_expires_at = None
        self.auth_expires_at = None
        self.api_key = ""

    def _clear_github_oauth_state(self) -> None:
        self.is_authenticated = False
        self.auth_account_label = None
        self.github_oauth_token = ""
        self.github_token_type = "bearer"
        self.github_scope = ""
        self.github_user_login = ""
        self.github_user_id = None

    def _github_auth_payload(self) -> dict[str, Any] | None:
        token = (self.github_oauth_token or "").strip()
        if not token:
            return None
        payload: dict[str, Any] = {
            "github_oauth_token": token,
            "github_token_type": (self.github_token_type or "bearer").strip()
            or "bearer",
        }
        if self.github_scope:
            payload["github_scope"] = self.github_scope
        if self.github_user_login:
            payload["github_user_login"] = self.github_user_login
        if self.github_user_id is not None:
            payload["github_user_id"] = self.github_user_id
        return payload

    def _apply_github_auth_payload(self, payload: dict[str, Any]) -> None:
        self.github_oauth_token = str(payload.get("github_oauth_token", "") or "")
        self.github_token_type = str(
            payload.get("github_token_type", "bearer") or "bearer"
        )
        self.github_scope = str(payload.get("github_scope", "") or "")
        self.github_user_login = str(
            payload.get("github_user_login", "") or ""
        )
        user_id = payload.get("github_user_id")
        self.github_user_id = int(user_id) if user_id is not None else None
        self.auth_account_label = self.github_user_login or None
        self.is_authenticated = bool(self.github_oauth_token)

    def _load_keyring_auth_payload(self) -> dict[str, Any] | None:
        if keyring is None:
            return None
        try:
            secret = keyring.get_password(
                self._keyring_service_name(),
                "oauth",
            )
        except KeyringError as exc:
            logger.warning(
                "Failed to load GitHub OAuth secret for provider '%s': %s",
                self.id,
                exc,
            )
            return None
        if not secret:
            return None
        try:
            payload = json.loads(secret)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _save_keyring_auth_payload(self, payload: dict[str, Any]) -> bool:
        if keyring is None:
            return False
        try:
            keyring.set_password(
                self._keyring_service_name(),
                "oauth",
                json.dumps(payload, ensure_ascii=False),
            )
            return True
        except KeyringError as exc:
            logger.warning(
                "Failed to save GitHub OAuth secret for provider '%s': %s",
                self.id,
                exc,
            )
            return False

    def _delete_keyring_auth_payload(self) -> None:
        if keyring is None:
            return
        try:
            keyring.delete_password(
                self._keyring_service_name(),
                "oauth",
            )
        except PasswordDeleteError:
            return
        except KeyringError as exc:
            logger.warning(
                "Failed to delete GitHub OAuth secret for provider '%s': %s",
                self.id,
                exc,
            )

    def _cleanup_expired_device_sessions(self, now: int | None = None) -> None:
        current_time = int(time.time()) if now is None else now
        expired_ids = [
            session_id
            for session_id, session in self._device_sessions.items()
            if session.expires_at <= current_time
        ]
        for session_id in expired_ids:
            self._device_sessions.pop(session_id, None)

    def _copilot_api_headers(self) -> dict[str, str]:
        return {
            "Editor-Version": "vscode/1.98.0",
            "Editor-Plugin-Version": "copilot-chat/0.26.7",
            "Copilot-Integration-Id": "vscode-chat",
            "User-Agent": "CoPaw/0.2",
            "Accept": "application/json",
        }

    def _github_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "CoPaw/0.2",
        }

    def _oauth_auth_headers(self) -> dict[str, str]:
        headers = self._github_headers()
        headers["Authorization"] = f"Bearer {self.github_oauth_token}"
        return headers

    def _copilot_token_valid(self) -> bool:
        expires_at = self.copilot_token_expires_at or 0
        return bool(
            self.copilot_access_token
            and expires_at > int(time.time()) + COPILOT_TOKEN_REFRESH_SKEW,
        )

    @staticmethod
    def _derive_copilot_base_url_from_token(token: str) -> str | None:
        trimmed = token.strip()
        if not trimmed:
            return None

        match = re.search(
            r"(?:^|;)\s*proxy-ep=([^;\s]+)", trimmed, re.IGNORECASE
        )
        proxy_ep = match.group(1).strip() if match else ""
        if not proxy_ep:
            return None

        host = re.sub(r"^https?://", "", proxy_ep, flags=re.IGNORECASE)
        host = re.sub(r"^proxy\.", "api.", host, flags=re.IGNORECASE)
        if not host:
            return None
        return f"https://{host}"

    def _resolve_copilot_base_url(
        self,
        payload: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> str:
        payload = payload or {}

        endpoint = payload.get("endpoint") or payload.get("api_url")
        if isinstance(endpoint, str) and endpoint.strip():
            return endpoint.strip().rstrip("/")

        endpoints = payload.get("endpoints")
        if isinstance(endpoints, dict):
            api_endpoint = endpoints.get("api") or endpoints.get("chat")
            if isinstance(api_endpoint, str) and api_endpoint.strip():
                return api_endpoint.strip().rstrip("/")

        derived = self._derive_copilot_base_url_from_token(token or "")
        if derived:
            return derived.rstrip("/")
        return GITHUB_COPILOT_API_URL

    def _sync_client(self, timeout: float = 10) -> httpx.Client:
        return httpx.Client(timeout=timeout, follow_redirects=True)

    def _client(self, timeout: float = 5) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.copilot_access_token or self.api_key,
            timeout=timeout,
            default_headers=self._copilot_api_headers(),
        )

    def _ensure_copilot_base_url_consistency(self) -> str:
        resolved_base_url = self._resolve_copilot_base_url(
            token=self.copilot_access_token,
        ).rstrip("/")
        current_base_url = (self.base_url or "").strip().rstrip("/")
        if current_base_url != resolved_base_url:
            self.base_url = resolved_base_url
        return resolved_base_url

    def _copilot_discovery_client(self, timeout: float = 5) -> AsyncOpenAI:
        base_url = self._ensure_copilot_base_url_consistency()
        return AsyncOpenAI(
            base_url=base_url,
            api_key=self.copilot_access_token or self.api_key,
            timeout=timeout,
            default_headers=self._copilot_api_headers(),
        )

    def _copilot_responses_client(self, timeout: float = 5) -> AsyncOpenAI:
        base_url = self._ensure_copilot_base_url_consistency()
        return AsyncOpenAI(
            base_url=base_url,
            api_key=self.copilot_access_token or self.api_key,
            timeout=timeout,
            default_headers=self._copilot_api_headers(),
        )

    async def start_device_authorization(
        self,
        timeout: float = 10,
    ) -> DeviceAuthorizationSession:
        self._cleanup_expired_device_sessions()

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                GITHUB_DEVICE_CODE_URL,
                headers=self._github_headers(),
                data={
                    "client_id": GITHUB_COPILOT_OAUTH_CLIENT_ID,
                    "scope": "read:user",
                },
            )
            response.raise_for_status()
            payload = response.json()

        session = DeviceAuthorizationSession(
            session_id=secrets.token_urlsafe(18),
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            verification_uri=str(payload["verification_uri"]),
            expires_at=int(time.time()) + int(payload.get("expires_in", 900)),
            interval=int(payload.get("interval", 5)),
        )
        self._device_sessions[session.session_id] = session
        return session

    async def poll_device_authorization(
        self,
        session_id: str,
        timeout: float = 10,
    ) -> DeviceAuthorizationPollResult:
        session = self._device_sessions.get(session_id)
        if session is None:
            return DeviceAuthorizationPollResult(
                status="missing",
                message="Authorization session not found",
            )

        if session.expires_at <= int(time.time()):
            self._device_sessions.pop(session_id, None)
            return DeviceAuthorizationPollResult(
                status="expired",
                message="Device code expired",
            )

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                GITHUB_ACCESS_TOKEN_URL,
                headers=self._github_headers(),
                data={
                    "client_id": GITHUB_COPILOT_OAUTH_CLIENT_ID,
                    "device_code": session.device_code,
                    "grant_type": (
                        "urn:ietf:params:oauth:grant-type:device_code"
                    ),
                },
            )
            response.raise_for_status()
            payload = response.json()

        if "error" in payload:
            result = self._map_device_flow_error(payload, session.interval)
            session.status = result.status
            session.last_message = result.message
            if result.interval is not None:
                session.interval = result.interval
            if result.status in {"expired", "denied", "error"}:
                self._device_sessions.pop(session_id, None)
            return result

        self.github_oauth_token = str(payload.get("access_token", ""))
        self.github_token_type = str(payload.get("token_type", "bearer"))
        self.github_scope = str(payload.get("scope", ""))
        self.is_authenticated = bool(self.github_oauth_token)
        await self._populate_github_user(timeout=timeout)
        await self._refresh_copilot_token_async(timeout=timeout)
        self._device_sessions.pop(session_id, None)
        return DeviceAuthorizationPollResult(
            status="authorized",
            message="GitHub authorization completed",
        )

    @staticmethod
    def _map_device_flow_error(
        payload: dict[str, Any],
        interval: int,
    ) -> DeviceAuthorizationPollResult:
        error = str(payload.get("error", ""))
        description = str(payload.get("error_description", "")).strip()
        message = description or error or "Unknown device authorization error"
        if error == "authorization_pending":
            return DeviceAuthorizationPollResult(
                status="pending",
                message=message,
                interval=interval,
            )
        if error == "slow_down":
            return DeviceAuthorizationPollResult(
                status="pending",
                message=message,
                interval=interval + 5,
                slow_down=True,
            )
        if error == "expired_token":
            return DeviceAuthorizationPollResult(
                status="expired",
                message=message,
            )
        if error == "access_denied":
            return DeviceAuthorizationPollResult(
                status="denied",
                message=message,
            )
        return DeviceAuthorizationPollResult(
            status="error",
            message=message,
        )

    async def _populate_github_user(self, timeout: float = 10) -> None:
        if not self.github_oauth_token:
            return
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            response = await client.get(
                GITHUB_USER_URL,
                headers=self._oauth_auth_headers(),
            )
            response.raise_for_status()
            payload = response.json()
        self.github_user_login = str(payload.get("login", ""))
        user_id = payload.get("id")
        self.github_user_id = int(user_id) if user_id is not None else None
        self.auth_account_label = self.github_user_login or None

    async def _refresh_copilot_token_async(self, timeout: float = 10) -> None:
        if self._copilot_token_valid():
            self.base_url = self._resolve_copilot_base_url(
                token=self.copilot_access_token,
            )
            self.api_key = self.copilot_access_token
            return
        if not self.github_oauth_token:
            raise ValueError("GitHub authorization required")

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            response = await client.get(
                GITHUB_COPILOT_TOKEN_URL,
                headers={
                    **self._oauth_auth_headers(),
                    **self._copilot_api_headers(),
                },
            )
            response.raise_for_status()
            payload = response.json()

        self._apply_copilot_token_payload(payload)

    def _refresh_copilot_token_sync(self, timeout: float = 10) -> None:
        if self._copilot_token_valid():
            self.base_url = self._resolve_copilot_base_url(
                token=self.copilot_access_token,
            )
            self.api_key = self.copilot_access_token
            return
        if not self.github_oauth_token:
            raise ValueError("GitHub authorization required")

        with self._sync_client(timeout=timeout) as client:
            response = client.get(
                GITHUB_COPILOT_TOKEN_URL,
                headers={
                    **self._oauth_auth_headers(),
                    **self._copilot_api_headers(),
                },
            )
            response.raise_for_status()
            payload = response.json()

        self._apply_copilot_token_payload(payload)

    def _apply_copilot_token_payload(self, payload: dict[str, Any]) -> None:
        token = str(
            payload.get("token", "") or payload.get("access_token", "")
        )
        if not token:
            raise ValueError("GitHub Copilot token exchange failed")
        expires_at = payload.get("expires_at")
        if expires_at is None:
            expires_at = int(time.time()) + DEFAULT_COPILOT_TOKEN_TTL
        self.copilot_access_token = token
        self.copilot_token_expires_at = int(expires_at)
        self.auth_expires_at = self.copilot_token_expires_at
        self.base_url = self._resolve_copilot_base_url(
            payload=payload, token=token
        )
        self.api_key = token

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        if not self.github_oauth_token:
            return False, "GitHub authorization required"
        try:
            await self._refresh_copilot_token_async(timeout=timeout)
            client = self._copilot_discovery_client(timeout=timeout)
            await client.models.list(timeout=timeout)
            return True, ""
        except APIError as exc:
            return (
                False,
                f"API error when connecting to `{self.base_url}`: {exc}",
            )
        except Exception as exc:
            return (
                False,
                f"Unknown exception when connecting to `{self.base_url}`: {exc}",
            )

    async def fetch_models(self, timeout: float = 5) -> list[ModelInfo]:
        if not self.github_oauth_token:
            return []
        try:
            await self._refresh_copilot_token_async(timeout=timeout)
            client = self._copilot_discovery_client(timeout=timeout)
            payload = await client.models.list(timeout=timeout)
            return self._normalize_models_payload(payload)
        except APIError:
            return []
        except Exception:
            return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        if not self.github_oauth_token:
            return False, "GitHub authorization required"
        model_id = (model_id or "").strip()
        if not model_id:
            return False, "Empty model ID"

        try:
            await self._refresh_copilot_token_async(timeout=timeout)
            client = self._copilot_responses_client(timeout=timeout)
            await client.responses.create(
                model=model_id,
                input=[
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "ping",
                            },
                        ],
                    },
                ],
                max_output_tokens=RESPONSES_API_MIN_MAX_OUTPUT_TOKENS,
                timeout=timeout,
            )
            return True, ""
        except APIError as exc:
            return (
                False,
                f"API error when connecting to model '{model_id}': {exc}",
            )
        except Exception as exc:
            return (
                False,
                f"Unknown exception when connecting to model '{model_id}': {exc}",
            )

    def get_chat_model_instance(self, model_id: str):
        self._refresh_copilot_token_sync(timeout=10)
        return OpenAIResponsesChatModelCompat(
            model_name=model_id,
            stream=True,
            api_key=self.copilot_access_token,
            stream_tool_parsing=False,
            client_kwargs={
                "base_url": self.base_url,
                "default_headers": self._copilot_api_headers(),
            },
            generate_kwargs=self.generate_kwargs,
        )

    def logout(self) -> None:
        self.auth_expires_at = None
        self._clear_github_oauth_state()
        self._clear_runtime_copilot_state()
        self.github_auth_storage = GITHUB_AUTH_STORAGE_NONE
        self.base_url = GITHUB_COPILOT_API_URL
        self._device_sessions.clear()

    def to_persisted_dict(self) -> dict[str, Any]:
        """Persist provider config while keeping OAuth secrets off disk when possible."""
        persisted = self.model_dump(exclude=self._PERSIST_EXCLUDES)
        payload = self._github_auth_payload()

        if payload is None:
            self._delete_keyring_auth_payload()
            self.github_auth_storage = GITHUB_AUTH_STORAGE_NONE
            for field in GITHUB_AUTH_PERSIST_FIELDS:
                persisted.pop(field, None)
            persisted["github_auth_storage"] = self.github_auth_storage
            return persisted

        persisted.update(payload)
        if self._save_keyring_auth_payload(payload):
            self.github_auth_storage = GITHUB_AUTH_STORAGE_KEYCHAIN
            for field in GITHUB_AUTH_PERSIST_FIELDS:
                persisted.pop(field, None)
        else:
            self.github_auth_storage = GITHUB_AUTH_STORAGE_JSON
            for field in (
                "github_scope",
                "github_user_login",
                "github_user_id",
            ):
                if persisted.get(field) in {"", None}:
                    persisted.pop(field, None)

        persisted["github_auth_storage"] = self.github_auth_storage
        return persisted

    async def get_info(self, mock_secret: bool = True) -> ProviderInfo:
        self.is_authenticated = bool(self.github_oauth_token)
        self.auth_account_label = self.github_user_login or None
        self.auth_expires_at = self.copilot_token_expires_at
        info = await super().get_info(mock_secret=mock_secret)
        info.api_key = ""
        return info
