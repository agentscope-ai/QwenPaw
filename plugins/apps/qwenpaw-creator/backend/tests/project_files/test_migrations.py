# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import pytest

from services.project_files.migrations import (
    PROJECT_MIGRATIONS,
    migrate_project_document,
)
from services.project_files.models import Project, motion_document_file_id
from services.project_files.serialization import (
    CanonicalJsonError,
    load_project_json,
)


def _raw_project() -> dict:
    return Project.new(project_id="project-1", name="Project").model_dump(
        mode="json",
    )


def _v1_project() -> dict:
    raw = _raw_project()
    raw["schema_version"] = 1
    return raw


def test_registered_migration_runs_before_strict_project_validation() -> None:
    raw = _v1_project()
    raw["schema_version"] = 0
    raw["legacy_name"] = raw.pop("name")

    def migrate_v0(document: dict) -> dict:
        document["schema_version"] = 1
        document["name"] = document.pop("legacy_name")
        return document

    def migrate_v1(document: dict) -> dict:
        document["schema_version"] = 2
        return document

    PROJECT_MIGRATIONS[0] = migrate_v0
    PROJECT_MIGRATIONS[1] = migrate_v1
    try:
        project = load_project_json(json.dumps(raw))
    finally:
        PROJECT_MIGRATIONS.pop(0, None)
        PROJECT_MIGRATIONS.pop(1, None)

    assert project.schema_version == 6
    assert project.name == "Project"
    assert project.timelines.order == ["timeline:main"]


def test_overlay_kind_is_dropped_when_migrating_from_v2() -> None:
    raw = _raw_project()
    raw["schema_version"] = 2
    timeline = raw["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"]["overlay-1"] = {
        "element_id": "overlay-1",
        "label": "宠物内心独白",
        "enabled": True,
        "span": {"start_tick": 0, "duration_tick": 100},
        "location": {
            "x": 0.5,
            "y": 0.5,
            "width": 1.0,
            "height": 1.0,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
            "rotation_degrees": 0.0,
            "opacity": 1.0,
        },
        "z_index": 10,
        "creation": {
            "type": "overlay",
            "overlay_kind": "pet_os",
            "text": "抓到你了",
            "vibe": "action",
            "prompt": "",
            "reference_version_ids": [],
            "motion": None,
        },
        "outputs": {},
        "render_source": None,
        "provenance_refs": [],
    }

    project = load_project_json(json.dumps(raw))

    assert project.schema_version == 6
    element = project.timelines.items["timeline:main"].elements_by_id[
        "overlay-1"
    ]
    creation = element.creation.model_dump(mode="json")
    assert "overlay_kind" not in creation
    assert creation["text"] == "抓到你了"
    assert creation["vibe"] == "action"


def test_interview_summary_kind_migrates_to_vibe_summary() -> None:
    raw = _raw_project()
    raw["schema_version"] = 2
    timeline = raw["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"]["overlay-2"] = {
        "element_id": "overlay-2",
        "label": "采访总结",
        "enabled": True,
        "span": {"start_tick": 0, "duration_tick": 100},
        "location": {
            "x": 0.5,
            "y": 0.5,
            "width": 1.0,
            "height": 1.0,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
            "rotation_degrees": 0.0,
            "opacity": 1.0,
        },
        "z_index": 10,
        "creation": {
            "type": "overlay",
            "overlay_kind": "interview_summary",
            "text": "本周亮点回顾",
            "vibe": "chill",
            "prompt": "",
            "reference_version_ids": [],
            "motion": None,
        },
        "outputs": {},
        "render_source": None,
        "provenance_refs": [],
    }

    project = load_project_json(json.dumps(raw))

    element = project.timelines.items["timeline:main"].elements_by_id[
        "overlay-2"
    ]
    creation = element.creation.model_dump(mode="json")
    # The interview presentation choice survives as vibe="summary": both
    # the render fallback and the frontend key interview styling off it.
    assert "overlay_kind" not in creation
    assert creation["vibe"] == "summary"


def _motion_overlay_element(motion: dict) -> dict:
    return {
        "element_id": "overlay-motion",
        "label": "装饰动效",
        "enabled": True,
        "span": {"start_tick": 0, "duration_tick": 100},
        "location": {
            "x": 0.5,
            "y": 0.5,
            "width": 0.5,
            "height": 0.5,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
            "rotation_degrees": 0.0,
            "opacity": 1.0,
        },
        "z_index": 10,
        "creation": {
            "type": "overlay",
            "text": "",
            "vibe": "chill",
            "prompt": "呼应台词的装饰动效",
            "reference_version_ids": [],
            "motion": motion,
        },
        "outputs": {},
        "render_source": None,
        "provenance_refs": [],
    }


def test_inline_html_js_motion_is_rejected_at_the_commit_boundary() -> None:
    # html_js documents must enter committed Projects only through the
    # design pipeline (probe + externalization); a hand-written inline
    # script document must fail Project validation, not compose.
    raw = _raw_project()
    timeline = raw["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"]["overlay-motion"] = _motion_overlay_element(
        {
            "format": "html_js",
            "html": (
                "<html><body><div></div>"
                "<script>window.__hf={seek:function(t){}};</script>"
                "</body></html>"
            ),
            "fps": 24,
            "loop": True,
        },
    )
    with pytest.raises(ValueError, match="inline html_js"):
        Project.model_validate(raw)
    # The serialization boundary fails closed with its uniform message.
    with pytest.raises(CanonicalJsonError):
        load_project_json(json.dumps(raw))


def test_externalized_html_js_motion_loads() -> None:
    raw = _raw_project()
    checksum = "a" * 64
    file_id = motion_document_file_id(checksum)
    raw["assets"]["files_by_id"][file_id] = {
        "file_id": file_id,
        "kind": "large_text",
        "relative_uri": f"assets/motion/{checksum}.html",
        "sha256": checksum,
        "size_bytes": 128,
        "media_type": "text/html; charset=utf-8",
        "schema_name": "motion_document",
        "schema_version": 1,
        "created_at": "2026-08-01T00:00:00Z",
    }
    timeline = raw["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"]["overlay-motion"] = _motion_overlay_element(
        {
            "format": "html_js",
            "html_file_id": file_id,
            "fps": 24,
            "loop": True,
        },
    )
    project = load_project_json(json.dumps(raw))
    element = project.timelines.items["timeline:main"].elements_by_id[
        "overlay-motion"
    ]
    assert element.creation.motion.html_file_id == file_id


def test_dangling_motion_document_reference_is_rejected() -> None:
    raw = _raw_project()
    timeline = raw["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"]["overlay-motion"] = _motion_overlay_element(
        {
            "format": "html_js",
            "html_file_id": "file-motion-abc123",
            "fps": 24,
            "loop": True,
        },
    )
    with pytest.raises(ValueError, match="does not exist"):
        Project.model_validate(raw)


def test_forged_motion_document_reference_is_rejected() -> None:
    # An IndexedFile whose id does not derive from its checksum (or whose
    # metadata does not match the design pipeline's publication shape)
    # cannot smuggle an unprobed document past the commit boundary.
    raw = _raw_project()
    checksum = "b" * 64
    raw["assets"]["files_by_id"]["file-motion-forged"] = {
        "file_id": "file-motion-forged",
        "kind": "large_text",
        "relative_uri": f"assets/motion/{checksum}.html",
        "sha256": checksum,
        "size_bytes": 128,
        "media_type": "text/html; charset=utf-8",
        "schema_name": "motion_document",
        "schema_version": 1,
        "created_at": "2026-08-01T00:00:00Z",
    }
    timeline = raw["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"]["overlay-motion"] = _motion_overlay_element(
        {
            "format": "html_js",
            "html_file_id": "file-motion-forged",
            "fps": 24,
            "loop": True,
        },
    )
    with pytest.raises(ValueError, match="content-addressed"):
        Project.model_validate(raw)


def test_non_motion_indexed_file_reference_is_rejected() -> None:
    raw = _raw_project()
    checksum = "c" * 64
    file_id = motion_document_file_id(checksum)
    raw["assets"]["files_by_id"][file_id] = {
        "file_id": file_id,
        "kind": "artifact_payload",
        "relative_uri": f"assets/artifacts/{file_id}.mp4",
        "sha256": checksum,
        "size_bytes": 128,
        "media_type": "video/mp4",
        "schema_name": None,
        "schema_version": None,
        "created_at": "2026-08-01T00:00:00Z",
    }
    timeline = raw["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"]["overlay-motion"] = _motion_overlay_element(
        {
            "format": "html_js",
            "html_file_id": file_id,
            "fps": 24,
            "loop": True,
        },
    )
    with pytest.raises(ValueError, match="content-addressed"):
        Project.model_validate(raw)


def test_inline_html_css_motion_still_loads() -> None:
    raw = _raw_project()
    timeline = raw["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"]["overlay-motion"] = _motion_overlay_element(
        {
            "format": "html_css",
            "html": (
                "<html><head><style>.a{animation:x 1s}</style></head>"
                "<body><div class='a'></div></body></html>"
            ),
            "fps": 24,
            "loop": True,
        },
    )
    project = load_project_json(json.dumps(raw))
    element = project.timelines.items["timeline:main"].elements_by_id[
        "overlay-motion"
    ]
    assert element.creation.motion.html is not None


def test_unregistered_or_future_schema_fails_closed() -> None:
    raw = _v1_project()
    raw["schema_version"] = 0
    with pytest.raises(CanonicalJsonError):
        load_project_json(json.dumps(raw))

    raw["schema_version"] = 7
    with pytest.raises(CanonicalJsonError):
        load_project_json(json.dumps(raw))


def test_migration_cannot_change_project_identity() -> None:
    raw = _v1_project()
    raw["schema_version"] = 0

    def invalid(document: dict) -> dict:
        document["schema_version"] = 1
        document["project_id"] = "different"
        return document

    PROJECT_MIGRATIONS[0] = invalid
    try:
        with pytest.raises(CanonicalJsonError):
            load_project_json(json.dumps(raw))
    finally:
        PROJECT_MIGRATIONS.pop(0, None)


def test_unregistered_v1_requires_explicit_import() -> None:
    raw = _v1_project()
    with pytest.raises(CanonicalJsonError) as caught:
        load_project_json(json.dumps(raw))
    assert "no Project migration is registered" in str(caught.value.__cause__)


def test_v3_migration_declares_existing_variants_as_required() -> None:
    raw = _raw_project()
    raw["schema_version"] = 3
    raw["visual"]["entities"] = {
        "order": ["char:hero"],
        "items": {
            "char:hero": {
                "entity_id": "char:hero",
                "kind": "character",
                "name": "Hero",
                "description": "",
                "continuity": "",
                "variants": {
                    "order": ["variant:peak", "variant:fallen"],
                    "items": {
                        "variant:peak": {"variant_id": "variant:peak"},
                        "variant:fallen": {"variant_id": "variant:fallen"},
                    },
                },
                "selected_artifact_version_id": None,
            },
        },
    }

    migrated = migrate_project_document(raw)

    # The chain continues through v4 -> v5 (overlay_kind removal).
    assert migrated["schema_version"] == 6
    assert migrated["visual"]["entities"]["items"]["char:hero"][
        "required_variant_ids"
    ] == ["variant:peak", "variant:fallen"]


def test_v2_variant_selections_and_bindings_migrate_deterministically() -> (
    None
):
    raw = _raw_project()
    raw["schema_version"] = 2
    raw["visual"]["entities"] = {
        "order": ["char:hero", "char:rival"],
        "items": {
            "char:hero": {
                "entity_id": "char:hero",
                "kind": "character",
                "name": "Hero",
                "description": "",
                "continuity": "",
                "variants": {
                    "order": ["var:peak", "var:fallen", "var:ambiguous"],
                    "items": {
                        "var:peak": {
                            "variant_id": "var:peak",
                            "requirements": "",
                            "prompt": "",
                            "reference_asset_version_ids": [],
                            "reference_artifact_version_ids": [],
                            "generated_artifact_version_ids": [
                                "artifact:peak-1",
                            ],
                        },
                        "var:fallen": {
                            "variant_id": "var:fallen",
                            "requirements": "",
                            "prompt": "",
                            "reference_asset_version_ids": [],
                            "reference_artifact_version_ids": [],
                            "generated_artifact_version_ids": [
                                "artifact:fallen-1",
                                "artifact:fallen-2",
                            ],
                        },
                        "var:ambiguous": {
                            "variant_id": "var:ambiguous",
                            "requirements": "",
                            "prompt": "",
                            "reference_asset_version_ids": [],
                            "reference_artifact_version_ids": [],
                            "generated_artifact_version_ids": [
                                "artifact:mislabeled",
                            ],
                        },
                    },
                },
                "selected_artifact_version_id": "artifact:fallen-1",
            },
            "char:rival": {
                "entity_id": "char:rival",
                "kind": "character",
                "name": "Rival",
                "description": "",
                "continuity": "",
                "variants": {
                    "order": ["var:fallen", "var:other"],
                    "items": {
                        "var:fallen": {
                            "variant_id": "var:fallen",
                            "requirements": "",
                            "prompt": "",
                            "reference_asset_version_ids": [],
                            "reference_artifact_version_ids": [],
                            "generated_artifact_version_ids": [],
                        },
                        "var:other": {
                            "variant_id": "var:other",
                            "requirements": "",
                            "prompt": "",
                            "reference_asset_version_ids": [],
                            "reference_artifact_version_ids": [],
                            "generated_artifact_version_ids": [],
                        },
                    },
                },
                "selected_artifact_version_id": None,
            },
        },
    }
    raw["assets"]["artifact_versions_by_id"] = {
        "artifact:peak-1": {
            "owner_ref": "asset:char:hero",
            "metadata": {"variantId": "var:peak"},
        },
        "artifact:fallen-1": {
            "owner_ref": "asset:char:hero",
            "metadata": {"variantId": "var:fallen"},
        },
        "artifact:fallen-2": {
            "owner_ref": "asset:char:hero",
            "metadata": {"variantId": "var:fallen"},
        },
        "artifact:mislabeled": {
            "owner_ref": "asset:char:hero",
            "metadata": {"variantId": "var:peak"},
        },
    }
    raw["timelines"]["items"]["timeline:main"]["elements_by_id"] = {
        "ep01": {
            "creation": {
                "type": "r2v",
                "character_refs": ["char:hero"],
                "scene_ref": None,
                "prop_refs": [],
                "storyboard_reference_version_ids": [
                    "artifact:fallen-1",
                ],
                "video_reference_version_ids": [],
            },
        },
        "ep02": {
            "creation": {
                "type": "r2v",
                "character_refs": ["char:rival"],
                "scene_ref": None,
                "prop_refs": [],
                "storyboard_reference_version_ids": [
                    "artifact:fallen-1",
                ],
                "video_reference_version_ids": [],
            },
        },
    }

    migrated = migrate_project_document(raw)

    hero = migrated["visual"]["entities"]["items"]["char:hero"]
    assert hero["required_variant_ids"] == [
        "var:peak",
        "var:fallen",
        "var:ambiguous",
    ]
    assert (
        hero["variants"]["items"]["var:peak"]["selected_artifact_version_id"]
        == "artifact:peak-1"
    )
    assert (
        hero["variants"]["items"]["var:fallen"]["selected_artifact_version_id"]
        == "artifact:fallen-1"
    )
    assert (
        hero["variants"]["items"]["var:ambiguous"][
            "selected_artifact_version_id"
        ]
        is None
    )
    assert hero["selected_artifact_version_id"] is None
    creation = migrated["timelines"]["items"]["timeline:main"][
        "elements_by_id"
    ]["ep01"]["creation"]
    assert creation["visual_variant_refs"] == {
        "char:hero": "var:fallen",
    }
    rival_creation = migrated["timelines"]["items"]["timeline:main"][
        "elements_by_id"
    ]["ep02"]["creation"]
    assert rival_creation["visual_variant_refs"] == {}


def test_v5_mode_tagged_r2v_creations_split_into_their_own_types() -> None:
    """v4 expressed t2v/s2v as r2v + generation_mode; v5 gives each mode its
    own creation carrying only provider inputs. The s2v "storyboard" (its
    portrait frame) becomes the declared portrait and the slot mapping is
    dropped; plain r2v elements only lose the tag."""

    from services.project_files.migrations import _migrate_v5_to_v6

    document = {
        "schema_version": 5,
        "assets": {
            "artifact_slots_by_id": {
                "slot:talk-sb": {"selected_version_id": "artifact-version-p1"},
            },
        },
        "timelines": {
            "items": {
                "timeline:main": {
                    "elements_by_id": {
                        "el:talk": {
                            "creation": {
                                "type": "r2v",
                                "generation_mode": "s2v",
                                "intent": "口播开场",
                                "character_refs": ["char:host"],
                                "video_prompt": "unused",
                                "recipe": None,
                            },
                            "outputs": {
                                "storyboard": {"slot_id": "slot:talk-sb"},
                                "main": {"slot_id": "slot:talk-main"},
                            },
                        },
                        "el:shot2": {
                            "creation": {
                                "type": "r2v",
                                "generation_mode": "t2v",
                                "intent": "灵感回归",
                                "narrative": "举起相机",
                                "continuity": "",
                                "video_prompt": "海边举起相机",
                                "recipe": None,
                            },
                            "outputs": {},
                        },
                        "el:shot1": {
                            "creation": {
                                "type": "r2v",
                                "generation_mode": "r2v",
                                "intent": "海边沉思",
                            },
                            "outputs": {},
                        },
                    },
                },
            },
        },
    }

    migrated = _migrate_v5_to_v6(document)

    talk = migrated["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "el:talk"
    ]
    assert talk["creation"] == {
        "type": "s2v",
        "intent": "口播开场",
        "character_ref": "char:host",
        "portrait_version_id": "artifact-version-p1",
        "script": "",
        "audio_version_id": None,
        "recipe": None,
    }
    assert "storyboard" not in talk["outputs"]
    assert talk["outputs"]["main"] == {"slot_id": "slot:talk-main"}

    shot2 = migrated["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "el:shot2"
    ]["creation"]
    assert shot2 == {
        "type": "t2v",
        "intent": "灵感回归",
        "narrative": "举起相机",
        "continuity": "",
        "video_prompt": "海边举起相机",
        "recipe": None,
    }

    shot1 = migrated["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "el:shot1"
    ]["creation"]
    assert shot1["type"] == "r2v"
    assert "generation_mode" not in shot1
    assert migrated["schema_version"] == 6
