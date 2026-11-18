# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import copy
import pytest


from services.project_files.edit_impact import (
    apply_frontend_edit_impacts,
    summarize_committed_edit_impact,
)


def _project() -> dict:
    return {
        "timelines": {
            "items": {
                "timeline:main": {
                    "timeline_id": "timeline:main",
                    "elements_by_id": {
                        "r2v-1": {
                            "element_id": "r2v-1",
                            "label": "R2V",
                            "span": {
                                "start_tick": 0,
                                "duration_tick": 4_000,
                            },
                            "creation": {
                                "type": "r2v",
                                "video_prompt": "old",
                                "shots": {"items": {}, "order": []},
                            },
                            "outputs": {
                                "storyboard": {
                                    "slot_id": "element:r2v-1:storyboard",
                                },
                                "video": {
                                    "slot_id": "element:r2v-1:video",
                                },
                            },
                        },
                        "overlay-1": {
                            "element_id": "overlay-1",
                            "label": "OS",
                            "span": {
                                "start_tick": 0,
                                "duration_tick": 2_000,
                            },
                            "creation": {
                                "type": "overlay",
                                "text": "old copy",
                                "prompt": "",
                                "reference_version_ids": [],
                                "motion": {
                                    "format": "html_css",
                                    "html": (
                                        "<html><head><style>"
                                        ".copy{animation:pop 1s}"
                                        "</style></head><body>"
                                        "<div class='copy'>old<br>copy</div>"
                                        "</body></html>"
                                    ),
                                },
                            },
                            "outputs": {},
                        },
                    },
                },
            },
        },
        "assets": {
            "artifact_slots_by_id": {
                "element:r2v-1:storyboard": {
                    "slot_id": "element:r2v-1:storyboard",
                    "owner_ref": "element:r2v-1",
                    "selected_version_id": "storyboard-v1",
                },
                "element:r2v-1:video": {
                    "slot_id": "element:r2v-1:video",
                    "owner_ref": "element:r2v-1",
                    "selected_version_id": "video-v1",
                },
                "timeline:timeline:main:render": {
                    "slot_id": "timeline:timeline:main:render",
                    "kind": "final_video",
                    "owner_ref": "timeline:timeline:main",
                    "selected_version_id": "final-v1",
                },
                "script:timeline:main": {
                    "slot_id": "script:timeline:main",
                    "kind": "timeline_script",
                    "owner_ref": "timeline:timeline:main",
                    "selected_version_id": "script-v1",
                },
            },
            "artifact_versions_by_id": {
                "storyboard-v1": {
                    "version_id": "storyboard-v1",
                    "owner_ref": "element:r2v-1",
                    "stale": False,
                    "stale_reason": None,
                },
                "video-v1": {
                    "version_id": "video-v1",
                    "owner_ref": "element:r2v-1",
                    "stale": False,
                    "stale_reason": None,
                },
                "final-v1": {
                    "version_id": "final-v1",
                    "owner_ref": "timeline:timeline:main",
                    "stale": False,
                    "stale_reason": None,
                },
                "script-v1": {
                    "version_id": "script-v1",
                    "kind": "timeline_script",
                    "owner_ref": "timeline:timeline:main",
                    "stale": False,
                    "stale_reason": None,
                },
            },
        },
    }


def _element_pointer(element_id: str, *suffix: str) -> str:
    return "/".join(
        (
            "",
            "timelines",
            "items",
            "timeline:main",
            "elements_by_id",
            element_id,
            *suffix,
        ),
    )


def _script_project() -> dict:
    project = _project()
    project["timelines"]["order"] = [
        "timeline:main",
        "timeline:next",
        "timeline:end",
    ]
    for timeline_id in project["timelines"]["order"]:
        timeline = project["timelines"]["items"].setdefault(
            timeline_id,
            {"timeline_id": timeline_id, "elements_by_id": {}},
        )
        timeline.update(
            title=timeline_id,
            synopsis=f"Story for {timeline_id}",
            planned_duration_seconds=300,
        )
        project["assets"]["artifact_slots_by_id"][f"script:{timeline_id}"] = {
            "kind": "timeline_script",
            "owner_ref": f"timeline:{timeline_id}",
            "selected_version_id": f"script:{timeline_id}:v1",
        }
        project["assets"]["artifact_versions_by_id"][
            f"script:{timeline_id}:v1"
        ] = {"stale": False, "stale_reason": None}
    return project


@pytest.mark.parametrize(
    ("path", "value", "invalidates"),
    [
        (("strategy", "constraints"), "所有视频不要生成字幕", False),
        (
            (
                "timelines",
                "items",
                "timeline:main",
                "planned_duration_seconds",
            ),
            142,
            False,
        ),
        (
            ("timelines", "items", "timeline:main", "synopsis"),
            "新的梗概",
            False,
        ),
        (
            ("timelines", "items", "timeline:main", "description"),
            "明确修改后的正文",
            True,
        ),
        (
            ("timelines", "items", "timeline:next", "description"),
            "其他集正文",
            False,
        ),
    ],
)
def test_authored_script_mirror_only_tracks_its_source_body(
    path,
    value,
    invalidates,
):
    base = _script_project()
    base["timelines"]["items"]["timeline:main"][
        "description"
    ] = "已经确认的正文"
    version_id = "script:timeline:main:v1"
    base["assets"]["artifact_versions_by_id"][version_id]["metadata"] = {
        "scriptSource": "timeline",
    }
    candidate = copy.deepcopy(base)
    node = candidate
    for token in path[:-1]:
        node = node.setdefault(token, {})
    node[path[-1]] = value
    updated, impact = apply_frontend_edit_impacts(
        candidate,
        ["/" + "/".join(path)],
        base=base,
    )
    assert (
        updated["assets"]["artifact_versions_by_id"][version_id]["stale"]
        is invalidates
    )
    assert (
        version_id in impact.invalidated_artifact_version_ids
    ) is invalidates


@pytest.mark.parametrize(
    ("pointer", "value"),
    [
        (_element_pointer("overlay-1", "creation", "text"), "new copy"),
        (_element_pointer("r2v-1", "creation", "video_prompt"), "new shot"),
        (_element_pointer("r2v-1", "span", "start_tick"), 1_000),
        (_element_pointer("r2v-1", "span", "duration_tick"), 5_000),
        (
            (
                "/assets/artifact_slots_by_id/element:r2v-1:video/"
                "selected_version_id"
            ),
            None,
        ),
        ("/timelines/items/timeline:main/color_grade", {"exposure": 0.2}),
    ],
)
def test_production_edits_do_not_invalidate_upstream_script(pointer, value):
    base = _script_project()
    candidate = copy.deepcopy(base)
    tokens = pointer.lstrip("/").split("/")
    node = candidate
    for token in tokens[:-1]:
        node = node[token]
    node[tokens[-1]] = value
    assert candidate != base

    updated, impact = apply_frontend_edit_impacts(
        candidate,
        [pointer],
        base=base,
    )
    versions = updated["assets"]["artifact_versions_by_id"]
    for timeline_id in base["timelines"]["order"]:
        version_id = f"script:{timeline_id}:v1"
        assert versions[version_id]["stale"] is False
        assert version_id not in impact.invalidated_artifact_version_ids
    assert versions["final-v1"]["stale"] is True


@pytest.mark.parametrize("timeline_id", ["timeline:main", "timeline:next"])
def test_duration_change_invalidates_only_own_script(timeline_id):
    base = _script_project()
    candidate = copy.deepcopy(base)
    candidate["timelines"]["items"][timeline_id][
        "planned_duration_seconds"
    ] = 142
    element = copy.deepcopy(
        base["timelines"]["items"]["timeline:main"]["elements_by_id"]["r2v-1"],
    )
    element["element_id"] = "r2v-2"
    candidate["timelines"]["items"][timeline_id]["elements_by_id"][
        "r2v-2"
    ] = element
    updated, impact = apply_frontend_edit_impacts(
        candidate,
        [
            f"/timelines/items/{timeline_id}/planned_duration_seconds",
            f"/timelines/items/{timeline_id}/elements_by_id/r2v-2",
        ],
        base=base,
    )
    versions = updated["assets"]["artifact_versions_by_id"]
    for other_id in base["timelines"]["order"]:
        assert versions[f"script:{other_id}:v1"]["stale"] is (
            other_id == timeline_id
        )
    assert (
        f"script:{timeline_id}:v1" in impact.invalidated_artifact_version_ids
    )
    assert (
        base["assets"]["artifact_versions_by_id"][f"script:{timeline_id}:v1"][
            "stale"
        ]
        is False
    )


@pytest.mark.parametrize("timeline_id", ["timeline:main", "timeline:next"])
@pytest.mark.parametrize("field", ["title", "synopsis"])
def test_live_narrative_changes_invalidate_own_and_sibling_scripts(
    timeline_id,
    field,
):
    base = _script_project()
    candidate = copy.deepcopy(base)
    candidate["timelines"]["items"][timeline_id][field] = "New story"
    updated, impact = apply_frontend_edit_impacts(
        candidate,
        [f"/timelines/items/{timeline_id}/{field}"],
        base=base,
    )
    assert impact.invalidated_artifact_version_ids == {
        f"script:{tid}:v1" for tid in base["timelines"]["order"]
    }
    assert (
        updated["assets"]["artifact_versions_by_id"]["final-v1"]["stale"]
        is False
    )


@pytest.mark.parametrize(
    ("path", "value", "invalidates"),
    [
        (("name",), "New project", True),
        (("description",), "New description", True),
        (("scenario",), "video_edit", True),
        (("strategy", "creative_brief"), "New brief", True),
        (("strategy", "audience"), "New audience", True),
        (("strategy", "creative_direction"), "New direction", True),
        (("strategy", "constraints"), "The protagonist must survive", True),
        # Every timeline overrides the project default in this fixture.
        (("settings", "target_duration_seconds"), 600, False),
        (
            ("timelines", "order"),
            ["timeline:end", "timeline:next", "timeline:main"],
            True,
        ),
    ],
)
def test_shared_story_inputs_invalidate_only_consuming_scripts(
    path,
    value,
    invalidates,
):
    base = _script_project()
    candidate = copy.deepcopy(base)
    node = candidate
    for token in path[:-1]:
        node = node.setdefault(token, {})
    node[path[-1]] = value
    _, impact = apply_frontend_edit_impacts(
        candidate,
        ["/" + "/".join(path)],
        base=base,
    )
    expected = (
        {f"script:{tid}:v1" for tid in base["timelines"]["order"]}
        if invalidates
        else set()
    )
    assert impact.invalidated_artifact_version_ids == expected


@pytest.mark.parametrize("existing_snapshot", [False, True])
def test_snapshot_history_is_excluded_from_script_inputs(existing_snapshot):
    base = _script_project()
    snapshot_id = "snapshot:timeline:main:1"
    snapshot = copy.deepcopy(base["timelines"]["items"]["timeline:main"])
    snapshot["timeline_id"] = snapshot_id
    if existing_snapshot:
        base["timelines"]["items"][snapshot_id] = copy.deepcopy(snapshot)
        base["timelines"]["order"].append(snapshot_id)
    candidate = copy.deepcopy(base)
    snapshot.update(
        title="Archived",
        synopsis="Old story",
        planned_duration_seconds=10,
    )
    candidate["timelines"]["items"][snapshot_id] = snapshot
    candidate["timelines"]["order"] = [
        snapshot_id,
        *base["timelines"]["order"][:3],
    ]
    candidate["assets"]["artifact_slots_by_id"]["snapshot-script"] = {
        "kind": "timeline_script",
        "owner_ref": f"timeline:{snapshot_id}",
        "selected_version_id": "snapshot-v1",
    }
    candidate["assets"]["artifact_versions_by_id"]["snapshot-v1"] = {
        "stale": False,
    }
    updated, impact = apply_frontend_edit_impacts(
        candidate,
        ["/timelines"],
        base=base,
    )
    assert not impact.invalidated_artifact_version_ids
    versions = updated["assets"]["artifact_versions_by_id"]
    assert all(version["stale"] is False for version in versions.values())

    candidate["timelines"]["items"]["timeline:main"]["synopsis"] = "New story"
    updated, impact = apply_frontend_edit_impacts(
        candidate,
        ["/timelines/items/timeline:main/synopsis"],
        base=base,
    )
    assert impact.invalidated_artifact_version_ids == {
        f"script:{tid}:v1" for tid in base["timelines"]["order"][:3]
    }
    versions = updated["assets"]["artifact_versions_by_id"]
    assert versions["snapshot-v1"]["stale"] is False


@pytest.mark.parametrize(
    ("path", "value", "invalidates"),
    [
        (("items", "s4", "current_intelligence_version_id"), "new", False),
        (("items", "s3", "current_intelligence_version_id"), "new", True),
        (("items", "s1", "current_intelligence_version_id"), None, True),
        (("items", "empty", "current_intelligence_version_id"), "new", True),
        (("order",), ["s1", "s2", "s3", "empty", "s4"], False),
        (("order",), ["empty", "s2", "s1", "s3", "s4"], True),
        (("order",), ["empty", "s1", "s2", "s3"], False),
    ],
)
def test_script_intelligence_uses_first_three_non_null_versions(
    path,
    value,
    invalidates,
):
    base = _script_project()
    source_ids = ["empty", "s1", "s2", "s3", "s4"]
    base["sources"] = {
        "sources": {
            "order": source_ids,
            "items": {
                sid: {
                    "current_intelligence_version_id": (
                        None if sid == "empty" else sid
                    ),
                }
                for sid in reversed(source_ids)
            },
        },
    }
    candidate = copy.deepcopy(base)
    node = candidate["sources"]["sources"]
    for token in path[:-1]:
        node = node[token]
    node[path[-1]] = value
    _, impact = apply_frontend_edit_impacts(
        candidate,
        ["/sources/sources/" + "/".join(path)],
        base=base,
    )
    expected = (
        {f"script:{tid}:v1" for tid in base["timelines"]["order"]}
        if invalidates
        else set()
    )
    assert impact.invalidated_artifact_version_ids == expected


def test_unchanged_script_inputs_preserve_existing_staleness():
    base = _script_project()
    version_id = "script:timeline:main:v1"
    base["assets"]["artifact_versions_by_id"][version_id].update(
        stale=True,
        stale_reason="Earlier story edit",
    )
    candidate = copy.deepcopy(base)
    candidate["timelines"]["items"]["timeline:next"][
        "planned_duration_seconds"
    ] = 142
    updated, impact = apply_frontend_edit_impacts(
        candidate,
        ["/timelines/items/timeline:next/planned_duration_seconds"],
        base=base,
    )
    assert updated["assets"]["artifact_versions_by_id"][version_id] == (
        base["assets"]["artifact_versions_by_id"][version_id]
    )
    assert impact.invalidated_artifact_version_ids == {
        "script:timeline:next:v1",
    }


def test_overlay_copy_edit_invalidates_only_timeline_render() -> None:
    base = _project()
    candidate = _project()
    candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "overlay-1"
    ]["creation"]["text"] = "brand new copy"
    project, impact = apply_frontend_edit_impacts(
        candidate,
        [_element_pointer("overlay-1", "creation", "text")],
        base=base,
    )

    versions = project["assets"]["artifact_versions_by_id"]
    assert versions["final-v1"]["stale"] is True
    assert versions["video-v1"]["stale"] is False
    creation = project["timelines"]["items"]["timeline:main"][
        "elements_by_id"
    ]["overlay-1"]["creation"]
    assert creation["motion"] is not None
    html = creation["motion"]["html"]
    assert ".copy{animation:pop 1s}" in html
    assert "old" not in html
    assert "brand new copy" in re.sub(r"<[^>]+>", "", html)
    assert impact.regeneration_required is False
    assert impact.render_timeline_ids == {"timeline:main"}
    assert versions["final-v1"]["metadata"]["pendingAffectedElementIds"] == [
        "overlay-1",
    ]


@pytest.mark.parametrize("mode", ["r2v", "t2v", "i2v"])
@pytest.mark.parametrize("field", ["video_prompt", "generate_audio"])
def test_video_input_invalidates_video_and_final_but_not_storyboard(
    mode,
    field,
) -> None:
    document = _project()
    document["timelines"]["items"]["timeline:main"]["elements_by_id"]["r2v-1"][
        "creation"
    ]["type"] = mode
    project, impact = apply_frontend_edit_impacts(
        document,
        [_element_pointer("r2v-1", "creation", field)],
    )

    versions = project["assets"]["artifact_versions_by_id"]
    assert versions["storyboard-v1"]["stale"] is False
    assert versions["video-v1"]["stale"] is True
    assert versions["final-v1"]["stale"] is True
    assert impact.regeneration_required is True
    assert impact.invalidated_artifact_version_ids == {"video-v1", "final-v1"}


def test_element_edits_keep_the_timeline_script_fresh() -> None:
    # The script shares ``owner_ref`` with the composed master but is drafted
    # from the story fields, not from Element content, so no Element edit may
    # obsolete it - a STALE script gates storyboard/video dispatch and its
    # re-run would overwrite the narrative written below it.
    for element_id, field_name in (
        ("r2v-1", "video_prompt"),
        ("r2v-1", "storyboard_prompt"),
        ("overlay-1", "text"),
    ):
        project, impact = apply_frontend_edit_impacts(
            _project(),
            [_element_pointer(element_id, "creation", field_name)],
        )

        versions = project["assets"]["artifact_versions_by_id"]
        assert versions["final-v1"]["stale"] is True, field_name
        assert "script-v1" not in impact.invalidated_artifact_version_ids
        assert versions["script-v1"] == {
            "version_id": "script-v1",
            "kind": "timeline_script",
            "owner_ref": "timeline:timeline:main",
            "stale": False,
            "stale_reason": None,
        }, field_name


def test_committed_impact_can_be_reconstructed_for_idempotent_replay() -> None:
    project, _ = apply_frontend_edit_impacts(
        _project(),
        [_element_pointer("r2v-1", "creation", "video_prompt")],
    )
    impact = summarize_committed_edit_impact(
        project,
        [
            _element_pointer("r2v-1", "creation", "video_prompt"),
            "/assets/artifact_versions_by_id/video-v1/stale",
            "/assets/artifact_versions_by_id/final-v1/stale",
        ],
    )

    assert impact.affected_element_ids == {"r2v-1"}
    assert impact.render_timeline_ids == {"timeline:main"}
    assert impact.invalidated_artifact_version_ids == {"video-v1", "final-v1"}
    assert impact.regeneration_required is True


def test_manual_rename_marks_the_title_as_user_supplied():
    before = _project()
    before.update(name="自动截取", name_source="auto")
    candidate = copy.deepcopy(before)
    candidate["name"] = "深夜来信"
    after, _ = apply_frontend_edit_impacts(candidate, ["/name"], base=before)
    assert after["name_source"] == "user"
    unchanged, _ = apply_frontend_edit_impacts(before, ["/description"])
    assert unchanged["name_source"] == "auto"
