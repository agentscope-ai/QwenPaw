"""Task 7.3: HTTP authorization and saved global ASR contract, no real services."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_membership import AgentAccessDeniedError
from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.app import agent_context
from qwenpaw.app.routers import agent_scoped, console, providers, workspace
from qwenpaw.config.config import Config
from qwenpaw.identity.models import PlatformRole


@pytest.fixture
def voice_http(monkeypatch, tmp_path):
    config = Config()
    config.agents.profiles = {"default": SimpleNamespace(enabled=True)}
    actor = ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="voice-test",
    )
    state = SimpleNamespace(
        actor=actor,
        role=AgentResourceRole.USER,
        deny=False,
        historical=False,
        config=config,
        saves=Mock(),
    )

    class Membership:
        async def require_role(self, **kwargs):
            if state.deny or state.role not in kwargs["allowed_roles"]:
                raise AgentAccessDeniedError()
            return SimpleNamespace(
                role=state.role, historical_read_only=state.historical
            )

    for module in (agent_context, agent_scoped, console, providers):
        monkeypatch.setattr(module, "is_multi_user_enabled", lambda: True)
    for module in (agent_context, agent_scoped, workspace):
        monkeypatch.setattr(module, "load_config", lambda: state.config)
    for module in (agent_context, agent_scoped):
        monkeypatch.setattr(
            module, "_get_agent_membership_service", lambda: Membership()
        )
    monkeypatch.setattr(workspace, "save_config", state.saves)
    import qwenpaw.config as config_module

    monkeypatch.setattr(config_module, "load_config", lambda: state.config)
    from qwenpaw.agents.utils import audio_transcription as audio

    monkeypatch.setattr(audio, "_get_manager", lambda: None)
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.actor = state.actor
        return await call_next(request)

    app.include_router(workspace.router, prefix="/api")
    app.include_router(console.router, prefix="/api")
    app.include_router(
        workspace.router,
        prefix="/api/agents/{agentId}",
        dependencies=[Depends(agent_scoped.require_agent_scoped_access)],
    )
    app.state.multi_agent_manager = SimpleNamespace(
        get_agent=AsyncMock(
            return_value=SimpleNamespace(agent_id="default", workspace_dir=tmp_path)
        )
    )
    state.client = TestClient(app)
    return state


MANAGEMENT = [
    ("GET", "audio-mode", None),
    ("PUT", "audio-mode", {"audio_mode": "native"}),
    ("GET", "transcription-provider-type", None),
    ("PUT", "transcription-provider-type", {"transcription_provider_type": "disabled"}),
    ("GET", "local-whisper-status", None),
    ("GET", "transcription-providers", None),
    ("PUT", "transcription-provider", {"provider_id": ""}),
    ("GET", "voice-transcription", None),
    ("PUT", "voice-transcription", {}),
    ("POST", "transcription-test", None),
]


@pytest.mark.parametrize("prefix", ["/api", "/api/agents/default"])
@pytest.mark.parametrize("role", list(AgentResourceRole))
@pytest.mark.parametrize("method,path,body", MANAGEMENT)
def test_members_cannot_manage_voice(voice_http, prefix, role, method, path, body):
    voice_http.role = role
    kwargs = {"json": body} if body is not None else {}
    if method == "POST":
        kwargs = {"files": {"file": ("sample.wav", b"audio", "audio/wav")}}
    response = voice_http.client.request(
        method, prefix + "/workspace/" + path, **kwargs
    )
    assert response.status_code == 403
    voice_http.saves.assert_not_called()


@pytest.mark.parametrize("prefix", ["/api", "/api/agents/default"])
@pytest.mark.parametrize("role", list(AgentResourceRole))
def test_agent_users_reach_disabled_transcribe(voice_http, prefix, role):
    voice_http.role = role
    response = voice_http.client.post(
        prefix + "/workspace/transcribe", files={"file": ("sample.wav", b"audio")}
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "TRANSCRIPTION_DISABLED"


@pytest.mark.parametrize("historical", [False, True])
def test_global_transcribe_requires_agent_write_access(voice_http, historical):
    voice_http.deny = not historical
    voice_http.historical = historical
    response = voice_http.client.post(
        "/api/workspace/transcribe", files={"file": ("sample.wav", b"audio")}
    )
    assert response.status_code == 403


def test_member_cannot_read_raw_logs(voice_http):
    assert voice_http.client.get("/api/console/debug/backend-logs").status_code == 403


def test_user_status_is_minimal(voice_http):
    response = voice_http.client.get("/api/workspace/transcription-status")
    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "available": False,
        "reason": "TRANSCRIPTION_DISABLED",
    }


def settings(**changes):
    return dict(
        audio_mode="auto",
        transcription_provider_type="disabled",
        transcription_provider_id="",
        transcription_model="whisper-1",
        transcription_local_model="base",
        **changes,
    )


def test_admin_joint_save_never_mutates_cached_config(voice_http):
    voice_http.actor = ActorContext(
        user_id=voice_http.actor.user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN,
        admin_mode=False,
        request_id="admin",
    )
    body = settings()
    body["audio_mode"] = "native"
    response = voice_http.client.put("/api/workspace/voice-transcription", json=body)
    assert response.status_code == 200
    assert response.json()["settings"] == body
    assert voice_http.config.agents.audio_mode == "auto"
    voice_http.saves.assert_called_once()
    assert voice_http.saves.call_args.args[0].agents.audio_mode == "native"


def test_local_model_default_is_explicit():
    assert getattr(Config().agents, "transcription_local_model", None) == "base"


@pytest.fixture
def saved_remote(voice_http, monkeypatch, tmp_path):
    from qwenpaw.agents.utils import audio_transcription as audio
    from qwenpaw.app import voice_service
    from qwenpaw.providers.openai_provider import OpenAIProvider

    provider = OpenAIProvider(
        id="fake",
        name="Fake",
        base_url="http://asr.invalid/v1",
        api_key="SYNTHETIC_SECRET",
    )
    manager = SimpleNamespace(
        get_provider=lambda pid: provider if pid == "fake" else None,
        builtin_providers={"fake": provider},
        custom_providers={},
        plugin_providers={},
    )
    monkeypatch.setattr(audio, "_get_manager", lambda: manager)
    monkeypatch.setattr("qwenpaw.models.runtime.is_multi_user_enabled", lambda: False)
    monkeypatch.setattr(voice_service, "audio_temp_root", lambda: tmp_path / "voice")
    voice_http.config.agents.transcription_provider_type = "whisper_api"
    voice_http.config.agents.transcription_provider_id = "fake"
    client = SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(text="hello"))
            )
        ),
        close=AsyncMock(),
    )
    monkeypatch.setattr("openai.AsyncOpenAI", Mock(return_value=client))
    voice_http.upstream = client
    voice_http.temp_root = tmp_path / "voice"
    return voice_http


@pytest.mark.parametrize(
    "data,code,status", [(b"", "EMPTY_AUDIO", 400), (b"12345", "FILE_TOO_LARGE", 413)]
)
def test_upload_stream_limit_and_empty_cleanup(
    saved_remote, monkeypatch, data, code, status
):
    monkeypatch.setattr("qwenpaw.app.voice_service.MAX_AUDIO_BYTES", 4)
    response = saved_remote.client.post(
        "/api/workspace/transcribe", files={"file": ("audio.wav", data)}
    )
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert not list(saved_remote.temp_root.rglob("audio*"))
    assert not list(saved_remote.temp_root.rglob("request-*"))
    saved_remote.upstream.audio.transcriptions.create.assert_not_awaited()


@pytest.mark.parametrize(
    "error,expected",
    [
        (None, None),
        (RuntimeError("SYNTHETIC_SECRET"), "UPSTREAM_FAILED"),
        (TimeoutError("SYNTHETIC_SECRET"), "UPSTREAM_TIMEOUT"),
    ],
)
def test_upload_success_and_failure_cleanup(saved_remote, error, expected, caplog):
    saved_remote.upstream.audio.transcriptions.create.side_effect = error
    response = saved_remote.client.post(
        "/api/workspace/transcribe", files={"file": ("audio.wav", b"sample")}
    )
    if expected:
        assert response.json()["detail"]["code"] == expected
    else:
        assert response.json() == {"text": "hello"}
    assert not list(saved_remote.temp_root.rglob("request-*"))
    assert "SYNTHETIC_SECRET" not in response.text + caplog.text
    saved_remote.upstream.close.assert_awaited_once()


@pytest.mark.parametrize("endpoint", ["transcribe", "transcription-test"])
def test_upload_cannot_override_infrastructure(saved_remote, endpoint):
    saved_remote.actor = ActorContext(
        user_id=saved_remote.actor.user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN,
        admin_mode=False,
        request_id="admin",
    )
    response = saved_remote.client.post(
        "/api/workspace/" + endpoint,
        files={"file": ("audio.wav", b"sample")},
        data={"model": "injected"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_TRANSCRIPTION_REQUEST"
    saved_remote.upstream.audio.transcriptions.create.assert_not_awaited()


def test_upload_rejects_unwritable_conversation(saved_remote, monkeypatch):
    from qwenpaw.app.chats.access import ChatAccessDeniedError

    monkeypatch.setattr(
        console,
        "require_conversation_access",
        AsyncMock(side_effect=ChatAccessDeniedError()),
    )
    ws = saved_remote.client.app.state.multi_agent_manager.get_agent.return_value
    ws.chat_manager = SimpleNamespace(conversation_repository=object())
    response = saved_remote.client.post(
        "/api/workspace/transcribe",
        files={"file": ("audio.wav", b"sample")},
        data={"conversation_id": str(uuid4())},
    )
    assert response.status_code == 404
    saved_remote.upstream.audio.transcriptions.create.assert_not_awaited()


def test_joint_validation_does_not_partially_save(saved_remote):
    saved_remote.actor = ActorContext(
        user_id=saved_remote.actor.user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN,
        admin_mode=False,
        request_id="admin",
    )
    body = settings()
    body.update(
        audio_mode="native",
        transcription_provider_type="whisper_api",
        transcription_provider_id="missing",
    )
    response = saved_remote.client.put("/api/workspace/voice-transcription", json=body)
    assert response.status_code == 400
    assert saved_remote.config.agents.audio_mode == "auto"
    saved_remote.saves.assert_not_called()


def test_admin_test_uses_saved_unregistered_asr_model(saved_remote):
    saved_remote.actor = ActorContext(
        user_id=saved_remote.actor.user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN,
        admin_mode=False,
        request_id="admin",
    )
    saved_remote.config.agents.transcription_model = "task73-whisper"
    saved_remote.deny = True
    response = saved_remote.client.post(
        "/api/workspace/transcription-test", files={"file": ("sample.wav", b"sample")}
    )
    assert response.json() == {"text": "hello"}
    assert (
        saved_remote.upstream.audio.transcriptions.create.call_args.kwargs["model"]
        == "task73-whisper"
    )


def test_old_single_field_route_rejects_other_settings(saved_remote):
    saved_remote.actor = ActorContext(
        user_id=saved_remote.actor.user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN,
        admin_mode=False,
        request_id="admin",
    )
    response = saved_remote.client.put(
        "/api/workspace/audio-mode",
        json={"audio_mode": "native", "transcription_model": "changed"},
    )
    assert response.status_code == 400
    saved_remote.saves.assert_not_called()


def test_multipart_total_bytes_are_bounded_before_spooling(saved_remote, monkeypatch):
    monkeypatch.setattr("qwenpaw.app.voice_service.MAX_AUDIO_BYTES", 4)
    response = saved_remote.client.post(
        "/api/workspace/transcribe",
        files={"file": ("audio.wav", b"sample")},
        data={"ignored": "x" * 70000},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "FILE_TOO_LARGE"
    saved_remote.upstream.audio.transcriptions.create.assert_not_awaited()


@pytest.mark.parametrize("kind", ["disabled", "local_whisper"])
def test_can_leave_broken_remote_configuration(saved_remote, kind):
    saved_remote.actor = ActorContext(
        user_id=saved_remote.actor.user_id,
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN,
        admin_mode=False,
        request_id="admin",
    )
    body = settings()
    body.update(transcription_provider_type=kind, transcription_provider_id="removed")
    response = saved_remote.client.put("/api/workspace/voice-transcription", json=body)
    assert response.status_code == 200
    assert response.json()["settings"]["transcription_provider_id"] == "removed"
    saved_remote.saves.assert_called_once()
