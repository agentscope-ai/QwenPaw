# -*- coding: utf-8 -*-
"""Restore coverage for conversation, memory, and workspace files."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.checkpoints.service import CheckpointService
from qwenpaw.checkpoints.policy import (
    sanitize_ref_component,
    session_file_path,
    session_key,
)
from qwenpaw.checkpoints.restore import MemoryRestorer, WorkspaceMutationGuard
from qwenpaw.checkpoints.models import CheckpointError, RestoreResult
from qwenpaw.checkpoints.render import render_restore
from qwenpaw.checkpoints.repository import CheckpointRepository
from qwenpaw.checkpoints.restore import RestoreService

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="checkpoint tests require git",
)

SESSION_ID = "session-1"
USER_ID = "user"
CHANNEL = "console"


def _write_session(
    workspace: Path,
    text: str,
    *,
    session_id: str = SESSION_ID,
    user_id: str = USER_ID,
    channel: str = CHANNEL,
) -> Path:
    path = session_file_path(
        workspace,
        session_id=session_id,
        user_id=user_id,
        channel=channel,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "agent": {
                    "state": {
                        "context": [
                            {
                                "id": f"msg-{text}",
                                "role": "user",
                                "content": [{"type": "text", "text": text}],
                            },
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _session_text(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    content = data["agent"]["state"]["context"][-1]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(
        block["text"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )


async def _checkpoint(
    engine: CheckpointService,
    text: str,
    *,
    session_id: str = SESSION_ID,
) -> str:
    ref = await engine.make_auto_checkpoint(
        session_id=session_id,
        user_id=USER_ID,
        channel=CHANNEL,
        query=text,
    )
    return engine.repository.run_git("rev-parse", ref)


def test_snapshot_name_preserves_unicode_and_removes_ref_separators() -> None:
    assert sanitize_ref_component("涓枃 蹇収/name") == "涓枃-蹇収-name"


@pytest.mark.parametrize(
    "name",
    [
        "CON",
        "con.txt",
        "PRN",
        "AUX.log",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"lpt{index}.txt" for index in range(1, 10)),
    ],
)
def test_snapshot_name_avoids_windows_reserved_device_names(name: str) -> None:
    assert sanitize_ref_component(name) == f"ref-{name}"


@pytest.mark.parametrize("name", ["COM10", "LPT10", "CONSOLE"])
def test_snapshot_name_preserves_non_reserved_windows_names(name: str) -> None:
    assert sanitize_ref_component(name) == name


def test_file_restore_dry_run_renders_every_candidate() -> None:
    restored = tuple(f"src/changed_{index:02d}.py" for index in range(30))
    deleted = tuple(f"docs/deleted_{index:02d}.md" for index in range(30))
    result = RestoreResult(
        target="#1",
        commit="a" * 40,
        restored_paths=("sessions/console/user_session-1.json", *restored),
        pre_restore_ref=None,
        dry_run=True,
        include_files=True,
        deleted_paths=deleted,
        file_paths=(*restored, *deleted),
    )

    rendered = render_restore(result)

    assert "**Would restore (30)**" in rendered
    assert "`src/changed_29.py`" in rendered
    assert "**Would delete (30)**" in rendered
    assert "`docs/deleted_29.md`" in rendered
    assert "and 10 more" not in rendered
    assert f"/checkpoint restore {'a' * 40}" in rendered
    assert '--files "src/changed_29.py"' in rendered
    assert '--files "docs/deleted_29.md"' in rendered
    assert rendered.rstrip().endswith("--confirm\n```")


def test_file_restore_candidates_skip_qwenpaw_state_files(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    service = RestoreService(engine)

    assert service._is_file_restore_candidate(
        "src/app.py",
        conv_rel="sessions/console/user_s1.json",
    )
    for rel in (
        "chats.json",
        "skill.json",
        "AGENTS.md",
        "PROFILE.md",
        "HEARTBEAT.md",
        "history.db",
        "chats.json.tmp",
        ".skill.json.lock",
        "jobs_history/job.json",
        "mem_agent/index.json",
        "mem_session/state.json",
        ".scroll/cache.json",
        "sessions/console/user_s1.json",
        "MEMORY.md",
        "memory/note.md",
    ):
        assert not service._is_file_restore_candidate(
            rel,
            conv_rel="sessions/console/user_s1.json",
        )


@pytest.mark.asyncio
async def test_snapshot_keeps_checkpoint_state_and_excludes_runtime_state(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    _write_session(tmp_path, "state boundary")
    (tmp_path / "MEMORY.md").write_text("long term", encoding="utf-8")
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "daily.md").write_text("daily", encoding="utf-8")
    mem_agent = tmp_path / "mem_agent"
    mem_agent.mkdir()
    (mem_agent / "index.json").write_text("{}", encoding="utf-8")
    venv_cache = tmp_path / ".venv"
    venv_cache.mkdir()
    (venv_cache / "cache.txt").write_text("cache", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("*.tmp\n", encoding="utf-8")

    commit = await _checkpoint(engine, "state boundary")
    tree_paths = set(
        engine.repository.run_git(
            "ls-tree",
            "-r",
            "--name-only",
            commit,
        ).splitlines(),
    )

    assert "sessions/console/user_session-1.json" in tree_paths
    assert "MEMORY.md" in tree_paths
    assert "memory/daily.md" in tree_paths
    assert "mem_agent/index.json" not in tree_paths
    assert ".venv/cache.txt" not in tree_paths
    assert ".gitignore" not in tree_paths


@pytest.mark.asyncio
async def test_conversation_restore_dry_run_then_confirm(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    session_path = _write_session(tmp_path, "first")
    first_commit = await _checkpoint(engine, "first")

    _write_session(tmp_path, "second")
    second_commit = await _checkpoint(engine, "second")

    preview = await engine.restore(
        target=first_commit[:12],
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        dry_run=True,
    )
    assert preview.dry_run is True
    assert preview.pre_restore_ref is None
    assert preview.restored_paths == ("sessions/console/user_session-1.json",)
    assert _session_text(session_path) == "second"
    assert (
        engine.session_head(
            session_key(
                channel=CHANNEL,
                user_id=USER_ID,
                session_id=SESSION_ID,
            ),
        )
        == second_commit
    )

    restored = await engine.restore(
        target=first_commit[:12],
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
    )
    assert restored.dry_run is False
    assert restored.pre_restore_ref is not None
    assert _session_text(session_path) == "first"
    assert (
        engine.session_head(
            session_key(
                channel=CHANNEL,
                user_id=USER_ID,
                session_id=SESSION_ID,
            ),
        )
        == first_commit
    )


@pytest.mark.asyncio
async def test_restore_with_memory_dry_run_then_confirm(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    session_path = _write_session(tmp_path, "with memory")
    (tmp_path / "MEMORY.md").write_text("memory before", encoding="utf-8")
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    note = memory_dir / "note.md"
    note.write_text("note before", encoding="utf-8")
    first_commit = await _checkpoint(engine, "with memory")

    _write_session(tmp_path, "after memory")
    (tmp_path / "MEMORY.md").write_text("memory after", encoding="utf-8")
    note.write_text("note after", encoding="utf-8")
    extra = memory_dir / "extra.md"
    extra.write_text("delete me", encoding="utf-8")

    preview = await engine.restore_with_memory(
        target=first_commit[:12],
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        dry_run=True,
    )
    assert preview.dry_run is True
    assert preview.include_memory is True
    assert "MEMORY.md" in preview.restored_paths
    assert "memory/note.md" in preview.restored_paths
    assert preview.deleted_paths == ("memory/extra.md",)
    assert _session_text(session_path) == "after memory"
    assert (tmp_path / "MEMORY.md").read_text(
        encoding="utf-8",
    ) == "memory after"
    assert extra.exists()

    restored = await engine.restore_with_memory(
        target=first_commit[:12],
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
    )
    assert restored.include_memory is True
    assert restored.pre_restore_ref is not None
    assert _session_text(session_path) == "with memory"
    assert (tmp_path / "MEMORY.md").read_text(
        encoding="utf-8",
    ) == "memory before"
    assert note.read_text(encoding="utf-8") == "note before"
    assert not extra.exists()


@pytest.mark.asyncio
async def test_restore_with_files_dry_run_then_confirm_skips_qwenpaw_state(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    session_path = _write_session(tmp_path, "with files")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('before')\n", encoding="utf-8")
    state_file = tmp_path / "chats.json"
    state_file.write_text("state before", encoding="utf-8")
    first_commit = await _checkpoint(engine, "with files")

    _write_session(tmp_path, "after files")
    source.write_text("print('after')\n", encoding="utf-8")
    added = tmp_path / "scratch.txt"
    added.write_text("remove me", encoding="utf-8")
    state_file.write_text("state after", encoding="utf-8")

    preview = await engine.restore_with_files(
        target=first_commit[:12],
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        dry_run=True,
    )
    assert preview.dry_run is True
    assert preview.include_files is True
    assert "src/app.py" in preview.restored_paths
    assert "scratch.txt" in preview.deleted_paths
    assert "chats.json" not in preview.restored_paths
    assert _session_text(session_path) == "after files"
    assert source.read_text(encoding="utf-8") == "print('after')\n"
    assert added.exists()
    assert state_file.read_text(encoding="utf-8") == "state after"

    with patch.object(
        engine.repository,
        "write_workspace_tree",
        wraps=engine.repository.write_workspace_tree,
    ) as write_tree:
        restored = await engine.restore_with_files(
            target=first_commit[:12],
            session_id=SESSION_ID,
            user_id=USER_ID,
            channel=CHANNEL,
            selected_files=("src/app.py", "scratch.txt"),
        )
    assert write_tree.call_count == 1
    assert restored.include_files is True
    assert restored.pre_restore_ref is not None
    assert _session_text(session_path) == "with files"
    assert source.read_text(encoding="utf-8") == "print('before')\n"
    assert not added.exists()
    assert state_file.read_text(encoding="utf-8") == "state after"


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable mode semantics")
def test_tree_restore_preserves_executable_mode(tmp_path: Path) -> None:
    source = tmp_path / "run.sh"
    source.write_bytes(b"#!/bin/sh\nexit 0\n")
    source.chmod(0o755)
    repository = CheckpointRepository(tmp_path)
    tree = repository.write_workspace_tree()

    source.chmod(0o644)
    preview = repository.plan_tree_restore(tree, {"run.sh"})
    assert preview == (["run.sh"], [])

    restored, deleted = repository.restore_tree_paths(tree, {"run.sh"})
    assert restored == ["run.sh"]
    assert deleted == []
    assert source.read_bytes() == b"#!/bin/sh\nexit 0\n"
    assert source.stat().st_mode & 0o111 == 0o111

    source.chmod(0o644)
    non_executable_tree = repository.write_workspace_tree()
    source.chmod(0o755)
    restored, deleted = repository.restore_tree_paths(
        non_executable_tree,
        {"run.sh"},
    )
    assert restored == ["run.sh"]
    assert deleted == []
    assert source.stat().st_mode & 0o111 == 0


def test_tree_restore_preserves_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = tmp_path / "current.txt"
    try:
        os.symlink("target.txt", link)
    except OSError as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")
    repository = CheckpointRepository(tmp_path)
    tree = repository.write_workspace_tree()

    link.unlink()
    link.write_text("target.txt", encoding="utf-8")
    preview = repository.plan_tree_restore(tree, {"current.txt"})
    assert preview == (["current.txt"], [])

    restored, deleted = repository.restore_tree_paths(
        tree,
        {"current.txt"},
    )
    assert restored == ["current.txt"]
    assert deleted == []
    assert link.is_symlink()
    assert os.readlink(link) == "target.txt"


@pytest.mark.parametrize(
    ("tree_output", "message"),
    [
        ("malformed-entry", "malformed Git tree entry"),
        (
            "160000 commit deadbeef\tvendor\0",
            "unsupported Git tree entry",
        ),
    ],
)
def test_tree_restore_rejects_invalid_tree_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tree_output: str,
    message: str,
) -> None:
    repository = CheckpointRepository(tmp_path)
    monkeypatch.setattr(
        repository,
        "run_git",
        lambda *_args, **_kwargs: tree_output,
    )

    with pytest.raises(CheckpointError, match=message):
        repository.plan_tree_restore("deadbeef", {"vendor"})


def test_tree_entry_discovery_does_not_load_blob_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = CheckpointRepository(tmp_path)
    monkeypatch.setattr(
        repository,
        "run_git",
        lambda *_args, **_kwargs: (
            "100644 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "\tmodels/one.bin\0"
            "100755 blob bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            "\tscripts/run.sh\0"
        ),
    )
    monkeypatch.setattr(
        repository,
        "read_blob",
        lambda *_args, **_kwargs: pytest.fail(
            "tree entry discovery must not load blob content",
        ),
    )

    entries = repository._tree_entries(
        "deadbeef",
        {"models/one.bin", "scripts/run.sh"},
    )

    assert {
        path: (entry.mode, entry.object_id) for path, entry in entries.items()
    } == {
        "models/one.bin": ("100644", "a" * 40),
        "scripts/run.sh": ("100755", "b" * 40),
    }


def test_tree_entry_discovery_uses_fixed_git_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = CheckpointRepository(tmp_path)
    calls: list[tuple[str, ...]] = []

    def run_git(*args: str, **_kwargs: object) -> str:
        calls.append(args)
        return (
            "100644 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "\tselected.txt\0"
            "160000 commit bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            "\tvendor/unrequested\0"
        )

    monkeypatch.setattr(repository, "run_git", run_git)
    paths = {f"missing/file_{index:04d}.txt" for index in range(5000)}
    paths.add("selected.txt")
    entries = repository._tree_entries("deadbeef", paths)

    assert set(entries) == {"selected.txt"}
    assert calls == [("ls-tree", "-r", "-z", "--full-tree", "deadbeef")]


def test_tree_restore_uses_constant_git_processes_for_many_files(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    paths: set[str] = set()
    for index in range(1000):
        rel = f"src/file_{index:04d}.py"
        (tmp_path / rel).write_text(f"VALUE = {index}\n", encoding="utf-8")
        paths.add(rel)

    repository = CheckpointRepository(tmp_path)
    tree = repository.write_workspace_tree()

    for operation in (
        repository.plan_tree_restore,
        repository.restore_tree_paths,
    ):
        with patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
            result = operation(tree, paths)

        assert result == ([], [])
        commands = [tuple(call.args[0]) for call in popen.call_args_list]
        assert len(commands) == 2
        assert sum("ls-tree" in command for command in commands) == 1
        assert (
            sum(
                "cat-file" in command and "--batch" in command
                for command in commands
            )
            == 1
        )


def test_memory_preview_uses_constant_git_processes(
    tmp_path: Path,
) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    for index in range(1000):
        (memory_dir / f"fact_{index:04d}.md").write_text(
            f"fact {index}\n",
            encoding="utf-8",
        )

    repository = CheckpointRepository(tmp_path)
    tree = repository.write_workspace_tree()
    restorer = MemoryRestorer(repository=repository)

    with patch("subprocess.Popen", wraps=subprocess.Popen) as popen:
        result = restorer.plan(tree)

    assert result == ([], [])
    commands = [tuple(call.args[0]) for call in popen.call_args_list]
    assert len(commands) == 3
    assert sum("ls-tree" in command for command in commands) == 2
    assert (
        sum(
            "cat-file" in command and "--batch" in command
            for command in commands
        )
        == 1
    )
    assert not any(
        "cat-file" in command and "blob" in command for command in commands
    )


def test_restore_rejects_symlink_parent_outside_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside.mkdir()
    repository = CheckpointRepository(workspace)
    linked = workspace / "linked"
    try:
        os.symlink(outside, linked, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symbolic links are unavailable: {exc}")

    with pytest.raises(CheckpointError, match="outside workspace|reparse"):
        repository.restore_internal_paths({"linked/escaped.txt": b"escaped"})

    assert not (outside / "escaped.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_restore_rejects_windows_junction_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside.mkdir()
    repository = CheckpointRepository(workspace)
    junction = workspace / "junction"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"junctions are unavailable: {created.stderr}")

    with pytest.raises(CheckpointError, match="outside workspace|reparse"):
        repository.restore_internal_paths(
            {"junction/escaped.txt": b"escaped"},
        )

    assert not (outside / "escaped.txt").exists()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    assert repository.delete_workspace_path("junction") is True
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not junction.exists()


@pytest.mark.asyncio
async def test_restore_with_memory_and_files_combines_both_scopes(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    session_path = _write_session(tmp_path, "combined")
    file_path = tmp_path / "docs" / "plan.md"
    file_path.parent.mkdir()
    file_path.write_text("file before", encoding="utf-8")
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    memory_file = memory_dir / "fact.md"
    memory_file.write_text("memory before", encoding="utf-8")
    first_commit = await _checkpoint(engine, "combined")

    _write_session(tmp_path, "combined later")
    file_path.write_text("file after", encoding="utf-8")
    memory_file.write_text("memory after", encoding="utf-8")

    preview = await engine.restore_with_files(
        target=first_commit[:12],
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        include_memory=True,
        dry_run=True,
    )
    assert preview.dry_run is True
    assert preview.include_files is True
    assert preview.include_memory is True
    assert "docs/plan.md" in preview.restored_paths
    assert "memory/fact.md" in preview.restored_paths
    assert file_path.read_text(encoding="utf-8") == "file after"
    assert memory_file.read_text(encoding="utf-8") == "memory after"

    restored = await engine.restore_with_files(
        target=first_commit[:12],
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        include_memory=True,
        selected_files=("docs/plan.md",),
    )
    assert restored.include_files is True
    assert restored.include_memory is True
    assert _session_text(session_path) == "combined"
    assert file_path.read_text(encoding="utf-8") == "file before"
    assert memory_file.read_text(encoding="utf-8") == "memory before"


@pytest.mark.asyncio
async def test_restore_with_files_can_select_an_exact_subset(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    session_path = _write_session(tmp_path, "selected files")
    selected = tmp_path / "src" / "selected.py"
    skipped = tmp_path / "src" / "skipped.py"
    selected.parent.mkdir()
    selected.write_text("selected before", encoding="utf-8")
    skipped.write_text("skipped before", encoding="utf-8")
    first_commit = await _checkpoint(engine, "selected files")

    _write_session(tmp_path, "selected files later")
    selected.write_text("selected after", encoding="utf-8")
    skipped.write_text("skipped after", encoding="utf-8")

    preview = await engine.restore_with_files(
        target=first_commit[:12],
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        selected_files=(r"src\selected.py",),
        dry_run=True,
    )
    assert "src/selected.py" in preview.restored_paths
    assert "src/skipped.py" not in preview.restored_paths
    assert selected.read_text(encoding="utf-8") == "selected after"

    restored = await engine.restore_with_files(
        target=first_commit[:12],
        session_id=SESSION_ID,
        user_id=USER_ID,
        channel=CHANNEL,
        selected_files=("src/selected.py",),
    )
    assert "src/selected.py" in restored.restored_paths
    assert "src/skipped.py" not in restored.restored_paths
    assert _session_text(session_path) == "selected files"
    assert selected.read_text(encoding="utf-8") == "selected before"
    assert skipped.read_text(encoding="utf-8") == "skipped after"


@pytest.mark.asyncio
async def test_restore_with_files_rejects_invalid_selections(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    _write_session(tmp_path, "selection validation")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("before", encoding="utf-8")
    first_commit = await _checkpoint(engine, "selection validation")
    source.write_text("after", encoding="utf-8")

    common = {
        "target": first_commit[:12],
        "session_id": SESSION_ID,
        "user_id": USER_ID,
        "channel": CHANNEL,
        "dry_run": True,
    }
    with pytest.raises(CheckpointError, match="workspace-relative"):
        await engine.restore_with_files(
            **common,
            selected_files=("../outside.txt",),
        )
    with pytest.raises(CheckpointError, match="state path"):
        await engine.restore_with_files(
            **common,
            selected_files=("mem_agent/index.json",),
        )
    with pytest.raises(CheckpointError, match="not changed"):
        await engine.restore_with_files(
            **common,
            selected_files=("docs/missing.md",),
        )

    confirm_args = {**common, "dry_run": False}
    with pytest.raises(CheckpointError, match="explicit.*--files"):
        await engine.restore_with_files(**confirm_args)

    head_before = engine.session_head(
        session_key(
            channel=CHANNEL,
            user_id=USER_ID,
            session_id=SESSION_ID,
        ),
    )
    with pytest.raises(CheckpointError, match="not changed"):
        await engine.restore_with_files(
            **confirm_args,
            selected_files=("docs/missing.md",),
        )
    pre_restore_refs = engine.repository.run_git(
        "for-each-ref",
        "--format=%(refname)",
        "refs/pre-restore",
    )
    assert pre_restore_refs == ""
    assert (
        engine.session_head(
            session_key(
                channel=CHANNEL,
                user_id=USER_ID,
                session_id=SESSION_ID,
            ),
        )
        == head_before
    )


@pytest.mark.asyncio
async def test_restore_rejects_checkpoint_from_another_session(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)
    _write_session(tmp_path, "source", session_id="source")
    _write_session(tmp_path, "fork", session_id="fork")
    fork_commit = await _checkpoint(engine, "fork", session_id="fork")

    with pytest.raises(CheckpointError, match="this session"):
        await engine.restore(
            target=fork_commit[:12],
            session_id="source",
            user_id=USER_ID,
            channel=CHANNEL,
            dry_run=True,
        )


def test_long_numeric_target_is_not_treated_as_timeline_index(
    tmp_path: Path,
) -> None:
    engine = CheckpointService(tmp_path)

    with pytest.raises(CheckpointError, match="this session"):
        engine.resolve_target(
            "123456789012",
            SESSION_ID,
            USER_ID,
            CHANNEL,
        )


@pytest.mark.asyncio
async def test_memory_restore_fails_when_workspace_does_not_quiesce() -> None:
    class BusyTasks:
        @staticmethod
        async def wait_all_idle() -> None:
            await asyncio.sleep(60)

    class Workspace:
        task_tracker = BusyTasks()

    guard = WorkspaceMutationGuard(Workspace(), timeout=0.01)

    with pytest.raises(CheckpointError, match="did not become idle"):
        await guard.quiesce()


@pytest.mark.asyncio
async def test_precise_guard_timeout_resumes_cron() -> None:
    class CronExecutor:
        def __init__(self) -> None:
            self.paused = False
            self.resume_count = 0

        def pause(self) -> None:
            self.paused = True

        def resume(self) -> None:
            self.paused = False
            self.resume_count += 1

    class Workspace:
        def __init__(self) -> None:
            self.task_tracker = TaskTracker()
            self.cron_executor = CronExecutor()

    workspace = Workspace()
    release = asyncio.Event()

    async def running_agent(_payload):
        await release.wait()
        yield "done"

    queue, _ = await workspace.task_tracker.attach_or_start(
        "running-agent",
        None,
        running_agent,
    )
    guard = WorkspaceMutationGuard(workspace, timeout=0.01)

    with pytest.raises(CheckpointError, match="did not become idle"):
        await guard.quiesce()

    assert workspace.cron_executor.paused is False
    assert workspace.cron_executor.resume_count == 1
    release.set()
    async for _ in workspace.task_tracker.stream_from_queue(
        queue,
        "running-agent",
    ):
        pass


@pytest.mark.asyncio
async def test_file_restore_quiesces_internal_workspace_writers(
    tmp_path: Path,
) -> None:
    class BusyTasks:
        def __init__(self) -> None:
            self.waiting = asyncio.Event()
            self.release = asyncio.Event()

        async def wait_all_idle(self) -> None:
            self.waiting.set()
            await self.release.wait()

    class CronExecutor:
        def __init__(self) -> None:
            self.paused = False
            self.resume_count = 0

        def pause(self) -> None:
            self.paused = True

        def resume(self) -> None:
            self.paused = False
            self.resume_count += 1

    class Workspace:
        def __init__(self) -> None:
            self.task_tracker = BusyTasks()
            self.cron_executor = CronExecutor()

    engine = CheckpointService(tmp_path)
    workspace = Workspace()
    engine.workspace = workspace
    _write_session(tmp_path, "before")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("before", encoding="utf-8")
    first_commit = await _checkpoint(engine, "before")
    _write_session(tmp_path, "after")
    source.write_text("after", encoding="utf-8")

    restore_task = asyncio.create_task(
        engine.restore_with_files(
            target=first_commit[:12],
            session_id=SESSION_ID,
            user_id=USER_ID,
            channel=CHANNEL,
            selected_files=("src/app.py",),
        ),
    )
    await asyncio.wait_for(workspace.task_tracker.waiting.wait(), timeout=1)

    assert workspace.cron_executor.paused is True
    assert source.read_text(encoding="utf-8") == "after"
    assert not restore_task.done()
    assert not engine.query_gate.is_set()

    workspace.task_tracker.release.set()
    restored = await restore_task

    assert restored.include_files is True
    assert source.read_text(encoding="utf-8") == "before"
    assert workspace.cron_executor.paused is False
    assert workspace.cron_executor.resume_count == 1
    assert engine.query_gate.is_set()


@pytest.mark.asyncio
async def test_restore_with_memory_rolls_back_session_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CheckpointService(tmp_path)
    session_path = _write_session(tmp_path, "first")
    first_commit = await _checkpoint(engine, "first")
    _write_session(tmp_path, "second")
    second_commit = await _checkpoint(engine, "second")

    original_restore_sync = MemoryRestorer.restore_sync

    def fail_for_target_commit(self, commit: str):
        if commit == first_commit:
            raise RuntimeError("memory restore failed")
        return original_restore_sync(self, commit)

    monkeypatch.setattr(
        MemoryRestorer,
        "restore_sync",
        fail_for_target_commit,
    )

    with pytest.raises(RuntimeError, match="memory restore failed"):
        await engine.restore_with_memory(
            target=first_commit[:12],
            session_id=SESSION_ID,
            user_id=USER_ID,
            channel=CHANNEL,
        )

    assert _session_text(session_path) == "second"
    assert (
        engine.session_head(
            session_key(
                channel=CHANNEL,
                user_id=USER_ID,
                session_id=SESSION_ID,
            ),
        )
        == second_commit
    )


@pytest.mark.asyncio
async def test_restore_io_does_not_block_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CheckpointService(tmp_path)
    _write_session(tmp_path, "first")
    first_commit = await _checkpoint(engine, "first")
    _write_session(tmp_path, "second")
    await _checkpoint(engine, "second")
    started = threading.Event()
    release = threading.Event()
    original_restore_paths = engine.repository.restore_internal_paths

    def slow_restore_paths(blobs: dict[str, bytes]) -> None:
        started.set()
        if not release.wait(timeout=5):
            raise RuntimeError("test restore release timed out")
        original_restore_paths(blobs)

    monkeypatch.setattr(
        engine.repository,
        "restore_internal_paths",
        slow_restore_paths,
    )
    restore_task = asyncio.create_task(
        engine.restore(
            target=first_commit[:12],
            session_id=SESSION_ID,
            user_id=USER_ID,
            channel=CHANNEL,
        ),
    )
    assert await asyncio.to_thread(started.wait, 5)

    heartbeats = 0

    async def heartbeat() -> None:
        nonlocal heartbeats
        for _ in range(5):
            await asyncio.sleep(0.01)
            heartbeats += 1

    await heartbeat()
    assert heartbeats == 5
    assert not restore_task.done()
    release.set()
    await restore_task


@pytest.mark.asyncio
async def test_cancelled_memory_restore_waits_for_transaction_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CheckpointService(tmp_path)
    session_path = _write_session(tmp_path, "first")
    memory_path = tmp_path / "MEMORY.md"
    memory_path.write_text("memory first", encoding="utf-8")
    first_commit = await _checkpoint(engine, "first")
    _write_session(tmp_path, "second")
    memory_path.write_text("memory second", encoding="utf-8")
    await _checkpoint(engine, "second")
    started = threading.Event()
    release = threading.Event()
    original_restore_sync = MemoryRestorer.restore_sync

    def slow_restore_sync(self, commit: str):
        if commit == first_commit:
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test memory release timed out")
        return original_restore_sync(self, commit)

    monkeypatch.setattr(
        MemoryRestorer,
        "restore_sync",
        slow_restore_sync,
    )
    restore_task = asyncio.create_task(
        engine.restore_with_memory(
            target=first_commit[:12],
            session_id=SESSION_ID,
            user_id=USER_ID,
            channel=CHANNEL,
        ),
    )
    assert await asyncio.to_thread(started.wait, 5)

    restore_task.cancel()
    await asyncio.sleep(0.02)
    gate_waiter = asyncio.create_task(engine.query_gate.wait())
    await asyncio.sleep(0.02)

    assert not restore_task.done()
    assert not gate_waiter.done()
    assert engine.maintenance_lock.locked()
    assert engine.lock.locked()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await restore_task
    await gate_waiter

    assert _session_text(session_path) == "first"
    assert memory_path.read_text(encoding="utf-8") == "memory first"
    assert engine.query_gate.is_set()
    assert not engine.maintenance_lock.locked()
    assert not engine.lock.locked()
    assert (
        engine.session_head(
            session_key(
                channel=CHANNEL,
                user_id=USER_ID,
                session_id=SESSION_ID,
            ),
        )
        == first_commit
    )


@pytest.mark.asyncio
async def test_cancelled_memory_restore_waits_for_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CheckpointService(tmp_path)
    session_path = _write_session(tmp_path, "first")
    memory_path = tmp_path / "MEMORY.md"
    memory_path.write_text("memory first", encoding="utf-8")
    first_commit = await _checkpoint(engine, "first")
    _write_session(tmp_path, "second")
    memory_path.write_text("memory second", encoding="utf-8")
    second_commit = await _checkpoint(engine, "second")
    started = threading.Event()
    release = threading.Event()
    original_restore_sync = MemoryRestorer.restore_sync

    def fail_target_restore(self, commit: str):
        if commit == first_commit:
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test memory release timed out")
            raise RuntimeError("memory restore failed")
        return original_restore_sync(self, commit)

    monkeypatch.setattr(
        MemoryRestorer,
        "restore_sync",
        fail_target_restore,
    )
    restore_task = asyncio.create_task(
        engine.restore_with_memory(
            target=first_commit[:12],
            session_id=SESSION_ID,
            user_id=USER_ID,
            channel=CHANNEL,
        ),
    )
    assert await asyncio.to_thread(started.wait, 5)
    restore_task.cancel()
    await asyncio.sleep(0.02)

    assert not restore_task.done()
    assert not engine.query_gate.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await restore_task

    assert _session_text(session_path) == "second"
    assert memory_path.read_text(encoding="utf-8") == "memory second"
    assert engine.query_gate.is_set()
    assert (
        engine.session_head(
            session_key(
                channel=CHANNEL,
                user_id=USER_ID,
                session_id=SESSION_ID,
            ),
        )
        == second_commit
    )


@pytest.mark.asyncio
async def test_conversation_restore_rolls_back_after_head_update_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = CheckpointService(tmp_path)
    session_path = _write_session(tmp_path, "first")
    first_commit = await _checkpoint(engine, "first")
    _write_session(tmp_path, "second")
    second_commit = await _checkpoint(engine, "second")
    original_set_head = engine.repository.set_session_head
    failed = False

    def fail_target_once(key: str, commit: str) -> None:
        nonlocal failed
        if commit == first_commit and not failed:
            failed = True
            raise OSError("heads write failed")
        original_set_head(key, commit)

    monkeypatch.setattr(
        engine.repository,
        "set_session_head",
        fail_target_once,
    )

    with pytest.raises(OSError, match="heads write failed"):
        await engine.restore(
            target=first_commit[:12],
            session_id=SESSION_ID,
            user_id=USER_ID,
            channel=CHANNEL,
        )

    assert _session_text(session_path) == "second"
    assert (
        engine.session_head(
            session_key(
                channel=CHANNEL,
                user_id=USER_ID,
                session_id=SESSION_ID,
            ),
        )
        == second_commit
    )
