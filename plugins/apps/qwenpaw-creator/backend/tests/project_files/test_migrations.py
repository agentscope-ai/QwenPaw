# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import pytest

from services.project_files.migrations import (
    PROJECT_MIGRATIONS,
    _migrate_v5_to_v6,
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


def _overlay_element(creation: dict, element_id: str = "overlay-1") -> dict:
    base = {"type": "overlay", "text": "", "vibe": "chill", "prompt": ""}
    base.update(reference_version_ids=[], motion=None)
    return {
        "element_id": element_id,
        "span": {"start_tick": 0, "duration_tick": 100},
        "location": {},
        "creation": {**base, **creation},
    }


def _motion_element(motion: dict) -> dict:
    creation = {"prompt": "呼应台词的装饰动效", "motion": motion}
    return _overlay_element(creation, element_id="overlay-motion")


def _install(raw: dict, element: dict) -> None:
    timeline = raw["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"][element["element_id"]] = element


def _element(project: Project, element_id: str):
    timeline = project.timelines.items["timeline:main"]
    return timeline.elements_by_id[element_id]


def test_overlay_kind_is_dropped_when_migrating_from_v2() -> None:
    raw = _raw_project()
    raw["schema_version"] = 2
    # The interview presentation choice survives as vibe="summary": both
    # the render fallback and the frontend key interview styling off it.
    creation = {
        "overlay_kind": "interview_summary",
        "text": "抓到你了",
        "vibe": "chill",
    }
    _install(raw, _overlay_element(creation))

    project = load_project_json(json.dumps(raw))

    assert project.schema_version == 9
    creation = _element(project, "overlay-1").creation.model_dump(mode="json")
    assert "overlay_kind" not in creation
    assert creation["text"] == "抓到你了"
    assert creation["vibe"] == "summary"


def test_inline_html_js_motion_is_rejected_at_the_commit_boundary() -> None:
    # html_js documents must enter committed Projects only through the
    # design pipeline (probe + externalization); a hand-written inline
    # script document must fail Project validation, not compose.
    raw = _raw_project()
    html = (
        "<html><body><div></div>"
        "<script>window.__hf={seek:function(t){}};</script>"
        "</body></html>"
    )
    motion = {"format": "html_js", "html": html, "fps": 24, "loop": True}
    _install(raw, _motion_element(motion))
    with pytest.raises(ValueError, match="inline html_js"):
        Project.model_validate(raw)
    # The serialization boundary fails closed with its uniform message.
    with pytest.raises(CanonicalJsonError):
        load_project_json(json.dumps(raw))


def _indexed_file(file_id: str, checksum: str, **overrides) -> dict:
    entry = {
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
    entry.update(overrides)
    return entry


def _html_js_ref(file_id: str) -> dict:
    motion = {"format": "html_js", "fps": 24, "loop": True}
    motion["html_file_id"] = file_id
    return motion


def test_externalized_html_js_motion_loads() -> None:
    checksum = "a" * 64
    file_id = motion_document_file_id(checksum)
    raw = _raw_project()
    raw["assets"]["files_by_id"][file_id] = _indexed_file(file_id, checksum)
    _install(raw, _motion_element(_html_js_ref(file_id)))
    project = load_project_json(json.dumps(raw))
    motion = _element(project, "overlay-motion").creation.motion
    assert motion.html_file_id == file_id


def test_invalid_motion_document_reference_is_rejected() -> None:
    # An IndexedFile whose id does not derive from its checksum (or whose
    # metadata does not match the design pipeline's publication shape)
    # cannot smuggle an unprobed document past the commit boundary.
    raw = _raw_project()
    raw["assets"]["files_by_id"]["file-motion-forged"] = _indexed_file(
        "file-motion-forged",
        "b" * 64,
    )
    _install(raw, _motion_element(_html_js_ref("file-motion-forged")))
    with pytest.raises(ValueError, match="content-addressed"):
        Project.model_validate(raw)


def test_unregistered_or_future_schema_fails_closed() -> None:
    raw = _v1_project()
    # v1 without a registered migration requires an explicit import step.
    with pytest.raises(CanonicalJsonError) as caught:
        load_project_json(json.dumps(raw))
    assert "no Project migration is registered" in str(caught.value.__cause__)

    for version in (0, 10):
        raw["schema_version"] = version
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


def _variant(variant_id: str, *generated: str) -> dict:
    return {
        "variant_id": variant_id,
        "requirements": "",
        "prompt": "",
        "reference_asset_version_ids": [],
        "reference_artifact_version_ids": [],
        "generated_artifact_version_ids": list(generated),
    }


def _entity(entity_id: str, name: str, variants: list) -> dict:
    return {
        "entity_id": entity_id,
        "kind": "character",
        "name": name,
        "description": "",
        "continuity": "",
        "variants": {
            "order": [v["variant_id"] for v in variants],
            "items": {v["variant_id"]: v for v in variants},
        },
        "selected_artifact_version_id": None,
    }


def _artifact(variant_id: str) -> dict:
    return {
        "owner_ref": "asset:char:hero",
        "metadata": {"variantId": variant_id},
    }


def _r2v_ref(character_ref: str) -> dict:
    creation = {
        "type": "r2v",
        "character_refs": [character_ref],
        "scene_ref": None,
        "prop_refs": [],
        "storyboard_reference_version_ids": ["artifact:fallen-1"],
        "video_reference_version_ids": [],
    }
    return {"creation": creation}


def test_v3_migration_declares_existing_variants_as_required() -> None:
    raw = _raw_project()
    raw["schema_version"] = 3
    peak = {"variant_id": "variant:peak"}
    fallen = {"variant_id": "variant:fallen"}
    hero = _entity("char:hero", "Hero", [peak, fallen])
    raw["visual"]["entities"] = {
        "order": ["char:hero"],
        "items": {"char:hero": hero},
    }

    migrated = migrate_project_document(raw)

    # The chain continues through v4 -> v5 (overlay_kind removal).
    assert migrated["schema_version"] == 9
    assert migrated["visual"]["entities"]["items"]["char:hero"][
        "required_variant_ids"
    ] == ["variant:peak", "variant:fallen"]


def test_v2_variant_selections_and_bindings_migrate_deterministically() -> (
    None
):
    raw = _raw_project()
    raw["schema_version"] = 2
    peak = _variant("var:peak", "artifact:peak-1")
    fallen = _variant("var:fallen", "artifact:fallen-1", "artifact:fallen-2")
    ambiguous = _variant("var:ambiguous", "artifact:mislabeled")
    hero = _entity("char:hero", "Hero", [peak, fallen, ambiguous])
    hero["selected_artifact_version_id"] = "artifact:fallen-1"
    raw["visual"]["entities"] = {
        "order": ["char:hero"],
        "items": {"char:hero": hero},
    }
    raw["assets"]["artifact_versions_by_id"] = {
        "artifact:peak-1": _artifact("var:peak"),
        "artifact:fallen-1": _artifact("var:fallen"),
        "artifact:fallen-2": _artifact("var:fallen"),
        # Mislabeled: listed under var:ambiguous but tagged var:peak.
        "artifact:mislabeled": _artifact("var:peak"),
    }
    raw["timelines"]["items"]["timeline:main"]["elements_by_id"] = {
        "ep01": _r2v_ref("char:hero"),
    }

    migrated = migrate_project_document(raw)

    hero = migrated["visual"]["entities"]["items"]["char:hero"]
    required = ["var:peak", "var:fallen", "var:ambiguous"]
    assert hero["required_variant_ids"] == required
    variants = hero["variants"]["items"]
    assert variants["var:peak"]["selected_artifact_version_id"] == (
        "artifact:peak-1"
    )
    assert variants["var:fallen"]["selected_artifact_version_id"] == (
        "artifact:fallen-1"
    )
    assert variants["var:ambiguous"]["selected_artifact_version_id"] is None
    assert hero["selected_artifact_version_id"] is None
    timeline = migrated["timelines"]["items"]["timeline:main"]
    elements = timeline["elements_by_id"]
    ep01_refs = elements["ep01"]["creation"]["visual_variant_refs"]
    assert ep01_refs == {"char:hero": "var:fallen"}


def test_v5_mode_tagged_r2v_creations_split_into_their_own_types() -> None:
    """v4 expressed t2v/s2v as r2v + generation_mode; v5 gives each mode its
    own creation carrying only provider inputs; the s2v storyboard frame
    becomes the declared portrait and its slot mapping is dropped."""

    talk_creation = {
        "type": "r2v",
        "generation_mode": "s2v",
        "intent": "口播开场",
        "character_refs": ["char:host"],
        "video_prompt": "unused",
        "recipe": None,
    }
    shot2_creation = {
        "type": "r2v",
        "generation_mode": "t2v",
        "intent": "灵感回归",
        "narrative": "举起相机",
        "continuity": "",
        "video_prompt": "海边举起相机",
        "recipe": None,
    }
    slots = {"slot:talk-sb": {"selected_version_id": "artifact-version-p1"}}
    document = {
        "schema_version": 5,
        "assets": {"artifact_slots_by_id": slots},
        "timelines": {
            "items": {
                "timeline:main": {
                    "elements_by_id": {
                        "el:talk": {
                            "creation": talk_creation,
                            "outputs": {
                                "storyboard": {"slot_id": "slot:talk-sb"},
                                "main": {"slot_id": "slot:talk-main"},
                            },
                        },
                        "el:shot2": {
                            "creation": shot2_creation,
                            "outputs": {},
                        },
                    },
                },
            },
        },
    }

    # t2v keeps every provider input and only sheds the mode tag. The
    # migration mutates in place, so snapshot the expectation up front.
    expected_shot2 = {**shot2_creation, "type": "t2v"}
    expected_shot2.pop("generation_mode")

    migrated = _migrate_v5_to_v6(document)

    timeline = migrated["timelines"]["items"]["timeline:main"]
    elements = timeline["elements_by_id"]
    talk = elements["el:talk"]
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

    assert elements["el:shot2"]["creation"] == expected_shot2
    assert migrated["schema_version"] == 6


def test_v6_and_v7_migrations_add_edit_plan_and_clear_color_grade() -> None:
    raw = _raw_project()
    raw["schema_version"] = 6
    for timeline in raw["timelines"]["items"].values():
        timeline.pop("edit_plan", None)
        timeline["color_grade"] = "明亮温暖清新：自由文本描述"

    migrated = migrate_project_document(raw)

    assert migrated["schema_version"] == 9
    for timeline in migrated["timelines"]["items"].values():
        assert timeline["edit_plan"] is None
        assert timeline["color_grade"] == ""
