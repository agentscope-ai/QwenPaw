# -*- coding: utf-8 -*-
"""共享应用发布快照的路径与完整性测试。"""

from pathlib import Path
from uuid import uuid4

import pytest


def test_snapshot_is_stable_and_filters_runtime_state(tmp_path: Path):
    from qwenpaw.publications.snapshot import PublicationSnapshotBuilder

    source = tmp_path / "source"
    source.mkdir()
    (source / "SOUL.md").write_text("你好", encoding="utf-8")
    (source / "nested").mkdir()
    (source / "nested" / "config.json").write_text('{"ok":true}', encoding="utf-8")
    (source / "sessions").mkdir()
    (source / "sessions" / "private.json").write_text("secret", encoding="utf-8")
    builder = PublicationSnapshotBuilder(tmp_path / "managed")

    first = builder.build(source, uuid4())
    second = builder.build(source, uuid4())

    assert first.workspace_hash == second.workspace_hash
    assert first.files == ("SOUL.md", "nested/config.json")
    assert not (first.path / "sessions").exists()
    assert first.workspace_key == f"published_workspaces/{first.publication_id}"
    assert builder.verify(first.workspace_key, first.workspace_hash)
    (first.path / "SOUL.md").write_text("已篡改", encoding="utf-8")
    assert not builder.verify(first.workspace_key, first.workspace_hash)
    assert not builder.verify("../source", first.workspace_hash)


def test_snapshot_rejects_symlink(tmp_path: Path):
    from qwenpaw.publications.snapshot import (
        PublicationSnapshotBuilder,
        SnapshotBuildError,
    )

    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    link = source / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前环境不允许创建目录符号链接")

    with pytest.raises(SnapshotBuildError, match="snapshot_symlink_denied"):
        PublicationSnapshotBuilder(tmp_path / "managed").build(source, uuid4())


def test_snapshot_rejects_existing_publication_target(tmp_path: Path):
    from qwenpaw.publications.snapshot import (
        PublicationSnapshotBuilder,
        SnapshotBuildError,
    )

    source = tmp_path / "source"
    source.mkdir()
    publication_id = uuid4()
    target = tmp_path / "managed" / "published_workspaces" / str(publication_id)
    target.mkdir(parents=True)

    with pytest.raises(SnapshotBuildError, match="publication_snapshot_exists"):
        PublicationSnapshotBuilder(tmp_path / "managed").build(source, publication_id)
