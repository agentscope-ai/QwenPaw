# -*- coding: utf-8 -*-
"""Mobile push subscriptions and privacy-safe Expo notifications."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from ..constant import WORKING_DIR
from ..utils.io_utils import read_json, run_sync_io, write_json_atomic

logger = logging.getLogger(__name__)

_SUBSCRIPTIONS_PATH = WORKING_DIR / "mobile_push_subscriptions.json"
_LOCK = asyncio.Lock()
_MAX_SUBSCRIPTIONS = 500
_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_EXPO_TOKEN_RE = re.compile(
    r"^(?:Exponent|Expo)PushToken\[[^\]\s]{10,256}\]$",
)

NotificationKind = Literal[
    "run_completed",
    "input_required",
    "approval_required",
    "run_failed",
]
NotificationPreview = Literal["full", "title_only", "hidden"]


class NotificationPreferences(BaseModel):
    """Per-device notification categories and lock-screen preview level."""

    enabled: bool = True
    run_completed: bool = True
    input_required: bool = True
    approval_required: bool = True
    run_failed: bool = True
    preview: NotificationPreview = "title_only"


class MobilePushSubscriptionRequest(BaseModel):
    """A mobile installation registered for one QwenPaw agent."""

    installation_id: str = Field(min_length=8, max_length=128)
    workspace_key: str = Field(min_length=16, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    platform: Literal["android", "ios"]
    expo_push_token: str = Field(min_length=16, max_length=320)
    preferences: NotificationPreferences


class MobilePushSubscriptionResponse(BaseModel):
    """Safe subscription state returned without the device push token."""

    installation_id: str
    workspace_key: str
    agent_id: str
    platform: Literal["android", "ios"]
    preferences: NotificationPreferences
    updated_at: float


@dataclass(frozen=True)
class MobileNotificationEvent:
    """One notification with opaque navigation identifiers only."""

    kind: NotificationKind
    agent_id: str
    title: str
    body: str
    chat_id: str | None = None
    session_id: str | None = None
    approval_request_id: str | None = None
    inbox_event_id: str | None = None


def _record_key(
    installation_id: str,
    workspace_key: str,
    agent_id: str,
) -> str:
    return f"{installation_id}:{workspace_key}:{agent_id}"


def _load_subscriptions() -> dict[str, dict[str, Any]]:
    if not _SUBSCRIPTIONS_PATH.exists():
        return {}
    try:
        data = read_json(_SUBSCRIPTIONS_PATH)
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read mobile push subscriptions: %s", exc)
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): value
        for key, value in data.items()
        if isinstance(value, dict)
    }


def _save_subscriptions(records: dict[str, dict[str, Any]]) -> None:
    write_json_atomic(_SUBSCRIPTIONS_PATH, records, sort_keys=True)


def _safe_response(record: dict[str, Any]) -> MobilePushSubscriptionResponse:
    return MobilePushSubscriptionResponse(
        installation_id=str(record["installation_id"]),
        workspace_key=str(record["workspace_key"]),
        agent_id=str(record["agent_id"]),
        platform=record["platform"],
        preferences=NotificationPreferences.model_validate(
            record["preferences"],
        ),
        updated_at=float(record["updated_at"]),
    )


async def register_mobile_push(
    request: MobilePushSubscriptionRequest,
) -> MobilePushSubscriptionResponse:
    """Create or update one device subscription."""
    if not _EXPO_TOKEN_RE.fullmatch(request.expo_push_token):
        raise ValueError("Invalid Expo push token")
    now = time.time()
    record = request.model_dump()
    record["updated_at"] = now
    key = _record_key(
        request.installation_id,
        request.workspace_key,
        request.agent_id,
    )
    async with _LOCK:
        records = await run_sync_io(_load_subscriptions)
        records[key] = record
        if len(records) > _MAX_SUBSCRIPTIONS:
            oldest = sorted(
                records,
                key=lambda item: float(
                    records[item].get("updated_at", 0),
                ),
            )
            for stale_key in oldest[: len(records) - _MAX_SUBSCRIPTIONS]:
                records.pop(stale_key, None)
        await run_sync_io(_save_subscriptions, records)
    return _safe_response(record)


async def get_mobile_push(
    installation_id: str,
    workspace_key: str,
    agent_id: str,
) -> MobilePushSubscriptionResponse | None:
    """Return one safe subscription state."""
    key = _record_key(installation_id, workspace_key, agent_id)
    async with _LOCK:
        records = await run_sync_io(_load_subscriptions)
    record = records.get(key)
    return _safe_response(record) if record else None


async def unregister_mobile_push(
    installation_id: str,
    workspace_key: str,
    agent_id: str,
) -> bool:
    """Remove one device subscription."""
    key = _record_key(installation_id, workspace_key, agent_id)
    async with _LOCK:
        records = await run_sync_io(_load_subscriptions)
        removed = records.pop(key, None) is not None
        if removed:
            await run_sync_io(_save_subscriptions, records)
    return removed


def _preview_text(
    event: MobileNotificationEvent,
    preview: NotificationPreview,
) -> tuple[str, str]:
    if preview == "hidden":
        return "QwenPaw", "你有一条新通知"
    generic = {
        "run_completed": ("任务已完成", "打开 QwenPaw 查看结果"),
        "input_required": ("需要你的输入", "打开 QwenPaw 继续任务"),
        "approval_required": ("需要你的审批", "打开 QwenPaw 处理请求"),
        "run_failed": ("任务未完成", "打开 QwenPaw 查看详情"),
    }
    if preview == "title_only":
        return generic[event.kind]
    title = " ".join(event.title.split())[:120] or generic[event.kind][0]
    body = " ".join(event.body.split())[:180] or generic[event.kind][1]
    return title, body


def _notification_data(
    event: MobileNotificationEvent,
    workspace_key: str,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "version": 1,
        "kind": event.kind,
        "workspace_key": workspace_key,
        "agent_id": event.agent_id,
    }
    optional = {
        "chat_id": event.chat_id,
        "session_id": event.session_id,
        "approval_request_id": event.approval_request_id,
        "inbox_event_id": event.inbox_event_id,
    }
    data.update({key: value for key, value in optional.items() if value})
    return data


async def _deactivate_tokens(tokens: set[str]) -> None:
    if not tokens:
        return
    async with _LOCK:
        records = await run_sync_io(_load_subscriptions)
        changed = False
        for record in records.values():
            if record.get("expo_push_token") not in tokens:
                continue
            preferences = dict(record.get("preferences") or {})
            preferences["enabled"] = False
            record["preferences"] = preferences
            changed = True
        if changed:
            await run_sync_io(_save_subscriptions, records)


async def _send_expo_messages(messages: list[dict[str, Any]]) -> None:
    access_token = os.environ.get("QWENPAW_EXPO_PUSH_ACCESS_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    _EXPO_PUSH_URL,
                    headers=headers,
                    json=messages,
                )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
            response.raise_for_status()
            payload = response.json()
            tickets = payload.get("data", [])
            if isinstance(tickets, dict):
                tickets = [tickets]
            invalid_tokens = {
                str(message["to"])
                for message, ticket in zip(messages, tickets)
                if isinstance(ticket, dict)
                and (ticket.get("details") or {}).get("error")
                == "DeviceNotRegistered"
            }
            await _deactivate_tokens(invalid_tokens)
            return
        except (httpx.HTTPError, ValueError):
            if attempt == 2:
                logger.warning(
                    "Mobile push delivery failed for %d device(s)",
                    len(messages),
                    exc_info=True,
                )
                return
            await asyncio.sleep(0.25 * (2**attempt))


async def notify_mobile_devices(event: MobileNotificationEvent) -> None:
    """Send one event to every matching, enabled mobile subscription."""
    async with _LOCK:
        records = await run_sync_io(_load_subscriptions)
    messages: list[dict[str, Any]] = []
    for record in records.values():
        if record.get("agent_id") != event.agent_id:
            continue
        try:
            preferences = NotificationPreferences.model_validate(
                record.get("preferences"),
            )
        except ValueError:
            continue
        if not preferences.enabled or not getattr(preferences, event.kind):
            continue
        token = record.get("expo_push_token")
        workspace_key = record.get("workspace_key")
        if not isinstance(token, str) or not isinstance(workspace_key, str):
            continue
        title, body = _preview_text(event, preferences.preview)
        messages.append(
            {
                "to": token,
                "title": title,
                "body": body,
                "sound": "default",
                "channelId": "qwenpaw-tasks",
                "data": _notification_data(event, workspace_key),
            },
        )
    for offset in range(0, len(messages), 100):
        await _send_expo_messages(messages[offset : offset + 100])


def schedule_mobile_notification(event: MobileNotificationEvent) -> None:
    """Schedule delivery without delaying the originating request."""
    asyncio.create_task(
        notify_mobile_devices(event),
        name=f"mobile-push-{event.kind}",
    )


def schedule_inbox_mobile_notification(event: dict[str, Any]) -> None:
    """Map an Inbox event to a supported mobile notification category."""
    event_type = str(event.get("event_type", "")).lower()
    status = str(event.get("status", "")).lower()
    severity = str(event.get("severity", "")).lower()
    kind: NotificationKind | None = None
    if "approval" in event_type:
        kind = "approval_required"
    elif status in {"failed", "error"} or severity in {"error", "critical"}:
        kind = "run_failed"
    elif "input" in event_type or status == "awaiting_user":
        kind = "input_required"
    elif status in {"completed", "success"}:
        kind = "run_completed"
    if kind is None:
        return
    payload = event.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    schedule_mobile_notification(
        MobileNotificationEvent(
            kind=kind,
            agent_id=str(event.get("agent_id") or "default"),
            title=str(event.get("title") or "QwenPaw"),
            body=str(event.get("body") or "打开 QwenPaw 查看详情"),
            chat_id=_optional_string(payload.get("chat_id")),
            session_id=_optional_string(payload.get("session_id")),
            inbox_event_id=_optional_string(event.get("id")),
        ),
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


async def _has_active_loop(workspace: Any, chat: Any) -> bool:
    try:
        from .agent_context import scoped_session_id
        from .routers.loops import (
            _build_loop_catalog,
            _session_context_state,
        )

        session_state = await workspace.session.get_session_state_dict(
            chat.session_id,
            chat.user_id,
            chat.channel,
        )
        agent_state, mode_state = _session_context_state(session_state)
        _, runtime_modes = _build_loop_catalog(workspace)
        context = SimpleNamespace(
            session_id=chat.session_id,
            session_state=agent_state,
            mode_state=mode_state,
            workspace=workspace,
            agent_config=workspace.config,
            agent=getattr(workspace, "agent", None),
        )
        with scoped_session_id(chat.session_id):
            for mode in getattr(workspace.plugins, "modes", []):
                descriptor = runtime_modes.get(getattr(mode, "name", ""))
                if descriptor in {None, "default"}:
                    continue
                if mode.is_active(context):
                    return True
    except Exception:  # pylint: disable=broad-except
        logger.debug(
            "Failed to inspect loop state for mobile push",
            exc_info=True,
        )
    return False


async def notify_chat_run_settled(
    workspace: Any,
    chat_id: str,
    outcome: Literal["completed", "failed", "cancelled"],
) -> None:
    """Schedule a completion, failure, or input notification for one chat."""
    if outcome == "cancelled":
        return
    chat = await workspace.chat_manager.get_chat(chat_id)
    if chat is None:
        return
    if outcome == "failed":
        kind: NotificationKind = "run_failed"
        title = "任务未完成"
        body = f"{chat.name or '会话'} 运行失败，打开查看详情。"
    elif await _has_active_loop(workspace, chat):
        kind = "input_required"
        title = "需要你的输入"
        body = f"{chat.name or '会话'} 正在等待你继续。"
    else:
        kind = "run_completed"
        title = "任务已完成"
        body = f"{chat.name or '会话'} 已完成回复。"
    schedule_mobile_notification(
        MobileNotificationEvent(
            kind=kind,
            agent_id=workspace.agent_id,
            title=title,
            body=body,
            chat_id=chat.id,
            session_id=chat.session_id,
        ),
    )
