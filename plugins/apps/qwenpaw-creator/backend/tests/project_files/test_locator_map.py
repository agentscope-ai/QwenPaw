# -*- coding: utf-8 -*-

from __future__ import annotations

from services.project_files.locator_map import derive_ui_locator


def _project() -> dict:
    return {
        "assets": {
            "files_by_id": {
                "file-img": {"media_type": "image/png"},
                "file-vid": {"media_type": "video/mp4"},
            },
            "artifact_versions_by_id": {
                "ver-storyboard": {
                    "version_id": "ver-storyboard",
                    "slot_id": "element:el-1:storyboard",
                    "kind": "r2v_storyboard_image",
                    "owner_ref": "element:el-1",
                    "file_id": "file-img",
                },
                "ver-video": {
                    "version_id": "ver-video",
                    "slot_id": "element:el-1:main",
                    "kind": "r2v_video",
                    "owner_ref": "element:el-1",
                    "file_id": "file-vid",
                },
                "ver-char": {
                    "version_id": "ver-char",
                    "slot_id": "asset:char-7:image",
                    "kind": "visual_asset_image",
                    "owner_ref": "asset:char-7",
                    "file_id": "file-img",
                },
            },
            "artifact_slots_by_id": {
                "element:el-1:storyboard": {
                    "slot_id": "element:el-1:storyboard",
                    "kind": "r2v_storyboard_image",
                    "owner_ref": "element:el-1",
                    "version_ids": ["ver-storyboard"],
                    "selected_version_id": "ver-storyboard",
                },
                "element:el-1:main": {
                    "slot_id": "element:el-1:main",
                    "kind": "r2v_video",
                    "owner_ref": "element:el-1",
                    "version_ids": ["ver-video"],
                    "selected_version_id": "ver-video",
                },
                "asset:char-7:image": {
                    "slot_id": "asset:char-7:image",
                    "kind": "visual_asset_image",
                    "owner_ref": "asset:char-7",
                    "version_ids": ["ver-char"],
                    "selected_version_id": "ver-char",
                },
            },
        },
    }


def test_storyboard_version_points_to_element_workbench() -> None:
    locator = derive_ui_locator(
        "/assets/artifact_versions_by_id/ver-storyboard",
        _project(),
    )
    assert locator == {
        "page": "element",
        "elementId": "el-1",
        "mediaType": "image",
        "artifactKind": "r2v_storyboard_image",
        "artifactVersionId": "ver-storyboard",
    }


def test_video_version_is_video_media() -> None:
    locator = derive_ui_locator(
        "/assets/artifact_versions_by_id/ver-video",
        _project(),
    )
    assert locator["page"] == "element"
    assert locator["elementId"] == "el-1"
    assert locator["mediaType"] == "video"
    assert locator["artifactVersionId"] == "ver-video"


def test_character_image_points_to_asset_detail() -> None:
    locator = derive_ui_locator(
        "/assets/artifact_versions_by_id/ver-char",
        _project(),
    )
    assert locator["page"] == "assets"
    assert locator["assetId"] == "char-7"
    assert locator["mediaType"] == "image"
    assert locator["artifactKind"] == "visual_asset_image"


def test_slot_selected_version_pointer_uses_selected_version() -> None:
    locator = derive_ui_locator(
        "/assets/artifact_slots_by_id/element:el-1:main/selected_version_id",
        _project(),
    )
    assert locator["page"] == "element"
    assert locator["mediaType"] == "video"
    assert locator["artifactVersionId"] == "ver-video"


def test_file_pointer_resolves_through_owning_version() -> None:
    locator = derive_ui_locator(
        "/assets/files_by_id/file-vid",
        _project(),
    )
    assert locator["mediaType"] == "video"
    assert locator["artifactVersionId"] == "ver-video"


def test_element_text_pointer_carries_pointer_as_field() -> None:
    locator = derive_ui_locator(
        "/timelines/items/tl-1/elements_by_id/el-1/creation/video_prompt",
        _project(),
    )
    assert locator == {
        "page": "plan",
        "mediaType": "text",
        "elementId": "el-1",
        "field": (
            "/timelines/items/tl-1/elements_by_id/el-1/creation/video_prompt"
        ),
    }


def test_top_level_prose_pointer_is_plan_text() -> None:
    locator = derive_ui_locator("/description", _project())
    assert locator == {
        "page": "plan",
        "mediaType": "text",
        "field": "/description",
    }


def test_unknown_pointer_returns_empty() -> None:
    assert not derive_ui_locator(None, _project())
    assert not derive_ui_locator("", _project())
