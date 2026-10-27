# -*- coding: utf-8 -*-
"""Integration tests for CLI update command internals.

Covers src/qwenpaw/cli/update_cmd.py (391 uncovered lines):
version comparison, PyPI release selection, install source
detection, service probing dataclasses.
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_subprocess_text_kwargs_encoding() -> None:
    """Subprocess text kwargs force utf-8 with replacement."""
    from qwenpaw.cli.update_cmd import _subprocess_text_kwargs

    kwargs = _subprocess_text_kwargs()
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"


@pytest.mark.integration
@pytest.mark.p1
def test_version_obj_parses_valid_version() -> None:
    """Valid version strings parse into Version objects."""
    from packaging.version import Version

    from qwenpaw.cli.update_cmd import _version_obj

    result = _version_obj("2.2.0b2")
    assert isinstance(result, Version)
    assert str(result) == "2.2.0b2"


@pytest.mark.integration
@pytest.mark.p1
def test_version_obj_keeps_invalid_raw() -> None:
    """Invalid version strings are returned unchanged."""
    from qwenpaw.cli.update_cmd import _version_obj

    result = _version_obj("not-a-version")
    assert result == "not-a-version"
    assert isinstance(result, str)


@pytest.mark.integration
@pytest.mark.p1
def test_is_newer_version_true() -> None:
    """Higher latest reports True."""
    from qwenpaw.cli.update_cmd import _is_newer_version

    assert _is_newer_version("2.3.0", "2.2.0") is True


@pytest.mark.integration
@pytest.mark.p1
def test_is_newer_version_false_when_equal() -> None:
    """Equal versions report False."""
    from qwenpaw.cli.update_cmd import _is_newer_version

    assert _is_newer_version("2.2.0", "2.2.0") is False


@pytest.mark.integration
@pytest.mark.p1
def test_is_newer_version_false_when_older() -> None:
    """Lower latest reports False."""
    from qwenpaw.cli.update_cmd import _is_newer_version

    assert _is_newer_version("2.1.0", "2.2.0") is False


@pytest.mark.integration
@pytest.mark.p1
def test_is_newer_version_none_when_unparseable() -> None:
    """Unparseable versions yield None (unknown)."""
    from qwenpaw.cli.update_cmd import _is_newer_version

    assert _is_newer_version("garbage", "2.2.0") is None


@pytest.mark.integration
@pytest.mark.p1
def test_is_newer_version_both_garbage_equal() -> None:
    """Two identical unparseable strings compare as not-newer."""
    from qwenpaw.cli.update_cmd import _is_newer_version

    assert _is_newer_version("abc", "abc") is False


@pytest.mark.integration
@pytest.mark.p1
def test_select_latest_version_stable() -> None:
    """Stable selection skips prereleases and empty releases."""
    from qwenpaw.cli.update_cmd import _select_latest_version

    data = {
        "releases": {
            "1.0.0": [{"url": "x"}],
            "2.0.0rc1": [{"url": "x"}],
            "2.1.0": [{"url": "x"}],
            "3.0.0": [],  # no files -> skipped
        },
    }
    assert (
        _select_latest_version(
            data,
            include_prerelease=False,
        )
        == "2.1.0"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_select_latest_version_with_prerelease() -> None:
    """Prerelease selection includes rc candidates."""
    from qwenpaw.cli.update_cmd import _select_latest_version

    data = {
        "releases": {
            "2.0.0": [{"url": "x"}],
            "2.1.0rc1": [{"url": "x"}],
        },
    }
    assert (
        _select_latest_version(
            data,
            include_prerelease=True,
        )
        == "2.1.0rc1"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_select_latest_version_invalid_releases_type() -> None:
    """Non-dict releases raise a ClickException."""
    import click

    from qwenpaw.cli.update_cmd import _select_latest_version

    with pytest.raises(click.ClickException):
        _select_latest_version(
            {"releases": "bad"},
            include_prerelease=False,
        )


@pytest.mark.integration
@pytest.mark.p1
def test_select_latest_version_no_candidates() -> None:
    """All-empty releases raise a ClickException."""
    import click

    from qwenpaw.cli.update_cmd import _select_latest_version

    with pytest.raises(click.ClickException):
        _select_latest_version({"releases": {}}, include_prerelease=False)


@pytest.mark.integration
@pytest.mark.p1
def test_detect_source_type_none_means_pypi() -> None:
    """No direct_url metadata means a plain PyPI install."""
    from qwenpaw.cli.update_cmd import _detect_source_type

    assert _detect_source_type(None) == ("pypi", None)


@pytest.mark.integration
@pytest.mark.p1
def test_detect_source_type_editable() -> None:
    """Editable installs are classified as editable."""
    from qwenpaw.cli.update_cmd import _detect_source_type

    direct = {
        "url": "file:///src/qwenpaw",
        "dir_info": {"editable": True},
    }
    kind, url = _detect_source_type(direct)
    assert kind == "editable"
    assert url == "file:///src/qwenpaw"


@pytest.mark.integration
@pytest.mark.p1
def test_detect_source_type_vcs() -> None:
    """VCS installs are classified as vcs."""
    from qwenpaw.cli.update_cmd import _detect_source_type

    direct = {"url": "https://git/repo", "vcs_info": {"vcs": "git"}}
    kind, _ = _detect_source_type(direct)
    assert kind == "vcs"


@pytest.mark.integration
@pytest.mark.p1
def test_detect_source_type_local_file() -> None:
    """file:// without editable dir_info means local wheel."""
    from qwenpaw.cli.update_cmd import _detect_source_type

    direct = {"url": "file:///wheels/qwenpaw.whl"}
    kind, url = _detect_source_type(direct)
    assert kind == "local"
    assert url == "file:///wheels/qwenpaw.whl"


@pytest.mark.integration
@pytest.mark.p1
def test_detect_source_type_direct_url_fallback() -> None:
    """Unknown URL schemes fall back to direct-url."""
    from qwenpaw.cli.update_cmd import _detect_source_type

    direct = {"url": "https://example.com/pkg.whl"}
    kind, url = _detect_source_type(direct)
    assert kind == "direct-url"
    assert url == "https://example.com/pkg.whl"


@pytest.mark.integration
@pytest.mark.p1
def test_install_info_dataclass_fields() -> None:
    """InstallInfo is a frozen dataclass with expected fields."""
    from qwenpaw.cli.update_cmd import InstallInfo

    info = InstallInfo(
        package_dir="/pkg",
        python_executable="/py",
        environment_root="/env",
        environment_kind="virtualenv",
        installer="pip",
        source_type="pypi",
    )
    assert info.package_dir == "/pkg"
    assert info.environment_kind == "virtualenv"
    assert info.source_url is None


@pytest.mark.integration
@pytest.mark.p1
def test_running_service_info_defaults() -> None:
    """RunningServiceInfo defaults to not-running."""
    from qwenpaw.cli.update_cmd import RunningServiceInfo

    info = RunningServiceInfo(is_running=False)
    assert info.is_running is False
    assert info.base_url is None
    assert info.version is None


@pytest.mark.integration
@pytest.mark.p1
def test_probe_service_unreachable() -> None:
    """Probing a dead endpoint returns not-running."""
    from qwenpaw.cli.update_cmd import _probe_service

    info = _probe_service("http://127.0.0.1:1")
    assert info.is_running is False
    assert info.base_url is None
