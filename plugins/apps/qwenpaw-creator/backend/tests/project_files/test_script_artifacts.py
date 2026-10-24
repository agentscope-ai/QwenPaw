# -*- coding: utf-8 -*-
"""timeline_script artifact 索引辅助：槽位约定、版本追加与幂等复放。"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from services.project_files.models import Project, Timeline
from services.project_files.script_artifacts import (
    add_script_version,
    ensure_timeline_script_slot,
    script_file_relative_uri,
    timeline_script_slot_id,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 15, tzinfo=UTC)


def _project() -> Project:
    project = Project.new(project_id="p-script", name="Script")
    project.timelines.items["timeline:ep2"] = Timeline(
        timeline_id="timeline:ep2",
        title="第二集 · 旧宅疑云",
        synopsis="林晚回到旧宅，发现母亲遗物的秘密。",
    )
    project.timelines.order.append("timeline:ep2")
    return project


def _add(project: Project, text: str, *, name: str = "剧本 v1"):
    checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return add_script_version(
        project,
        "timeline:ep2",
        text,
        file_id=f"file-script-{checksum[:12]}",
        checksum=checksum,
        name=name,
        now=NOW,
        based_on_generation=1,
        provenance_refs=["asset-version:sv-novel"],
    )


def test_ensure_slot_returns_canonical_id_without_creating_empty_slot() -> (
    None
):
    project = _project()
    slot_id = ensure_timeline_script_slot(project, "timeline:ep2")
    assert slot_id == "script:timeline:ep2"
    # 空槽位违反 AssetIndex 不变量，首版本前不得出现在索引中。
    assert slot_id not in project.assets.artifact_slots_by_id


def test_ensure_slot_rejects_unknown_timeline() -> None:
    with pytest.raises(ValueError, match="timeline 不存在"):
        ensure_timeline_script_slot(_project(), "timeline:ghost")


def test_version_lifecycle_creates_slot_then_appends_and_reselects() -> None:
    project = _project()
    first = _add(project, "## 场 1 · 内景 · 旧宅大厅 · 夜\n\n开场。\n")

    slot_id = timeline_script_slot_id("timeline:ep2")
    slot = project.assets.artifact_slots_by_id[slot_id]
    assert slot.kind == "timeline_script"
    assert slot.owner_ref == "timeline:timeline:ep2"
    assert slot.version_ids == [first.version_id]
    assert slot.selected_version_id == first.version_id
    assert first.provenance_refs == ["asset-version:sv-novel"]
    indexed = project.assets.files_by_id[first.file_id]
    assert indexed.media_type == "text/markdown"
    assert indexed.relative_uri == script_file_relative_uri(first.file_id)

    second = _add(project, "修改稿。\n", name="剧本 v2")
    slot = project.assets.artifact_slots_by_id[slot_id]
    assert slot.version_ids == [first.version_id, second.version_id]
    assert slot.selected_version_id == second.version_id
    # 完整 Project 序列化往返必须通过 AssetIndex 全部校验。
    Project.model_validate(project.model_dump(mode="json"))


def test_same_content_replays_idempotently() -> None:
    project = _project()
    first = _add(project, "初稿。\n")
    _add(project, "修改稿。\n", name="剧本 v2")
    replay = _add(project, "初稿。\n")

    assert replay.version_id == first.version_id
    slot = project.assets.artifact_slots_by_id["script:timeline:ep2"]
    assert len(slot.version_ids) == 2
    # 复放只是重新选中旧版本。
    assert slot.selected_version_id == first.version_id
