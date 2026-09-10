# -*- coding: utf-8 -*-
import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.portability import skill_transfer
from qwenpaw.portability.compatibility import (
    AssetZone,
    CompatibilityStore,
    RunState,
    load_manifest,
    mcp_inline_secret_risks,
    redact_sensitive_text,
    write_summary,
)


def _skill(tmp_path: Path, name: str = "demo") -> SimpleNamespace:
    root = tmp_path / name
    root.mkdir()
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: demo\n---\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        source_id=name,
        name=name,
        description="demo",
        directory=root,
    )


def test_skill_tree_reads_without_direntry_file_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _skill(tmp_path).directory
    path = root / "SKILL.md"
    info = path.lstat()
    # Windows DirEntry.stat() omits the identity supplied by lstat/fstat.
    entry = SimpleNamespace(
        path=str(path),
        is_symlink=lambda: False,
        is_dir=lambda **_kwargs: False,
        is_file=lambda **_kwargs: True,
        stat=lambda **_kwargs: SimpleNamespace(
            st_dev=0,
            st_ino=0,
            st_size=info.st_size,
            st_mtime_ns=info.st_mtime_ns,
            st_ctime_ns=info.st_ctime_ns,
            st_mode=info.st_mode,
        ),
    )
    with monkeypatch.context() as patch:
        patch.setattr(os, "scandir", lambda _path: nullcontext([entry]))
        entries = list(skill_transfer.read_bounded_skill_tree(root))

    assert len(entries) == 1
    assert entries[0].relative == Path("SKILL.md")
    assert entries[0].data == path.read_bytes()


def test_repair_workflow_requires_current_passing_test(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest.json"
    store = CompatibilityStore(path)
    store.prepare(
        migration_id="migration-1",
        source="codex",
        skills=[_skill(tmp_path)],
    )

    store.finalize(
        "demo",
        passed=False,
        summary="bound to codex",
        reason="bound",
    )
    store.mark_changed("demo", "updated SKILL.md")
    manifest = store.finalize(
        "demo",
        passed=True,
        summary="native loader passed",
        reason="works",
    )
    assert manifest.by_zone(AssetZone.MIGRATE)[0].last_test.passed


def test_hard_stop_preserves_repair_items(
    tmp_path: Path,
) -> None:
    store = CompatibilityStore(tmp_path / "manifest.json")
    store.prepare(
        migration_id="migration-3",
        source="codex",
        skills=[_skill(tmp_path)],
    )
    manifest = store.finish(stopped=True, reason="mission limit")
    assert manifest.state is RunState.STOPPED_LIMIT
    assert manifest.assets[0].zone is AssetZone.REPAIR
    assert manifest.stop_reason == "mission limit"


def test_manifest_and_summary_are_owner_only_and_secret_free(
    tmp_path: Path,
) -> None:
    secret = "correct-horse-battery-staple"
    server = SimpleNamespace(
        source_id="mcp",
        name="mcp",
        transport="stdio",
        command="npx",
        args=["--api-key", secret],
        env={"TOKEN": secret},
        headers={"Authorization": secret},
        cwd="",
        url="",
        metadata={},
    )
    path = tmp_path / "manifest.json"
    store = CompatibilityStore(path)
    manifest = store.prepare(
        migration_id="migration-4",
        source="codex",
        mcp_servers=[server],
        plugins=[
            SimpleNamespace(
                source_id="plugin",
                name="plugin",
                marketplace="local",
                version="1",
                install_source="/tmp/plugin",
                metadata={"password": secret},
            ),
        ],
    )
    summary = tmp_path / "summary.md"
    write_summary(summary, manifest)
    assert secret not in path.read_text(encoding="utf-8")
    assert all("metadata" not in item.snapshot for item in manifest.assets)
    assert "unsafe_bindings" not in manifest.assets[0].snapshot
    if os.name == "posix":
        assert path.stat().st_mode & 0o077 == 0
        assert summary.stat().st_mode & 0o077 == 0
    assert load_manifest(path) == manifest


@pytest.mark.parametrize(
    "args,url",
    [
        (["-phunter2"], ""),
        (["--database-url", "postgresql://u:p@example/db"], ""),
        ([], "https://hooks.slack.com/services/T/B/secret"),
        (["X-Custom-Auth: secret-value"], ""),
    ],
)
def test_inline_mcp_credentials_fail_closed(args, url) -> None:
    assert mcp_inline_secret_risks("npx", args, url)


def test_standalone_token_is_redacted_and_rejected() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz"
    assert secret not in redact_sensitive_text(f"use {secret}")
    assert mcp_inline_secret_risks(f"runner {secret}", []) == ["command"]
