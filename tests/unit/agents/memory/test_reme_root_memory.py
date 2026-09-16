# -*- coding: utf-8 -*-
"""Tests for syncing the workspace root MEMORY.md into ReMe."""

import asyncio
from pathlib import Path

import pytest
from reme.components import ApplicationContext
from reme.components.file_store import BaseFileStore
from reme.schema import FileNode
from watchfiles import Change

from qwenpaw.agents.memory.reme_root_memory import (
    RootMemorySyncStep,
    RootMemoryWatchStep,
    is_root_memory_path,
)


class _FileStore(BaseFileStore):
    def __init__(self, nodes: list[FileNode] | None = None) -> None:
        super().__init__()
        self._nodes = list(nodes or [])

    async def upsert(self, files) -> None:
        del files

    async def delete(self, path) -> None:
        del path

    async def clear(self) -> None:
        self._nodes.clear()

    async def get_nodes(self, paths: list[str] | None = None) -> list[FileNode]:
        del paths
        return list(self._nodes)

    async def get_outlinks(self, path, scope=None):
        del path, scope
        return []

    async def get_inlinks(self, path, scope=None):
        del path, scope
        return []

    async def vector_search(self, query, limit, search_filter):
        del query, limit, search_filter
        return []

    async def keyword_search(self, query, limit, search_filter):
        del query, limit, search_filter
        return []


class _RecordingRootMemorySyncStep(RootMemorySyncStep):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.dispatched_changes: list[dict[str, str]] = []

    async def dispatch_steps(self, dispatch_steps, **kwargs):
        assert dispatch_steps == ["update_index_step"]
        self.dispatched_changes = list(kwargs["changes"])
        return []


class _RecordingRootMemoryWatchStep(RootMemoryWatchStep):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.dispatched_changes: list[dict[str, str]] = []

    async def dispatch_steps(self, dispatch_steps, **kwargs):
        assert dispatch_steps == ["update_index_step"]
        self.dispatched_changes.extend(kwargs["changes"])
        return []


async def _run_sync(
    workspace: Path,
    nodes: list[FileNode] | None = None,
) -> _RecordingRootMemorySyncStep:
    app_context = ApplicationContext(workspace_dir=str(workspace))
    step = _RecordingRootMemorySyncStep(
        app_context=app_context,
        dispatch_steps=["update_index_step"],
    )
    await step(file_store=_FileStore(nodes))

    return step


@pytest.mark.asyncio
async def test_sync_emits_added_only_for_root_memory(tmp_path: Path) -> None:
    root_memory = tmp_path / "MEMORY.md"
    root_memory.write_text("root memory", encoding="utf-8")

    step = await _run_sync(tmp_path)

    assert step.dispatched_changes == [
        {"change": "added", "path": str(root_memory.absolute())},
    ]


@pytest.mark.asyncio
async def test_sync_emits_modified_when_root_memory_mtime_changes(
    tmp_path: Path,
) -> None:
    root_memory = tmp_path / "MEMORY.md"
    root_memory.write_text("updated root memory", encoding="utf-8")
    current_mtime = root_memory.stat().st_mtime

    step = await _run_sync(
        tmp_path,
        [FileNode(path="MEMORY.md", st_mtime=current_mtime - 10)],
    )

    assert step.dispatched_changes == [
        {"change": "modified", "path": str(root_memory.absolute())},
    ]


@pytest.mark.asyncio
async def test_sync_skips_unchanged_root_memory(tmp_path: Path) -> None:
    root_memory = tmp_path / "MEMORY.md"
    root_memory.write_text("unchanged root memory", encoding="utf-8")
    current_mtime = root_memory.stat().st_mtime

    step = await _run_sync(
        tmp_path,
        [FileNode(path="MEMORY.md", st_mtime=current_mtime)],
    )

    assert step.dispatched_changes == []


@pytest.mark.asyncio
async def test_sync_emits_deleted_when_indexed_root_memory_is_removed(
    tmp_path: Path,
) -> None:
    step = await _run_sync(
        tmp_path,
        [FileNode(path="MEMORY.md", st_mtime=123.0)],
    )

    assert step.dispatched_changes == [
        {"change": "deleted", "path": str((tmp_path / "MEMORY.md").absolute())},
    ]


@pytest.mark.asyncio
async def test_sync_ignores_other_root_markdown(tmp_path: Path) -> None:
    (tmp_path / "PROFILE.md").write_text("not memory", encoding="utf-8")

    step = await _run_sync(tmp_path)

    assert step.dispatched_changes == []


def test_is_root_memory_path_matches_only_exact_workspace_file(
    tmp_path: Path,
) -> None:
    assert is_root_memory_path(tmp_path / "MEMORY.md", tmp_path)
    assert not is_root_memory_path(tmp_path / "PROFILE.md", tmp_path)
    assert not is_root_memory_path(
        tmp_path / "nested" / "MEMORY.md",
        tmp_path,
    )


@pytest.mark.asyncio
async def test_watch_dispatches_only_root_memory_events(tmp_path: Path) -> None:
    stop_event = asyncio.Event()
    root_memory = tmp_path / "MEMORY.md"
    profile = tmp_path / "PROFILE.md"
    root_memory.write_text("new memory", encoding="utf-8")
    current_mtime = root_memory.stat().st_mtime

    async def fake_awatch(*paths, **kwargs):
        assert paths == (tmp_path.absolute(),)
        assert kwargs["recursive"] is False
        assert kwargs["stop_event"] is stop_event
        yield {
            (Change.added, str(root_memory)),
            (Change.modified, str(profile)),
        }
        stop_event.set()

    app_context = ApplicationContext(workspace_dir=str(tmp_path))
    step = _RecordingRootMemoryWatchStep(
        app_context=app_context,
        dispatch_steps=["update_index_step"],
        awatch_factory=fake_awatch,
    )

    await step(
        stop_event=stop_event,
        file_store=_FileStore(
            [FileNode(path="MEMORY.md", st_mtime=current_mtime)],
        ),
    )

    assert step.dispatched_changes == [
        {"change": "added", "path": str(root_memory.absolute())},
    ]


@pytest.mark.asyncio
async def test_watch_requires_background_stop_event(tmp_path: Path) -> None:
    app_context = ApplicationContext(workspace_dir=str(tmp_path))
    step = RootMemoryWatchStep(app_context=app_context)

    with pytest.raises(RuntimeError, match="requires stop_event"):
        await step()


@pytest.mark.asyncio
async def test_watch_reconciles_changes_missed_before_watcher_baseline(
    tmp_path: Path,
) -> None:
    stop_event = asyncio.Event()
    root_memory = tmp_path / "MEMORY.md"
    root_memory.write_text("updated before baseline", encoding="utf-8")

    async def fake_awatch(*paths, **kwargs):
        del paths, kwargs
        yield set()
        stop_event.set()

    app_context = ApplicationContext(workspace_dir=str(tmp_path))
    step = _RecordingRootMemoryWatchStep(
        app_context=app_context,
        dispatch_steps=["update_index_step"],
        awatch_factory=fake_awatch,
    )

    await step(
        stop_event=stop_event,
        file_store=_FileStore(
            [
                FileNode(
                    path="MEMORY.md",
                    st_mtime=root_memory.stat().st_mtime - 10,
                ),
            ],
        ),
    )

    assert step.dispatched_changes == [
        {"change": "modified", "path": str(root_memory.absolute())},
    ]
