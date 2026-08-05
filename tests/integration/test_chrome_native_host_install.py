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
def test_recorded_probe_failure_blocks_installed(
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

    assert status["installed"] is False
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
