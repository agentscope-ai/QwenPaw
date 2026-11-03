# -*- coding: utf-8 -*-
"""Unit tests for the legacy pywebview desktop bridge."""

# pylint: disable=protected-access

import io
import signal
import subprocess
import sys
import time
import types
import urllib.request

import pytest

from qwenpaw.cli import desktop_cmd, shutdown_cmd
from qwenpaw.cli.desktop_cmd import _shutdown_backend_process


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class _Process:
    pid = 17944


def test_shutdown_backend_process_uses_shared_graceful_shutdown(
    monkeypatch,
) -> None:
    proc = _Process()
    terminated: list[tuple[int, _Process]] = []

    def terminate(pid: int, *, process: _Process) -> bool:
        terminated.append((pid, process))
        return True

    monkeypatch.setattr(
        desktop_cmd,
        "_terminate_pid",
        terminate,
    )

    assert _shutdown_backend_process(proc) is True
    assert terminated == [(17944, proc)]


def test_shutdown_backend_process_reports_failed_force_fallback(
    monkeypatch,
) -> None:
    proc = _Process()
    monkeypatch.setattr(
        desktop_cmd,
        "_terminate_pid",
        lambda _pid, *, process: False,
    )

    assert _shutdown_backend_process(proc) is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal behavior")
def test_shutdown_backend_reaps_graceful_child_without_reaper(
    monkeypatch,
) -> None:
    script = (
        "import signal, sys\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "print('ready', flush=True)\n"
        "signal.pause()\n"
    )
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [sys.executable, "-u", "-c", script],
        stdout=subprocess.PIPE,
        text=True,
    )
    signals: list[signal.Signals] = []
    original_signal = shutdown_cmd._signal_process_tree_unix

    def record_signal(pid: int, sig: signal.Signals) -> None:
        signals.append(sig)
        original_signal(pid, sig)

    monkeypatch.setattr(
        shutdown_cmd,
        "_signal_process_tree_unix",
        record_signal,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        start = time.monotonic()
        assert _shutdown_backend_process(proc) is True
        assert time.monotonic() - start < 3.0
        assert proc.returncode == 0
        assert signals == [signal.SIGTERM]
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stdout is not None:
            proc.stdout.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal behavior")
def test_shutdown_backend_force_fallback_reaps_child(monkeypatch) -> None:
    script = (
        "import signal\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('ready', flush=True)\n"
        "signal.pause()\n"
    )
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        [sys.executable, "-u", "-c", script],
        stdout=subprocess.PIPE,
        text=True,
    )
    signals: list[signal.Signals] = []
    original_signal = shutdown_cmd._signal_process_tree_unix

    def record_signal(pid: int, sig: signal.Signals) -> None:
        signals.append(sig)
        original_signal(pid, sig)

    monkeypatch.setattr(
        shutdown_cmd,
        "_signal_process_tree_unix",
        record_signal,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        assert shutdown_cmd._terminate_pid(
            proc.pid,
            timeout_sec=0.2,
            process=proc,
        )
        assert proc.returncode == -signal.SIGKILL
        assert signals == [signal.SIGTERM, signal.SIGKILL]
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stdout is not None:
            proc.stdout.close()


def test_save_file_passes_headers_to_download_request(
    monkeypatch,
    tmp_path,
) -> None:
    destination = tmp_path / "backup.zip"
    monkeypatch.setattr(
        desktop_cmd,
        "webview",
        types.SimpleNamespace(
            SAVE_DIALOG=1,
            windows=[
                types.SimpleNamespace(
                    create_file_dialog=lambda *_args, **_kwargs: str(
                        destination,
                    ),
                ),
            ],
        ),
    )

    captured_url = ""
    captured_headers: dict[str, str] = {}

    def fake_urlopen(request: urllib.request.Request) -> _Response:
        nonlocal captured_headers, captured_url
        captured_url = request.full_url
        captured_headers = {
            key.lower(): value for key, value in request.header_items()
        }
        return _Response(b"zip")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    saved = desktop_cmd.WebViewAPI().save_file(
        "http://127.0.0.1:43123/api/backups/abc/export",
        "backup.zip",
        {"Authorization": "Bearer tok", "X-Agent-Id": "agent-a"},
    )

    assert saved is True
    assert destination.read_bytes() == b"zip"
    assert captured_url == "http://127.0.0.1:43123/api/backups/abc/export"
    assert captured_headers["authorization"] == "Bearer tok"
    assert captured_headers["x-agent-id"] == "agent-a"
