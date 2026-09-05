# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Transient image failures reopen a retry slot; deterministic ones stay walls.

Reproduces the 2026-08 production deadlock: a network blip failed the image
Task terminally, and because identical retries derive the same durable slot,
every same-argument resend hit "图片 Task 已终止: FAILED" forever.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pytest

from domain.enums import CreatorCommandType
from domain.errors import ConflictError, ValidationError
from services.media_files import image_execution
from services.media_files.image_execution import (
    FileImageExecutionService,
    ImageModelCapabilityError,
    ImageReferenceBudgetError,
    _append_storyboard_panel_aspect_contract,
    _resolve_request,
    _storyboard_panel_aspect_contract,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.project_files.store import ProjectSnapshot
from services.runtime_files.models import ChangeOrigin, ReviewPolicy
from utils.exceptions import ModelError

from .conftest import make_r2v_element, r2v_project_services


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"retry-image" * 16

PROJECT_ID = "image-resilience-project"
ELEMENT_ID = "r2v-1"

_SAFETY_MESSAGE = (
    "Image generation failed with status 400: "
    "Your request was rejected by the safety system"
)
_PHOTO_URL = "https://example.com/messi-photo.jpg"


def test_storyboard_panel_aspect_contract_preserves_each_video_frame() -> None:
    contract = _storyboard_panel_aspect_contract("9:16", 5)
    assert "target video aspect ratio is 9:16" in contract
    assert "EVERY individual storyboard panel" in contract
    assert "outer storyboard delivery canvas is also 9:16" in contract
    # ceil(sqrt(5)) == 3, and only a square grid keeps cells at 9:16.
    assert "3 columns by 3 rows grid" in contract
    assert "Leave the remaining 4 grid cell(s)" in contract
    assert "never draw, frame or fill a placeholder panel" in contract
    assert "Do not use masonry, a hero panel or mixed-size frames" in contract
    assert "Do not add a title, header, footer" in contract
    assert "Never stretch, squash, crop, merge, skew" in contract
    assert "exactly one visual instance of each named character" in contract
    assert "never be duplicated or cloned inside one panel" in contract

    # Six panels used to be laid out 3 columns by 2 rows, which scales every
    # cell by rows/columns and yields 32:27 cells on a 16:9 sheet.
    six = _storyboard_panel_aspect_contract("16:9", 6)
    assert "3 columns by 3 rows grid" in six
    assert "columns by 2 rows" not in six
    assert "Leave the remaining 3 grid cell(s)" in six

    # A perfect square fills the grid, so there is no whitespace clause.
    four = _storyboard_panel_aspect_contract("16:9", 4)
    assert "2 columns by 2 rows grid" in four
    assert "Leave the remaining" not in four

    appended = _append_storyboard_panel_aspect_contract(
        "legacy storyboard prompt",
        "9:16",
    )
    assert appended.startswith("legacy storyboard prompt")
    assert appended.count("STORYBOARD PANEL ASPECT CONTRACT") == 1
    assert (
        _append_storyboard_panel_aspect_contract(appended, "9:16") == appended
    )


def test_storyboard_resolution_appends_project_panel_ratio_before_spend(
    tmp_path,
    monkeypatch,
) -> None:
    services = _services(tmp_path, monkeypatch)
    snapshot = services.projects.read(PROJECT_ID)
    snapshot.project.settings.aspect_ratio = "9:16"
    resolved = _resolve_request(
        snapshot=snapshot,
        project_root=services.projects.project_root(PROJECT_ID),
        command=CreatorCommandType.GENERATE_STORYBOARD_IMAGE,
        target_ref=f"element:{ELEMENT_ID}",
        arguments={"prompt": "legacy prompt without a panel ratio"},
    )
    assert "EVERY individual storyboard panel's inner picture frame" in (
        resolved.prompt
    )
    assert "exactly 9:16" in resolved.prompt
    assert "columns by" not in resolved.prompt
    assert "placeholder panel" not in resolved.prompt
    assert resolved.aspect_ratio == "9:16"


class _CountingProvider:
    # Safety behaviour is exercised after the model-capability preflight, so
    # this test provider must identify the documented model contract it mocks.
    model_name = "qwen-image-2.0-pro"

    def __init__(self, *, fail_with: str | None = None) -> None:
        self.calls = 0
        self._fail_with = fail_with

    async def generate(self, **_kwargs):
        self.calls += 1
        if self._fail_with is not None:
            raise RuntimeError(self._fail_with)
        return {"content": _PNG, "media_type": "image/png"}


def _services(tmp_path, monkeypatch) -> CreatorFileServices:
    return r2v_project_services(
        tmp_path,
        monkeypatch,
        project_id=PROJECT_ID,
        name="Image Resilience",
        elements=(
            make_r2v_element(
                ELEMENT_ID,
                label="并肩入场",
                description="两位球员并肩走向球场",
                narrative="两位球员并肩走向球场",
                storyboard_prompt="动画分镜：两位球员并肩入场",
            ),
        ),
    )


def _execute(services, provider, key="storyboard-key"):
    return asyncio.run(
        FileImageExecutionService(services, provider=provider).execute(
            project_id=PROJECT_ID,
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key=key,
        ),
    )


def test_transient_failure_reopens_a_retry_slot(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)

    with pytest.raises(RuntimeError, match="All connection attempts failed"):
        _execute(
            services,
            _CountingProvider(fail_with="All connection attempts failed"),
        )

    # The identical retry must run again instead of hitting the wall.
    result = _execute(services, _CountingProvider())
    assert result.replayed is False and result.artifact_version_id


def test_deterministic_rejection_keeps_the_terminal_wall(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path, monkeypatch)

    # Safety refusals surface as non-retryable ModelError.
    with pytest.raises(ModelError):
        _execute(services, _CountingProvider(fail_with=_SAFETY_MESSAGE))

    with pytest.raises(ConflictError) as caught:
        _execute(services, _CountingProvider())
    message = str(caught.value)
    assert "原失败原因" in message
    assert "rejected by the safety system" in message
    assert "调整 arguments" in message


class _MutatingImageProvider:
    """Commits a Project change mid-render: the fan-out sibling race."""

    def __init__(self, services: CreatorFileServices, mutate) -> None:
        self._services = services
        self._mutate = mutate
        self.calls = 0

    async def generate(self, **_kwargs):
        self.calls += 1
        base = self._services.projects.read(PROJECT_ID)
        candidate = base.project.model_dump(mode="json")
        self._mutate(candidate)
        self._services.commits.commit(
            base=base,
            candidate=candidate,
            origin=ChangeOrigin.RUNTIME_TASK,
            review_policy=ReviewPolicy.AUTO_FIX,
        )
        return {"content": _PNG, "media_type": "image/png"}


def test_sibling_commit_during_render_does_not_quarantine(
    tmp_path,
    monkeypatch,
) -> None:
    """An etag drift that leaves the render inputs intact still publishes."""

    services = _services(tmp_path, monkeypatch)

    def bump_description(candidate: dict) -> None:
        candidate["description"] = "sibling committed while rendering"

    result = _execute(
        services,
        _MutatingImageProvider(services, bump_description),
    )

    assert result.artifact_version_id
    finished = services.projects.read(PROJECT_ID).project
    element = finished.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ]
    assert (
        element.outputs["storyboard"].slot_id
        == f"element:{ELEMENT_ID}:storyboard"
    )


def test_redispatch_rescues_quarantined_stale_result(
    tmp_path,
    monkeypatch,
) -> None:
    """A quarantined-but-paid render is imported, not re-rendered: once
    the render inputs validate again the stored result commits (billed
    once)."""

    services = _services(tmp_path, monkeypatch)
    removed: dict = {}

    def drop_element(candidate: dict) -> None:
        timeline = candidate["timelines"]["items"]["timeline:main"]
        removed["element"] = timeline["elements_by_id"].pop(ELEMENT_ID)

    provider = _MutatingImageProvider(services, drop_element)
    with pytest.raises(ConflictError, match="结果已隔离"):
        _execute(services, provider)
    assert provider.calls == 1

    # The element comes back (same id), making the stored result valid
    # again — the shape of the fan-out incident after its inputs settle.
    base = services.projects.read(PROJECT_ID)
    candidate = base.project.model_dump(mode="json")
    timeline = candidate["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"][ELEMENT_ID] = removed["element"]
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
    )

    result = _execute(services, provider)

    assert provider.calls == 1  # no second render, no second bill
    assert result.replayed is True
    assert result.artifact_version_id


def _execute_safety(service, *, key, reference_urls=()):
    arguments = {}
    if reference_urls:
        arguments["referenceImageUrls"] = list(reference_urls)
    return asyncio.run(
        service.execute(
            project_id=PROJECT_ID,
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref=f"element:{ELEMENT_ID}",
            arguments=arguments,
            idempotency_key=key,
        ),
    )


def test_safety_rejection_blocks_verbatim_refs_until_dropped(
    tmp_path,
    monkeypatch,
):
    """The refusal names the refs it saw, resending the same refs is
    intercepted locally, and dropping them unblocks generation."""

    services = _services(tmp_path, monkeypatch)
    provider = _CountingProvider(fail_with=_SAFETY_MESSAGE)
    service = FileImageExecutionService(services, provider=provider)

    with pytest.raises(ModelError) as caught:
        _execute_safety(service, key="k1", reference_urls=[_PHOTO_URL])
    message = str(caught.value)
    assert _PHOTO_URL in message
    assert "仅修改 prompt 的重试不会成功" in message
    assert caught.value.retryable is False
    assert provider.calls == 1

    # Reworded prompt, identical refs, fresh idempotency key: the provider
    # must not be consulted again.
    with pytest.raises(ConflictError, match="已本地拦截"):
        _execute_safety(service, key="k2", reference_urls=[_PHOTO_URL])
    assert provider.calls == 1

    # Same service, refs removed: the local block must not apply.
    provider._fail_with = None  # pylint: disable=protected-access
    result = _execute_safety(service, key="k3")
    assert result.artifact_version_id
    assert provider.calls == 2


def _snapshot(*, variants: dict | None) -> ProjectSnapshot:
    now = datetime.now(timezone.utc).isoformat()
    variant_collection = variants or {"items": {}, "order": []}
    project = Project.model_validate(
        {
            "project_id": "project-naming",
            "name": "Naming",
            "created_at": now,
            "updated_at": now,
            "visual": {
                "entities": {
                    "items": {
                        "char:haaland": {
                            "entity_id": "char:haaland",
                            "kind": "character",
                            "name": "Erling Haaland (Pixar卡通版)",
                            "description": "Pixar 风格哈兰德",
                            "required_variant_ids": list(
                                variant_collection["order"],
                            ),
                            "variants": variant_collection,
                        },
                    },
                    "order": ["char:haaland"],
                },
            },
        },
    )
    return ProjectSnapshot(project=project, etag="etag-1", generation=1)


def test_generate_asset_artifact_name_includes_the_variant_id(
    tmp_path,
) -> None:
    """Stage variants have independent slots and distinguishable titles."""

    def resolve(snapshot, arguments):
        return _resolve_request(
            snapshot=snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments=arguments,
        )

    snapshot = _snapshot(
        variants={
            "items": {
                "var:haaland-rough": {
                    "variant_id": "var:haaland-rough",
                    "prompt": "rough stage design sheet",
                },
                "var:haaland-idol": {
                    "variant_id": "var:haaland-idol",
                    "prompt": "idol stage design sheet",
                },
            },
            "order": ["var:haaland-rough", "var:haaland-idol"],
        },
    )
    resolved = resolve(snapshot, {"variantId": "var:haaland-idol"})
    assert (
        resolved.artifact_name == "Erling Haaland (Pixar卡通版)（haaland-idol）视觉图"
    )
    assert resolved.variant_id == "var:haaland-idol"
    assert (
        resolved.slot_id == "asset:char:haaland:variant:var:haaland-idol:image"
    )

    with pytest.raises(ValidationError, match="必须提供 variantId"):
        resolve(snapshot, {})


def test_generate_asset_rejects_entity_description_as_paid_prompt_fallback(
    tmp_path,
) -> None:
    snapshot = _snapshot(
        variants={
            "items": {
                "var:empty": {
                    "variant_id": "var:empty",
                    "prompt": "",
                },
            },
            "order": ["var:empty"],
        },
    )

    with pytest.raises(ValidationError, match="不能作为付费生成兜底"):
        _resolve_request(
            snapshot=snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments={"variantId": "var:empty"},
        )


def _with_remote_variant_refs(
    snapshot: ProjectSnapshot,
    variant_id: str,
    count: int,
) -> ProjectSnapshot:
    candidate = snapshot.project.model_dump(mode="json")
    references = [f"ref-{index}" for index in range(1, count + 1)]
    candidate["visual"]["entities"]["items"]["char:haaland"]["variants"][
        "items"
    ][variant_id]["reference_asset_version_ids"] = references
    created_at = datetime.now(timezone.utc).isoformat()
    for version_id in references:
        url = f"https://images.example/{version_id}.png"
        candidate["assets"]["source_versions_by_id"][version_id] = {
            "version_id": version_id,
            "logical_asset_id": f"asset-{version_id}",
            "name": version_id,
            "checksum": hashlib.sha256(url.encode()).hexdigest(),
            "media_kind": "image",
            "media_type": "image/png",
            "created_at": created_at,
            "metadata": {
                "sourceKind": "remote_url",
                "checksumKind": "source_url_sha256",
                "publicSourceUrl": url,
            },
        }
    return ProjectSnapshot(
        project=Project.model_validate(candidate),
        etag="etag-budget",
        generation=1,
    )


def test_resolved_reference_budget_reports_automatic_and_explicit_refs(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot = _snapshot(
        variants={
            "items": {
                "var:budget": {
                    "variant_id": "var:budget",
                    "prompt": "budget test",
                },
            },
            "order": ["var:budget"],
        },
    )
    budget_snapshot = _with_remote_variant_refs(snapshot, "var:budget", 3)
    monkeypatch.setattr(
        image_execution,
        "_validate_public_remote_url",
        lambda value: value,
    )

    def resolve(model_name, arguments):
        return _resolve_request(
            snapshot=budget_snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments=arguments,
            image_model_name=model_name,
        )

    with pytest.raises(ImageReferenceBudgetError) as captured:
        resolve(
            "qwen-image-3.0",
            {
                "variantId": "var:budget",
                "referenceImageUrls": ["https://images.example/explicit.png"],
            },
        )

    error = captured.value
    assert error.code == "IMAGE_REFERENCE_BUDGET_EXCEEDED"
    assert error.details["limit"] == 3
    assert error.details["resolvedCount"] == 4
    assert error.details["automaticReferenceVersionIds"] == [
        "ref-1",
        "ref-2",
        "ref-3",
    ]
    assert error.details["explicitReferenceUrls"] == [
        "https://images.example/explicit.png",
    ]
    assert error.details["documentationUrl"].startswith("https://")

    openai_request = resolve("gpt-image-2", {"variantId": "var:budget"})
    assert len(openai_request.reference_image_urls) == 3

    with pytest.raises(ImageModelCapabilityError):
        resolve("private-gateway-alias", {"variantId": "var:budget"})

    with pytest.raises(ImageModelCapabilityError) as empty_model:
        resolve("", {"variantId": "var:budget"})
    assert empty_model.value.details["modelName"] == "未配置"


def test_output_moderation_refusal_is_treated_as_deterministic() -> None:
    """Field run 2026-08-26: DashScope refused a rendered character sheet with
    its own wording, which matched none of the request-level markers. The
    refusal was therefore retried against provider quota and the node stalled
    with six dependents gated behind it.
    """
    from services.media_files.image_execution import (
        _is_safety_rejection_message,
    )

    green_net = (
        "Image generation failed with status 400: Green net check failed "
        "for image (output): Output data may contain inappropriate content"
    )
    assert _is_safety_rejection_message(green_net)
    # The request-level variants must keep working.
    assert _is_safety_rejection_message(
        "Image generation failed with status 400: Your request was rejected "
        "by the safety system",
    )
    # A genuinely transient fault must not be misread as a content refusal.
    assert not _is_safety_rejection_message(
        "Image generation failed: rate limited after all retries",
    )


def test_content_refusal_error_carries_advice_not_a_config_hint() -> None:
    """A scheduler-dispatched failure never reaches the agent's tool-result
    recovery path, so the provider message itself is all the agent sees on a
    failed work-graph node. Field run 2026-08-26: it ended in "Check
    creator_image_model configuration", which points at the wrong cause and
    left twelve nodes gated behind an unfixed prompt.
    """
    from models.image.base import (
        CONTENT_REFUSAL_ADVICE,
        is_content_refusal,
    )

    green_net = (
        "Green net check failed for image (output): Output data may contain "
        "inappropriate content"
    )
    assert is_content_refusal(green_net)
    assert is_content_refusal("Your request was rejected by the safety system")
    assert not is_content_refusal("upstream timed out")
    assert not is_content_refusal("")
    # The advice has to name the remedy, not the configuration.
    assert "deterministic" in CONTENT_REFUSAL_ADVICE
    assert "Rewrite the prompt" in CONTENT_REFUSAL_ADVICE
    assert "configuration" in CONTENT_REFUSAL_ADVICE  # says it is *not* one


def test_over_budget_automatic_chain_truncates_instead_of_stalling(
    tmp_path,
    monkeypatch,
) -> None:
    """Field runs 2026-08-26: seven Elements across two projects resolved more
    automatic references than the model accepts. Every dispatch failed the
    budget check identically, so those storyboards never rendered and the
    finished timelines kept holes. Nobody wrote those lists, so keeping the
    highest-priority references beats stalling the node forever.
    """
    snapshot = _snapshot(
        variants={
            "items": {
                "var:budget": {
                    "variant_id": "var:budget",
                    "prompt": "budget test",
                },
            },
            "order": ["var:budget"],
        },
    )
    # Five automatic references against a three-reference model.
    budget_snapshot = _with_remote_variant_refs(snapshot, "var:budget", 5)
    monkeypatch.setattr(
        image_execution,
        "_validate_public_remote_url",
        lambda value: value,
    )

    resolved = _resolve_request(
        snapshot=budget_snapshot,
        project_root=Path(tmp_path),
        command=CreatorCommandType.GENERATE_ASSET,
        target_ref="asset:char:haaland",
        arguments={"variantId": "var:budget"},
        image_model_name="qwen-image-3.0",
        max_reference_images=3,
    )
    assert len(resolved.reference_version_ids) == 3
    # Priority order is preserved: the dropped tail is the least
    # identity-critical, never an arbitrary subset.
    assert list(resolved.reference_version_ids) == ["ref-1", "ref-2", "ref-3"]

    # An explicit list stays a hard error: the author named those images.
    with pytest.raises(ImageReferenceBudgetError):
        _resolve_request(
            snapshot=budget_snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments={
                "variantId": "var:budget",
                "referenceImageUrls": ["https://images.example/explicit.png"],
            },
            image_model_name="qwen-image-3.0",
            max_reference_images=3,
        )


def test_image_reference_marker_spec_follows_provider_docs() -> None:
    """Only the qwen families document addressing an input image in-prompt."""
    from models.image.base import image_reference_marker_spec

    for model in (
        "qwen-image-3.0-pro",
        "qwen-image-2.0-pro",
        "qwen-image-edit-plus",
    ):
        spec = image_reference_marker_spec(model)
        assert spec is not None, model
        assert spec.render_index(2) == "图2"
        assert "qwen-image-edit-guide" in spec.documentation_url

    # gpt-image takes many references but documents array order only, so
    # inventing a marker would be text it has no contract for.
    assert image_reference_marker_spec("gpt-image-2") is None
    assert image_reference_marker_spec("gpt-image-1") is None
    # Nothing to disambiguate at zero or one reference.
    assert image_reference_marker_spec("qwen-image") is None
    assert image_reference_marker_spec("qwen-mt-image") is None
    # Unverified families stay fail-closed rather than guessing.
    assert image_reference_marker_spec("gemini-3-pro-image") is None
    assert image_reference_marker_spec("unknown-alias") is None


def test_multi_reference_image_prompt_is_labelled_and_rendered() -> None:
    """Field gap: image prompts named none of their references, so the model
    had to infer each input's job from its pixels.
    """
    from services.media_files.image_execution import (
        _IMAGE_REFERENCE_ROLE_MARKER,
        _labelled_reference_prompt,
    )
    from services.project_files.models import ArtifactVersion

    project = Project.new(project_id="p-img", name="Img")
    for vid, name in (("art:a", "分镜图"), ("art:b", "角色视觉图")):
        project.assets.artifact_versions_by_id[vid] = ArtifactVersion(
            version_id=vid,
            slot_id=f"visual:{vid}",
            kind="visual_asset_image",
            owner_ref=f"visual:{vid}",
            name=name,
            file_id=f"file-{vid}",
            checksum="0" * 64,
            based_on_generation=1,
            created_at="2026-08-27T00:00:00Z",
        )
    ids = ["art:a", "art:b"]

    qwen = _labelled_reference_prompt(
        "画面参考 [Image 2] 的人物。",
        project,
        ids,
        image_model_name="qwen-image-3.0-pro",
        has_explicit_urls=False,
    )
    assert _IMAGE_REFERENCE_ROLE_MARKER in qwen
    assert "图1 = 分镜图" in qwen and "图2 = 角色视觉图" in qwen
    # The author's inline canonical marker is rendered by the same pass.
    assert "参考 图2 的人物" in qwen
    assert "[Image" not in qwen

    # No documented addressing: ordinal prose, never a literal [Image N].
    openai = _labelled_reference_prompt(
        "画面参考 [Image 2] 的人物。",
        project,
        ids,
        image_model_name="gpt-image-2",
        has_explicit_urls=False,
    )
    assert "第1张参考图 = 分镜图" in openai
    assert "[Image" not in openai

    # A raw URL is not version-backed, so labelling part of the payload would
    # misnumber the rest.
    assert _IMAGE_REFERENCE_ROLE_MARKER not in _labelled_reference_prompt(
        "prompt",
        project,
        ids,
        image_model_name="qwen-image-3.0-pro",
        has_explicit_urls=True,
    )
    # Nothing to disambiguate with one reference.
    assert _IMAGE_REFERENCE_ROLE_MARKER not in _labelled_reference_prompt(
        "prompt",
        project,
        ["art:a"],
        image_model_name="qwen-image-3.0-pro",
        has_explicit_urls=False,
    )
