# -*- coding: utf-8 -*-
"""Naming rules for GENERATE_ASSET artifact versions."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from domain.enums import CreatorCommandType
from domain.errors import ValidationError
from services.media_files.image_execution import _resolve_request
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
