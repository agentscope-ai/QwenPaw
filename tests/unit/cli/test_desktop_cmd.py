# -*- coding: utf-8 -*-
"""Unit tests for the legacy pywebview desktop bridge."""

import io
import types
import urllib.request

from qwenpaw.cli import desktop_cmd
from qwenpaw.cli.desktop_cmd import _shutdown_backend_process


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class _Process:
    pid = 17944

    def __init__(self) -> None:
        self.wait_timeouts: list[float] = []

    def wait(self, timeout: float) -> int:
        self.wait_timeouts.append(timeout)
        return 0


def test_shutdown_backend_process_uses_shared_graceful_shutdown(
    monkeypatch,
) -> None:
    proc = _Process()
    terminated: list[int] = []

    def terminate(pid: int) -> bool:
        terminated.append(pid)
        return True

    monkeypatch.setattr(
        desktop_cmd,
        "_terminate_pid",
        terminate,
    )

    assert _shutdown_backend_process(proc) is True
    assert terminated == [17944]
    assert proc.wait_timeouts == [1.0]


def test_shutdown_backend_process_reports_failed_force_fallback(
    monkeypatch,
) -> None:
    proc = _Process()
    monkeypatch.setattr(desktop_cmd, "_terminate_pid", lambda _pid: False)

    assert _shutdown_backend_process(proc) is False
    assert not proc.wait_timeouts


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
