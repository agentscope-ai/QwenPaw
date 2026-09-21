# -*- coding: utf-8 -*-
"""Opt-in Platform PKCE connection and read-only reply synchronization.

The shared Platform protocol supports a loopback browser callback. QwenPaw
uses the existing CLI public client with a presentation-only source hint.
No CLI credentials or browser cookies are reused.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from . import community_store as store

PLATFORM = "https://platform.agentscope.io"
AUTH_TTL = 300
PAGE_SIZE = 50
PAGES_PER_SYNC = 5


class CommunityConnectionError(Exception):
    """A sanitized error code suitable for the local settings UI."""

    def __init__(self, code: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True)
class ConnectionConfig:
    """Platform client defaults with explicit operator overrides."""

    client_id: str = ""
    scopes: str = ""
    messages_enabled: bool = True
    interval: float = 120

    @classmethod
    def from_environment(cls) -> "ConnectionConfig":
        return cls(
            client_id=os.getenv(
                "QWENPAW_COMMUNITY_CLIENT_ID",
                "agentscope-platform-cli",
            ).strip(),
            scopes=os.getenv(
                "QWENPAW_COMMUNITY_SCOPES",
                "platform:control",
            ).strip(),
            messages_enabled=os.getenv(
                "QWENPAW_COMMUNITY_MESSAGES_ENABLED",
                "true",
            ).lower()
            in {"true", "1", "yes"},
        )

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.scopes)


def safe_platform_link(value: Any) -> str | None:
    """Permit only HTTPS Platform destinations in untrusted notifications."""
    if not isinstance(value, str) or len(value) > 4096:
        return None
    if any(ord(char) < 32 for char in value) or "\\" in value:
        return None
    url = (
        PLATFORM + value
        if value.startswith("/") and not value.startswith("//")
        else value
    )
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "platform.agentscope.io"
    ):
        return None
    return url


def _timestamp(value: Any) -> float:
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00"),
        ).timestamp()
    except (TypeError, ValueError, OverflowError):
        return time.time()


def normalize_message(kind: str, item: dict, *, initial: bool) -> dict | None:
    """Convert Platform My Messages feeds to local inbox events."""
    if kind in ("interactions", "feedback", "notifications"):
        return normalize_platform_message(kind, item, initial=initial)
    is_reply = kind == "comments"
    remote_id = item.get("reply_id" if is_reply else "mention_id")
    if (
        not isinstance(remote_id, (str, int))
        or isinstance(remote_id, bool)
        or not str(remote_id)
    ):
        return None
    title = item.get("resource_name" if is_reply else "source_title") or (
        "Community reply" if is_reply else "Community mention"
    )
    body = item.get("reply_content" if is_reply else "source_summary") or ""
    url = item.get("resource_link" if is_reply else "source_link")
    if not url and not is_reply:
        url = item.get("mentioned_resource_link")
    event_type = "reply" if is_reply else "mention"
    if (
        is_reply
        and item.get("event_type") == "comment_on_my_resource"
        and item.get("resource_type") in ("plugin", "app", "skill")
    ):
        event_type = "resource_feedback"
    elif (
        not is_reply
        and item.get("event_type") == "mention_my_resource"
        and item.get("source_type") == "community"
        and item.get("content_type") == "question"
        and item.get("mentioned_resource_type") in ("plugin", "skill")
    ):
        event_type = "resource_feedback"
    return {
        "remote_id": f"{kind}:{remote_id}",
        "event_type": event_type,
        "title": str(title)[:300],
        "body": str(body)[:8000],
        "created_at": _timestamp(
            item.get("created_at") or item.get("occurred_at"),
        ),
        "read": (
            not bool(item["has_unread"]) if "has_unread" in item else initial
        ),
        "payload": {
            "discussion_url": safe_platform_link(url),
            "received_at": time.time(),
            "resource_name": str(
                item.get(
                    "resource_name" if is_reply else "mentioned_resource_name",
                )
                or "",
            )[:300],
            "resource_type": item.get(
                "resource_type" if is_reply else "mentioned_resource_type",
            ),
            "resource_id": item.get(
                "resource_id" if is_reply else "mentioned_resource_id",
            ),
            "sender": {
                "name": str(
                    item.get(
                        (
                            "replier_display_name"
                            if is_reply
                            else "actor_display_name"
                        ),
                    )
                    or "",
                )[:200],
                "avatar_url": safe_platform_link(
                    item.get(
                        (
                            "replier_avatar_url"
                            if is_reply
                            else "actor_avatar_url"
                        ),
                    ),
                ),
            },
        },
    }


def normalize_platform_message(
    kind: str,
    item: dict,
    *,
    initial: bool,
) -> dict | None:
    """Map remaining My Messages tabs without changing remote read state."""
    id_key = {
        "interactions": "interaction_id",
        "feedback": "id",
        "notifications": "notification_id",
    }[kind]
    remote_id = item.get(id_key)
    if (
        not isinstance(remote_id, (str, int))
        or isinstance(remote_id, bool)
        or not str(remote_id)
    ):
        return None
    occurred = item.get("created_at")
    if kind == "interactions":
        title = (
            (item.get("action_type_label") or item.get("action_type") or "")
            + " "
            + (item.get("target_title") or "")
        )
        body = item.get("target_summary")
        url = item.get("target_link") or item.get("parent_link")
        occurred = item.get("occurred_at")
    elif kind == "feedback":
        title = item.get("description_preview") or item.get("description")
        body = item.get("last_comment_preview") or item.get("description")
        url = PLATFORM + "/notifications"
        occurred = (
            item.get("last_comment_at") or item.get("updated_at") or occurred
        )
        # A ticket can receive further replies under the same ticket ID.
        remote_id = f"{remote_id}:{occurred}"
    else:
        title, body, url = (
            item.get("title"),
            item.get("content"),
            item.get("link_url"),
        )
    return {
        "remote_id": f"{kind}:{remote_id}",
        "event_type": {
            "interactions": "interaction",
            "feedback": "platform_feedback",
            "notifications": "notification",
        }[kind],
        "title": str(title or "Platform message")[:300],
        "body": str(body or "")[:8000],
        "created_at": _timestamp(occurred),
        "read": (
            not bool(item["has_unread"]) if "has_unread" in item else initial
        ),
        "payload": {
            "discussion_url": safe_platform_link(url),
            "received_at": time.time(),
            "platform_tab": kind,
            "resource_name": str(item.get("target_title") or "")[:300],
            "resource_type": item.get("target_type"),
            "resource_id": item.get("target_id"),
            "sender": {
                "name": str(
                    item.get("actor_display_name")
                    or item.get("last_comment_author_role_label")
                    or "AgentScope Platform",
                )[:200],
            },
        },
    }


def _page_events(
    kind: str,
    items: list,
    *,
    initial: bool,
    head: str | None,
    checkpoint: str | None,
) -> tuple[list[dict], str | None, bool]:
    """Normalize one page up to the previously persisted remote event."""
    events = []
    for item in items:
        if not isinstance(item, dict):
            continue
        event = normalize_message(kind, item, initial=initial)
        if event is None:
            continue
        head = head or event["remote_id"]
        if event["remote_id"] == checkpoint:
            return events, head, True
        events.append(event)
    return events, head, False


class CommunityConnectionService:
    """Own one runtime's ephemeral authorization and durable connection."""

    def __init__(
        self,
        config: ConnectionConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or ConnectionConfig.from_environment()
        self._transport = transport
        self._lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        self._sync_lock = asyncio.Lock()
        self._flow: dict | None = None
        self._server: asyncio.Server | None = None
        self._expiry_task: asyncio.Task | None = None
        self._closed = asyncio.Event()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        **kwargs,
    ) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with httpx.AsyncClient(
                base_url=PLATFORM,
                timeout=15,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    headers=headers,
                    **kwargs,
                )
            if response.status_code == 401:
                raise CommunityConnectionError("authorization_expired", 401)
            if response.status_code == 403:
                raise CommunityConnectionError("permission_not_granted", 403)
            if response.status_code == 429:
                raise CommunityConnectionError("rate_limited", 429)
            if not response.is_success:
                raise CommunityConnectionError("platform_unavailable", 502)
            data = response.json()
            if not isinstance(data, dict) or data.get("success") is False:
                raise CommunityConnectionError(
                    "invalid_platform_response",
                    502,
                )
            return data
        except httpx.RequestError as exc:
            raise CommunityConnectionError("network_unavailable", 502) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise CommunityConnectionError(
                "invalid_platform_response",
                502,
            ) from exc

    async def status(self, *, local: bool) -> dict:
        connection = await store.get_connection()
        sync = await store.get_sync_state()
        reason = "not_configured" if not self.config.configured else None
        if reason is None and not local:
            reason = "unsupported_remote"
        pending = self._flow and self._flow["status"] in {
            "pending",
            "exchanging",
        }
        status = "connected" if connection else "disconnected"
        if not connection:
            status = reason or ("authorizing" if pending else "disconnected")
        elif sync.get("last_error") == "authorization_expired":
            status = "expired"
        return {
            "status": status,
            "configured": self.config.configured,
            "connected": connection is not None,
            "local_login_supported": reason is None,
            "connection_available": reason is None,
            "unavailable_reason": reason,
            "messages_enabled": self.config.configured
            and self.config.messages_enabled,
            "messages_available": self.config.configured
            and self.config.messages_enabled,
            "messages_unavailable_reason": (
                None
                if self.config.messages_enabled
                else "messages_not_configured"
            ),
            "supported_notifications": [
                "replies",
                "mentions",
                "resource_comments",
                "resource_questions",
                "interactions",
                "feedback",
                "notifications",
            ],
            "account": (
                {
                    "id": connection["account_id"],
                    "display_name": connection.get("display_name"),
                    "avatar_url": connection.get("avatar_url"),
                }
                if connection
                else None
            ),
            "sync_enabled": bool(
                connection and connection.get("sync_enabled"),
            ),
            "message_types": (connection or {}).get(
                "message_types",
                store.MESSAGE_TYPES,
            ),
            "last_success_at": sync.get("last_success_at"),
            "last_error": sync.get("last_error"),
            "authorization": (
                {
                    key: self._flow.get(key)
                    for key in ("flow_id", "authorize_url", "expires_at")
                }
                if pending
                else None
            ),
        }

    async def start(self, *, local: bool) -> dict:
        if not self.config.configured:
            raise CommunityConnectionError("not_configured", 409)
        if not local:
            raise CommunityConnectionError("unsupported_remote", 409)
        async with self._lock:
            await self._stop_flow("cancelled")
            self._closed.clear()
            state, verifier, flow_id = (
                secrets.token_urlsafe(32),
                secrets.token_urlsafe(48),
                secrets.token_urlsafe(24),
            )
            self._server = await asyncio.start_server(
                self._callback,
                "127.0.0.1",
                0,
                limit=8192,
            )
            port = self._server.sockets[0].getsockname()[1]
            callback_path = f"/callback/{secrets.token_urlsafe(24)}"
            redirect_uri = f"http://127.0.0.1:{port}{callback_path}"
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(verifier.encode()).digest(),
                )
                .decode()
                .rstrip("=")
            )
            self._flow = {
                "flow_id": flow_id,
                "state": state,
                "verifier": verifier,
                "redirect_uri": redirect_uri,
                "callback_path": callback_path,
                "status": "pending",
                "expires_at": time.time() + AUTH_TTL,
            }
            self._expiry_task = asyncio.create_task(self._expire(flow_id))
            authorize_url = (
                PLATFORM
                + "/cli/login?"
                + urlencode(
                    {
                        "client_id": self.config.client_id,
                        "source": "qwenpaw-community",
                        "response_type": "code",
                        "redirect_uri": redirect_uri,
                        "scope": self.config.scopes,
                        "state": state,
                        "code_challenge": challenge,
                        "code_challenge_method": "S256",
                    },
                )
            )
            self._flow["authorize_url"] = authorize_url
            return {
                "flow_id": flow_id,
                "authorize_url": authorize_url,
                "expires_at": self._flow["expires_at"],
            }

    async def authorization_status(self, flow_id: str) -> dict:
        async with self._lock:
            if not self._flow or not secrets.compare_digest(
                self._flow["flow_id"],
                flow_id,
            ):
                raise CommunityConnectionError("authorization_not_found", 404)
            return {
                key: self._flow.get(key)
                for key in ("flow_id", "status", "error", "expires_at")
            }

    async def cancel(self, flow_id: str) -> None:
        async with self._lock:
            if not self._flow or not secrets.compare_digest(
                self._flow["flow_id"],
                flow_id,
            ):
                raise CommunityConnectionError("authorization_not_found", 404)
            await self._stop_flow("cancelled")

    async def _stop_flow(self, status: str) -> None:
        if self._flow and self._flow["status"] in {"pending", "exchanging"}:
            self._flow["status"] = status
            self._flow.pop("verifier", None)
            self._flow.pop("state", None)
        if self._server:
            self._server.close()
            # Do not await active client transports from inside their own
            # callback; the callback closes its writer after completing.
            self._server = None
        if (
            self._expiry_task
            and self._expiry_task is not asyncio.current_task()
        ):
            self._expiry_task.cancel()
        self._expiry_task = None

    async def _expire(self, flow_id: str) -> None:
        await asyncio.sleep(AUTH_TTL)
        async with self._lock:
            if self._flow and self._flow["flow_id"] == flow_id:
                await self._stop_flow("expired")

    async def _callback(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        message, status = "Authorization failed. Return to QwenPaw.", 400
        try:
            peer = writer.get_extra_info("peername")
            if not peer or peer[0] != "127.0.0.1":
                raise CommunityConnectionError("invalid_callback")
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            first = raw.decode("ascii").split("\r\n", 1)[0].split()
            if len(first) != 3 or first[0] != "GET":
                raise CommunityConnectionError("invalid_callback")
            parsed = urlsplit(first[1])
            if parsed.scheme or parsed.netloc:
                raise CommunityConnectionError("invalid_callback")
            query = parse_qs(parsed.query)
            await self.complete(parsed.path, query)
            message, status = (
                "Connected. You can close this window and return to QwenPaw.",
                200,
            )
        except (
            CommunityConnectionError,
            ValueError,
            UnicodeError,
            asyncio.TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            pass
        finally:
            body = message.encode()
            reason = "OK" if status == 200 else "Bad Request"
            headers = (
                f"HTTP/1.1 {status} {reason}\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n"
                "Cache-Control: no-store\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n"
            )
            writer.write(headers.encode() + body)
            try:
                await writer.drain()
            except (OSError, ConnectionError):
                pass
            writer.close()
            await writer.wait_closed()

    async def complete(
        self,
        callback_path: str,
        query: dict[str, list[str]],
    ) -> None:
        """Consume exactly one matching callback before exchanging the code."""
        async with self._lock:
            flow = self._flow
            if (
                not flow
                or flow["status"] != "pending"
                or flow["expires_at"] <= time.time()
            ):
                raise CommunityConnectionError("authorization_expired")
            if (
                callback_path != flow["callback_path"]
                or len(query.get("state", [])) != 1
                or not secrets.compare_digest(query["state"][0], flow["state"])
            ):
                raise CommunityConnectionError("invalid_state")
            if "error" in query:
                await self._stop_flow("cancelled")
                raise CommunityConnectionError("authorization_cancelled")
            if len(query.get("code", [])) != 1 or not query["code"][0]:
                raise CommunityConnectionError("missing_code")
            flow["status"] = "exchanging"
            verifier = flow.pop("verifier")
            flow.pop("state", None)
        try:
            tokens = await self._request(
                "POST",
                "/api/cli/v1/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "client_id": self.config.client_id,
                    "code": query["code"][0],
                    "code_verifier": verifier,
                    "redirect_uri": flow["redirect_uri"],
                },
            )
            connection = await self._finalize_login(tokens)
            async with self._lock:
                if (
                    self._flow is not flow
                    or flow["status"] != "exchanging"
                    or flow["expires_at"] <= time.time()
                ):
                    raise CommunityConnectionError("authorization_cancelled")
                await store.save_connection(
                    connection,
                    authorization_completed=True,
                )
                flow["status"] = "completed"
                await self._stop_flow("completed")
        except CommunityConnectionError as exc:
            async with self._lock:
                if self._flow is flow and flow["status"] == "exchanging":
                    flow["error"] = exc.code
                    await self._stop_flow("failed")
            raise

    async def _finalize_login(self, tokens: dict) -> dict:
        """Match platform-cli finalizeLogin before requesting /me."""
        refresh_token = tokens.get("refresh_token")
        if isinstance(refresh_token, str) and refresh_token:
            try:
                tokens = await self._request(
                    "POST",
                    "/api/cli/v1/auth/refresh",
                    json={"refresh_token": refresh_token},
                )
            except CommunityConnectionError:
                # Upstream falls back to the login response if refresh fails.
                # We still validate its token against /me before connecting.
                pass
        return await self._connection_from_tokens(tokens)

    async def _connection_from_tokens(
        self,
        tokens: dict,
        previous: dict | None = None,
    ) -> dict:
        access = tokens.get("access_token")
        if (
            not isinstance(access, str)
            or not access
            or str(tokens.get("token_type", "Bearer")).lower() != "bearer"
        ):
            raise CommunityConnectionError("invalid_token_response", 502)
        me = await self._request("GET", "/api/cli/v1/me", token=access)
        user = me.get("user") or {}
        if not isinstance(user, dict):
            raise CommunityConnectionError("missing_account_identity", 502)
        account_id = user.get("id") or me.get("user_id")
        if (
            not isinstance(account_id, (str, int))
            or isinstance(account_id, bool)
            or not str(account_id)
        ):
            raise CommunityConnectionError("missing_account_identity", 502)
        if previous and str(account_id) != previous["account_id"]:
            raise CommunityConnectionError("account_changed", 409)
        try:
            expires_in = max(0, int(tokens.get("expires_in") or 0))
        except (ValueError, TypeError) as exc:
            raise CommunityConnectionError(
                "invalid_token_response",
                502,
            ) from exc
        return {
            "account_id": str(account_id),
            "display_name": str(
                user.get("display_name") or me.get("username") or account_id,
            )[:200],
            "access_token": access,
            "refresh_token": tokens.get("refresh_token")
            or (previous or {}).get("refresh_token"),
            "expires_at": time.time() + expires_in if expires_in else None,
            "sync_enabled": (previous or {}).get(
                "sync_enabled",
                self.config.messages_enabled,
            ),
            "message_types": (previous or {}).get(
                "message_types",
                store.MESSAGE_TYPES,
            ),
            "connection_id": (previous or {}).get("connection_id")
            or str(uuid.uuid4()),
        }

    async def _fresh_connection(
        self,
        *,
        force_refresh: bool = False,
        expected_connection_id: str | None = None,
    ) -> dict:
        async with self._refresh_lock:
            connection = await store.get_connection()
            if not connection:
                raise CommunityConnectionError("not_connected", 409)
            if (
                expected_connection_id
                and connection["connection_id"] != expected_connection_id
            ):
                raise CommunityConnectionError("connection_changed", 409)
            expires = connection.get("expires_at")
            if not force_refresh and (
                not expires or expires > time.time() + 60
            ):
                return connection
            if not connection.get("refresh_token"):
                raise CommunityConnectionError("authorization_expired", 401)
            tokens = await self._request(
                "POST",
                "/api/cli/v1/auth/refresh",
                json={"refresh_token": connection["refresh_token"]},
            )
            refreshed = await self._connection_from_tokens(tokens, connection)
            async with self._lock:
                current = await store.get_connection()
                if (
                    not current
                    or current.get("connection_id")
                    != connection["connection_id"]
                ):
                    raise CommunityConnectionError("connection_changed", 409)
                # A pause requested during refresh must not be overwritten by
                # the preference snapshot taken before the network request.
                refreshed["sync_enabled"] = current.get("sync_enabled", False)
                refreshed["message_types"] = current.get(
                    "message_types",
                    store.MESSAGE_TYPES,
                )
                saved = await store.save_connection(
                    refreshed,
                    expected_account_id=connection["account_id"],
                    expected_connection_id=connection["connection_id"],
                )
                if not saved:
                    raise CommunityConnectionError("connection_changed", 409)
            return refreshed

    async def disconnect(self) -> dict:
        async with self._lock:
            await self._stop_flow("cancelled")
            old = await store.get_connection()
            await store.disconnect()
        revoked = old is None
        if old:
            token = old.get("refresh_token") or old.get("access_token")
            try:
                await self._request(
                    "POST",
                    "/api/cli/v1/oauth/revoke",
                    token=old.get("access_token"),
                    json={
                        "token": token,
                        "token_type_hint": (
                            "refresh_token"
                            if old.get("refresh_token")
                            else "access_token"
                        ),
                    },
                )
                revoked = True
            except CommunityConnectionError:
                pass
        return {"disconnected": True, "remote_revoked": revoked}

    async def set_sync(
        self,
        enabled: bool | None = None,
        message_types: Sequence[str] | None = None,
    ) -> dict:
        if message_types is not None and any(
            kind not in store.MESSAGE_TYPES for kind in message_types
        ):
            raise CommunityConnectionError("invalid_message_type", 422)
        if enabled and (
            not self.config.configured or not self.config.messages_enabled
        ):
            raise CommunityConnectionError("messages_not_configured", 409)
        async with self._lock:
            connection = await store.get_connection()
            if not connection:
                raise CommunityConnectionError("not_connected", 409)
            if enabled is not None:
                connection["sync_enabled"] = enabled
            if message_types is not None:
                connection["message_types"] = list(
                    dict.fromkeys(message_types),
                )
            saved = await store.save_connection(
                connection,
                expected_account_id=connection["account_id"],
                expected_connection_id=connection["connection_id"],
            )
            if not saved:
                raise CommunityConnectionError("connection_changed", 409)
        return {
            "sync_enabled": connection.get("sync_enabled", False),
            "message_types": connection.get(
                "message_types",
                store.MESSAGE_TYPES,
            ),
        }

    async def community_request(
        self,
        method: str,
        path: str,
        *,
        account_id: str | None = None,
        **kwargs,
    ) -> dict:
        """Proxy community routes without exposing credentials."""
        if method == "GET":
            data = await self._request(method, path, **kwargs)
            payload = data.get("data")
            if not isinstance(payload, dict):
                raise CommunityConnectionError(
                    "invalid_platform_response",
                    502,
                )
            return payload
        connection = await store.get_connection()
        if method != "GET" and (
            not connection or connection["account_id"] != account_id
        ):
            raise CommunityConnectionError("connection_changed", 409)
        if connection:
            connection = await self._fresh_connection(
                expected_connection_id=connection["connection_id"],
            )
        try:
            data = await self._request(
                method,
                path,
                token=connection["access_token"] if connection else None,
                **kwargs,
            )
        except CommunityConnectionError as exc:
            # A failed write may have posted already; never retry it.
            if (
                method != "GET"
                or not connection
                or exc.code != "authorization_expired"
            ):
                raise
            connection = await self._fresh_connection(
                force_refresh=True,
                expected_connection_id=connection["connection_id"],
            )
            data = await self._request(
                method,
                path,
                token=connection["access_token"],
                **kwargs,
            )
        if connection:
            current = await store.get_connection()
            if (
                not current
                or current["connection_id"] != connection["connection_id"]
            ):
                raise CommunityConnectionError("connection_changed", 409)
        payload = data.get("data")
        if not isinstance(payload, dict):
            raise CommunityConnectionError("invalid_platform_response", 502)
        return payload

    async def _message_page(
        self,
        connection: dict,
        endpoint: str,
        page: int,
    ) -> tuple[dict, dict]:
        """Read one page, refreshing an expired token at most once."""
        params = {
            "page": page,
            "page_size": PAGE_SIZE,
            "mark_read": "false",
        }
        try:
            data = await self._request(
                "GET",
                f"/api/v1/messages/{endpoint}",
                token=connection["access_token"],
                params=params,
            )
        except CommunityConnectionError as exc:
            if exc.code != "authorization_expired":
                raise
            connection = await self._fresh_connection(
                force_refresh=True,
                expected_connection_id=connection["connection_id"],
            )
            data = await self._request(
                "GET",
                f"/api/v1/messages/{endpoint}",
                token=connection["access_token"],
                params=params,
            )
        payload = data.get("data") or {}
        if not isinstance(payload, dict) or not isinstance(
            payload.get("items"),
            list,
        ):
            raise CommunityConnectionError("invalid_message_response", 502)
        return payload, connection

    async def sync_once(self) -> dict:
        if not self.config.configured or not self.config.messages_enabled:
            raise CommunityConnectionError("messages_not_configured", 409)
        if self._sync_lock.locked():
            return {"status": "running", "inserted": 0}
        async with self._sync_lock:
            connection = await store.get_connection()
            if not connection or not connection.get("sync_enabled"):
                return {"status": "disabled", "inserted": 0}
            try:
                connection = await self._fresh_connection(
                    expected_connection_id=connection["connection_id"],
                )
                state = await store.get_sync_state()
                cursor = dict(state.get("cursor") or {})
                inserted = 0
                for kind, endpoint in (
                    ("comments", "comment-replies"),
                    ("mentions", "mentions"),
                    ("interactions", "interactions"),
                    ("feedback", "feedback"),
                    ("notifications", "notifications"),
                ):
                    current = await store.get_connection()
                    if not current or kind not in current.get(
                        "message_types",
                        store.MESSAGE_TYPES,
                    ):
                        continue
                    progress = dict(cursor.get(kind) or {})
                    initial = not progress.get("initialized")
                    page = max(1, int(progress.get("next_page") or 1))
                    head = progress.get("head_id")
                    checkpoint = progress.get("checkpoint")
                    finished = False
                    for _ in range(PAGES_PER_SYNC):
                        current = await store.get_connection()
                        if (
                            not current
                            or current.get("connection_id")
                            != connection["connection_id"]
                        ):
                            raise CommunityConnectionError(
                                "connection_changed",
                                409,
                            )
                        if not current.get("sync_enabled"):
                            return {"status": "disabled", "inserted": inserted}
                        if kind not in current.get(
                            "message_types",
                            store.MESSAGE_TYPES,
                        ):
                            break
                        payload, connection = await self._message_page(
                            connection,
                            endpoint,
                            page,
                        )
                        items = payload["items"]
                        events, head, finished = _page_events(
                            kind,
                            items,
                            initial=initial,
                            head=head,
                            checkpoint=checkpoint,
                        )
                        page += 1
                        total = payload.get("total")
                        finished = (
                            finished
                            or len(items) < PAGE_SIZE
                            or (
                                isinstance(total, int)
                                and (page - 1) * PAGE_SIZE >= total
                            )
                        )
                        cursor[kind] = {
                            "checkpoint": head if finished else checkpoint,
                            "head_id": None if finished else head,
                            "next_page": 1 if finished else page,
                            "initialized": not initial or finished,
                        }
                        inserted += await store.ingest(
                            connection["account_id"],
                            events,
                            cursor,
                            connection_id=connection["connection_id"],
                        )
                        if finished:
                            break
                return {
                    "status": "synced",
                    "inserted": inserted,
                    "catching_up": any(
                        value.get("next_page", 1) > 1
                        for value in cursor.values()
                    ),
                }
            except CommunityConnectionError as exc:
                await store.update_sync_state(
                    connection["account_id"],
                    {"last_error": exc.code, "last_attempt_at": time.time()},
                    connection_id=connection.get("connection_id"),
                )
                raise

    async def poll_loop(self) -> None:
        """Poll with backoff without interrupting the Agent runtime."""
        failures = 0
        while not self._closed.is_set():
            try:
                if self.config.configured and self.config.messages_enabled:
                    await self.sync_once()
                failures = 0
            except Exception:
                failures = min(failures + 1, 5)
            delay = min(
                1800,
                self.config.interval * (2**failures),
            ) + secrets.randbelow(16)
            try:
                await asyncio.wait_for(self._closed.wait(), delay)
            except asyncio.TimeoutError:
                pass

    async def close(self) -> None:
        self._closed.set()
        async with self._lock:
            await self._stop_flow("cancelled")
