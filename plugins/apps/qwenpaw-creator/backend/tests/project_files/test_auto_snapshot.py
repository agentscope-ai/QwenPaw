# -*- coding: utf-8 -*-
from __future__ import annotations

import copy

import pytest

from services.project_files.auto_snapshot import (
    _next_snapshot_id,
    _timeline_element_changes,
    auto_snapshot_timelines,
)

pytestmark = pytest.mark.unit

TL = "timeline:main"
ELEM = "elem:1"


def _minimal_project(
    *,
    timeline_id: str = TL,
    name: str = "主时间轴",
    elements: dict | None = None,
) -> dict:
    return {
        "timelines": {
            "items": {
                timeline_id: {
                    "timeline_id": timeline_id,
                    "name": name,
                    "description": "",
                    "ticks_per_second": 30,
                    "elements_by_id": elements or {},
                    "order": list((elements or {}).keys()),
                },
            },
            "order": [timeline_id],
        },
    }


def _element(elem_id: str, label: str = "Shot 1") -> dict:
    return {
        "element_id": elem_id,
        "label": label,
        "kind": "shot",
        "span": {"start_tick": 0, "end_tick": 30},
    }


def _elems(doc: dict, tid: str = TL) -> dict:
    return doc["timelines"]["items"][tid]["elements_by_id"]


class TestTimelineElementChanges:
    def test_no_changes(self):
        base = _minimal_project()
        candidate = copy.deepcopy(base)
        assert _timeline_element_changes(base, candidate) == set()

    def test_element_added(self):
        base = _minimal_project()
        candidate = copy.deepcopy(base)
        _elems(candidate)[ELEM] = _element(ELEM)
        assert _timeline_element_changes(base, candidate) == {TL}

    def test_element_removed(self):
        base = _minimal_project(elements={ELEM: _element(ELEM)})
        candidate = copy.deepcopy(base)
        del _elems(candidate)[ELEM]
        assert _timeline_element_changes(base, candidate) == {TL}

    def test_element_field_changed(self):
        base = _minimal_project(elements={ELEM: _element(ELEM)})
        candidate = copy.deepcopy(base)
        _elems(candidate)[ELEM]["label"] = "Updated Shot"
        assert _timeline_element_changes(base, candidate) == {TL}

    def test_name_only_change_not_detected(self):
        base = _minimal_project(elements={ELEM: _element(ELEM)})
        candidate = copy.deepcopy(base)
        candidate["timelines"]["items"][TL]["name"] = "Renamed"
        changes = _timeline_element_changes(base, candidate)
        assert TL not in changes

    def test_multiple_timelines_changed(self):
        base = _minimal_project(elements={ELEM: _element(ELEM)})
        base["timelines"]["items"]["timeline:b"] = {
            "timeline_id": "timeline:b",
            "name": "B",
            "description": "",
            "ticks_per_second": 30,
            "elements_by_id": {"elem:b1": _element("elem:b1")},
        }
        base["timelines"]["order"].append("timeline:b")

        candidate = copy.deepcopy(base)
        _elems(candidate)[ELEM]["label"] = "Changed"
        _elems(candidate, "timeline:b")["elem:b1"]["label"] = "Changed B"

        result = _timeline_element_changes(base, candidate)
        assert result == {TL, "timeline:b"}


class TestNextSnapshotId:
    def test_first_snapshot(self):
        items = {TL: {}}
        result = _next_snapshot_id(items, TL)
        assert result == "snapshot:timeline:main:1"

    def test_second_snapshot(self):
        items = {
            TL: {},
            "snapshot:timeline:main:1": {},
        }
        result = _next_snapshot_id(items, TL)
        assert result == "snapshot:timeline:main:2"

    def test_independent_per_timeline(self):
        items = {
            TL: {},
            "snapshot:timeline:main:1": {},
            "snapshot:timeline:main:2": {},
        }
        result = _next_snapshot_id(items, "timeline:b")
        assert result == "snapshot:timeline:b:1"

    def test_gap_after_deletion_never_collides(self):
        # :1 was deleted; count+1 would mint :2 again and collide.
        items = {TL: {}, "snapshot:timeline:main:2": {}}
        assert _next_snapshot_id(items, TL) == "snapshot:timeline:main:3"


class TestAutoSnapshotTimelines:
    def test_no_change_no_snapshot(self):
        base = _minimal_project(elements={ELEM: _element(ELEM)})
        candidate = copy.deepcopy(base)
        auto_snapshot_timelines(base, candidate)
        assert len(candidate["timelines"]["items"]) == 1

    def test_empty_timeline_not_snapshotted(self):
        base = _minimal_project()
        candidate = copy.deepcopy(base)
        candidate["timelines"]["items"][TL]["name"] = "Changed"
        auto_snapshot_timelines(base, candidate)
        assert len(candidate["timelines"]["items"]) == 1

    def test_element_change_creates_snapshot(self):
        base = _minimal_project(elements={ELEM: _element(ELEM)})
        candidate = copy.deepcopy(base)
        _elems(candidate)[ELEM]["label"] = "Modified"

        auto_snapshot_timelines(base, candidate)

        items = candidate["timelines"]["items"]
        assert len(items) == 2
        sid = "snapshot:timeline:main:1"
        assert sid in items
        snapshot = items[sid]
        assert snapshot["timeline_id"] == sid
        assert "快照" in snapshot["name"]
        assert "主时间轴" in snapshot["name"]
        remapped = f"{sid}:{ELEM}"
        assert remapped in snapshot["elements_by_id"]
        assert sid in candidate["timelines"]["order"]

    def test_snapshot_freezes_base_and_live_keeps_the_edit(self):
        """铁律①：用户修改的永远是 live timeline —— 快照只冻结修改前
        的底稿，绝不吞掉 candidate 的变更。"""
        base = _minimal_project(elements={ELEM: _element(ELEM)})
        candidate = copy.deepcopy(base)
        _elems(candidate)[ELEM]["label"] = "Modified"

        auto_snapshot_timelines(base, candidate)

        assert _elems(candidate)[ELEM]["label"] == "Modified"
        sid = "snapshot:timeline:main:1"
        snapshot = candidate["timelines"]["items"][sid]
        remapped = f"{sid}:{ELEM}"
        assert snapshot["elements_by_id"][remapped]["label"] == "Shot 1"

    def test_snapshot_name_never_leaks_internal_ids(self):
        base = _minimal_project(
            name="",
            elements={ELEM: _element(ELEM)},
        )
        candidate = copy.deepcopy(base)
        _elems(candidate)[ELEM]["label"] = "Modified"

        auto_snapshot_timelines(base, candidate)

        snapshot = candidate["timelines"]["items"]["snapshot:timeline:main:1"]
        assert "timeline:main" not in snapshot["name"]
        assert "时间线" in snapshot["name"]

    def _age_snapshot(self, doc: dict, sid: str) -> None:
        snapshot = doc["timelines"]["items"][sid]
        snapshot["name"] = f"{snapshot['name'][:-16]}2020-01-01 00:00"

    def test_fresh_auto_snapshot_suppresses_resnapshot(self):
        base = _minimal_project(elements={ELEM: _element(ELEM)})
        c1 = copy.deepcopy(base)
        _elems(c1)[ELEM]["label"] = "V2"
        auto_snapshot_timelines(base, c1)
        assert "snapshot:timeline:main:1" in c1["timelines"]["items"]

        # 十分钟内的第二次编辑不再重复留底。
        base2 = copy.deepcopy(c1)
        c2 = copy.deepcopy(base2)
        _elems(c2)[ELEM]["label"] = "V3"
        auto_snapshot_timelines(base2, c2)
        assert "snapshot:timeline:main:2" not in c2["timelines"]["items"]
        assert _elems(c2)[ELEM]["label"] == "V3"

    def test_multiple_snapshots_increment(self):
        base = _minimal_project(elements={ELEM: _element(ELEM)})

        c1 = copy.deepcopy(base)
        _elems(c1)[ELEM]["label"] = "V2"
        auto_snapshot_timelines(base, c1)
        assert "snapshot:timeline:main:1" in c1["timelines"]["items"]

        # 窗口外（把首个快照的时间戳做旧）再次编辑会继续编号留底。
        self._age_snapshot(c1, "snapshot:timeline:main:1")
        base2 = copy.deepcopy(c1)
        c2 = copy.deepcopy(base2)
        _elems(c2)[ELEM]["label"] = "V3"
        auto_snapshot_timelines(base2, c2)
        items = c2["timelines"]["items"]
        assert "snapshot:timeline:main:1" in items
        assert "snapshot:timeline:main:2" in items


class TestSnapshotProjectValidation:
    """Frozen snapshots must survive full Project validation.

    Snapshot copies remap element ids (and therefore their outputs'
    slot ids) without cloning the ArtifactSlots — the validator exempts
    snapshot-timeline elements from asset-reference checks, while live
    timelines keep the strict guarantees.
    """

    @staticmethod
    def _project_with_output() -> dict:
        from datetime import datetime, timezone

        from services.project_files.models import Project

        raw = Project.new(
            project_id="project-snap",
            name="Snapshot Project",
            scenario="video_edit",
            now=datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc),
        ).model_dump(mode="json")
        raw["assets"]["files_by_id"] = {
            "file-video": {
                "file_id": "file-video",
                "kind": "artifact_payload",
                "relative_uri": "assets/artifacts/element-1/main.mp4",
                "sha256": "a" * 64,
                "size_bytes": 123,
                "media_type": "video/mp4",
                "created_at": "2026-09-03T08:00:00Z",
            },
        }
        raw["assets"]["artifact_versions_by_id"] = {
            "artifact-1": {
                "version_id": "artifact-1",
                "slot_id": "element:element-1:main",
                "kind": "element_video",
                "owner_ref": "element:element-1",
                "name": "main video",
                "file_id": "file-video",
                "checksum": "a" * 64,
                "based_on_generation": 1,
                "provenance_refs": [],
                "thumbnail_file_id": None,
                "duration_seconds": 3,
                "input_fingerprint": None,
                "stale": False,
                "created_at": "2026-09-03T08:00:00Z",
                "metadata": {},
            },
        }
        raw["assets"]["artifact_slots_by_id"] = {
            "element:element-1:main": {
                "slot_id": "element:element-1:main",
                "kind": "element_video",
                "owner_ref": "element:element-1",
                "version_ids": ["artifact-1"],
                "selected_version_id": "artifact-1",
                "metadata": {},
            },
        }
        raw["timelines"]["items"]["timeline:main"]["elements_by_id"] = {
            "element-1": {
                "element_id": "element-1",
                "label": "T2V Element",
                "enabled": True,
                "span": {"start_tick": 0, "duration_tick": 3000},
                "location": None,
                "z_index": 0,
                "creation": {
                    "type": "t2v",
                    "intent": "",
                    "video_prompt": "一只猫",
                },
                "outputs": {"main": {"slot_id": "element:element-1:main"}},
                "render_source": None,
                "provenance_refs": [],
            },
        }
        return raw

    def test_snapshot_with_remapped_outputs_validates(self):
        from services.project_files.models import Project

        raw = self._project_with_output()
        Project.model_validate(raw)  # live baseline is valid

        base = copy.deepcopy(raw)
        # The candidate drops the element; the frozen base copy carries the
        # remapped slot reference under test.
        raw["timelines"]["items"]["timeline:main"]["elements_by_id"] = {}
        auto_snapshot_timelines(base, raw)
        snapshot_ids = [
            tid
            for tid in raw["timelines"]["order"]
            if tid.startswith("snapshot:")
        ]
        assert snapshot_ids, "auto snapshot must fire for element changes"
        # The snapshot's remapped slot reference has no ArtifactSlot — the
        # exemption keeps the whole Project valid regardless.
        Project.model_validate(raw)

    def test_live_timeline_keeps_strict_slot_validation(self):
        from services.project_files.models import Project

        raw = self._project_with_output()
        raw["timelines"]["items"]["timeline:main"]["elements_by_id"][
            "element-1"
        ]["outputs"]["main"]["slot_id"] = "element:missing:main"
        with pytest.raises(Exception, match="ArtifactSlot"):
            Project.model_validate(raw)
