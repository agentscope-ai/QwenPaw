# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-branches,too-many-statements
"""Authoritative validation for direct Source Intelligence analysis versions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from domain.errors import StorageIntegrityError
from domain.refs import workspace_asset_ref
from services.media.source_intelligence import parse_source_intelligence_files

from .workspace_refs import analysis_authority_from_source_run


def validated_source_analysis_versions(
    *,
    run_id: str,
    status: str,
    target_refs: Sequence[str],
    read_set: Sequence[Mapping[str, Any]],
    run_metadata: Mapping[str, Any],
    assets_by_version: Mapping[str, Mapping[str, Any]],
    workspace_texts: Mapping[str, str],
) -> frozenset[str]:
    """Return exact AssetVersion ids authorized by one successful Source Run.

    Authority is fail-closed and independent from the ref currently being
    checked.  It combines the Runtime-owned native-media read-set with the
    the immutable, fully parsed version directory.  ``selected-version.ref``
    and ``current.ref`` are mutable selections: SourceTerminalGuard checks them
    at publication time, but moving either selection later must not invalidate
    an older exact analysis ref.
    """

    asset_logical = {
        str(version_id): str(row.get("logical_asset_id") or "")
        for version_id, row in assets_by_version.items()
    }
    candidates = analysis_authority_from_source_run(
        status,
        target_refs,
        read_set,
        asset_logical,
    )[1]
    if status != "SUCCEEDED":
        return frozenset()
    if len(candidates) != 1:
        raise StorageIntegrityError(
            "Source Intelligence Run 必须绑定唯一 Runtime-observed AssetVersion",
        )
    version_id = next(iter(candidates))
    asset = assets_by_version.get(version_id)
    if asset is None:
        raise StorageIntegrityError(
            "Source Intelligence AssetVersion authority 丢失",
        )
    logical_id = str(asset.get("logical_asset_id") or "")
    suffix = f"/understanding/versions/{run_id}/index.txt"
    source_roots = {
        path.removesuffix(suffix)
        for path in workspace_texts
        if path.startswith(f"sources/{logical_id}--") and path.endswith(suffix)
    }
    if len(source_roots) != 1:
        raise StorageIntegrityError(
            "Source Intelligence immutable version directory 不唯一或不存在",
        )
    source_root = next(iter(source_roots))
    version_root = f"{source_root}/understanding/versions/{run_id}/"
    files = {
        path.removeprefix(version_root): text
        for path, text in workspace_texts.items()
        if path.startswith(version_root)
    }
    index = parse_source_intelligence_files(files)
    if (
        index.id != run_id
        or index.asset_id != logical_id
        or index.asset_version_id != version_id
        or index.source_checksum != str(asset.get("checksum") or "")
    ):
        raise StorageIntegrityError(
            "Source Intelligence index identity/checksum 与 authority 不一致",
        )
    model_run_ids = {item.id for item in index.model_runs}
    allowed_model_run_ids = {run_id, f"{run_id}:asr"}
    if run_id not in model_run_ids or not model_run_ids.issubset(
        allowed_model_run_ids,
    ):
        raise StorageIntegrityError(
            "Source Intelligence index modelRunId 不属于当前 Source Run",
        )
    actual_pairs = {
        (str(item.get("provider") or ""), str(item.get("model") or ""))
        for item in run_metadata.get("attempts") or ()
        if isinstance(item, Mapping) and item.get("status") == "SUCCEEDED"
    }
    primary_pairs = {
        (item.provider, item.model)
        for item in index.model_runs
        if item.id == run_id
    }
    if not primary_pairs.issubset(actual_pairs):
        raise StorageIntegrityError(
            "Source Intelligence index provider/model 不属于真实成功调用",
        )
    if index.coverage["visual"].mode != "available":
        raise StorageIntegrityError(
            "Source Intelligence 必须声明真实 native visual coverage",
        )
    for modality in ("ocr", "audio"):
        if index.coverage[modality].mode == "available":
            raise StorageIntegrityError(
                f"Source Intelligence 当前直读链不得声明 {modality} coverage",
            )
    if (
        index.words
        or index.ocr_segments
        or index.audio_events
        or index.entities
        or index.shots
    ):
        raise StorageIntegrityError(
            "Source Intelligence 当前直读链只允许 semanticEntries 与 ASR transcript",
        )
    if bool(index.transcript) != (index.coverage["asr"].mode == "available"):
        raise StorageIntegrityError(
            "Source Intelligence ASR coverage 与 transcript 不一致",
        )
    if index.media.media_kind != str(asset.get("media_kind") or ""):
        raise StorageIntegrityError(
            "Source Intelligence mediaKind 与 AssetVersion 不一致",
        )
    is_video = str(asset.get("media_kind") or "") == "video"
    if is_video and not index.semantic_entries:
        raise StorageIntegrityError(
            "视频 Source Intelligence 至少需要一个语义时间片段",
        )
    evidence_ref = workspace_asset_ref(logical_id, version_id)
    for item in index.semantic_entries:
        if set(item.evidence_frame_refs) != {evidence_ref}:
            raise StorageIntegrityError(
                "Source Intelligence evidenceFrameRefs 缺少 exact AssetVersion provenance",
            )
        if is_video and (item.start_ms is None or item.end_ms is None):
            raise StorageIntegrityError(
                "视频 Source Intelligence semantic entry 缺少整数毫秒时间范围",
            )
        if not is_video and (
            item.start_ms is not None or item.end_ms is not None
        ):
            raise StorageIntegrityError(
                "静态素材 Source Intelligence 不得伪造时间范围",
            )
    for item in index.transcript:
        if (
            set(item.evidence_frame_refs) != {evidence_ref}
            or item.model_run_id != f"{run_id}:asr"
        ):
            raise StorageIntegrityError(
                "ASR transcript 缺少 exact AssetVersion/ASR provenance",
            )
    if not index.summary.strip():
        raise StorageIntegrityError("Source Intelligence summary 不能为空")
    return frozenset({version_id})


__all__ = ["validated_source_analysis_versions"]
