import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.app.realtime_voice.contracts import (
    PROTOCOL_VERSION,
    RealtimeVoiceServiceError,
)
from qwenpaw.app.realtime_voice.service import RealtimeVoiceService
from qwenpaw.config.config import ModelSlotConfig


class ProviderManager:
    def __init__(self, *, router=None, chat=None):
        self._router = router
        self._chat = chat

    def get_active_voice_router_model(self):
        return self._router

    def get_active_model(self):
        return self._chat


def workspace(*, router=None, chat=None):
    return SimpleNamespace(
        config=SimpleNamespace(
            active_voice_router_model=router,
            active_model=chat,
        ),
    )


def slot(name: str) -> ModelSlotConfig:
    return ModelSlotConfig(provider_id="provider", model=name)


def live_session(session_id="old", principal="owner"):
    return SimpleNamespace(
        session_id=session_id,
        principal=principal,
        agent_id="default",
        provider_session=None,
        coordinator=None,
        router_model=None,
        admission_mode="queue",
        api_key="test-key",
        config=SimpleNamespace(
            provider_id="provider",
            language="en-US",
            continuation_grace_ms=1200,
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
            context_max_chars=1800,
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


def test_router_model_resolution_uses_confirmed_precedence():
    global_router = slot("global-router")
    global_chat = slot("global-chat")
    service = RealtimeVoiceService(
        ProviderManager(router=global_router, chat=global_chat),
    )

    assert service.resolve_router_model(
        workspace(router=slot("agent-router"), chat=slot("agent-chat")),
    ) == slot("agent-router")
    assert (
        service.resolve_router_model(
            workspace(chat=slot("agent-chat")),
        )
        == global_router
    )
    service = RealtimeVoiceService(ProviderManager(chat=global_chat))
    assert service.resolve_router_model(
        workspace(chat=slot("agent-chat")),
    ) == slot("agent-chat")
    assert service.resolve_router_model(workspace()) == global_chat


def test_capabilities_advertise_the_media_protocol_version():
    manager = ProviderManager()
    manager.get_active_realtime_model = lambda: None
    manager.list_realtime_voice_capabilities = lambda: []
    current_workspace = workspace()
    current_workspace.agent_id = "default"
    capabilities = RealtimeVoiceService(manager).capabilities(
        current_workspace
    )
    assert capabilities["protocol_version"] == PROTOCOL_VERSION
