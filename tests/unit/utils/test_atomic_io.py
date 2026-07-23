# -*- coding: utf-8 -*-
"""Tests for cross-platform atomic file writes."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from qwenpaw.utils.atomic_io import (
    read_json_async,
    write_json_atomic,
    write_json_atomic_async,
    write_text_atomic,
    write_yaml_atomic,
)


def test_write_json_atomic_replaces_complete_document(tmp_path: Path) -> None:
    """JSON writes replace the destination with one complete document."""
    path = tmp_path / "state.json"
    path.write_text("old", encoding="utf-8")

    write_json_atomic(path, {"value": "new"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": "new"}
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_write_text_atomic_preserves_destination_on_replace_error(
    tmp_path: Path,
) -> None:
    """A failed Windows-style replace leaves the previous file intact."""
    path = tmp_path / "state.txt"
    path.write_text("old", encoding="utf-8")

    with (
        patch(
            "qwenpaw.utils.atomic_io.os.replace",
            side_effect=PermissionError("locked"),
        ),
        pytest.raises(PermissionError, match="locked"),
    ):
        write_text_atomic(path, "new")

    assert path.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".state.txt.*.tmp"))


def test_write_text_atomic_preserves_existing_mode(tmp_path: Path) -> None:
    """Replacing an existing file keeps its permission bits."""
    path = tmp_path / "state.txt"
    path.write_text("old", encoding="utf-8")
    path.chmod(0o640)

    write_text_atomic(path, "new")

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_write_yaml_atomic_serializes_and_appends_content(
    tmp_path: Path,
) -> None:
    """YAML and optional trailing content share one atomic replacement."""
    path = tmp_path / "state.yaml"

    write_yaml_atomic(
        path,
        {"name": "QwenPaw"},
        extra_content="# managed\n",
    )

    content = path.read_text(encoding="utf-8")
    assert yaml.safe_load(content) == {"name": "QwenPaw"}
    assert content.endswith("# managed\n")


@pytest.mark.skipif(
    os.name == "nt",
    reason="symlink creation needs privileges",
)
def test_write_text_atomic_preserves_symlink(tmp_path: Path) -> None:
    """Writing through a symlink replaces its target, not the link."""
    target = tmp_path / "target.txt"
    target.write_text("old", encoding="utf-8")
    link = tmp_path / "state.txt"
    link.symlink_to(target.name)

    write_text_atomic(link, "new")

    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "new"


@pytest.mark.asyncio
async def test_async_json_helpers_run_sync_io_in_worker_thread(
    tmp_path: Path,
) -> None:
    """Async JSON helpers keep their synchronous work off the event loop."""
    path = tmp_path / "state.json"
    event_loop_thread = threading.get_ident()
    write_thread: int | None = None
    read_thread: int | None = None

    def fake_write(*_args, **_kwargs) -> None:
        nonlocal write_thread
        write_thread = threading.get_ident()

    def fake_read(*_args, **_kwargs) -> dict[str, bool]:
        nonlocal read_thread
        read_thread = threading.get_ident()
        return {"ok": True}

    with (
        patch("qwenpaw.utils.atomic_io.write_json_atomic", fake_write),
        patch("qwenpaw.utils.atomic_io.read_json", fake_read),
    ):
        await write_json_atomic_async(path, {"ok": True})
        payload = await read_json_async(path)

    assert payload == {"ok": True}
    assert write_thread is not None
    assert read_thread is not None
    assert write_thread != event_loop_thread
    assert read_thread != event_loop_thread


@pytest.mark.asyncio
async def test_async_json_write_allows_event_loop_progress(
    tmp_path: Path,
) -> None:
    """A delayed synchronous write does not delay unrelated coroutines."""
    path = tmp_path / "state.json"
    started = threading.Event()
    release = threading.Event()

    def delayed_write(*_args, **_kwargs) -> None:
        started.set()
        release.wait(timeout=2)

    with patch(
        "qwenpaw.utils.atomic_io.write_json_atomic",
        delayed_write,
    ):
        task = asyncio.create_task(
            write_json_atomic_async(path, {"ok": True}),
        )
        await asyncio.to_thread(started.wait, 2)
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        await task
