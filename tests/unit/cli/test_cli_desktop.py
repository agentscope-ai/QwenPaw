# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.cli import desktop_cmd as desktop_cmd_module


def test_detect_windows_webview2_runtime_version_returns_first_valid(
    monkeypatch,
) -> None:
    values = iter(
        [
            "0.0.0.0",
            None,
            "136.0.3240.8",
        ],
    )

    monkeypatch.setattr(desktop_cmd_module.sys, "platform", "win32")
    monkeypatch.setattr(
        desktop_cmd_module,
        "_read_windows_registry_value",
        lambda *_args: next(values),
    )

    assert (
        desktop_cmd_module._detect_windows_webview2_runtime_version()
        == "136.0.3240.8"
    )


def test_detect_windows_webview2_runtime_version_returns_none(
    monkeypatch,
) -> None:
    monkeypatch.setattr(desktop_cmd_module.sys, "platform", "win32")
    monkeypatch.setattr(
        desktop_cmd_module,
        "_read_windows_registry_value",
        lambda *_args: "",
    )

    assert desktop_cmd_module._detect_windows_webview2_runtime_version() is None


def test_ensure_desktop_webview_available_requires_webview2_runtime(
    monkeypatch,
) -> None:
    dialogs: list[tuple[str, str]] = []

    monkeypatch.setattr(desktop_cmd_module.sys, "platform", "win32")
    monkeypatch.setattr(desktop_cmd_module, "webview", object())
    monkeypatch.setattr(
        desktop_cmd_module,
        "_detect_windows_webview2_runtime_version",
        lambda: None,
    )
    monkeypatch.setattr(
        desktop_cmd_module,
        "_show_windows_message_box",
        lambda title, message: dialogs.append((title, message)),
    )

    with pytest.raises(SystemExit) as exc_info:
        desktop_cmd_module._ensure_desktop_webview_available()

    assert exc_info.value.code == 1
    assert dialogs
    assert "WebView2 Runtime was not detected" in dialogs[0][1]


def test_start_desktop_window_forces_edgechromium_on_windows(
    monkeypatch,
) -> None:
    calls: dict[str, object] = {}

    class _FakeWebview:
        def create_window(self, *args, **kwargs) -> None:
            calls["create"] = (args, kwargs)

        def start(self, **kwargs) -> None:
            calls["start"] = kwargs

    monkeypatch.setattr(desktop_cmd_module.sys, "platform", "win32")
    monkeypatch.setattr(desktop_cmd_module, "webview", _FakeWebview())

    desktop_cmd_module._start_desktop_window("http://127.0.0.1:8088")

    assert "create" in calls
    assert calls["start"] == {
        "private_mode": False,
        "gui": "edgechromium",
    }
