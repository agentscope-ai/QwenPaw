# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest
from pydantic import ValidationError

from services.project_files import (
    CanonicalJsonError,
    Project,
    canonical_json_bytes,
    load_project_document,
    load_project_json,
    project_document_etag,
    project_etag,
    project_file_bytes,
)
from services.project_files.models import (
    ElementLocation,
    EntityCollection,
    R2VCreation,
    TimelineElement,
    TimelineSpan,
    VisualEntity,
    VisualVariant,
)


pytestmark = pytest.mark.unit


def _edit_project() -> Project:
    raw = Project.new(
        project_id="project-edit",
        name="Edit Project",
        scenario="video_edit",
        now=datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc),
    ).model_dump(mode="json")
    raw["assets"] = {
        "files_by_id": {
            "file-source": {
                "file_id": "file-source",
                "kind": "source_original",
                "relative_uri": "assets/sources/source-1/version-1/original.mp4",
                "sha256": "a" * 64,
                "size_bytes": 123,
                "media_type": "video/mp4",
                "created_at": "2026-07-15T08:00:00Z",
            },
        },
        "source_versions_by_id": {
            "source-version-1": {
                "version_id": "source-version-1",
                "logical_asset_id": "logical-source-1",
                "name": "source.mp4",
                "file_id": "file-source",
                "checksum": "a" * 64,
                "media_kind": "video",
                "media_type": "video/mp4",
                "duration_seconds": 10,
                "created_at": "2026-07-15T08:00:00Z",
            },
        },
    }
    raw["sources"] = {
        "sources": {
            "items": {
                "source-1": {
                    "source_id": "source-1",
                    "display_name": "Source",
                    "logical_asset_id": "logical-source-1",
                    "selected_asset_version_id": "source-version-1",
                },
            },
            "order": ["source-1"],
        },
    }
    raw["timelines"]["items"]["timeline:main"]["elements_by_id"] = {
        "element-1": {
            "element_id": "element-1",
            "label": "Edit Element",
            "enabled": True,
            "span": {"start_tick": 0, "duration_tick": 3000},
            "location": {},
            "z_index": 0,
            "creation": {
                "type": "edit",
                "intent": "选择素材高光",
                "reason": "素材理解确认该范围有关键动作",
                "original_sound": "preserve",
                "source_intelligence_version_id": None,
            },
            "outputs": {},
            "render_source": {
                "type": "source_asset_version",
                "version_id": "source-version-1",
                "source_in_tick": 0,
                "source_out_tick": 3000,
                "playback_rate": 1,
                "loop": False,
            },
            "provenance_refs": [],
        },
    }
    return Project.model_validate(raw)


def test_project_new_has_complete_valid_defaults_and_utc_time():
    project = Project.new(
        project_id="project-001",
        name="Project",
        now=datetime(2026, 7, 15, 16, 0, tzinfo=timezone.utc),
    )

    assert project.schema_version == 9
    assert project.generation == 0
    assert project.created_at.tzinfo == timezone.utc
    assert project.timelines.order == ["timeline:main"]
    assert project.timelines.items["timeline:main"].elements_by_id == {}
    assert project.assets.files_by_id == {}


def _variant_project() -> Project:
    project = Project.new(project_id="project-variants", name="Variants")
    project.visual.entities = EntityCollection(
        items={
            "char:hero": VisualEntity(
                entity_id="char:hero",
                kind="character",
                name="Hero",
                required_variant_ids=["variant:peak", "variant:fallen"],
                variants=EntityCollection(
                    items={
                        "variant:peak": VisualVariant(
                            variant_id="variant:peak",
                        ),
                        "variant:fallen": VisualVariant(
                            variant_id="variant:fallen",
                        ),
                    },
                    order=["variant:peak", "variant:fallen"],
                ),
            ),
        },
        order=["char:hero"],
    )
    project.timelines.items["timeline:main"].elements_by_id[
        "element:hero"
    ] = TimelineElement(
        element_id="element:hero",
        span=TimelineSpan(start_tick=0, duration_tick=1_000),
        location=ElementLocation(),
        creation=R2VCreation(
            character_refs=["char:hero"],
            visual_variant_refs={"char:hero": "variant:fallen"},
        ),
    )
    return Project.model_validate(project.model_dump(mode="json"))


def test_r2v_variant_binding_must_target_a_referenced_entity_and_variant():
    project = _variant_project()
    raw = project.model_dump(mode="json")
    creation = raw["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "element:hero"
    ]["creation"]

    creation["visual_variant_refs"] = {
        "char:hero": "variant:missing",
    }
    with pytest.raises(
        ValidationError,
        match="element element:hero: .*missing variant variant:missing",
    ):
        Project.model_validate(raw)

    creation["visual_variant_refs"] = {
        "char:other": "variant:fallen",
    }
    with pytest.raises(
        ValidationError,
        match=(
            "element element:hero: .*unreferenced entity char:other; "
            "add it to this creation's character_refs"
        ),
    ):
        Project.model_validate(raw)


def test_visual_variants_must_be_declared_in_required_variant_ids():
    with pytest.raises(
        ValidationError,
        match="must be declared in required_variant_ids",
    ):
        VisualEntity(
            entity_id="char:hero",
            kind="character",
            name="Hero",
            required_variant_ids=[],
            variants=EntityCollection(
                items={
                    "variant:peak": VisualVariant(variant_id="variant:peak"),
                },
                order=["variant:peak"],
            ),
        )


def test_canonical_serialization_is_stable_human_readable_and_round_trips():
    project = _edit_project()
    first = project_file_bytes(project)
    second = project_file_bytes(
        Project.model_validate(project.model_dump(mode="json")),
    )

    assert first == second
    assert first.endswith(b"\n")
    assert not first.startswith(b"\xef\xbb\xbf")
    assert first.index(b'"schema_version"') < first.index(b'"project_id"')
    assert load_project_json(first) == project
    assert project_etag(load_project_json(first)) == project_etag(project)


def test_legacy_document_etag_survives_in_memory_schema_migration():
    project = Project.new(
        project_id="project-legacy",
        name="Legacy",
        now=datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
    )
    project.visual.entities = EntityCollection(
        items={
            "char:hero": VisualEntity(
                entity_id="char:hero",
                kind="character",
                name="Hero",
                required_variant_ids=["variant:peak"],
                variants=EntityCollection(
                    items={
                        "variant:peak": VisualVariant(
                            variant_id="variant:peak",
                        ),
                    },
                    order=["variant:peak"],
                ),
            ),
        },
        order=["char:hero"],
    )
    raw = Project.model_validate(project.model_dump(mode="json")).model_dump(
        mode="json",
    )
    raw["schema_version"] = 3
    del raw["visual"]["entities"]["items"]["char:hero"]["required_variant_ids"]
    # Legacy documents predate the character voice field entirely.
    del raw["visual"]["entities"]["items"]["char:hero"]["voice"]

    migrated = load_project_document(raw)

    assert migrated.schema_version == 9
    assert migrated.visual.entities.items[
        "char:hero"
    ].required_variant_ids == ["variant:peak"]
    assert project_document_etag(raw, project=migrated) == (
        # Pinned against the current schema dump: bump when Project gains
        # fields, the mechanism under test is that migration-added fields
        # stay out of the source-document hash.
        "sha256:64744d1ed0c8209fb9b616e416c46f6b8f5a4dc89e56bd1de87e294dfa0d68db"
    )
    assert project_document_etag(raw, project=migrated) != project_etag(
        migrated,
    )


def test_dynamic_map_keys_are_sorted_but_business_order_is_preserved():
    value = {"z": 1, "a": 2, "order": ["z", "a"]}
    assert canonical_json_bytes(value) == b'{"a":2,"order":["z","a"],"z":1}'


def test_parser_rejects_duplicate_keys_non_object_root_and_non_finite_numbers():
    with pytest.raises(CanonicalJsonError, match="duplicate"):
        load_project_json('{"schema_version":1,"schema_version":1}')
    with pytest.raises(CanonicalJsonError, match="root"):
        load_project_json("[]")
    with pytest.raises(CanonicalJsonError, match="invalid JSON number"):
        load_project_json('{"value": NaN}')


@pytest.mark.parametrize(
    "relative_uri",
    ["assets", "../outside.bin", "/assets/file.bin", r"assets\\file.bin"],
)
def test_indexed_file_uri_must_name_a_file_below_assets(relative_uri):
    raw = _edit_project().model_dump(mode="json")
    raw["assets"]["files_by_id"]["file-source"]["relative_uri"] = relative_uri

    with pytest.raises(ValidationError, match="relative_uri"):
        Project.model_validate(raw)


def test_project_json_is_plain_json_with_no_runtime_state():
    payload = json.loads(project_file_bytes(_edit_project()))

    assert "runtime" not in payload
    assert "reviews" not in payload


def test_fabricated_artifact_slots_are_rejected():
    """Hand-written slots (unknown kind or empty shell) must not validate.

    Reproduces the 2026-08 incident: the model fabricated video slots via
    jq_project (kind ``r2v_video``, no versions) to claim completion, and
    the real pipeline write-back later collided with them.
    """

    raw = Project.new(project_id="project-1", name="Initial").model_dump(
        mode="json",
    )
    raw["assets"]["artifact_slots_by_id"]["element:el:x:main"] = {
        "slot_id": "element:el:x:main",
        "kind": "r2v_video",
        "owner_ref": "element:el:x",
        "version_ids": [],
        "selected_version_id": None,
        "metadata": {},
    }
    with pytest.raises(ValidationError, match="unknown kind"):
        Project.model_validate(raw)

    # A known kind with no versions is still an empty shell no pipeline
    # ever writes.
    raw["assets"]["artifact_slots_by_id"]["element:el:x:main"][
        "kind"
    ] = "element_video"
    with pytest.raises(ValidationError, match="no artifact"):
        Project.model_validate(raw)
