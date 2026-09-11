# -*- coding: utf-8 -*-
"""Protocol and lifecycle tests for the scoped Git blob batch reader."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from qwenpaw.checkpoints.git_batch import GitBlobBatch
from qwenpaw.checkpoints.models import CheckpointError


def _batch(
    tmp_path: Path,
    script: str,
    *,
    timeout: float = 5,
) -> GitBlobBatch:
    return GitBlobBatch(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=os.environ,
        timeout=timeout,
    )


def test_batch_reader_streams_binary_blobs(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        "for request in sys.stdin.buffer:\n"
        "    key = request[:-1]\n"
        "    data = b'first\\n\\x00last' if key == b'one' else b''\n"
        "    size = str(len(data)).encode()\n"
        "    sys.stdout.buffer.write(key + b' blob ' + size + b'\\n')\n"
        "    sys.stdout.buffer.write(data + b'\\n')\n"
        "    sys.stdout.buffer.flush()\n"
    )

    with _batch(tmp_path, script) as blobs:
        with blobs.stream_blob("one", error_message="missing") as stream:
            assert stream.size == len(b"first\n\x00last")
            assert stream.read(2) == b"fi"
            assert stream.read(3) == b"rst"
            assert stream.read() == b"\n\x00last"
        assert blobs.read_blob("two", error_message="missing") == b""


def test_batch_reader_drains_partially_read_blob(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        "for request in sys.stdin.buffer:\n"
        "    key = request[:-1]\n"
        "    data = b'first' if key == b'one' else b'second'\n"
        "    size = str(len(data)).encode()\n"
        "    sys.stdout.buffer.write(key + b' blob ' + size + b'\\n')\n"
        "    sys.stdout.buffer.write(data + b'\\n')\n"
        "    sys.stdout.buffer.flush()\n"
    )

    with _batch(tmp_path, script) as blobs:
        with blobs.stream_blob("one", error_message="missing") as stream:
            assert stream.read(1) == b"f"
        assert blobs.read_blob("two", error_message="missing") == b"second"


def test_batch_reader_reports_early_process_failure(tmp_path: Path) -> None:
    script = "import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n"

    with pytest.raises(CheckpointError, match="boom"):
        with _batch(tmp_path, script) as blobs:
            blobs.read_blob("object", error_message="missing")


def test_batch_reader_reports_failure_after_response(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        "sys.stdin.buffer.readline()\n"
        "sys.stdout.buffer.write(b'object blob 1\\nx\\n')\n"
        "sys.stdout.buffer.flush()\n"
        "sys.exit(3)\n"
    )

    with pytest.raises(CheckpointError, match="status 3"):
        with _batch(tmp_path, script) as blobs:
            assert blobs.read_blob("object", error_message="missing") == b"x"


def test_batch_reader_times_out_and_reaps_process(tmp_path: Path) -> None:
    script = "import sys, time\nsys.stdin.buffer.readline()\ntime.sleep(30)\n"

    with pytest.raises(CheckpointError, match="timed out"):
        with _batch(tmp_path, script, timeout=0.1) as blobs:
            blobs.read_blob("object", error_message="missing")
