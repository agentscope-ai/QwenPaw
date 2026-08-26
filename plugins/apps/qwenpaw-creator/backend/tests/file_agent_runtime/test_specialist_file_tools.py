# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

import pytest

from domain.enums import SpecialistRole
from services.project_files.facade import CreatorFileServices
from services.specialist_tools import FileSpecialistToolRegistry


def _names(manifest) -> set[str]:
    return {item["function"]["name"] for item in manifest}


def test_specialist_registry_owns_role_specific_media_tools(tmp_path) -> None:
    registry = FileSpecialistToolRegistry(
        CreatorFileServices.create(tmp_path.resolve()),
    )

    visual = _names(
        registry.manifest_for(
            SpecialistRole.VISUAL_DEVELOPMENT,
            admitted_target_refs=["asset:hero"],
        ),
    )
    r2v = _names(
        registry.manifest_for(
            SpecialistRole.R2V_GENERATION_DIRECTOR,
            admitted_target_refs=["element:r2v-1"],
        ),
    )
    editing = _names(
        registry.manifest_for(
            SpecialistRole.AI_EDITING_DIRECTOR,
            admitted_target_refs=["timeline:timeline:main"],
        ),
    )
    source = _names(
        registry.manifest_for(
            SpecialistRole.SOURCE_INTELLIGENCE,
            admitted_target_refs=["asset:source-1"],
        ),
    )

    assert "image_generation" in visual
    assert {"image_generation", "r2v_generation"} <= r2v
    # The editing director is a pure orchestration role: composition/export
    # is triggered directly by the user via HTTP endpoints.
    assert "ai_edit" not in editing
    assert "compose_final_video" not in editing
    assert {"read_project", "jq_project"} <= editing
    assert "transcribe_source_audio" in source
    assert "commit_source_intelligence" in source
    assert {"read_project", "read_project_file"} <= source
    assert "jq_project" not in source
    assert "elements_at" not in source
    assert "r2v_generation" not in visual
    assert "image_generation" not in editing


def test_project_assets_scope_admits_image_asset_children(tmp_path) -> None:
    registry = FileSpecialistToolRegistry(
        CreatorFileServices.create(tmp_path.resolve()),
    )
    manifest = registry.manifest_for(
        SpecialistRole.VISUAL_DEVELOPMENT,
        admitted_target_refs=["project:assets"],
    )
    tool = next(
        item
        for item in manifest
        if item["function"]["name"] == "image_generation"
    )["function"]
    target = tool["parameters"]["properties"]["targetRef"]
    image_arguments = tool["parameters"]["properties"]["arguments"]
    spec = registry.spec_for(
        SpecialistRole.VISUAL_DEVELOPMENT,
        "image_generation",
    )

    assert spec is not None
    assert "enum" not in target
    # Cast lineups joined the Project-assets scope alongside entities.
    assert target["pattern"] == r"^(asset|lineup):.+$"
    assert "不能直接使用 project:assets" in target["description"]
    assert image_arguments["properties"]["variantId"]["minLength"] == 1
    assert "多个" in image_arguments["properties"]["variantId"]["description"]
    assert spec.admits_target_ref(
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        target_ref="asset:char-cat",
        admitted_target_refs=["project:assets"],
    )
    assert not spec.admits_target_ref(
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        target_ref="project:assets",
        admitted_target_refs=["project:assets"],
    )
    assert not spec.admits_target_ref(
        role=SpecialistRole.VISUAL_DEVELOPMENT,
        target_ref="timeline:char-cat",
        admitted_target_refs=["project:assets"],
    )


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("qwen-image-3.0-pro", 3),
        ("qwen-mt-image", 1),
        ("gpt-image-2", 16),
        ("qwen-image-max", 0),
        ("private-gateway-alias", 0),
    ],
)
def test_image_manifest_uses_official_model_reference_limit(
    tmp_path,
    monkeypatch,
    model_name,
    expected,
) -> None:
    monkeypatch.setattr(
        "services.specialist_tools.get_image_model_name",
        lambda: model_name,
    )
    manifest = FileSpecialistToolRegistry(
        CreatorFileServices.create(tmp_path.resolve()),
    ).manifest_for(
        SpecialistRole.VISUAL_DEVELOPMENT,
        admitted_target_refs=["asset:hero"],
    )
    image_tool = next(
        item
        for item in manifest
        if item["function"]["name"] == "image_generation"
    )
    references = image_tool["function"]["parameters"]["properties"][
        "arguments"
    ]["properties"]["referenceVersionIds"]

    assert references["maxItems"] == expected


def test_project_assets_scope_does_not_expand_for_r2v_image_tool(
    tmp_path,
) -> None:
    registry = FileSpecialistToolRegistry(
        CreatorFileServices.create(tmp_path.resolve()),
    )
    spec = registry.spec_for(
        SpecialistRole.R2V_GENERATION_DIRECTOR,
        "image_generation",
    )

    assert spec is not None
    assert not spec.admits_target_ref(
        role=SpecialistRole.R2V_GENERATION_DIRECTOR,
        target_ref="asset:char-cat",
        admitted_target_refs=["project:assets"],
    )


def test_unique_prefix_correction_recovers_id_transcription_slips() -> None:
    # Field run 2026-08-09: the model flipped one hex run inside a
    # content-addressed asset id and the whole 18-asset delegation
    # burned on PERMISSION_DENIED. A unique long-prefix match is
    # deterministic evidence of the intended target.
    from services.specialist_tools import _unique_prefix_correction

    admitted = [
        "asset:asset-0636e4ce478c58b683df30a9966b6c34",
        "asset:asset-b0d373c89a3e54ea8344ae2ee4527e27",
        "asset:asset-f683a4e5799e56949482f6ac52a94da1",
    ]
    # The real slip observed in the run: head intact, tail corrupted.
    assert (
        _unique_prefix_correction(
            "asset:asset-0636e4ce478c58b0ab03802f6cac5204",
            admitted,
        )
        == admitted[0]
    )
    # Exact members need no correction path but resolve to themselves.
    assert _unique_prefix_correction(admitted[1], admitted) == admitted[1]
    # A short or shared-structural-prefix-only ref stays rejected: the
    # 8-extra-character requirement is measured beyond "asset:asset-".
    assert _unique_prefix_correction("asset:asset-0636", admitted) is None
    assert _unique_prefix_correction("", admitted) is None
    # Ambiguity fails closed: two admitted refs sharing the same long
    # head must never be silently disambiguated.
    twins = [
        "asset:asset-aaaaaaaabbbbbbbb1111",
        "asset:asset-aaaaaaaabbbbbbbb2222",
    ]
    assert (
        _unique_prefix_correction("asset:asset-aaaaaaaabbbbbbbb3333", twins)
        is None
    )
