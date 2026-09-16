# -*- coding: utf-8 -*-
"""Bridge the workspace root MEMORY.md into ReMe's file index."""

import os
from pathlib import Path
from typing import Any, Callable

from reme.components import R
from reme.schema import FileNode
from reme.steps import BaseStep
from watchfiles import Change, awatch

ROOT_MEMORY_FILENAME = "MEMORY.md"


def _normalized_absolute_path(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).absolute()))


def is_root_memory_path(
    path: str | Path,
    workspace_path: str | Path,
) -> bool:
    """Return whether path is exactly the workspace root MEMORY.md."""
    expected = Path(workspace_path) / ROOT_MEMORY_FILENAME
    return _normalized_absolute_path(path) == _normalized_absolute_path(expected)


def root_memory_events(
    raw_changes: set[tuple[Change, str]],
    workspace_path: Path,
) -> list[dict[str, str]]:
    """Normalize a watcher batch and retain only root MEMORY.md events."""
    target = (workspace_path / ROOT_MEMORY_FILENAME).absolute()
    seen: set[Change] = set()
    for change, path in raw_changes:
        supported = change in (
            Change.added,
            Change.modified,
            Change.deleted,
        )
        if supported and is_root_memory_path(path, workspace_path):
            seen.add(change)
    if not seen:
        return []
    if not target.is_file():
        final_change = Change.deleted
    elif seen == {Change.added}:
        final_change = Change.added
    else:
        final_change = Change.modified
    return [{"change": final_change.name, "path": str(target)}]


def _root_memory_changes(
    target: Path,
    indexed: FileNode | None,
) -> list[dict[str, str]]:
    """Return the single change required to synchronize root MEMORY.md."""
    absolute_target = target.absolute()
    if not target.is_file():
        if indexed is None:
            return []
        return [{"change": "deleted", "path": str(absolute_target)}]

    if indexed is None:
        return [{"change": "added", "path": str(absolute_target)}]
    if target.stat().st_mtime != indexed.st_mtime:
        return [{"change": "modified", "path": str(absolute_target)}]
    return []


@R.register("qwenpaw_root_memory_sync_step")
class RootMemorySyncStep(BaseStep):
    """Synchronize only the workspace root MEMORY.md with the file store."""

    async def execute(self):
        assert self.context is not None
        target = self.workspace_path / ROOT_MEMORY_FILENAME
        nodes = await self.file_store.get_nodes()
        indexed = next(
            (node for node in nodes if node.path == ROOT_MEMORY_FILENAME),
            None,
        )
        changes = _root_memory_changes(target, indexed)
        self.context["changes"] = changes
        if changes:
            await self.dispatch_steps(
                self.dispatch_step_specs,
                changes=changes,
            )
        self.context.response.metadata["root_memory_changes"] = len(changes)
        return self.context.response


@R.register("qwenpaw_root_memory_watch_step")
class RootMemoryWatchStep(BaseStep):
    """Watch only the workspace root MEMORY.md for index updates."""

    def __init__(
        self,
        awatch_factory: Callable[..., Any] = awatch,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._awatch_factory = awatch_factory

    def _filter(self, _change: Change, path: str) -> bool:
        return is_root_memory_path(path, self.workspace_path)

    async def execute(self):
        if self.context is None or self.context.stop_event is None:
            raise RuntimeError(
                "qwenpaw_root_memory_watch_step requires stop_event",
            )

        async for raw_changes in self._awatch_factory(
            self.workspace_path,
            watch_filter=self._filter,
            recursive=False,
            force_polling=True,
            debounce=5_000,
            step=1_000,
            poll_delay_ms=5_000,
            rust_timeout=1_000,
            yield_on_timeout=True,
            stop_event=self.context.stop_event,
        ):
            changes = root_memory_events(raw_changes, self.workspace_path)
            if not changes and not raw_changes:
                nodes = await self.file_store.get_nodes()
                indexed = next(
                    (node for node in nodes if node.path == ROOT_MEMORY_FILENAME),
                    None,
                )
                changes = _root_memory_changes(
                    self.workspace_path / ROOT_MEMORY_FILENAME,
                    indexed,
                )
            if changes:
                await self.dispatch_steps(
                    self.dispatch_step_specs,
                    changes=changes,
                )
            if self.context.stop_event.is_set():
                break
        return self.context.response
