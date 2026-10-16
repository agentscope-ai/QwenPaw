# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import io
import logging
import logging.handlers
import sys
from pathlib import Path

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
    crash_log_path = tmp_path / "desktop-crash.log"
    crash_log_path.write_text("previous crash\n", encoding="utf-8")
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()
    faulthandler_calls = []

    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    monkeypatch.setenv("QWENPAW_LOG_MAX_BACKUPS", "3")
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
        assert faulthandler_calls[0]["file"].name.endswith("desktop-crash.log")
        assert (tmp_path / "desktop-crash.log.1").read_text(
            encoding="utf-8",
        ) == "previous crash\n"
    finally:
        crash_log_file = getattr(tauri_logging, "_CRASH_LOG_FILE", None)
        if crash_log_file is not None:
            crash_log_file.close()
            tauri_logging._CRASH_LOG_FILE = None
        logger = logging.getLogger("qwenpaw")
        for handler in list(logger.handlers):
            base = getattr(handler, "baseFilename", None)
            if base is not None and base == str(log_path.resolve()):
                logger.removeHandler(handler)
                handler.close()


def test_sidecar_tee_output_triggers_log_rotation(monkeypatch, tmp_path):
    log_path = tmp_path / "desktop.log"
    primary_stdout = io.StringIO()
    primary_stderr = io.StringIO()

    monkeypatch.setattr(sys, "stdout", primary_stdout)
    monkeypatch.setattr(sys, "stderr", primary_stderr)
    monkeypatch.setattr(
        tauri_logging.faulthandler,
        "enable",
        lambda **kwargs: None,
    )
    original_rename = logging.handlers.os.rename
    rename_sources = []

    def deny_rename_while_legacy_tee_is_open(source, destination):
        legacy_handle = getattr(tauri_logging, "_LOG_FILE", None)
        if (
            source == str(log_path)
            and legacy_handle is not None
            and not legacy_handle.closed
        ):
            raise PermissionError("legacy tee handle denies delete sharing")
        original_rename(source, destination)
        rename_sources.append(source)

    monkeypatch.setattr(
        logging.handlers.os,
        "rename",
        deny_rename_while_legacy_tee_is_open,
    )

    try:
        tauri_logging.install_sidecar_logging(log_path)
        handler = next(
            handler
            for handler in logging.getLogger("qwenpaw").handlers
            if getattr(handler, "baseFilename", None)
            == str(log_path.resolve())
        )
        handler.maxBytes = handler.stream.tell() + 3

        print("sidecar line")
        sys.stdout.write("unpaired surrogate: \udcff\n")
        logging.getLogger("qwenpaw.tauri").info("trigger rollover")
        sys.stdout.flush()

        assert (tmp_path / "desktop.log.1").exists()
        assert getattr(tauri_logging, "_LOG_FILE", None) is None
        assert str(log_path) in rename_sources
        log_contents = "\n".join(
            path.read_text(encoding="utf-8")
            for path in tmp_path.glob("desktop.log*")
        )
        assert "sidecar line" in log_contents
        assert "unpaired surrogate: ?\n" in log_contents
        assert "trigger rollover" in log_contents
        assert primary_stdout.getvalue() == (
            "sidecar line\nunpaired surrogate: \udcff\n"
        )
    finally:
        legacy_handle = getattr(tauri_logging, "_LOG_FILE", None)
        if legacy_handle is not None:
            legacy_handle.close()
            tauri_logging._LOG_FILE = None
        crash_log_file = getattr(tauri_logging, "_CRASH_LOG_FILE", None)
        if crash_log_file is not None:
            crash_log_file.close()
            tauri_logging._CRASH_LOG_FILE = None
        logger = logging.getLogger("qwenpaw")
        for handler in list(logger.handlers):
            base = getattr(handler, "baseFilename", None)
            if base is not None and base == str(log_path.resolve()):
                logger.removeHandler(handler)
                handler.close()


def test_locked_previous_crash_log_does_not_block_sidecar_startup(
    monkeypatch,
    tmp_path,
    caplog,
):
    log_path = tmp_path / "desktop.log"
    crash_log_path = tmp_path / "desktop-crash.log"
    crash_log_path.write_text("previous crash\n", encoding="utf-8")
    (tmp_path / "desktop-crash.log.1").write_text(
        "older crash\n",
        encoding="utf-8",
    )
    original_replace = Path.replace

    def deny_crash_log_replace(path, target):
        if path == crash_log_path:
            raise PermissionError("crash log is open elsewhere")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", deny_crash_log_replace)
    monkeypatch.setattr(
        tauri_logging.faulthandler,
        "enable",
        lambda **kwargs: None,
    )

    try:
        tauri_logging.install_sidecar_logging(log_path)

        assert tauri_logging._CRASH_LOG_FILE is not None
        assert "Could not rotate previous crash logs" in caplog.text
        assert (tmp_path / "desktop-crash.log.2").read_text(
            encoding="utf-8",
        ) == "older crash\n"
    finally:
        if tauri_logging._CRASH_LOG_FILE is not None:
            tauri_logging._CRASH_LOG_FILE.close()
            tauri_logging._CRASH_LOG_FILE = None
        logger = logging.getLogger("qwenpaw")
        for handler in list(logger.handlers):
            base = getattr(handler, "baseFilename", None)
            if base is not None and base == str(log_path.resolve()):
                logger.removeHandler(handler)
                handler.close()
