# -*- coding: utf-8 -*-
"""Tests for shared channel utilities."""
# pylint: disable=protected-access

import base64
import asyncio
import threading
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest

from qwenpaw.app.channels.utils import (
    MediaDataError,
    data_url_filename,
    materialize_data_url,
    parse_data_url,
    parse_data_url_async,
)
from qwenpaw.app.channels import utils as channel_utils


PNG_DATA_URL = (
    "data:image/png;base64," + base64.b64encode(b"png-data").decode()
)


def test_parse_data_url_decodes_payload() -> None:
    """Base64 data URLs should return bytes and normalized metadata."""
    media = parse_data_url(PNG_DATA_URL)

    assert media is not None
    assert media.data == b"png-data"
    assert media.media_type == "image/png"
    assert media.suffix == ".png"


def test_parse_data_url_rejects_invalid_base64() -> None:
    """Malformed Base64 should fail before any filesystem access."""
    with pytest.raises(MediaDataError):
        parse_data_url("data:image/png;base64,not-valid!")


def test_parse_data_url_enforces_size_limit() -> None:
    """Decoded media must respect the configured size limit."""
    with pytest.raises(MediaDataError):
        parse_data_url(PNG_DATA_URL, max_bytes=2)


async def test_materialize_data_url_cleans_up_file(tmp_path) -> None:
    """Generated files should exist only for the send operation."""
    async with materialize_data_url(
        PNG_DATA_URL,
        tmp_path,
        filename_hint="screen capture.png",
    ) as media:
        assert media is not None
        materialized = Path(media.path)
        assert materialized.read_bytes() == b"png-data"
        assert materialized.suffix == ".png"
        assert media.filename == "screen capture.png"

    assert not materialized.exists()


@pytest.mark.parametrize("as_uri", [False, True])
async def test_materialize_data_url_preserves_local_path(
    tmp_path,
    as_uri,
) -> None:
    """Non-data references should not be rewritten."""
    local_path = tmp_path / "file.bin"
    local_path.write_bytes(b"data")

    source = local_path.as_uri() if as_uri else str(local_path)
    assert await parse_data_url_async(source) is None
    async with materialize_data_url(
        source,
        tmp_path / "unused",
        filename_hint="ignored.png",
        max_bytes=1,
    ) as media:
        assert media.path == source
        assert media.filename is None

    assert local_path.read_bytes() == b"data"
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        (None, "file.png"),
        ("", "file.png"),
        ("capture", "capture.png"),
        ("screen capture.png", "screen capture.png"),
        ("../../capture.png", "capture.png"),
        (r"C:\media\capture.png", "capture.png"),
    ],
)
def test_data_url_filename_uses_portable_basename(hint, expected) -> None:
    """Display names retain the supplied basename on every platform."""
    assert data_url_filename(hint, ".png") == expected


@pytest.mark.parametrize("materialize", [False, True])
async def test_data_url_preparation_runs_off_loop(
    tmp_path,
    materialize,
) -> None:
    """Parsing and file writes run on a worker while the loop progresses."""
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    started = asyncio.Event()
    release = threading.Event()
    original = parse_data_url
    worker_threads = []

    def slow_parse(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    async def prepare():
        if materialize:
            async with materialize_data_url(PNG_DATA_URL, tmp_path):
                pass
        else:
            await parse_data_url_async(PNG_DATA_URL)

    with patch.object(channel_utils, "parse_data_url", side_effect=slow_parse):
        task = asyncio.create_task(prepare())
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            assert not task.done()
            assert len(worker_threads) == 1
            assert worker_threads[0] != loop_thread
        finally:
            release.set()
            await task


@pytest.mark.parametrize("cancel_during_creation", [False, True])
async def test_materialize_cancellation_cleans_up(
    tmp_path,
    cancel_during_creation,
) -> None:
    """Cancellation during preparation or sending never leaves a file."""
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    sending = asyncio.Event()
    original = channel_utils._materialize_data_url

    def slow_create(*args, **kwargs):
        media = original(*args, **kwargs)
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=5)
        return media

    async def send():
        async with materialize_data_url(PNG_DATA_URL, tmp_path):
            sending.set()
            await asyncio.Future()

    with patch.object(
        channel_utils,
        "_materialize_data_url",
        side_effect=slow_create,
    ):
        task = asyncio.create_task(send())
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            if not cancel_during_creation:
                release.set()
                await asyncio.wait_for(sending.wait(), timeout=2)
            task.cancel()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert not list(tmp_path.iterdir())


async def test_materialize_send_error_cleans_up(tmp_path) -> None:
    """An upload failure must still release the temporary file."""
    with pytest.raises(RuntimeError, match="upload failed"):
        async with materialize_data_url(PNG_DATA_URL, tmp_path):
            raise RuntimeError("upload failed")
    assert not list(tmp_path.iterdir())


async def test_materialize_write_error_cleans_up(tmp_path) -> None:
    """A failed disk write propagates without leaving the created file."""
    original = channel_utils.os.fdopen

    @contextmanager
    def failing_open(*args, **kwargs):
        with original(*args, **kwargs):
            yield Mock(write=Mock(side_effect=OSError("disk error")))

    with patch.object(channel_utils.os, "fdopen", side_effect=failing_open):
        with pytest.raises(OSError, match="disk error"):
            async with materialize_data_url(PNG_DATA_URL, tmp_path):
                pytest.fail("Preparation should have failed")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("source", "max_bytes"),
    [("data:image/png;base64,invalid!", 1024), (PNG_DATA_URL, 2)],
)
async def test_materialize_rejected_data_creates_no_file(
    source,
    max_bytes,
    tmp_path,
) -> None:
    """Invalid and oversized media never enter the filesystem stage."""
    mkdir = Mock(side_effect=AssertionError("Unexpected filesystem access"))
    with patch.object(Path, "mkdir", mkdir):
        async with materialize_data_url(
            source,
            tmp_path,
            max_bytes=max_bytes,
        ) as media:
            assert media is None
