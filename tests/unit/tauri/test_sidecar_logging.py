# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import io
import logging
import sys

from qwenpaw.tauri import sidecar_logging as tauri_logging


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
    tmp_path,
):
    log_path = tmp_path / "desktop.log"
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    faulthandler_calls = []

    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    monkeypatch.setattr(
        tauri_logging.faulthandler,
        "enable",
        lambda **kwargs: faulthandler_calls.append(kwargs),
    )

    try:
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
    finally:
        if tauri_logging._LOG_FILE is not None:
            tauri_logging._LOG_FILE.close()
            tauri_logging._LOG_FILE = None
        logger = logging.getLogger("qwenpaw")
        for handler in list(logger.handlers):
            base = getattr(handler, "baseFilename", None)
            if base is not None and base == str(log_path.resolve()):
                logger.removeHandler(handler)
                handler.close()
