# -*- coding: utf-8 -*-
"""Tests for mobile push registration, privacy, and delivery filtering."""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app import mobile_push
from qwenpaw.app.mobile_push import (
    MobileNotificationEvent,
    MobilePushSubscriptionRequest,
    NotificationPreferences,
)


def _request(
    *,
    installation_id: str = "installation-one",
    agent_id: str = "default",
    preview: str = "title_only",
) -> MobilePushSubscriptionRequest:
    return MobilePushSubscriptionRequest(
        installation_id=installation_id,
        workspace_key="workspace-key-0123456789",
        agent_id=agent_id,
        platform="android",
        expo_push_token=(
            "ExponentPushToken[abcdefghijklmnopqrstuvwxyz123456]"
        ),
        preferences=NotificationPreferences(preview=preview),
    )


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mobile_push,
        "_SUBSCRIPTIONS_PATH",
        tmp_path / "mobile_push_subscriptions.json",
    )


@pytest.mark.asyncio
async def test_registration_never_returns_push_token() -> None:
    response = await mobile_push.register_mobile_push(_request())

    assert response.installation_id == "installation-one"
    assert "push_token" not in response.model_dump()
    loaded = await mobile_push.get_mobile_push(
        "installation-one",
        "workspace-key-0123456789",
        "default",
    )
    assert loaded == response


@pytest.mark.asyncio
async def test_rejects_invalid_expo_token() -> None:
    request = _request().model_copy(update={"expo_push_token": "secret"})

    with pytest.raises(ValueError, match="Invalid Expo push token"):
        await mobile_push.register_mobile_push(request)


@pytest.mark.asyncio
async def test_delivery_filters_agent_and_uses_private_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await mobile_push.register_mobile_push(_request(preview="hidden"))
    await mobile_push.register_mobile_push(
        _request(installation_id="installation-two", agent_id="other"),
    )
    sent: list[list[dict]] = []

    async def capture(messages: list[dict]) -> None:
        sent.append(messages)

    monkeypatch.setattr(mobile_push, "_send_expo_messages", capture)
    await mobile_push.notify_mobile_devices(
        MobileNotificationEvent(
            kind="approval_required",
            agent_id="default",
            title="Sensitive tool name",
            body="Sensitive command arguments",
            chat_id="chat-one",
        ),
    )

    assert len(sent) == 1
    assert len(sent[0]) == 1
    assert sent[0][0]["title"] == "QwenPaw"
    assert sent[0][0]["body"] == "你有一条新通知"
    assert "Sensitive" not in str(sent[0][0])
    assert sent[0][0]["data"]["chat_id"] == "chat-one"


@pytest.mark.asyncio
async def test_disabled_category_is_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    request.preferences.run_completed = False
    await mobile_push.register_mobile_push(request)
    sent: list[list[dict]] = []

    async def capture(messages: list[dict]) -> None:
        sent.append(messages)

    monkeypatch.setattr(mobile_push, "_send_expo_messages", capture)
    await mobile_push.notify_mobile_devices(
        MobileNotificationEvent(
            kind="run_completed",
            agent_id="default",
            title="Done",
            body="Completed",
        ),
    )

    assert not sent


@pytest.mark.asyncio
async def test_unregister_removes_only_matching_subscription() -> None:
    await mobile_push.register_mobile_push(_request())

    assert await mobile_push.unregister_mobile_push(
        "installation-one",
        "workspace-key-0123456789",
        "default",
    )
    assert (
        await mobile_push.get_mobile_push(
            "installation-one",
            "workspace-key-0123456789",
            "default",
        )
        is None
    )
