import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.app.chats.models import ChatSpec, SessionSource
from qwenpaw.app.realtime_voice.contracts import (
    PROTOCOL_VERSION,
    RealtimeVoiceServiceError,
)
from qwenpaw.app.realtime_voice.service import RealtimeVoiceService


class ProviderManager:
    pass


def workspace():
    return SimpleNamespace(config=SimpleNamespace())


def live_session(session_id="old", principal="owner"):
    return SimpleNamespace(
        session_id=session_id,
        principal=principal,
        agent_id="default",
        provider_session=None,
        coordinator=None,
        api_key="test-key",
        config=SimpleNamespace(
            provider_id="provider",
            language="en-US",
            presentation_capacity=32,
            playback_timeout_seconds=90,
            max_history_turns=20,
        ),
        chat=SimpleNamespace(id="chat"),
        workspace=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_release_bootstrap_is_idempotent_and_preserves_chat_bridge():
    service = RealtimeVoiceService(ProviderManager())
    old, new = live_session(), live_session("new")
    service._sessions = {"old": old, "new": new}
    service._leases = {"owner": new}
    service._grants = {"grant": SimpleNamespace(session_id="old")}
    bridge = object()
    service._bridges["chat"] = bridge
    await service.release_session("old", "owner", "default")
    await service.release_session("old", "owner", "default")
    assert service._sessions == {"new": new}
    assert service._leases == {"owner": new}
    assert service._bridges["chat"] is bridge
    assert not service._grants
    await service.release_session("new", "owner", "default")
    assert not service._sessions and not service._leases


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "principal,agent_id", [("other", "default"), ("owner", "other")]
)
async def test_release_session_checks_owner(principal, agent_id):
    service = RealtimeVoiceService(ProviderManager())
    old = live_session()
    service._sessions["old"] = old
    with pytest.raises(RealtimeVoiceServiceError) as error:
        await service.release_session("old", principal, agent_id)
    assert error.value.status_code == 403
    assert service._sessions["old"] is old


@pytest.mark.asyncio
async def test_release_during_provider_start_closes_only_late_coordinator(
    monkeypatch,
):
    started, finish = asyncio.Event(), asyncio.Event()

    async def start():
        started.set()
        await finish.wait()

    coordinator = SimpleNamespace(start=start, close=AsyncMock())
    factory = Mock(return_value=coordinator)
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.service.VoiceCoordinator",
        factory,
    )
    manager = SimpleNamespace(
        get_realtime_voice_registration=lambda _: SimpleNamespace(
            factory=lambda *_: object(),
        )
    )
    service = RealtimeVoiceService(manager)
    old, new = live_session(), live_session("new")
    service._sessions["old"] = old
    service._leases["owner"] = old
    service._bridges["chat"] = object()
    pending = asyncio.create_task(service.connect(old))
    await asyncio.wait_for(started.wait(), 1)
    assert factory.call_args.kwargs["language"] == "en-US"
    await service.release_session("old", "owner", "default")
    service._sessions["new"] = new
    service._leases["owner"] = new
    finish.set()
    with pytest.raises(RealtimeVoiceServiceError, match="ended"):
        await pending
    coordinator.close.assert_awaited_once()
    assert old.coordinator is None
    assert service._leases["owner"] is new


@pytest.mark.asyncio
async def test_connect_uses_native_realtime_coordinator_without_text_router(
    monkeypatch,
):
    coordinator = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
    factory = Mock(return_value=coordinator)
    monkeypatch.setattr(
        "qwenpaw.app.realtime_voice.service.VoiceCoordinator",
        factory,
    )
    providers = [object(), object()]
    provider_factory = Mock(side_effect=providers)
    manager = SimpleNamespace(
        get_realtime_voice_registration=lambda _: SimpleNamespace(
            factory=provider_factory,
        )
    )
    service = RealtimeVoiceService(manager)
    live = live_session()
    service._sessions[live.session_id] = live
    service._bridges["chat"] = object()

    assert await service.connect(live) is coordinator
    assert factory.call_args.args[1] is service._bridges["chat"]
    assert factory.call_args.args[2]._chat is live.chat
    assert factory.call_args.kwargs["presentation_provider"] is providers[1]
    assert provider_factory.call_count == 2
    coordinator.start.assert_awaited_once()


def test_capabilities_advertise_the_media_protocol_version():
    manager = ProviderManager()
    manager.get_active_realtime_model = lambda: None
    manager.list_realtime_voice_capabilities = list
    current_workspace = workspace()
    current_workspace.agent_id = "default"
    capabilities = RealtimeVoiceService(manager).capabilities(current_workspace)
    assert capabilities["protocol_version"] == PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_new_voice_chat_uses_downgrade_safe_chat_source():
    chat_manager = SimpleNamespace(
        create_chat=AsyncMock(side_effect=lambda chat: chat),
    )
    current_workspace = SimpleNamespace(
        agent_id="default",
        chat_manager=chat_manager,
    )
    config = SimpleNamespace(
        provider_id="dashscope",
        realtime_model="qwen-omni-turbo-realtime",
        region="cn-beijing",
        voice="Cherry",
    )

    chat = await RealtimeVoiceService._resolve_chat(
        current_workspace,
        "local-single-user",
        None,
        config,
    )

    assert chat.source == SessionSource.chat
    assert chat.meta["realtime_voice"]["version"] == 3
    chat_manager.create_chat.assert_awaited_once_with(chat)


@pytest.mark.asyncio
async def test_voice_chat_resume_uses_capability_metadata():
    voice_chat = ChatSpec(
        session_id="realtime_voice:voice-1",
        user_id="local-single-user",
        meta={"realtime_voice": {"version": 3}},
    )
    chat_manager = SimpleNamespace(
        get_chat=AsyncMock(return_value=voice_chat),
    )
    current_workspace = SimpleNamespace(chat_manager=chat_manager)

    resolved = await RealtimeVoiceService._resolve_chat(
        current_workspace,
        "local-single-user",
        voice_chat.id,
        SimpleNamespace(),
    )

    assert resolved is voice_chat
