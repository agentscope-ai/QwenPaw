# -*- coding: utf-8 -*-
"""Mission state for parallel migration compatibility repair."""

from __future__ import annotations

from pathlib import Path

from ..modes.mission.state import (
    init_progress_txt,
    read_loop_config,
    read_prd,
    write_loop_config,
    write_prd_json,
    write_task_md,
)
from .compatibility import AssetZone, CompatibilityManifest


def prepare_mission(
    root: Path,
    manifest: CompatibilityManifest,
    session_id: str,
    max_attempts: int,
) -> Path:
    """Create one already-approved Mission whose stories are repair assets."""
    loop_dir = root / "mission"
    loop_dir.mkdir(mode=0o700)
    write_task_md(loop_dir, "并行修复迁移工具，直到原生兼容性测试通过。")
    init_progress_txt(loop_dir)
    stories = [
        {
            "id": f"ASSET-{index:04d}",
            "assetKey": asset.asset_key,
            "title": asset.asset_key,
            "description": f"修复并验证 {asset.asset_key}",
            "acceptanceCriteria": [
                "QwenPaw 原生格式、安全、隐私和环境检查全部通过",
                "最新测试结果对应最新修订",
            ],
            "priority": 1,
            "passes": False,
            "notes": "",
        }
        for index, asset in enumerate(
            manifest.by_zone(AssetZone.REPAIR),
            start=1,
        )
    ]
    write_prd_json(
        loop_dir,
        {
            "project": "QwenPaw Portability",
            "branchName": "",
            "description": "并行兼容性修复",
            "userStories": stories,
        },
    )
    write_loop_config(
        loop_dir,
        {
            "current_phase": "execution",
            "session_id": session_id,
            "max_iterations": max_attempts,
            "max_retries_per_story": max(0, max_attempts - 1),
            "internal": True,
            "migration_id": manifest.migration_id,
        },
    )
    return loop_dir


def sync_mission(
    loop_dir: Path,
    manifest: CompatibilityManifest,
    *,
    stopped: bool = False,
) -> None:
    """Mirror authoritative compatibility state into Mission stories."""
    prd = read_prd(loop_dir)
    assets = {item.asset_key: item for item in manifest.assets}
    for story in prd.get("userStories", []):
        asset = assets.get(story.get("assetKey"))
        if asset is None:
            continue
        story["passes"] = asset.zone is AssetZone.MIGRATE
        story["notes"] = asset.reason
    write_prd_json(loop_dir, prd)

    cfg = read_loop_config(loop_dir)
    if not manifest.by_zone(AssetZone.REPAIR):
        cfg["current_phase"] = "completed"
    elif stopped:
        cfg["current_phase"] = "max_iterations_reached"
    write_loop_config(loop_dir, cfg)
