# -*- coding: utf-8 -*-
"""Tests for asynchronous and atomic filesystem utilities."""

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

from qwenpaw.utils.io_utils import (
    append_text_async,
    read_bytes_async,
    read_json_async,
    read_text_async,
    run_sync_io,
    write_bytes_async,
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
            "qwenpaw.utils.io_utils.os.replace",
            side_effect=PermissionError("locked"),
        ),
        pytest.raises(PermissionError, match="locked"),
    ):
        write_text_atomic(path, "new")

    assert path.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".state.txt.*.tmp"))


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows does not expose complete POSIX permission bits",
)
def test_write_text_atomic_preserves_existing_mode(tmp_path: Path) -> None:
    """Replacing an existing file keeps its permission bits."""
    path = tmp_path / "state.txt"
    path.write_text("old", encoding="utf-8")
    path.chmod(0o640)

    write_text_atomic(path, "new")

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX umask semantics do not apply on Windows",
)
def test_write_text_atomic_new_state_file_is_private(tmp_path: Path) -> None:
    """New internal state remains private even under a permissive umask."""
    path = tmp_path / "state.txt"
    previous_umask = os.umask(0)
    try:
        write_text_atomic(path, "new")
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX umask semantics do not apply on Windows",
)
def test_write_text_atomic_uses_explicit_user_mode(tmp_path: Path) -> None:
    """A complete user artifact receives its explicit non-writable mode."""
    path = tmp_path / "artifact.txt"
    previous_umask = os.umask(0o027)
    try:
        write_text_atomic(path, "new", new_file_mode=0o644)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(path.stat().st_mode) == 0o644


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX permission bits are required",
)
def test_write_text_atomic_temp_is_private_while_writing(
    tmp_path: Path,
) -> None:
    """The temporary inode stays private until complete content is synced."""
    path = tmp_path / "artifact.txt"
    observed_mode: int | None = None
    real_fsync = os.fsync

    def inspect_fsync(fd: int) -> None:
        nonlocal observed_mode
        observed_mode = stat.S_IMODE(os.fstat(fd).st_mode)
        real_fsync(fd)

    with patch("qwenpaw.utils.io_utils.os.fsync", inspect_fsync):
        write_text_atomic(path, "new", new_file_mode=0o644)

    assert observed_mode == 0o600
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX permission bits are required",
)
def test_write_text_atomic_sets_existing_mode_before_replace(
    tmp_path: Path,
) -> None:
    """Atomic publication exposes the preserved mode immediately."""
    path = tmp_path / "state.txt"
    path.write_text("old", encoding="utf-8")
    path.chmod(0o640)
    observed_mode: int | None = None
    real_replace = os.replace

    def inspect_replace(source: Path, destination: Path) -> None:
        nonlocal observed_mode
        observed_mode = stat.S_IMODE(Path(source).stat().st_mode)
        real_replace(source, destination)

    with patch("qwenpaw.utils.io_utils.os.replace", inspect_replace):
        write_text_atomic(path, "new")

    assert observed_mode == 0o640
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
        patch("qwenpaw.utils.io_utils.write_json_atomic", fake_write),
        patch("qwenpaw.utils.io_utils.read_json", fake_read),
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
        "qwenpaw.utils.io_utils.write_json_atomic",
        delayed_write,
    ):
        task = asyncio.create_task(
            write_json_atomic_async(path, {"ok": True}),
        )
        await run_sync_io(started.wait, 2)
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        await task


@pytest.mark.asyncio
async def test_async_plain_file_helpers_round_trip(tmp_path: Path) -> None:
    """Plain helpers expose common file operations without manual offload."""
    text_path = tmp_path / "events.txt"
    bytes_path = tmp_path / "artifact.bin"

    await append_text_async(text_path, "first\n")
    await append_text_async(text_path, "second\n")
    await write_bytes_async(bytes_path, b"\x00\x01")

    assert await read_text_async(text_path) == "first\nsecond\n"
    assert await read_bytes_async(bytes_path) == b"\x00\x01"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX umask semantics do not apply on Windows",
)
async def test_write_bytes_async_publishes_only_new_files(
    tmp_path: Path,
) -> None:
    """Explicit publication mode applies only when creating a new file."""
    new_path = tmp_path / "new.bin"
    existing_path = tmp_path / "existing.bin"
    existing_path.write_bytes(b"old")
    existing_path.chmod(0o640)
    previous_umask = os.umask(0o077)
    try:
        await write_bytes_async(
            new_path,
            b"new",
            new_file_mode=0o644,
        )
        await write_bytes_async(
            existing_path,
            b"updated",
            new_file_mode=0o644,
        )
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(new_path.stat().st_mode) == 0o644
    assert stat.S_IMODE(existing_path.stat().st_mode) == 0o640


@pytest.mark.asyncio
async def test_cancelled_append_holds_lock_until_worker_finishes(
    tmp_path: Path,
) -> None:
    """Cancellation must not release a path lock before its thread exits."""
    path = tmp_path / "events.txt"
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()

    def delayed_append(
        _path: Path | str,
        content: str,
        _encoding: str,
    ) -> None:
        if content == "first":
            first_started.set()
            release_first.wait(timeout=2)
        else:
            second_started.set()

    with patch("qwenpaw.utils.io_utils._append_text", delayed_append):
        first = asyncio.create_task(append_text_async(path, "first"))
        while not first_started.is_set():
            await asyncio.sleep(0)

        first.cancel()
        second = asyncio.create_task(append_text_async(path, "second"))
        await asyncio.sleep(0.05)

        assert not second_started.is_set()
        release_first.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second

    assert second_started.is_set()
