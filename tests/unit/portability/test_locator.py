# -*- coding: utf-8 -*-
"""Cross-user and cross-platform source-location regression tests."""

from pathlib import Path

import pytest

from qwenpaw.portability.providers.locator import resolve_source_location


def test_codex_location_uses_each_users_home(tmp_path: Path) -> None:
    home = tmp_path / "another-user"
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True)

    location = resolve_source_location(
        "codex",
        user_home=home,
        environ={},
    )

    assert location.data_home == str(codex_home.resolve())
    assert location.data_home_source == "platform_default"
    assert location.data_home_exists is True


@pytest.mark.parametrize(
    ("platform_name", "environment", "relative"),
    [
        (
            "darwin",
            {},
            Path("Library/Application Support/Qoder/User"),
        ),
        (
            "linux",
            {},
            Path(".config/Qoder/User"),
        ),
        (
            "linux",
            {"XDG_CONFIG_HOME": "/opt/user-config"},
            Path("/opt/user-config/Qoder/User"),
        ),
        (
            "win32",
            {"APPDATA": "/windows/AppData/Roaming"},
            Path("/windows/AppData/Roaming/Qoder/User"),
        ),
    ],
)
def test_qoder_editor_location_is_platform_specific(
    tmp_path: Path,
    platform_name: str,
    environment: dict[str, str],
    relative: Path,
) -> None:
    home = tmp_path / "user"
    location = resolve_source_location(
        "qoder",
        user_home=home,
        platform_name=platform_name,
        environ=environment,
    )
    expected = relative if relative.is_absolute() else home / relative

    assert location.data_home == str((home / ".qoder").resolve())
    assert location.user_data_home == str(expected.resolve())


def test_qoder_dedicated_environment_variables_are_honored(
    tmp_path: Path,
) -> None:
    qoder_home = tmp_path / "qoder-home"
    user_data = tmp_path / "qoder-user-data"

    location = resolve_source_location(
        "qoder",
        user_home=tmp_path,
        environ={
            "QODER_HOME": str(qoder_home),
            "QODER_USER_DATA_HOME": str(user_data),
        },
    )

    assert location.data_home == str(qoder_home.resolve())
    assert location.user_data_home == str(user_data.resolve())
    assert location.data_home_source == "environment:QODER_HOME"
