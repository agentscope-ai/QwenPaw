# -*- coding: utf-8 -*-
from types import SimpleNamespace

from copaw.agents.memory.memory_manager import MemoryManager


def test_sanitize_memory_watch_paths_removes_legacy_memory_md(tmp_path) -> None:
    watch_paths = [
        str(tmp_path / "MEMORY.md"),
        str(tmp_path / "memory.md"),
        str(tmp_path / "memory"),
    ]

    sanitized = MemoryManager._sanitize_memory_watch_paths(
        watch_paths=watch_paths,
        working_path=tmp_path,
    )

    assert str(tmp_path / "memory.md") not in sanitized
    assert str(tmp_path / "MEMORY.md") in sanitized
    assert str(tmp_path / "memory") in sanitized


def test_sanitize_memory_watch_paths_adds_memory_md_when_missing(tmp_path) -> None:
    watch_paths = [str(tmp_path / "memory")]

    sanitized = MemoryManager._sanitize_memory_watch_paths(
        watch_paths=watch_paths,
        working_path=tmp_path,
    )

    assert sanitized[0] == str(tmp_path / "MEMORY.md")
    assert str(tmp_path / "memory") in sanitized


def test_patch_memory_watcher_paths_touches_memory_md(tmp_path) -> None:
    watcher_config = SimpleNamespace(
        watch_paths=[
            str(tmp_path / "memory.md"),
            str(tmp_path / "memory"),
        ],
    )
    manager = MemoryManager.__new__(MemoryManager)
    manager.working_path = tmp_path
    manager.service_context = SimpleNamespace(
        service_config=SimpleNamespace(
            file_watchers={
                "default": watcher_config,
            },
        ),
    )

    MemoryManager._patch_memory_watcher_paths(manager)

    assert (tmp_path / "MEMORY.md").exists()
    assert str(tmp_path / "memory.md") not in watcher_config.watch_paths
    assert watcher_config.watch_paths[0] == str(tmp_path / "MEMORY.md")
