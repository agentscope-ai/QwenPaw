# -*- coding: utf-8 -*-
"""Shared DingTalk OpenAPI client for channel-side API calls."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin

import aiohttp

from .constants import DINGTALK_TOKEN_TTL_SECONDS

logger = logging.getLogger(__name__)

_IDEMPOTENT_RETRYABLE_METHODS = frozenset(
    {"DELETE", "GET", "HEAD", "OPTIONS"},
)
_RETRYABLE_STATUS_CODES = frozenset({429, 503})
_MAX_RETRY_ATTEMPTS = 2
_RETRY_BASE_DELAY_SECONDS = 0.25
_RETRYABLE_NETWORK_EXCEPTIONS = (
    asyncio.TimeoutError,
    aiohttp.ClientConnectionError,
    aiohttp.ClientPayloadError,
)


class DingTalkOpenAPIError(RuntimeError):
    """Raised when a DingTalk OpenAPI call fails."""

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        status: int | None = None,
        body: Any = None,
    ):
        super().__init__(message)
        self.url = url
        self.status = status
        self.body = body

    def __str__(self) -> str:
        base = super().__str__()
        parts = [base]
        if self.status is not None:
            parts.append(f"status={self.status}")
        if self.url:
            parts.append(f"url={self.url}")
        if self.body not in (None, ""):
            parts.append(f"body={self._truncate_body(self.body)}")
        return " ".join(parts)

    @staticmethod
    def _truncate_body(body: Any, limit: int = 500) -> str:
        if isinstance(body, (dict, list)):
            try:
                text = json.dumps(body, ensure_ascii=False)
            except Exception:
                text = str(body)
        else:
            text = str(body)
        return text[:limit]


class DingTalkOpenAPIClient:
    """Thin DingTalk OpenAPI wrapper with token caching and JSON requests."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        http_session: aiohttp.ClientSession,
        *,
        base_url: str = "https://api.dingtalk.com",
        token_ttl_seconds: int = DINGTALK_TOKEN_TTL_SECONDS,
    ):
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.http_session = http_session
        self.base_url = (base_url or "https://api.dingtalk.com").rstrip("/")
        self.token_ttl_seconds = token_ttl_seconds
        self._token_lock = asyncio.Lock()
        self._token_value: str | None = None
        self._token_expires_at: float = 0.0

    def has_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def check_credentials(self) -> tuple[bool, str]:
        """Validate that the configured app credentials can fetch a token."""
        if not self.has_credentials():
            return False, "DingTalk client_id/client_secret missing"
        try:
            await self.get_access_token()
            return True, ""
        except DingTalkOpenAPIError as exc:
            return False, str(exc)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Unexpected DingTalk credential check failure")
            return False, f"Unexpected DingTalk credential check failure: {exc}"

    async def get_access_token(self) -> str:
        """Get and cache DingTalk access token."""
        url = self._resolve_url("/v1.0/oauth2/accessToken")
        if not self.has_credentials():
            raise DingTalkOpenAPIError(
                "DingTalk client_id/client_secret missing",
                url=url,
            )

        now = asyncio.get_running_loop().time()
        if self._token_value and now < self._token_expires_at:
            return self._token_value

        async with self._token_lock:
            now = asyncio.get_running_loop().time()
            if self._token_value and now < self._token_expires_at:
                return self._token_value

            async def _fetch_token() -> str:
                payload = {
                    "appKey": self.client_id,
                    "appSecret": self.client_secret,
                }
                async with self.http_session.post(url, json=payload) as resp:
                    body_text = await resp.text()
                    if resp.status in _RETRYABLE_STATUS_CODES:
                        raise self._make_error(
                            "DingTalk access token request failed",
                            url=url,
                            status=resp.status,
                            body=body_text,
                        )

                    data = self._parse_json(body_text)
                    if resp.status >= 400:
                        raise self._make_error(
                            "DingTalk access token request failed",
                            url=url,
                            status=resp.status,
                            body=data if data else body_text,
                        )

                token = data.get("accessToken") or data.get("access_token")
                if not token:
                    raise DingTalkOpenAPIError(
                        "DingTalk access token missing in response",
                        url=url,
                        body=data,
                    )
                return str(token)

            token = await self._with_retry(
                operation="DingTalk access token request",
                url=url,
                action=_fetch_token,
            )
            self._token_value = token
            self._token_expires_at = (
                asyncio.get_running_loop().time() + self.token_ttl_seconds
            )
            return self._token_value

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth: bool = True,
        retry_on_transient: bool | None = None,
    ) -> Any:
        """Send a JSON request to DingTalk and return parsed JSON."""
        resolved_url = self._resolve_url(url)
        if self.http_session is None:
            raise DingTalkOpenAPIError(
                "DingTalk HTTP session is not initialized",
                url=resolved_url,
            )

        request_headers = dict(headers or {})
        if json_body is not None and "Content-Type" not in request_headers:
            request_headers["Content-Type"] = "application/json"
        if auth:
            request_headers.setdefault(
                "x-acs-dingtalk-access-token",
                await self.get_access_token(),
            )

        method_name = (method or "GET").upper()
        normalized_params = self._normalize_params(params)
        should_retry = (
            method_name in _IDEMPOTENT_RETRYABLE_METHODS
            if retry_on_transient is None
            else bool(retry_on_transient)
        )

        async def _request_once() -> Any:
            async with self.http_session.request(
                method_name,
                resolved_url,
                json=json_body,
                params=normalized_params,
                headers=request_headers,
            ) as resp:
                body_text = await resp.text()
                if resp.status in _RETRYABLE_STATUS_CODES:
                    raise self._make_error(
                        f"DingTalk {method_name} request failed",
                        url=resolved_url,
                        status=resp.status,
                        body=body_text,
                    )

                data = self._parse_json(body_text)
                if resp.status >= 400:
                    raise self._make_error(
                        f"DingTalk {method_name} request failed",
                        url=resolved_url,
                        status=resp.status,
                        body=data if data else body_text,
                    )
                if isinstance(data, dict):
                    errcode = data.get("errcode")
                    if errcode not in (None, 0, "0"):
                        raise self._make_error(
                            f"DingTalk {method_name} API error",
                            url=resolved_url,
                            status=resp.status,
                            body=data,
                        )
                return data

        try:
            if should_retry:
                return await self._with_retry(
                    operation=f"DingTalk {method_name} request",
                    url=resolved_url,
                    action=_request_once,
                )
            return await _request_once()
        except asyncio.CancelledError:  # pragma: no cover - passthrough
            raise
        except DingTalkOpenAPIError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            raise DingTalkOpenAPIError(
                f"DingTalk {method_name} request failed: {exc}",
                url=resolved_url,
            ) from exc

    def _resolve_url(self, url: str) -> str:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return urljoin(f"{self.base_url}/", url.lstrip("/"))

    async def _with_retry(
        self,
        *,
        operation: str,
        url: str,
        action: Callable[[], Awaitable[Any]],
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRY_ATTEMPTS + 1):
            try:
                return await action()
            except asyncio.CancelledError:  # pragma: no cover - passthrough
                raise
            except DingTalkOpenAPIError as exc:
                if not self._is_retryable_error(exc) or attempt >= _MAX_RETRY_ATTEMPTS:
                    raise
                last_error = exc
            except _RETRYABLE_NETWORK_EXCEPTIONS as exc:
                if attempt >= _MAX_RETRY_ATTEMPTS:
                    raise DingTalkOpenAPIError(
                        f"{operation} failed after retries: {exc}",
                        url=url,
                    ) from exc
                last_error = exc

            delay = self._retry_delay_seconds(attempt)
            logger.warning(
                "Retrying DingTalk %s (attempt %s/%s) in %.2fs after %s",
                operation,
                attempt + 1,
                _MAX_RETRY_ATTEMPTS + 1,
                delay,
                last_error,
            )
            await asyncio.sleep(delay)

        if isinstance(last_error, DingTalkOpenAPIError):
            raise last_error
        if last_error is not None:
            raise DingTalkOpenAPIError(
                f"{operation} failed after retries: {last_error}",
                url=url,
            ) from last_error
        raise DingTalkOpenAPIError(
            f"{operation} failed after retries",
            url=url,
        )

    @staticmethod
    def _is_retryable_error(exc: DingTalkOpenAPIError) -> bool:
        return exc.status in _RETRYABLE_STATUS_CODES

    @staticmethod
    def _retry_delay_seconds(attempt: int) -> float:
        delay = _RETRY_BASE_DELAY_SECONDS * (2**attempt)
        return min(delay, 1.0)

    @staticmethod
    def _parse_json(body_text: str) -> dict[str, Any]:
        if not body_text:
            return {}
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise DingTalkOpenAPIError(
                "DingTalk response is not valid JSON",
                body=body_text,
            ) from exc
        return payload if isinstance(payload, dict) else {"result": payload}

    @staticmethod
    def _normalize_params(
        params: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not params:
            return params

        normalized: dict[str, Any] = {}
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, bool):
                normalized[key] = "true" if value else "false"
            else:
                normalized[key] = value
        return normalized

    @staticmethod
    def _make_error(
        message: str,
        *,
        url: str,
        status: int,
        body: Any,
    ) -> DingTalkOpenAPIError:
        return DingTalkOpenAPIError(
            message,
            url=url,
            status=status,
            body=body,
        )
