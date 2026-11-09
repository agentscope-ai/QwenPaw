# -*- coding: utf-8 -*-
"""Unit tests for the legacy pywebview desktop bridge."""

# pylint: disable=protected-access

import io
import json
import signal
import subprocess
import sys
import tempfile
import time
import types
import urllib.request
from pathlib import Path

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


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="the decoded-path branch only runs on Windows",
)
def test_open_workspace_html_opens_the_decoded_local_path(
    monkeypatch,
) -> None:
    """A percent-encoded UTF-8 file URI opens via its decoded local path.

    Windows ShellExecute percent-decodes file URLs with the ANSI code page,
    so a UTF-8 (Chinese) workspace path sent as ``file:///E:/%E5%...``
    failed with ERROR_FILE_NOT_FOUND (issue #8502).
    """
    workspace_dir = Path(tempfile.mkdtemp())
    report = workspace_dir / "工作区" / "report.html"
    report.parent.mkdir(parents=True)
    report.write_text("<html></html>", encoding="utf-8")
    encoded_uri = report.as_uri()

    opened: list[str] = []

    def fake_browser_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(desktop_cmd.webbrowser, "open", fake_browser_open)

    def fake_urlopen(request: urllib.request.Request) -> _Response:
        return _Response(json.dumps({"uri": encoded_uri}).encode("utf-8"))

    monkeypatch.setattr(desktop_cmd, "urlopen", fake_urlopen)

    resolved = desktop_cmd.WebViewAPI().open_workspace_html(
        "http://127.0.0.1:43123/api/workspace/html-file-uri",
        {},
    )

    assert resolved is True
    assert opened == [str(report)]


def test_open_workspace_html_keeps_the_file_uri_off_windows(
    monkeypatch,
) -> None:
    """Non-Windows platforms keep receiving the original file URI.

    macOS ``webbrowser.open`` goes through AppleScript ``open location``,
    which expects a URL — a bare path like ``/tmp/report.html`` breaks
    HTML preview there (review comment on PR #8524).
    """
    opened: list[str] = []

    def fake_browser_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(desktop_cmd.webbrowser, "open", fake_browser_open)

    def fake_urlopen(request: urllib.request.Request) -> _Response:
        uri = "file:///tmp/report.html"
        return _Response(json.dumps({"uri": uri}).encode("utf-8"))

    monkeypatch.setattr(desktop_cmd, "urlopen", fake_urlopen)
    monkeypatch.setattr(desktop_cmd.sys, "platform", "darwin")

    resolved = desktop_cmd.WebViewAPI().open_workspace_html(
        "http://127.0.0.1:43123/api/workspace/html-file-uri",
        {},
    )

    assert resolved is True
    assert opened == ["file:///tmp/report.html"]


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="the UNC decode branch only runs on Windows",
)
def test_open_workspace_html_decodes_unc_uri_with_host(monkeypatch) -> None:
    """A UNC file URI keeps its host segment after decoding (Windows).

    ``file://server/share/report.html`` carries the host in ``netloc``;
    decoding only ``path`` produced ``\\share\\report.html`` and lost the
    ``\\\\server`` prefix (review comment on PR #8524).
    """
    opened: list[str] = []

    def fake_browser_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(desktop_cmd.webbrowser, "open", fake_browser_open)

    def fake_urlopen(request: urllib.request.Request) -> _Response:
        uri = "file://server/share/report.html"
        return _Response(json.dumps({"uri": uri}).encode("utf-8"))

    monkeypatch.setattr(desktop_cmd, "urlopen", fake_urlopen)
    monkeypatch.setattr(desktop_cmd.sys, "platform", "win32")

    resolved = desktop_cmd.WebViewAPI().open_workspace_html(
        "http://127.0.0.1:43123/api/workspace/html-file-uri",
        {},
    )

    assert resolved is True
    assert opened == ["\\\\server\\share\\report.html"]


def test_open_workspace_html_rejects_non_loopback_target() -> None:
    assert (
        desktop_cmd.WebViewAPI().open_workspace_html(
            "http://example.invalid/api/workspace/html-file-uri",
            {},
        )
        is False
    )
