# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import io
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest

from qwenpaw.tauri import sidecar_logging as tauri_logging


def _patch_stdio(monkeypatch):
    # Patch inside the test body: pytest re-installs its own capture streams
    # between fixture setup and the test call.
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    return primary_stdout, primary_stderr


@pytest.fixture
def sidecar_env(monkeypatch, tmp_path):
    """Isolate faulthandler and the project file handler."""
    faulthandler_calls = []
    monkeypatch.setattr(
        tauri_logging.faulthandler,
        "enable",
        lambda **kwargs: faulthandler_calls.append(kwargs),
    )
    log_path = tmp_path / "desktop.log"

    yield log_path, faulthandler_calls

    tauri_logging._LOG_FILE = None
    if tauri_logging._CRASH_FD is not None:
        os.close(tauri_logging._CRASH_FD)
        tauri_logging._CRASH_FD = None
    for name in ("qwenpaw", "apscheduler"):
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            base = getattr(handler, "baseFilename", None)
            if base is not None and base == str(log_path.resolve()):
                logger.removeHandler(handler)
                handler.close()


def test_tee_stream_writes_text_to_both_streams():
    primary = io.StringIO()
    secondary = io.StringIO()
    stream = tauri_logging._TeeStream(primary, secondary)

    assert stream.write("hello") == 5
    stream.writelines([" ", "world"])

    assert primary.getvalue() == "hello world"
    assert secondary.getvalue() == "hello world"
    assert stream.writable()
    assert not stream.readable()
    assert not stream.seekable()


def test_install_sidecar_logging_writes_startup_context_and_tees_output(
    monkeypatch,
    sidecar_env,
):
    log_path, faulthandler_calls = sidecar_env
    primary_stdout, primary_stderr = _patch_stdio(monkeypatch)

    assert tauri_logging.install_sidecar_logging(log_path) == log_path

    print("stdout hello")
    print("stderr hello", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()

    content = log_path.read_text(encoding="utf-8")
    assert "qwenpaw tauri sidecar" in content
    assert "stdout hello" in content
    assert "stderr hello" in content
    assert primary_stdout.getvalue().strip() == "stdout hello"
    assert primary_stderr.getvalue().strip() == "stderr hello"

    assert faulthandler_calls
    assert faulthandler_calls[0]["all_threads"] is True
    crash_fd = faulthandler_calls[0]["file"]
    assert crash_fd == tauri_logging._CRASH_FD
    crash_path = log_path.with_name("desktop-crash.log")
    assert os.path.samestat(os.fstat(crash_fd), os.stat(crash_path))
    assert "qwenpaw tauri sidecar" in crash_path.read_text(encoding="utf-8")


def test_sidecar_log_rotates_with_teed_output(monkeypatch, sidecar_env):
    log_path, _ = sidecar_env
    _patch_stdio(monkeypatch)
    monkeypatch.setenv("QWENPAW_LOG_MAX_SIZE", "2KB")
    monkeypatch.setenv("QWENPAW_LOG_MAX_BACKUPS", "2")

    tauri_logging.install_sidecar_logging(log_path)
    for i in range(200):
        print(f"filler line {i:04d} " + "x" * 40)
        logging.getLogger("qwenpaw.tauri").info("record %d", i)
    print("after-rotation marker")

    backup = log_path.with_name("desktop.log.1")
    assert backup.exists()
    assert not log_path.with_name("desktop.log.3").exists()
    assert log_path.stat().st_size <= 2048 + 200
    # Teed output must follow the handler onto the fresh file, not keep
    # writing into the renamed backup.
    assert "after-rotation marker" in log_path.read_text(encoding="utf-8")
    assert "after-rotation marker" not in backup.read_text(encoding="utf-8")


def test_handler_stream_replaces_unencodable_text(monkeypatch, sidecar_env):
    log_path, _ = sidecar_env
    _patch_stdio(monkeypatch)
    tauri_logging.install_sidecar_logging(log_path)

    assert tauri_logging._LOG_FILE.write("bad \udc80 surrogate\n") == 16

    assert "bad ? surrogate" in log_path.read_text(encoding="utf-8")


def test_oversized_crash_log_rotates_at_startup(monkeypatch, sidecar_env):
    log_path, faulthandler_calls = sidecar_env
    _patch_stdio(monkeypatch)
    monkeypatch.setenv("QWENPAW_LOG_MAX_SIZE", "1KB")
    crash_path = log_path.with_name("desktop-crash.log")
    old_trace = "Fatal Python error: old trace\n" * 40
    crash_path.write_text(old_trace, encoding="utf-8")

    tauri_logging.install_sidecar_logging(log_path)

    backup = log_path.with_name("desktop-crash.log.1")
    assert backup.read_text(encoding="utf-8") == old_trace
    content = crash_path.read_text(encoding="utf-8")
    assert "old trace" not in content
    assert "qwenpaw tauri sidecar" in content
    # faulthandler must get the fresh file, not the rotated one.
    assert os.path.samestat(
        os.fstat(faulthandler_calls[0]["file"]),
        os.stat(crash_path),
    )


_STARTUP_CRASH_SCRIPT = """
import faulthandler, logging, sys
from pathlib import Path
import uvicorn
from qwenpaw.tauri.sidecar_logging import install_sidecar_logging

install_sidecar_logging(Path(sys.argv[1]))
# Same order as the desktop entry point: uvicorn.Config runs dictConfig,
# which closes every logging handler created so far.
uvicorn.Config(lambda scope, receive, send: None, log_level="info")
logging.getLogger("qwenpaw.tauri").info("record after uvicorn config")
print("stdout after uvicorn config", flush=True)
faulthandler._sigsegv()
"""


def test_logs_survive_uvicorn_logging_config_until_native_crash(tmp_path):
    log_path = tmp_path / "desktop.log"
    env = {**os.environ, "QWENPAW_WORKING_DIR": str(tmp_path / "home")}
    src_dir = Path(tauri_logging.__file__).resolve().parents[2]
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(src_dir), env.get("PYTHONPATH")]),
    )

    proc = subprocess.run(
        [sys.executable, "-c", _STARTUP_CRASH_SCRIPT, str(log_path)],
        env=env,
        capture_output=True,
        timeout=120,
        check=False,
    )

    assert proc.returncode != 0
    crash = log_path.with_name("desktop-crash.log").read_text(
        encoding="utf-8",
        errors="replace",
    )
    assert "most recent call first" in crash
    content = log_path.read_text(encoding="utf-8")
    assert "record after uvicorn config" in content
    assert "stdout after uvicorn config" in content
