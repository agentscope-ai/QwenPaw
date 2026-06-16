# -*- coding: utf-8 -*-
"""Tests for DataPaw path translation helpers."""

from pathlib import Path


def test_resolve_artifact_path_accepts_paths_relative_to_artifacts_root(
    tmp_path,
):
    from plugin_datapaw.core.path_context import PathContext

    artifacts_root = tmp_path / "workspace" / "artifacts"
    context = PathContext(mount_dir=artifacts_root)

    resolved = context.resolve_artifact_path(
        "1781507554217/graph_HaNXVR4K/fetch_data/data/raw/overview_daily.csv",
    )

    assert resolved == (
        artifacts_root
        / "1781507554217"
        / "graph_HaNXVR4K"
        / "fetch_data"
        / "data"
        / "raw"
        / "overview_daily.csv"
    ).resolve()


def test_resolve_artifact_path_tolerates_workspace_artifacts_prefix(tmp_path):
    from plugin_datapaw.core.path_context import PathContext

    artifacts_root = tmp_path / "workspace" / "artifacts"
    context = PathContext(mount_dir=artifacts_root)

    resolved = context.resolve_artifact_path(
        "artifacts/1781507554217/graph_TLk7Z83W/user_growth_trend/charts/dau_trend.png",
    )

    assert resolved == (
        artifacts_root
        / "1781507554217"
        / "graph_TLk7Z83W"
        / "user_growth_trend"
        / "charts"
        / "dau_trend.png"
    ).resolve()


def test_resolve_artifact_path_tolerates_workspace_absolute_artifacts_prefix(
    tmp_path,
):
    from plugin_datapaw.core.path_context import PathContext

    artifacts_root = tmp_path / "workspace" / "artifacts"
    context = PathContext(mount_dir=artifacts_root)

    resolved = context.resolve_artifact_path(
        "/workspace/artifacts/1781507554217/graph_TLk7Z83W/user_growth_trend/charts/dau_trend.png",
    )

    assert resolved == (
        artifacts_root
        / "1781507554217"
        / "graph_TLk7Z83W"
        / "user_growth_trend"
        / "charts"
        / "dau_trend.png"
    ).resolve()


def test_resolve_artifact_path_keeps_host_absolute_paths(tmp_path):
    from plugin_datapaw.core.path_context import PathContext

    artifacts_root = tmp_path / "workspace" / "artifacts"
    host_path = artifacts_root / "1781507554217" / "graph" / "node" / "x.csv"
    context = PathContext(mount_dir=artifacts_root)

    assert context.resolve_artifact_path(str(host_path)) == host_path.resolve()

