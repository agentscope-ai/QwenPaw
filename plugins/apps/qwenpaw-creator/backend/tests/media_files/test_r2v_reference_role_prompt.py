# -*- coding: utf-8 -*-
"""Runtime-injected reference-image role mapping for r2v video prompts."""
from __future__ import annotations

import pytest

from services.media_files.r2v_execution import (
    _REFERENCE_ROLE_MARKER,
    _append_reference_role_mapping,
)
from services.project_files.models import (
    ArtifactVersion,
    Project,
    SourceAssetVersion,
)


pytestmark = pytest.mark.unit

_NOW = "2026-08-26T00:00:00Z"


def _project() -> Project:
    project = Project.new(project_id="p-roles", name="Roles")
    project.assets.artifact_versions_by_id["art:sb"] = ArtifactVersion(
        version_id="art:sb",
        slot_id="element:elem:1:storyboard",
        kind="r2v_storyboard_image",
        owner_ref="element:elem:1",
        name="第一镜 分镜图",
        file_id="file-sb",
        checksum="0" * 64,
        based_on_generation=1,
        created_at=_NOW,
    )
    project.assets.artifact_versions_by_id["art:ahai"] = ArtifactVersion(
        version_id="art:ahai",
        slot_id="visual:char:ahai:var:storm",
        kind="visual_asset_image",
        owner_ref="visual:char:ahai",
        name="阿海（ahai:storm）视觉图",
        file_id="file-ahai",
        checksum="1" * 64,
        based_on_generation=1,
        created_at=_NOW,
    )
    project.assets.source_versions_by_id["src:upload"] = SourceAssetVersion(
        version_id="src:upload",
        logical_asset_id="asset:upload",
        name="用户上传参考",
        file_id="file-upload",
        checksum="2" * 64,
        media_kind="image",
        media_type="image/png",
        created_at=_NOW,
    )
    return project


def test_mapping_labels_every_reference_in_payload_order(monkeypatch) -> None:
    """Numbering follows the submitted order, not the authored prompt."""
    from models import config as model_config

    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan3.0-video",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "")

    prompt = _append_reference_role_mapping(
        "阿海登上灯塔。",
        _project(),
        ["art:sb", "art:ahai", "src:upload"],
        storyboard_id="art:sb",
    )

    assert prompt.startswith("阿海登上灯塔。")
    assert _REFERENCE_ROLE_MARKER in prompt
    # The block is authored in the canonical form; _render_reference_markers
    # rewrites it to the provider's dialect at submit time.
    assert "[Image 1] = 分镜图（第一镜 分镜图）" in prompt
    assert "[Image 2] = 阿海（ahai:storm）视觉图" in prompt
    assert "[Image 3] = 用户上传参考" in prompt

    # Re-appending must not duplicate the block.
    again = _append_reference_role_mapping(
        prompt,
        _project(),
        ["art:sb", "art:ahai", "src:upload"],
        storyboard_id="art:sb",
    )
    assert again == prompt
    assert again.count(_REFERENCE_ROLE_MARKER) == 1


def test_submit_path_renders_the_block_into_each_provider_dialect(
    monkeypatch,
) -> None:
    """Canonical in the block; submit renders the provider's own form."""
    from models import config as model_config
    from services.media_files.r2v_execution import _render_reference_markers

    for model_name, backend, first in (
        ("happyhorse-video", "", "[Image 1]"),
        ("wan3.0-video", "", "图1"),
        ("doubao-seedance-2.0", "seedance2", "图片1"),
        ("kling-v2", "kling", "@image_1"),
    ):
        monkeypatch.setattr(
            model_config,
            "get_video_model_name",
            lambda name=model_name: name,
        )
        monkeypatch.setattr(
            model_config,
            "get_video_backend",
            lambda key=backend: key,
        )
        block = _append_reference_role_mapping(
            "镜头描述。",
            _project(),
            ["art:sb", "art:ahai"],
            storyboard_id="art:sb",
        )
        assert "[Image 1] = 分镜图（第一镜 分镜图）" in block
        rendered = _render_reference_markers(block)
        assert f"{first} = 分镜图（第一镜 分镜图）" in rendered


def test_structured_reference_models_get_no_invented_numbering(
    monkeypatch,
) -> None:
    """Inventing an inline index would misdescribe a structured payload."""
    from models import config as model_config

    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "some-structured-model",
    )
    monkeypatch.setattr(
        model_config,
        "get_video_backend",
        lambda: "unknown-backend",
    )

    prompt = _append_reference_role_mapping(
        "镜头描述。",
        _project(),
        ["art:sb", "art:ahai"],
        storyboard_id="art:sb",
    )
    assert prompt == "镜头描述。"
    assert _REFERENCE_ROLE_MARKER not in prompt


def test_no_references_leaves_prompt_untouched(monkeypatch) -> None:
    from models import config as model_config

    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan3.0-video",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "")

    assert (
        _append_reference_role_mapping(
            "纯文本。",
            _project(),
            [],
            storyboard_id="",
        )
        == "纯文本。"
    )
