# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Canonical storyboard references: preview, resolution and payload agree.

All references below are synthetic. No network or real provider is used.
"""

from __future__ import annotations

import hashlib

import pytest

from domain.enums import CreatorCommandType
from domain.errors import ValidationError
from services.media_files.image_execution import _resolve_request
from services.media_files.visual_reference_resolution import (
    preview_r2v_reference_order,
)
from services.project_files.models import Project, SourceAssetVersion
from services.project_files.store import ProjectSnapshot

from .conftest import make_r2v_element

pytestmark = pytest.mark.unit


def _snapshot(
    prompt="[Image 2] 的人物站在 [Image 1] 的场景，拿 [Image 3] 的道具。",
):
    project = Project.new(
        project_id="image-ref-contract",
        name="Reference contract",
    )
    element = make_r2v_element("shot:one", storyboard_prompt=prompt)
    project.timelines.items["timeline:main"].elements_by_id[
        element.element_id
    ] = element
    # Exact IDs deliberately do not sort into their semantic/input order.
    ids = ["src:z-scene", "src:a-person", "src:m-prop"]
    for index, version_id in enumerate(ids):
        # Two different exact versions deliberately share a transport URL.
        url = f"https://images.example/{'shared' if index < 2 else 'prop'}.png"
        project.assets.source_versions_by_id[version_id] = SourceAssetVersion(
            version_id=version_id,
            logical_asset_id=f"asset:{version_id}",
            name=["公寓", "女子", "钥匙"][index],
            checksum=hashlib.sha256(url.encode()).hexdigest(),
            media_kind="image",
            media_type="image/png",
            created_at=project.created_at,
            metadata={
                "sourceKind": "remote_url",
                "checksumKind": "source_url_sha256",
                "publicSourceUrl": url,
            },
        )
    element.creation.storyboard_reference_version_ids = ids
    # A different video sequence must never contaminate storyboard preview.
    element.creation.video_reference_version_ids = list(reversed(ids))
    return ProjectSnapshot(project=project, etag="fixture-etag", generation=1)


def _resolve(snapshot, tmp_path, model="qwen-image-3.0-pro"):
    return _resolve_request(
        snapshot=snapshot,
        project_root=tmp_path,
        command=CreatorCommandType.GENERATE_STORYBOARD_IMAGE,
        target_ref="element:shot:one",
        arguments={},
        image_model_name=model,
    )


def test_actual_resolver_matches_phase_preview_and_provider_wording(
    tmp_path,
):
    snapshot = _snapshot()
    model = "qwen-image-3.0-pro"
    preview = preview_r2v_reference_order(
        snapshot.project,
        "shot:one",
        stage="storyboard",
        image_model_name=model,
        project_root=tmp_path,
    )
    request = _resolve(snapshot, tmp_path, model)
    assert preview["ready"]
    assert [ref["versionId"] for ref in preview["references"]] == list(
        request.reference_version_ids,
    )
    assert len(request.reference_image_urls) == 3
    assert request.reference_image_urls[0] == request.reference_image_urls[1]
    assert "图2 的人物" in request.prompt
    assert "[Image" not in request.prompt


def test_invalid_indices_are_visible_and_rejected_before_provider(
    tmp_path,
):
    snapshot = _snapshot("采用 [Image 4] 的人物。")
    preview = preview_r2v_reference_order(
        snapshot.project,
        "shot:one",
        stage="storyboard",
        image_model_name="qwen-image-3.0-pro",
        project_root=tmp_path,
    )
    assert preview["invalidMarkerIndices"] == [4]
    assert preview["ready"] is False
    with pytest.raises(ValidationError, match="参考图编号"):
        _resolve(snapshot, tmp_path)


def test_layout_accepts_frame_classifiers_without_guessing_conflicts():
    from services.storyboard_layout import declared_storyboard_panel_count

    assert declared_storyboard_panel_count("1 张关键帧") == 1
    assert declared_storyboard_panel_count("共 8 格分镜面板") == 8
    assert declared_storyboard_panel_count("4个关键帧，9个分镜格") is None
