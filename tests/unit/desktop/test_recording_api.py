# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from test_event_stream_recorder import _FakeClient, _FakeIngestor

from record_replay.api import build_router
from record_replay.errors import RecordingProtocolError
from record_replay.event_stream_recorder import EventStreamDesktopRecorder
from record_replay.learn_models import (
    LearnEvidenceEnvelope,
    LearnModelTarget,
    SkillDraftStep,
    StructuredSkillDraft,
)
from record_replay.learning import DesktopLearningService
from record_replay.models import RecordingState
from record_replay.service import DesktopRecordingService
from record_replay.session_store import RecordingStore


class _NativeClient(_FakeClient):
    """The API tests use the EventStream peer, never a legacy RPC lane."""

    async def status(self, *, recording_id=None):
        native = await super().status(recording_id=recording_id)
        native["permissions"] = {
            "input_monitoring": True,
            "accessibility": True,
        }
        return native


class _Manager:
    def __init__(self, workspace_dir: Path) -> None:
        self.reloaded: list[str] = []
        self.workspace = SimpleNamespace(
            agent_id="default",
            workspace_dir=workspace_dir,
        )

    async def get_agent(self, agent_id: str):
        return self.workspace if agent_id == "default" else None

    def note_agent_config_changed(self, _agent_id: str) -> int:
        return 1

    async def reload_agent(self, agent_id: str) -> bool:
        self.reloaded.append(agent_id)
        return True


def _app(
    tmp_path: Path,
    stream=None,
    *,
    learning: DesktopLearningService | None = None,
) -> FastAPI:
    app = FastAPI()
    recording = DesktopRecordingService(
        event_stream_recorder=stream
        or EventStreamDesktopRecorder(
            _NativeClient(tmp_path / "staging"),
            ingestor=_FakeIngestor(),
        ),
    )
    learning_service = learning or DesktopLearningService()

    async def request_scope(request: Request):
        request.state.desktop_recording_service = recording
        request.state.desktop_learning_service = learning_service
        yield

    app.state.multi_agent_manager = _Manager(tmp_path)
    app.include_router(
        build_router(request_scope, prefix="/desktop/recording"),
        prefix="/api",
    )
    return app


def test_product_api_runs_start_pause_resume_stop(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        headers = {"X-Agent-Id": "default"}
        initial = client.get("/api/desktop/recording", headers=headers)
        assert initial.status_code == 200
        assert initial.json()["state"] == "idle"
        assert initial.json()["available"] is True

        started = client.post(
            "/api/desktop/recording/start",
            headers=headers,
        )
        assert started.status_code == 200
        assert started.json()["state"] == "recording"
        assert started.json()["recording"]["agent_id"] == "default"

        paused = client.post("/api/desktop/recording/pause", headers=headers)
        assert paused.json()["state"] == "paused"
        resumed = client.post("/api/desktop/recording/resume", headers=headers)
        assert resumed.json()["state"] == "recording"

        stopped = client.post("/api/desktop/recording/stop", headers=headers)
        assert stopped.status_code == 200
        assert stopped.json()["state"] == "idle"
        assert stopped.json()["recording"] is None
        assert stopped.json()["last_recording"]["state"] == "completed"
        recording_id = stopped.json()["last_recording"]["recording_id"]
        summary_path = tmp_path / "recordings" / recording_id / "summary.json"
        assert summary_path.is_file()


@pytest.mark.parametrize(
    "code",
    [
        "input_monitoring_denied",
        "input_monitoring_permission_required",
        "accessibility_permission_required",
        "screen_recording_permission_required",
        "recording_permission_revoked",
    ],
)
def test_product_api_returns_stable_permission_error(
    tmp_path: Path,
    code: str,
) -> None:
    stream = _event_stream_stub()
    detail = f"{code}:Grant access to QwenPaw Computer Use"
    stream.start.side_effect = RecordingProtocolError(detail)
    with TestClient(_app(tmp_path, stream)) as client:
        response = client.post(
            "/api/desktop/recording/start",
            headers={"X-Agent-Id": "default"},
        )
    assert response.status_code == 403
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize(
    "code",
    [
        "recording_screen_locked",
        "recording_secure_input",
        "recording_session_inactive",
        "recording_environment_changed",
    ],
)
def test_environment_refusal_is_a_conflict_not_a_network_failure(
    tmp_path: Path,
    code: str,
):
    stream = _event_stream_stub()
    stream.start.side_effect = RecordingProtocolError(
        f"{code}:Start a new recording.",
    )
    with TestClient(_app(tmp_path, stream)) as client:
        response = client.post(
            "/api/desktop/recording/start",
            headers={"X-Agent-Id": "default"},
        )
    assert response.status_code == 409
    assert response.json()["detail"].startswith(code + ":")


def test_product_api_requests_permission_through_runtime(
    tmp_path: Path,
) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post("/api/desktop/recording/permission/request")
    assert response.status_code == 200
    assert response.json()["input_monitoring"] == "granted"
    assert response.json()["accessibility"] == "granted"


def _event_stream_stub() -> SimpleNamespace:
    return SimpleNamespace(
        available=AsyncMock(return_value=True),
        runtime_status=AsyncMock(
            return_value={
                "available": True,
                "state": "idle",
                "permissions": {
                    "accessibility": True,
                    "input_monitoring": True,
                },
            },
        ),
        snapshot=AsyncMock(
            return_value=SimpleNamespace(active=None, last=None),
        ),
        start=AsyncMock(),
        request_permissions=AsyncMock(),
    )


def test_advertised_event_stream_disconnect_recovers_same_recorder(
    tmp_path: Path,
) -> None:
    stream = _event_stream_stub()
    native = stream.runtime_status.return_value
    stream.runtime_status.side_effect = [
        RecordingProtocolError("event_stream_disconnected"),
        native,
    ]
    app = _app(tmp_path, stream)
    with TestClient(app) as client:
        failed = client.get("/api/desktop/recording")
        assert failed.status_code == 503
        assert failed.json() == {"detail": "event_stream_disconnected"}
        recovered = client.get("/api/desktop/recording")
        assert recovered.status_code == 200
        assert recovered.json()["input_monitoring"] == "granted"
        assert recovered.json()["accessibility"] == "granted"


@pytest.mark.asyncio
async def test_late_failed_probe_cannot_erase_successful_negotiation():
    stream = _event_stream_stub()
    waiting, release = asyncio.Event(), asyncio.Event()

    async def delayed_unavailable():
        waiting.set()
        await release.wait()
        return False

    stream.available.side_effect = delayed_unavailable
    service = DesktopRecordingService(event_stream_recorder=stream)
    first = asyncio.create_task(service.status())
    await waiting.wait()
    stream.available.side_effect = None
    assert (await service.status()).available is True
    release.set()
    assert (await first).available is True
    # Later requests use runtime_status/reconnect, not a new optional probe.
    assert (await service.status()).available is True
    assert stream.available.await_count == 2
    assert stream.runtime_status.await_count == 3


@pytest.mark.parametrize("operation", ["status", "start", "permission"])
def test_known_event_stream_outage_never_changes_permission_subject(
    tmp_path: Path,
    operation: str,
) -> None:
    stream = _event_stream_stub()
    app = _app(tmp_path, stream)
    with TestClient(app) as client:
        assert client.get("/api/desktop/recording").status_code == 200
        # Once the Helper advertised EventStream, a restart/outage must not
        # switch either controls or permission requests to the Tauri app.
        stream.available.return_value = False
        methods = {
            "status": stream.runtime_status,
            "start": stream.start,
            "permission": stream.request_permissions,
        }
        methods[operation].side_effect = RecordingProtocolError(
            "event_stream_disconnected",
        )
        if operation == "status":
            response = client.get("/api/desktop/recording")
        else:
            suffix = "start" if operation == "start" else "permission/request"
            response = client.post(
                f"/api/desktop/recording/{suffix}",
                headers={"X-Agent-Id": "default"},
            )
        assert response.status_code == 503
        assert response.json() == {"detail": "event_stream_disconnected"}


def test_absent_contract_does_not_record_or_request_permissions(
    tmp_path: Path,
) -> None:
    stream = _event_stream_stub()
    stream.available.return_value = False
    with TestClient(_app(tmp_path, stream)) as client:
        status = client.get("/api/desktop/recording")
        assert status.status_code == 200
        assert status.json()["available"] is False
        assert status.json()["input_monitoring"] == "unavailable"
        assert status.json()["accessibility"] == "unavailable"
        for suffix in ("start", "permission/request"):
            response = client.post(f"/api/desktop/recording/{suffix}")
            assert response.status_code == 503
            assert response.json() == {"detail": "desktop_runtime_unavailable"}
        # Missing at first startup must be recoverable via the same client.
        stream.available.return_value = True
        assert client.get("/api/desktop/recording").json()["available"] is True
    stream.start.assert_not_awaited()
    stream.request_permissions.assert_not_awaited()
    assert not (tmp_path / "recordings").exists()


@pytest.mark.parametrize("operation", ["pause", "resume", "stop"])
def test_controls_without_active_recording_return_conflict(
    tmp_path,
    operation,
):
    with TestClient(_app(tmp_path)) as client:
        response = client.post(f"/api/desktop/recording/{operation}")
        assert response.status_code == 409
    assert not (tmp_path / "recordings").exists()


def test_product_api_previews_generates_and_materializes_skill(
    tmp_path: Path,
) -> None:
    store = RecordingStore(tmp_path)
    session = store.create(
        workspace_id="default",
        user_id="local-console",
        agent_id="default",
    )
    store.transition(session.recording_id, RecordingState.RECORDING)
    from record_replay.models import RecordingEvent

    store.append_events(
        session.recording_id,
        [
            RecordingEvent(
                seq=1,
                t_monotonic_ms=10,
                type="click",
                app={
                    "bundle_id": "com.apple.calculator",
                    "name": "Calculator",
                },
                target={
                    "role": "AXButton",
                    "identifier": "Nine",
                    "name": "9",
                },
                input={"button": "left", "x": 20, "y": 30},
            ),
        ],
    )
    store.transition(session.recording_id, RecordingState.FINALIZING)
    store.complete(session.recording_id)

    target = LearnModelTarget(
        provider_id="test-provider",
        model="test-model",
        is_local=False,
    )

    async def generate(
        _agent_id: str,
        _target: LearnModelTarget,
        envelope: LearnEvidenceEnvelope,
    ) -> StructuredSkillDraft:
        event = envelope.events[0]
        return StructuredSkillDraft(
            name="enter-nine",
            description="Enter nine in Calculator when requested.",
            goal=envelope.intent.goal,
            steps=[
                SkillDraftStep(
                    source_event_id=event.evidence_id,
                    action=event.type,
                    locator=event.locator,
                    instruction="Activate the number nine button",
                    verification="Confirm Calculator displays nine",
                ),
            ],
        )

    learning = DesktopLearningService(
        target_resolver=lambda _agent_id: target,
        draft_generator=generate,
    )
    headers = {"X-Agent-Id": "default"}
    with TestClient(_app(tmp_path, learning=learning)) as client:
        review = client.post(
            "/api/desktop/recording/learn/review",
            headers=headers,
            json={"recording_id": str(session.recording_id)},
        )
        assert review.status_code == 200
        assert review.json()["events"][0]["source_sequences"] == [1]
        assert "bounds" not in review.json()["events"][0]["locator"]
        assert "x" not in review.json()["events"][0]["action"]

        preview = client.post(
            "/api/desktop/recording/learn/prepare",
            headers=headers,
            json={
                "recording_id": str(session.recording_id),
                "goal": "Enter 9 in Calculator",
            },
        )
        assert preview.status_code == 200
        assert preview.json()["external_transfer"] is True
        assert preview.json()["evidence_event_count"] == 1

        generated = client.post(
            "/api/desktop/recording/learn/generate",
            headers=headers,
            json={
                "consent_token": preview.json()["consent_token"],
                "consent": True,
            },
        )
        assert generated.status_code == 200
        draft = generated.json()
        assert draft["source_sequences"] == [1]
        assert draft["needs_confirmation"] is False

        recovered = client.get(
            f"/api/desktop/recording/learn/draft/{session.recording_id}",
            headers=headers,
        )
        assert recovered.status_code == 200
        assert recovered.json() == draft

        created = client.post(
            "/api/desktop/recording/learn/materialize",
            headers=headers,
            json={
                "draft_id": draft["draft_id"],
                "name": draft["name"],
                "content": draft["content"],
                "approved": True,
            },
        )
        assert created.status_code == 200
        assert created.json() == {
            "api_schema_version": 1,
            "created": True,
            "name": "enter-nine",
            "enabled": True,
            "reload_scheduled": True,
        }
        recovered = client.get(
            f"/api/desktop/recording/learn/draft/{session.recording_id}",
            headers=headers,
        )
        assert recovered.status_code == 200
        assert recovered.json() is None
    assert (tmp_path / "skills" / "enter-nine" / "SKILL.md").is_file()
