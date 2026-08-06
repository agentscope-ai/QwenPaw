# -*- coding: utf-8 -*-
"""Chrome plugin integration contracts grouped by runtime boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from plugins.bundle.chrome import extension_setup

# test_chrome_host_launcher.py

# pylint: disable=protected-access,unused-argument


SETUP_SOURCE = Path("plugins/bundle/chrome/extension_setup.py")


# test_chrome_host_probe_gate.py

# pylint: disable=protected-access,unused-argument


@pytest.mark.integration
@pytest.mark.p1
def test_probe_round_trips_through_the_real_launcher(
    isolated_home: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", sys.executable)
    extension_setup.setup_extension_files(home=isolated_home)
    launcher = extension_setup.native_host_launcher_path(
        isolated_home / ".qwenpaw",
    )

    outcome = extension_setup._probe_native_host(launcher)

    assert outcome["ok"] is True


@pytest.mark.integration
@pytest.mark.p2
def test_broken_launcher_reports_failure_without_raising(
    tmp_path: Path,
    isolated_home: Path,
) -> None:
    launcher = tmp_path / "qwenpaw-nm-host"
    launcher.write_text("#!/usr/bin/env sh\nexit 3\n", encoding="utf-8")
    launcher.chmod(0o755)

    outcome = extension_setup._probe_native_host(launcher)

    assert outcome["ok"] is False
    assert outcome["stage"]


@pytest.mark.integration
@pytest.mark.p2
def test_recorded_probe_failure_is_diagnostic_only(
    isolated_home: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", sys.executable)
    extension_setup.setup_extension_files(home=isolated_home)
    state_path = (
        isolated_home
        / ".qwenpaw"
        / (extension_setup.INSTALL_MODE_STATE_FILENAME)
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["native_host_probe"] = {"ok": False, "stage": "launch"}
    state_path.write_text(json.dumps(state), encoding="utf-8")

    status = extension_setup.extension_install_status(home=isolated_home)

    assert status["installed"] is True
    assert status["native_host_repair_required"] is True
    assert status["native_host_repair_instruction"]


@pytest.mark.integration
@pytest.mark.p1
def test_successful_install_records_a_passing_probe(
    isolated_home: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", sys.executable)
    result = extension_setup.setup_extension_files(home=isolated_home)

    state_path = (
        isolated_home
        / ".qwenpaw"
        / (extension_setup.INSTALL_MODE_STATE_FILENAME)
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["native_host_probe"]["ok"] is True
    assert result["installed"] is True


def test_non_reset_repair_preserves_existing_bridge_token(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", sys.executable)
    extension_setup.setup_extension_files(home=isolated_home)
    config_path = isolated_home / ".qwenpaw" / "nm-bridge.json"
    original_token = json.loads(config_path.read_text(encoding="utf-8"))[
        "token"
    ]

    extension_setup.setup_extension_files(home=isolated_home, reset=False)
    repaired_token = json.loads(config_path.read_text(encoding="utf-8"))[
        "token"
    ]

    assert repaired_token == original_token


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            r"\\?\D:\Programs\QwenPaw Desktop\python.exe",
            r"D:\Programs\QwenPaw Desktop\python.exe",
        ),
        (
            r"\\?\UNC\server\share\python.exe",
            r"\\server\share\python.exe",
        ),
        (
            r"D:\Programs\QwenPaw Desktop\python.exe",
            r"D:\Programs\QwenPaw Desktop\python.exe",
        ),
        (
            r"D:\Programs\100% QwenPaw\python.exe",
            r"D:\Programs\100%% QwenPaw\python.exe",
        ),
    ],
)
def test_windows_batch_path_literal_normalizes_and_escapes(
    source: str,
    expected: str,
) -> None:
    assert extension_setup._windows_batch_path_literal(source) == expected


def test_windows_launcher_uses_cmd_safe_path_literals(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interpreter = r"\\?\D:\Programs\100% QwenPaw\python.exe"
    monkeypatch.setattr(
        extension_setup,
        "_resolve_host_interpreter",
        lambda: interpreter,
    )

    launcher = extension_setup._write_host(
        isolated_home / ".qwenpaw",
        platform="win32",
    )
    launcher_text = launcher.read_text(encoding="utf-8")

    assert "\\\\?\\" not in launcher_text
    assert '"D:\\Programs\\100%% QwenPaw\\python.exe"' in launcher_text
    assert launcher_text.endswith('" %*\n')


# test_chrome_extensions_page_opener.py


@pytest.mark.integration
@pytest.mark.p2
def test_windows_chrome_locator_uses_local_appdata_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chrome = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.touch()

    class MissingRegistry:
        HKEY_CURRENT_USER = object()
        HKEY_LOCAL_MACHINE = object()

        @staticmethod
        def OpenKey(*_args):  # noqa: N802
            raise FileNotFoundError

    monkeypatch.setitem(sys.modules, "winreg", MissingRegistry)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    assert extension_setup._find_windows_chrome_executable() == chrome


@pytest.mark.integration
@pytest.mark.p2
def test_windows_open_chrome_extensions_uses_resolved_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chrome = tmp_path / "chrome.exe"
    chrome.touch()
    launched: list[tuple[list[str], dict]] = []

    def fake_popen(command: list[str], **kwargs):
        launched.append((command, kwargs))
        return object()

    monkeypatch.setattr(
        extension_setup,
        "_find_windows_chrome_executable",
        lambda: chrome,
    )
    monkeypatch.setattr(extension_setup.subprocess, "Popen", fake_popen)

    result = extension_setup.open_chrome_extensions_page(platform="win32")

    assert result == {
        "opened": True,
        "url": extension_setup.CHROME_EXTENSIONS_URL,
    }
    assert launched[0][0] == [
        str(chrome),
        extension_setup.CHROME_EXTENSIONS_URL,
    ]


@pytest.mark.integration
@pytest.mark.p2
def test_windows_open_chrome_extensions_reports_missing_chrome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        extension_setup,
        "_find_windows_chrome_executable",
        lambda: None,
    )
    monkeypatch.setattr(
        extension_setup.webbrowser,
        "open",
        lambda *_args: pytest.fail("Windows must not use the default browser"),
    )

    result = extension_setup.open_chrome_extensions_page(platform="win32")

    assert result["opened"] is False
    assert result["error"] == "Google Chrome executable was not found."


@pytest.mark.integration
@pytest.mark.p2
def test_windows_open_chrome_extensions_reports_launch_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chrome = tmp_path / "chrome.exe"
    chrome.touch()

    def raise_oserror(*_args, **_kwargs):
        raise OSError("launch denied")

    monkeypatch.setattr(
        extension_setup,
        "_find_windows_chrome_executable",
        lambda: chrome,
    )
    monkeypatch.setattr(extension_setup.subprocess, "Popen", raise_oserror)

    result = extension_setup.open_chrome_extensions_page(platform="win32")

    assert result["opened"] is False
    assert result["error"] == "Could not start Google Chrome: launch denied"


# test_chrome_install_boundary.py

SETUP = Path("plugins/bundle/chrome/extension_setup.py")
HOST = Path("plugins/bundle/chrome/assets/scripts/nm_host.py")


# test_chrome_native_host_registry.py

# pylint: disable=protected-access


KEY_PATH = (
    "Software\\Google\\Chrome\\NativeMessagingHosts\\com.qwenpaw.browser"
)


class FakeRegistry:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set_value(self, key_path: str, value: str) -> None:
        self.values[key_path] = value

    def get_value(self, key_path: str) -> str | None:
        return self.values.get(key_path)

    def delete_value(self, key_path: str) -> None:
        self.values.pop(key_path, None)


@pytest.fixture
def successful_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep fake-Windows coverage independent of a macOS batch launch."""
    monkeypatch.setattr(
        extension_setup,
        "_probe_native_host",
        lambda launcher: {"ok": True, "stage": "", "detail": ""},
    )


def _install(home: Path, registry: FakeRegistry) -> dict:
    return extension_setup.setup_extension_files(
        home=home,
        platform="win32",
        registry=registry,
    )


# test_chrome_native_manifest_path.py
