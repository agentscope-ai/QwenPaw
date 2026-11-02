# -*- coding: utf-8 -*-
"""Local safety checks for the opt-in real-video acceptance runner."""

from __future__ import annotations

# pylint: disable=protected-access

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest

from services.project_files.assets import AssetFileStore
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    ElementLocation,
    ElementOutput,
    IndexedFile,
    Project,
    R2VCreation,
    TimelineElement,
    TimelineSpan,
)
from utils.paths import unique_task_work_path

from scripts import pawapp_real_video_acceptance as acceptance

pytestmark = pytest.mark.unit


def _plan(**updates) -> acceptance.AcceptancePlan:
    values = {
        "project_id": "project-1",
        "target_ref": "element:shot-1",
        "source_generation": 4,
        "provider": "wan",
        "model": "wan3.0-video-prime",
        "endpoint_host": "dashscope.aliyuncs.com",
        "credential_present": True,
        "original_duration_seconds": 10,
        "output_duration_seconds": 2,
        "output_resolution": "480P",
        "aspect_ratio": "16:9",
        "reference_count": 2,
        "reference_media": ("image", "image"),
        "active_video_tasks": 0,
    }
    values.update(updates)
    return acceptance.AcceptancePlan(**values)


class _Provider:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def submit(self, **_kwargs) -> str:
        self.events.append("delegate")
        return "provider-task-1"

    async def poll(self, provider_task_id: str):
        return {"task_id": provider_task_id, "status": "RUNNING"}

    async def submit_s2v(self, **_kwargs) -> str:
        self.events.append("delegate-s2v")
        return "provider-task-s2v-1"

    async def poll_s2v(self, provider_task_id: str):
        return {"task_id": provider_task_id, "status": "RUNNING"}


class _SuccessfulVideoProvider(_Provider):
    async def poll(self, provider_task_id: str):
        path = unique_task_work_path(
            "acceptance-video",
            ".mp4",
            prefix="pawapp-acceptance-test-",
        )
        path.write_bytes(
            b"\x00\x00\x00\x18ftypmp42" + b"bounded-video" * 64,
        )
        return {
            "task_id": provider_task_id,
            "status": "SUCCEEDED",
            "result_url": path.resolve().as_uri(),
            "media_type": "video/mp4",
            "durationSeconds": 2,
        }


@pytest.mark.asyncio
async def test_provider_claim_is_durable_before_the_only_submit() -> None:
    events: list[str] = []
    provider = acceptance.OneSubmitR2VProvider(
        _Provider(events),
        claim=lambda: events.append("claim"),
    )

    assert await provider.submit(prompt="bounded") == "provider-task-1"
    assert events == ["claim", "delegate"]
    assert provider.submitted == 1

    with pytest.raises(
        RuntimeError,
        match="acceptance_provider_submit_limit_reached",
    ):
        await provider.submit(prompt="must-not-run")
    assert events == ["claim", "delegate"]


@pytest.mark.asyncio
async def test_persisted_submit_claim_blocks_a_restart() -> None:
    events: list[str] = []
    provider = acceptance.OneSubmitR2VProvider(
        _Provider(events),
        submitted=1,
        claim=lambda: events.append("claim"),
    )

    with pytest.raises(
        RuntimeError,
        match="acceptance_provider_submit_limit_reached",
    ):
        await provider.submit(prompt="resume-must-poll")
    assert not events
    assert await provider.poll("accepted-task") == {
        "task_id": "accepted-task",
        "status": "RUNNING",
    }


def test_plan_is_pinned_to_the_reviewed_provider_shape() -> None:
    acceptance.validate_plan_safety(_plan())

    for changed in (
        {"model": "wan3.0-video"},
        {"provider": "veo"},
        {"endpoint_host": "dashscope-intl.aliyuncs.com"},
        {"credential_present": False},
        {"active_video_tasks": 1},
        {"reference_media": ("image", "video")},
    ):
        with pytest.raises(ValueError):
            acceptance.validate_plan_safety(_plan(**changed))


def test_billing_ack_requires_exact_token_and_bounded_ceiling() -> None:
    result = acceptance.validate_billing_ack(
        _plan(),
        confirmation=acceptance.CONFIRMATION,
        unit_price_cny="0.45",
        max_charge_cny="0.90",
    )
    assert result == {
        "acknowledged_unit_price_cny": "0.45",
        "acknowledged_maximum_charge_cny": "0.90",
        "charge_ceiling_cny": "0.90",
    }
    assert Decimal(result["acknowledged_maximum_charge_cny"]) == Decimal(
        "0.90",
    )

    rejected = (
        {
            "confirmation": "yes",
            "unit_price_cny": "0.45",
            "max_charge_cny": "0.90",
        },
        {
            "confirmation": acceptance.CONFIRMATION,
            "unit_price_cny": "0.45",
            "max_charge_cny": "0.89",
        },
        {
            "confirmation": acceptance.CONFIRMATION,
            "unit_price_cny": "0.45",
            "max_charge_cny": "2.01",
        },
    )
    for arguments in rejected:
        with pytest.raises(ValueError):
            acceptance.validate_billing_ack(_plan(), **arguments)


def test_submit_claim_is_written_once(tmp_path) -> None:
    path = tmp_path / "acceptance-manifest.json"
    manifest = {"provider_submit_attempts": 0, "state": "prepared"}

    acceptance._claim_provider_submit(path, manifest)

    stored = acceptance._read_manifest(path)
    assert stored["provider_submit_attempts"] == 1
    assert stored["state"] == "provider_submit_claimed"
    assert stored["provider_submit_claimed_at"]
    with pytest.raises(
        RuntimeError,
        match="acceptance_provider_submit_limit_reached",
    ):
        acceptance._claim_provider_submit(path, manifest)


def _source_project(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(root))
    monkeypatch.setenv(
        "CREATOR_MODEL_CONFIG_PATH",
        str(root / "config" / "model_config.json"),
    )
    config = {
        "video": {
            "enabled": True,
            "protocol": "DashScope（百炼）",
            "model_name": "wan3.0-video-prime",
            "base_url": "https://dashscope.aliyuncs.com/api/v1",
            "api_key": "unit-test-only",
            "reuse_llm_key": False,
        },
        "media_review": {"mode": "auto_approve"},
        "agent_runtime": {"media_call_budget": 1},
    }
    config_path = root / "config" / "model_config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(config), encoding="utf-8")
    services = CreatorFileServices.create(root)
    project = Project.new(project_id="project-1", name="Acceptance")
    project.timelines.items["timeline:main"].elements_by_id[
        "shot-1"
    ] = TimelineElement(
        element_id="shot-1",
        label="Acceptance shot",
        span=TimelineSpan(start_tick=0, duration_tick=10_000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="A paper kite rises.",
            storyboard_prompt="A paper kite above a quiet field.",
            video_prompt="A paper kite rises slowly above a quiet field.",
        ),
    )
    services.projects.create(project)

    content = b"\x89PNG\r\n\x1a\n" + b"storyboard" * 32
    digest = hashlib.sha256(content).hexdigest()
    relative_uri = "assets/artifacts/storyboard.png"
    files = AssetFileStore(services.projects.project_root("project-1"))
    files.publish(
        files.stage_bytes(content, staging_id="acceptance-storyboard"),
        relative_uri,
        expected_sha256=digest,
        expected_size_bytes=len(content),
    )
    snapshot = services.projects.read("project-1")
    candidate = snapshot.project.model_copy(deep=True)
    now = datetime.now(timezone.utc)
    candidate.assets.files_by_id["file-storyboard"] = IndexedFile(
        file_id="file-storyboard",
        kind="artifact_payload",
        relative_uri=relative_uri,
        sha256=digest,
        size_bytes=len(content),
        media_type="image/png",
        created_at=now,
    )
    candidate.assets.artifact_versions_by_id[
        "version-storyboard"
    ] = ArtifactVersion(
        version_id="version-storyboard",
        slot_id="element:shot-1:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:shot-1",
        name="Acceptance storyboard",
        file_id="file-storyboard",
        checksum=digest,
        based_on_generation=snapshot.generation,
        created_at=now,
    )
    candidate.assets.artifact_slots_by_id[
        "element:shot-1:storyboard"
    ] = ArtifactSlot(
        slot_id="element:shot-1:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:shot-1",
        version_ids=["version-storyboard"],
        selected_version_id="version-storyboard",
    )
    candidate.timelines.items["timeline:main"].elements_by_id[
        "shot-1"
    ].outputs["storyboard"] = ElementOutput(
        slot_id="element:shot-1:storyboard",
    )
    candidate.generation = snapshot.generation + 1
    candidate.updated_at = now
    services.projects.replace("project-1", candidate, snapshot.etag)


@pytest.mark.asyncio
async def test_fake_provider_completes_host_artifact_without_touching_source(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    _source_project(source, monkeypatch)
    source_before = CreatorFileServices.create(source).projects.read(
        "project-1",
    )
    plan = _plan(source_generation=source_before.generation)
    run_dir = tmp_path / "acceptance-run"
    manifest_path, manifest = acceptance.prepare_run_directory(
        source,
        run_dir,
        plan,
        {
            "acknowledged_unit_price_cny": "0.45",
            "acknowledged_maximum_charge_cny": "0.90",
            "charge_ceiling_cny": "0.90",
        },
    )
    events: list[str] = []

    result = await acceptance.run_acceptance(
        run_dir,
        manifest_path,
        manifest,
        timeout_seconds=10,
        provider=_SuccessfulVideoProvider(events),
        poll_interval_seconds=0.01,
    )

    assert result["state"] == "succeeded"
    assert result["provider_submit_attempts"] == 1
    assert result["artifact"]["media_type"] == "video/mp4"
    assert result["artifact"]["size_bytes"] > 0
    assert events == ["delegate"]
    source_after = CreatorFileServices.create(source).projects.read(
        "project-1",
    )
    assert source_after.etag == source_before.etag
    copied = CreatorFileServices.create(run_dir / "creator").projects.read(
        "project-1",
    )
    element = copied.project.timelines.items["timeline:main"].elements_by_id[
        "shot-1"
    ]
    assert copied.project.settings.resolution == "480P"
    assert element.span.duration_tick == 2_000
    assert (run_dir / "acceptance-result.json").is_file()
