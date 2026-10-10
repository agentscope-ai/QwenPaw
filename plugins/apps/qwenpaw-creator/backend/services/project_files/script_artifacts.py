# -*- coding: utf-8 -*-
"""timeline_script artifact 的索引写入辅助（方案 2.3）。

一条 Timeline（叙事节点）的剧本是一个 ``timeline_script`` ArtifactSlot，
slot_id 约定 ``script:<timelineId>``，owner_ref ``timeline:<timelineId>``；
每个版本指向 AssetIndex 中的一个 markdown 文件，由此免费获得多版本、
selected、stale、provenance、Review 的全套既有机制。

本模块只维护 **索引对象**（ArtifactSlot / ArtifactVersion / IndexedFile
条目）；markdown 文件本体的落盘由调用方（agent 工具 / 执行服务）通过
AssetFileStore 完成，落盘路径必须与 :func:`script_file_relative_uri`
一致，否则 AssetIndex 校验会在提交时拒绝。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Sequence
from uuid import NAMESPACE_URL, uuid5

from .models import (
    ArtifactSlot,
    ArtifactVersion,
    IndexedFile,
    Project,
)

SCRIPT_SLOT_KIND = "timeline_script"
SCRIPT_MEDIA_TYPE = "text/markdown"


def timeline_script_slot_id(timeline_id: str) -> str:
    """剧本槽位的约定 ID：``script:<timelineId>``。"""

    return f"script:{timeline_id}"


def timeline_script_owner_ref(timeline_id: str) -> str:
    return f"timeline:{timeline_id}"


def script_file_relative_uri(file_id: str) -> str:
    """剧本 markdown 文件在 Project assets 目录下的约定路径。"""

    return PurePosixPath("assets", "artifacts", f"{file_id}.md").as_posix()


def script_version_id(timeline_id: str, checksum: str) -> str:
    """内容寻址的版本 ID：同一 timeline 的同一内容不会重复建版本。"""

    digest = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:timeline-script:{timeline_id}:{checksum}",
    ).hex
    return f"artifact-script-{digest}"


def ensure_timeline_script_slot(project: Project, timeline_id: str) -> str:
    """返回该 timeline 的剧本 slot_id，并校验既有槽位归属。

    注意：AssetIndex 不允许存在没有版本的空槽位（空槽只能来自伪造的
    jq 变换），所以本函数在槽位缺失时**不插入空槽**——首个版本由
    :func:`add_script_version` 连同槽位一起创建。这里只负责：
    - 校验 timeline 存在；
    - 若槽位已存在，校验 kind / owner_ref 归属一致；
    - 返回约定 slot_id。
    """

    if timeline_id not in project.timelines.items:
        raise ValueError(f"timeline 不存在: {timeline_id}")
    slot_id = timeline_script_slot_id(timeline_id)
    slot = project.assets.artifact_slots_by_id.get(slot_id)
    if slot is not None and (
        slot.kind != SCRIPT_SLOT_KIND
        or slot.owner_ref != timeline_script_owner_ref(timeline_id)
    ):
        raise ValueError(f"剧本槽位 {slot_id} 归属冲突（kind/owner_ref 不匹配）")
    return slot_id


def add_script_version(
    project: Project,
    timeline_id: str,
    markdown_text: str,
    *,
    file_id: str,
    checksum: str,
    name: str,
    now: datetime,
    based_on_generation: int,
    provenance_refs: Sequence[str] = (),
    input_fingerprint: str | None = None,
) -> ArtifactVersion:
    """把一个剧本版本追加进 slot 并设为 selected，返回该版本。

    只维护索引：IndexedFile 条目按 ``markdown_text`` 计算 size，
    调用方必须把 UTF-8 字节以 ``checksum`` 为内容、
    :func:`script_file_relative_uri` 为路径落盘。
    同 (timeline, checksum) 重复调用是幂等的 select 复放。
    """

    slot_id = ensure_timeline_script_slot(project, timeline_id)
    version_id = script_version_id(timeline_id, checksum)
    existing = project.assets.artifact_versions_by_id.get(version_id)
    slot = project.assets.artifact_slots_by_id.get(slot_id)
    if existing is not None and slot is not None:
        # 内容寻址复放：重新选中即可，不追加重复版本。
        slot.selected_version_id = version_id
        return existing

    content = markdown_text.encode("utf-8")
    if file_id not in project.assets.files_by_id:
        project.assets.files_by_id[file_id] = IndexedFile(
            file_id=file_id,
            kind="artifact_payload",
            relative_uri=script_file_relative_uri(file_id),
            sha256=checksum,
            size_bytes=len(content),
            media_type=SCRIPT_MEDIA_TYPE,
            created_at=now,
        )
    version = ArtifactVersion(
        version_id=version_id,
        slot_id=slot_id,
        kind=SCRIPT_SLOT_KIND,
        owner_ref=timeline_script_owner_ref(timeline_id),
        name=name,
        file_id=file_id,
        checksum=checksum,
        based_on_generation=based_on_generation,
        provenance_refs=list(provenance_refs),
        input_fingerprint=input_fingerprint,
        created_at=now,
    )
    project.assets.artifact_versions_by_id[version_id] = version
    if slot is None:
        project.assets.artifact_slots_by_id[slot_id] = ArtifactSlot(
            slot_id=slot_id,
            kind=SCRIPT_SLOT_KIND,
            owner_ref=timeline_script_owner_ref(timeline_id),
            version_ids=[version_id],
            selected_version_id=version_id,
        )
    else:
        if version_id not in slot.version_ids:
            slot.version_ids = [*slot.version_ids, version_id]
        slot.selected_version_id = version_id
    return version


__all__ = [
    "SCRIPT_MEDIA_TYPE",
    "SCRIPT_SLOT_KIND",
    "add_script_version",
    "ensure_timeline_script_slot",
    "script_file_relative_uri",
    "script_version_id",
    "timeline_script_owner_ref",
    "timeline_script_slot_id",
]
