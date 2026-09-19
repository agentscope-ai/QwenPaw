# -*- coding: utf-8 -*-
"""Creator's typed PawApp model-setup boundary."""

# pylint: disable=protected-access

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Response

from api import model_routes
from domain.errors import ConflictError
from services import setup_coordination

from qwenpaw.pawapp import SetupRequest
from qwenpaw.pawapp.tasks import TaskScope, TaskStoreError

SCOPE = TaskScope(
    principal_id="alice",
    workspace_id="workspace-1",
    app_id=setup_coordination.APP_ID,
)


class _SetupCollector:
    def __init__(self) -> None:
        self.entries = []
        self.checks = []

    def setup_entry(self, registration):
        self.entries.append(registration)
        return self

    def setup_check(self, registration):
        self.checks.append(registration)
        return self


def _request(
    *,
    entry_id: str = setup_coordination.IMAGE_ENTRY_ID,
    requirement_id: str = setup_coordination.IMAGE_REQUIREMENT_ID,
) -> SetupRequest:
    return SetupRequest(
        request_id="setup_123",
        scope=SCOPE,
        descriptor_digest="descriptor-1",
        entry_id=entry_id,
        requirement_ids=(requirement_id,),
        origin_ref="chat-1",
        presentation="app_entry",
        expires_at=2000,
        return_target="chat-1",
        created_at=1000,
        updated_at=1000,
    )


def test_registered_entries_match_the_typed_manifest() -> None:
    collector = _SetupCollector()
    setup_coordination.register_creator_setup(collector)
    manifest_path = Path(__file__).resolve().parents[3] / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = manifest["pawapp"]["configuration"]["setup_entries"]
    registered = [
        item.descriptor.model_dump(mode="json", exclude={"schema_version"})
        for item in collector.entries
    ]

    assert registered == declared
    assert [item.requirement.id for item in collector.checks] == [
        setup_coordination.LLM_REQUIREMENT_ID,
        setup_coordination.IMAGE_REQUIREMENT_ID,
        setup_coordination.VIDEO_REQUIREMENT_ID,
    ]
    assert collector.checks[0].requirement.required_for == ("create-video",)


@pytest.mark.asyncio
async def test_model_checks_report_public_revision_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = model_routes._defaults()
    config.llm.enabled = True
    config.llm.model_name = "planning-model"
    config.llm.base_url = "https://llm.example/v1"
    config.llm.api_key = "shared-secret"
    config.image.enabled = True
    config.image.model_name = "image-model"
    config.image.base_url = "https://image.example/v1"
    config.image.reuse_llm_key = True
    config.video.enabled = False
    monkeypatch.setattr(
        setup_coordination,
        "_load_snapshot",
        lambda: (config, 7),
    )

    llm = await setup_coordination.check_llm_model(SCOPE, {})
    image = await setup_coordination.check_image_model(SCOPE, {})
    video = await setup_coordination.check_video_model(SCOPE, {})

    assert llm.state == "ready"
    assert llm.checked_revision == 7
    assert image.state == "ready"
    assert image.checked_revision == 7
    assert video.state == "needs_configuration"
    assert video.reason_code == "creator_video_model_missing"
    assert "shared-secret" not in llm.model_dump_json()
    assert "shared-secret" not in image.model_dump_json()
    assert "shared-secret" not in video.model_dump_json()


@pytest.mark.asyncio
async def test_keyless_sglang_video_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = model_routes._defaults()
    config.video.enabled = True
    config.video.model_name = "MiniMax-H3-Distill"
    config.video.base_url = "http://127.0.0.1:30000/v1"
    config.video.protocol = "MiniMax H3（SGLang 自部署）"
    config.video.api_key = ""
    config.video.reuse_llm_key = False
    monkeypatch.setattr(
        setup_coordination,
        "_load_snapshot",
        lambda: (config, 11),
    )

    result = await setup_coordination.check_video_model(SCOPE, {})

    assert result.state == "ready"
    assert result.checked_revision == 11


@pytest.mark.asyncio
async def test_model_check_rejects_another_app_scope() -> None:
    with pytest.raises(TaskStoreError, match="setup_scope_mismatch"):
        await setup_coordination.check_image_model(
            SCOPE.model_copy(update={"app_id": "other-app"}),
            {},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("opener", "entry_id", "requirement_id", "purpose"),
    [
        (
            setup_coordination.open_llm_setup,
            setup_coordination.LLM_ENTRY_ID,
            setup_coordination.LLM_REQUIREMENT_ID,
            "llm",
        ),
        (
            setup_coordination.open_image_setup,
            setup_coordination.IMAGE_ENTRY_ID,
            setup_coordination.IMAGE_REQUIREMENT_ID,
            "image",
        ),
        (
            setup_coordination.open_video_setup,
            setup_coordination.VIDEO_ENTRY_ID,
            setup_coordination.VIDEO_REQUIREMENT_ID,
            "video",
        ),
    ],
)
async def test_setup_entry_opens_the_exact_model_section(
    opener,
    entry_id: str,
    requirement_id: str,
    purpose: str,
) -> None:
    action = await opener(
        _request(entry_id=entry_id, requirement_id=requirement_id),
    )

    assert action.path == (
        f"/apps/qwenpaw-creator?setup={purpose}&setupRequest=setup_123"
    )
    assert action.entry_id == entry_id


@pytest.mark.asyncio
async def test_backend_completion_uses_authenticated_scope() -> None:
    setup_request = _request()
    coordinator = SimpleNamespace(
        backend_request=AsyncMock(
            return_value=(SCOPE, SimpleNamespace(request=setup_request)),
        ),
        complete=AsyncMock(),
    )
    request = SimpleNamespace(
        state=SimpleNamespace(user="alice"),
        app=SimpleNamespace(
            state=SimpleNamespace(pawapp_setup=coordinator),
        ),
    )

    await setup_coordination.complete_model_setup(request, "setup_123", 13)

    coordinator.backend_request.assert_awaited_once_with(
        "alice",
        setup_coordination.APP_ID,
        "setup_123",
    )
    completed_scope, result = coordinator.complete.await_args.args
    assert completed_scope == SCOPE
    assert result.request_id == "setup_123"
    assert result.outcome == "saved"
    assert result.changed_requirement_ids == (
        setup_coordination.IMAGE_REQUIREMENT_ID,
    )
    assert result.config_revisions == {
        setup_coordination.IMAGE_REQUIREMENT_ID: 13,
    }


@pytest.mark.asyncio
async def test_backend_completion_rejects_entry_requirement_mismatch() -> None:
    setup_request = _request(
        requirement_id=setup_coordination.VIDEO_REQUIREMENT_ID,
    )
    coordinator = SimpleNamespace(
        backend_request=AsyncMock(
            return_value=(SCOPE, SimpleNamespace(request=setup_request)),
        ),
        complete=AsyncMock(),
    )
    request = SimpleNamespace(
        state=SimpleNamespace(user="alice"),
        app=SimpleNamespace(
            state=SimpleNamespace(pawapp_setup=coordinator),
        ),
    )

    with pytest.raises(TaskStoreError, match="setup_result_scope_mismatch"):
        await setup_coordination.complete_model_setup(request, "setup_123", 13)
    coordinator.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_save_binds_and_replays_the_setup_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("CREATOR_MODEL_CONFIG_PATH", raising=False)
    monkeypatch.setattr(
        model_routes,
        "require_creator_data_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        model_routes,
        "mutate_model_config",
        lambda _mutator: None,
    )
    monkeypatch.setattr(
        model_routes,
        "_notify_agent_model_config_changed",
        lambda: None,
    )
    completion = AsyncMock()
    monkeypatch.setattr(model_routes, "complete_model_setup", completion)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(provider_manager=None)),
    )
    config = model_routes._defaults()

    first_response = Response()
    assert await model_routes.update_model_config(
        config,
        request,
        first_response,
        idempotency_key="model-save-1",
        setup_request_id="setup_123",
    ) == {"ok": True}
    assert first_response.headers["X-Idempotent-Replay"] == "false"
    completion.assert_awaited_once_with(request, "setup_123", 0)

    replay_response = Response()
    await model_routes.update_model_config(
        config,
        request,
        replay_response,
        idempotency_key="model-save-1",
        setup_request_id="setup_123",
    )
    assert replay_response.headers["X-Idempotent-Replay"] == "true"
    assert completion.await_count == 2

    with pytest.raises(ConflictError, match="Idempotency-Key"):
        await model_routes.update_model_config(
            config,
            request,
            Response(),
            idempotency_key="model-save-1",
            setup_request_id="setup_other",
        )
