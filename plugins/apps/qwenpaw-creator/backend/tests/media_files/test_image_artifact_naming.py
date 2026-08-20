# -*- coding: utf-8 -*-
"""Naming rules for GENERATE_ASSET artifact versions."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pytest

from domain.enums import CreatorCommandType
from domain.errors import ValidationError
from services.media_files import image_execution
from services.media_files.image_execution import (
    ImageModelCapabilityError,
    ImageReferenceBudgetError,
    _resolve_request,
)
from services.project_files.models import Project
from services.project_files.store import ProjectSnapshot


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


def test_generate_asset_artifact_name_includes_the_variant_id(
    tmp_path,
) -> None:
    """Stage variants have independent slots and distinguishable titles."""

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
    resolved = _resolve_request(
        snapshot=snapshot,
        project_root=Path(tmp_path),
        command=CreatorCommandType.GENERATE_ASSET,
        target_ref="asset:char:haaland",
        arguments={"variantId": "var:haaland-idol"},
    )
    assert resolved.artifact_name == (
        "Erling Haaland (Pixar卡通版)（haaland-idol）视觉图"
    )
    assert resolved.variant_id == "var:haaland-idol"
    assert resolved.slot_id == (
        "asset:char:haaland:variant:var:haaland-idol:image"
    )

    with pytest.raises(ValidationError, match="必须提供 variantId"):
        _resolve_request(
            snapshot=snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments={},
        )
    with pytest.raises(ValidationError, match="variantId 必须是字符串"):
        _resolve_request(
            snapshot=snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments={"variantId": 1},
        )

    compatibility = _resolve_request(
        snapshot=snapshot,
        project_root=Path(tmp_path),
        command=CreatorCommandType.GENERATE_ASSET,
        target_ref="asset:char:haaland",
        arguments={"promptIndex": 0},
    )
    assert compatibility.variant_id == "var:haaland-rough"


def test_generate_asset_artifact_name_without_variants_keeps_plain_title(
    tmp_path,
) -> None:
    snapshot = _snapshot(variants=None)
    resolved = _resolve_request(
        snapshot=snapshot,
        project_root=Path(tmp_path),
        command=CreatorCommandType.GENERATE_ASSET,
        target_ref="asset:char:haaland",
        arguments={"prompt": "explicit prompt"},
    )
    assert resolved.artifact_name == "Erling Haaland (Pixar卡通版) 视觉图"
    assert resolved.variant_id is None


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

    with pytest.raises(ImageReferenceBudgetError) as captured:
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

    openai_request = _resolve_request(
        snapshot=budget_snapshot,
        project_root=Path(tmp_path),
        command=CreatorCommandType.GENERATE_ASSET,
        target_ref="asset:char:haaland",
        arguments={"variantId": "var:budget"},
        image_model_name="gpt-image-2",
    )
    assert len(openai_request.reference_image_urls) == 3

    with pytest.raises(ImageModelCapabilityError):
        _resolve_request(
            snapshot=budget_snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments={"variantId": "var:budget"},
            image_model_name="private-gateway-alias",
        )

    with pytest.raises(ImageModelCapabilityError) as empty_model:
        _resolve_request(
            snapshot=budget_snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments={"variantId": "var:budget"},
            image_model_name="",
        )
    assert empty_model.value.details["modelName"] == "未配置"
