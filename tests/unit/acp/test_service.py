# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from copaw.acp.config import ACPConfig, ACPHarnessConfig
from copaw.acp.errors import ACPConfigurationError
from copaw.acp.service import ACPService
from copaw.acp.types import ACPConversationSession


class _FakeRuntime:
    def __init__(self) -> None:
        self.prompt_called = False
        self.closed = False

    async def prompt(self, **kwargs) -> None:
        _ = kwargs
        self.prompt_called = True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_run_turn_blocks_dangerous_prompt_for_unverified_harness(
    monkeypatch,
) -> None:
    service = ACPService(
        config=ACPConfig(
            enabled=True,
            require_approval=True,
        ),
    )

    async def fail_get_or_create(**kwargs):
        _ = kwargs
        raise AssertionError("should not spawn harness for blocked prompt")

    monkeypatch.setattr(
        service,
        "_get_or_create_conversation",
        fail_get_or_create,
    )

    async def fake_on_message(_msg, _last) -> None:
        return None

    with pytest.raises(
        ACPConfigurationError,
        match="仅允许只读操作",
    ):
        await service.run_turn(
            chat_id="chat-1",
            session_id="session-1",
            user_id="user-1",
            channel="console",
            harness="opencode",
            prompt_blocks=[
                {"type": "text", "text": "创建一个新文件 note.txt"},
            ],
            cwd=".",
            keep_session=False,
            on_message=fake_on_message,
        )


@pytest.mark.asyncio
async def test_run_turn_allows_read_only_prompt_for_unverified_harness(
    monkeypatch,
) -> None:
    service = ACPService(
        config=ACPConfig(
            enabled=True,
            require_approval=True,
        ),
    )
    runtime = _FakeRuntime()
    captured: dict[str, object] = {}

    async def fake_get_or_create(**kwargs):
        captured["called"] = True
        _ = kwargs
        return (
            ACPConversationSession(
                chat_id="chat-1",
                harness="opencode",
                acp_session_id="acp-session-1",
                cwd="/tmp/workspace",
                keep_session=False,
                runtime=runtime,
            ),
            True,
        )

    monkeypatch.setattr(
        service,
        "_get_or_create_conversation",
        fake_get_or_create,
    )

    async def fake_on_message(_msg, _last) -> None:
        return None

    result = await service.run_turn(
        chat_id="chat-1",
        session_id="session-1",
        user_id="user-1",
        channel="console",
        harness="opencode",
        prompt_blocks=[
            {"type": "text", "text": "读取 README.md 并总结结构"},
        ],
        cwd="/tmp/workspace",
        keep_session=False,
        on_message=fake_on_message,
    )

    assert captured["called"] is True
    assert runtime.prompt_called is True
    assert runtime.closed is True
    assert result.session_id == "acp-session-1"


@pytest.mark.asyncio
async def test_run_turn_allows_verified_harness_dangerous_prompt(
    monkeypatch,
) -> None:
    config = ACPConfig(
        enabled=True,
        require_approval=True,
    )
    config.harnesses["opencode"] = ACPHarnessConfig(
        enabled=True,
        command="npx",
        args=["demo"],
        permission_broker_verified=True,
    )
    service = ACPService(config=config)
    runtime = _FakeRuntime()

    async def fake_get_or_create(**kwargs):
        _ = kwargs
        return (
            ACPConversationSession(
                chat_id="chat-1",
                harness="opencode",
                acp_session_id="acp-session-1",
                cwd="/tmp/workspace",
                keep_session=False,
                runtime=runtime,
            ),
            True,
        )

    monkeypatch.setattr(
        service,
        "_get_or_create_conversation",
        fake_get_or_create,
    )

    async def fake_on_message(_msg, _last) -> None:
        return None

    await service.run_turn(
        chat_id="chat-1",
        session_id="session-1",
        user_id="user-1",
        channel="console",
        harness="opencode",
        prompt_blocks=[
            {"type": "text", "text": "create a new file named note.txt"},
        ],
        cwd="/tmp/workspace",
        keep_session=False,
        on_message=fake_on_message,
    )

    assert runtime.prompt_called is True


@pytest.mark.asyncio
async def test_run_turn_allows_preapproved_prompt_for_unverified_harness(
    monkeypatch,
) -> None:
    service = ACPService(
        config=ACPConfig(
            enabled=True,
            require_approval=True,
        ),
    )
    runtime = _FakeRuntime()

    async def fake_get_or_create(**kwargs):
        _ = kwargs
        return (
            ACPConversationSession(
                chat_id="chat-1",
                harness="opencode",
                acp_session_id="acp-session-1",
                cwd="/tmp/workspace",
                keep_session=False,
                runtime=runtime,
            ),
            True,
        )

    monkeypatch.setattr(
        service,
        "_get_or_create_conversation",
        fake_get_or_create,
    )

    async def fake_on_message(_msg, _last) -> None:
        return None

    await service.run_turn(
        chat_id="chat-1",
        session_id="session-1",
        user_id="user-1",
        channel="console",
        harness="opencode",
        prompt_blocks=[
            {"type": "text", "text": "创建一个新文件 note.txt"},
        ],
        cwd="/tmp/workspace",
        keep_session=False,
        preapproved=True,
        on_message=fake_on_message,
    )

    assert runtime.prompt_called is True
