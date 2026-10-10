# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""Cast lineup pipeline: the lineup locks relative consistency, so its
selected image must lead every reference chain and its generation must
anchor on each character's canonical variant."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.enums import CreatorCommandType
from domain.errors import ValidationError
from services.media_files.image_execution import (
    _lineup_character_reference_ids,
    _resolve_request,
)
from services.media_files.visual_design_readiness import (
    assert_visual_design_ready_for_storyboards,
    visual_design_readiness_issues,
)
from services.media_files.visual_reference_resolution import (
    resolve_r2v_visual_reference_version_ids,
)
from services.project_files.models import (
    ArtifactVersion,
    ElementLocation,
    IndexedFile,
    Project,
    R2VCreation,
    TimelineElement,
    TimelineSpan,
    VisualCastLineup,
    VisualEntity,
    VisualVariant,
)


pytestmark = pytest.mark.unit


def _entity(
    entity_id: str,
    *,
    canonical: str | None = None,
    variants: dict[str, str | None] | None = None,
) -> VisualEntity:
    items = {}
    order = []
    for variant_id, selected in (variants or {}).items():
        items[variant_id] = VisualVariant(
            variant_id=variant_id,
            selected_artifact_version_id=selected,
        )
        order.append(variant_id)
    return VisualEntity(
        entity_id=entity_id,
        kind="character",
        name=entity_id.removeprefix("char:"),
        required_variant_ids=order,
        canonical_variant_id=canonical,
        variants={"items": items, "order": order},
    )


def _project(*entities: VisualEntity) -> Project:
    project = Project.new(project_id="p-lineup", name="Lineup")
    for entity in entities:
        project.visual.entities.items[entity.entity_id] = entity
        project.visual.entities.order.append(entity.entity_id)
    return project


def _lineup(*character_refs: str, selected: str | None = None):
    return VisualCastLineup(
        lineup_id="lineup:main",
        name="主阵容",
        character_refs=list(character_refs),
        generated_artifact_version_ids=[selected] if selected else [],
        selected_artifact_version_id=selected,
        relative_notes="A:B ≈ 195:170cm",
    )


def _ab_project(*, selected: str | None = None) -> Project:
    """Two finished characters plus a registered lineup:main."""

    project = _project(
        _entity("char:a", variants={"var:x": "art:a-main"}),
        _entity("char:b", variants={"var:y": "art:b-main"}),
    )
    project.visual.cast_lineups.items["lineup:main"] = _lineup(
        "char:a",
        "char:b",
        selected=selected,
    )
    project.visual.cast_lineups.order.append("lineup:main")
    return project


def test_lineup_anchors_prefer_the_canonical_variant() -> None:
    project = _project(
        _entity(
            "char:a",
            canonical="var:master",
            variants={"var:other": "art:a-other", "var:master": "art:a-main"},
        ),
        _entity("char:b", variants={"var:solo": "art:b-main"}),
    )
    anchors, missing = _lineup_character_reference_ids(
        project,
        _lineup("char:a", "char:b"),
    )

    # char:a resolves through its canonical variant, not the first variant.
    assert anchors == ["art:a-main", "art:b-main"]
    assert not missing


def test_resolve_rejects_lineup_generation_with_unfinished_characters(
    tmp_path,
) -> None:
    project = _project(
        _entity("char:a", variants={"var:x": None}),
        _entity("char:b", variants={"var:y": "art:b-main"}),
    )
    project.visual.cast_lineups.items["lineup:main"] = _lineup(
        "char:a",
        "char:b",
    )
    project.visual.cast_lineups.order.append("lineup:main")

    with pytest.raises(ValidationError, match="char:a"):
        _resolve_request(
            # type-checked as ProjectSnapshot; only .project is consumed
            snapshot=SimpleNamespace(project=project),  # type: ignore
            project_root=tmp_path,
            command=CreatorCommandType.GENERATE_CAST_LINEUP_IMAGE,
            target_ref="lineup:lineup:main",
            arguments={},
        )


def _add_images(project: Project, *version_ids: str) -> None:
    for version_id in version_ids:
        file_id = f"file-{version_id}"
        project.assets.files_by_id[file_id] = IndexedFile(
            file_id=file_id,
            kind="artifact_payload",
            relative_uri=f"assets/artifacts/{file_id}.png",
            sha256="0" * 64,
            size_bytes=1,
            media_type="image/png",
            created_at="2026-09-09T00:00:00Z",
        )
        project.assets.artifact_versions_by_id[version_id] = ArtifactVersion(
            version_id=version_id,
            slot_id=f"asset:{version_id}",
            kind="visual_asset_image",
            name=version_id,
            owner_ref=f"asset:{version_id}",
            file_id=file_id,
            checksum="0" * 64,
            based_on_generation=1,
            created_at="2026-09-09T00:00:00Z",
            metadata={
                "provider": {
                    "source_url": f"https://example.com/{file_id}.png",
                },
            },
        )


@pytest.mark.parametrize("explicit_order", [False, True])
def test_lineup_request_preserves_seated_cast_without_extra_standing_people(
    tmp_path,
    explicit_order,
) -> None:
    project = _ab_project()
    lineup = project.visual.cast_lineups.items["lineup:main"]
    lineup.description = "两人坐在沙发上，A 左 B 右，只有 B 持茶壶。"
    _add_images(project, "art:a-main", "art:b-main")
    expected = ("art:a-main", "art:b-main")
    if explicit_order:
        expected = tuple(reversed(expected))
        lineup.reference_artifact_version_ids = list(expected)
    resolved = _resolve_request(
        snapshot=SimpleNamespace(project=project),
        project_root=tmp_path,
        command=CreatorCommandType.GENERATE_CAST_LINEUP_IMAGE,
        target_ref="lineup:lineup:main",
        arguments={},
        image_model_name="qwen-image-3.0-pro",
    )
    assert resolved.reference_version_ids == expected
    assert len(resolved.reference_image_urls) == 2
    assert lineup.description in resolved.prompt
    assert "画面总共只有 2 人" in resolved.prompt
    assert "每个角色只出现一次" in resolved.prompt
    assert "只有未指定姿态时才采用中性全身并排站姿" in resolved.prompt
    assert "所有角色全身站立并排" not in resolved.prompt


@pytest.mark.parametrize(
    "case",
    ["nested", "changed_identity", "stale", "unrelated_image"],
)
def test_four_person_lineup_reuses_existing_group_within_reference_budget(
    tmp_path,
    case,
) -> None:
    project = _project(
        *[
            _entity(f"char:{name}", variants={"var:main": f"art:{name}"})
            for name in "abcd"
        ],
    )
    lineup = _lineup(*(f"char:{name}" for name in "abcd"))
    lineup.description = "[Image 1] 提供前三人的身份，[Image 2] 提供第四人的身份。"
    lineup.reference_artifact_version_ids = ["art:abc", "art:d"]
    project.visual.cast_lineups.items[lineup.lineup_id] = lineup
    _add_images(
        project,
        "art:a",
        "art:b",
        "art:c",
        "art:d",
        "art:ab",
        "art:abc",
        "art:b-new",
    )
    versions = project.assets.artifact_versions_by_id
    for version_id, ancestors in [
        ("art:ab", ["art:a", "art:b"]),
        ("art:abc", ["art:ab", "art:c"]),
    ]:
        versions[version_id].kind = "cast_lineup_image"
        versions[version_id].provenance_refs = [
            f"artifact-version:{v}" for v in ancestors
        ]
    if case == "stale":
        versions["art:ab"].stale = True
    elif case == "unrelated_image":
        versions["art:abc"].kind = "visual_asset_image"
        lineup.description = "四人同框，各角色身份保持一致。"
    elif case == "changed_identity":
        project.visual.entities.items["char:b"].variants.items[
            "var:main"
        ].selected_artifact_version_id = "art:b-new"

    def resolve():
        return _resolve_request(
            snapshot=SimpleNamespace(project=project),
            project_root=tmp_path,
            command=CreatorCommandType.GENERATE_CAST_LINEUP_IMAGE,
            target_ref="lineup:lineup:main",
            arguments={},
            image_model_name="qwen-image-3.0-pro",
        )

    if case in {"stale", "unrelated_image"}:
        # An unrelated scene/prop image or stale nested group cannot replace
        # the missing individual identities, even if it has similar lineage.
        with pytest.raises(
            ValidationError,
            match="IMAGE_REFERENCE_BUDGET_EXCEEDED",
        ):
            resolve()
    else:
        expected = ("art:abc", "art:d")
        if case == "changed_identity":
            expected += ("art:b-new",)
        resolved = resolve()
        assert resolved.reference_version_ids == expected
        assert tuple(row["versionId"] for row in resolved.read_set) == expected
        assert len(resolved.reference_image_urls) == len(expected)
        assert not resolved.budget_dropped_version_ids


def _duo_creation() -> R2VCreation:
    return R2VCreation(
        character_refs=["char:a"],
        visual_variant_refs={"char:a": "var:x"},
        cast_lineup_refs=["lineup:main"],
    )


def test_reference_chain_leads_with_the_lineup_anchor() -> None:
    project = _ab_project(selected="art:lineup-main")

    resolved = resolve_r2v_visual_reference_version_ids(
        project,
        _duo_creation(),
        [],
    )

    assert resolved[0] == "art:lineup-main"
    assert "art:a-main" in resolved


def _add_duo_element(project: Project, *, lineup_refs: list[str]) -> None:
    project.timelines.items["timeline:main"].elements_by_id[
        "elem:duo"
    ] = TimelineElement(
        element_id="elem:duo",
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            character_refs=["char:a", "char:b"],
            visual_variant_refs={"char:a": "var:x", "char:b": "var:y"},
            cast_lineup_refs=lineup_refs,
        ),
    )


def test_storyboard_gate_blocks_declared_lineups_without_artwork() -> None:
    """Field run 2026-08-05: the specialist finished individual artwork
    and skipped the lineup entirely, so storyboards shipped without the
    group anchor. A declared cast_lineup_refs is the model's own contract
    and must hold the storyboard gate until the image exists."""
    project = _ab_project()
    _add_duo_element(project, lineup_refs=["lineup:main"])

    issues = visual_design_readiness_issues(project)
    assert [issue.code for issue in issues] == ["MISSING_CAST_LINEUP_IMAGE"]
    with pytest.raises(ValidationError, match="阵容图 lineup:main 尚未生成"):
        assert_visual_design_ready_for_storyboards(project)

    # Once the lineup image exists the same declared refs open the gate.
    drawn = _ab_project(selected="art:lineup-main")
    _add_duo_element(drawn, lineup_refs=["lineup:main"])
    assert not visual_design_readiness_issues(drawn)
