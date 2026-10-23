# -*- coding: utf-8 -*-
"""Installed CLI runtime discovery without the Desktop launcher."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from pathlib import Path
import sys
from types import SimpleNamespace

from click.testing import CliRunner
import pytest

CONTEXT = (
    "QWENPAW_TAURI_RESOURCE_DIR",
    "QWENPAW_CHANNEL_RUNTIME_MANIFEST",
    "QWENPAW_DESKTOP_PY_RUNTIME",
    "QWENPAW_CHANNEL_SUPPORT_ROOT",
    "QWENPAW_CHANNEL_DEPENDENCY_PATHS",
)


@pytest.fixture
def installed_cli(tmp_path, monkeypatch):
    from qwenpaw.__version__ import __version__
    from qwenpaw.config import utils as config_utils

    root = tmp_path / "install"
    backend = root / "binaries/qwenpaw-backend/qwenpaw.exe"
    python = root / "binaries/python-runtime/python/python.exe"
    site = root / "binaries/channel-runtime/site"
    worker = site / "qwenpaw/channel_protocol/shared_worker.py"
    index = site / "qwenpaw/official_channels/index.json"
    for path in (backend, python, worker, index):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path == index else "# bundled file\n")
    manifest_path = root / "binaries/channel-runtime/runtime.json"
    manifest = {
        "schema_version": 1,
        "host_version": __version__,
        "preset": "channels-full",
        "python_executable": "binaries/python-runtime/python/python.exe",
        "support_root": "binaries/channel-runtime/site",
        "dependency_paths": ["binaries/channel-runtime/site"],
        "python": {
            "version": list(sys.version_info[:2]),
            "implementation": sys.implementation.name,
            "cache_tag": sys.implementation.cache_tag,
            "sys_platform": sys.platform,
            "system": platform.system(),
            "machine": platform.machine(),
            "supported_tags": ["py3-none-any"],
        },
        "python_runtime_release": "test-bundle",
        "host_wheel_sha256": "0" * 64,
        "official_index_sha256": hashlib.sha256(
            index.read_bytes(),
        ).hexdigest(),
    }

    def save():
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    save()
    for key in (*CONTEXT, "QWENPAW_CHANNEL_PRESET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(backend))
    working = tmp_path / "working"
    monkeypatch.setattr(config_utils, "WORKING_DIR", working)
    return SimpleNamespace(
        root=root,
        backend=backend,
        python=python,
        site=site,
        worker=worker,
        manifest=manifest,
        manifest_path=manifest_path,
        save=save,
        working=working,
    )


def test_installed_cli_discovers_validated_channel_runtime(installed_cli):
    from qwenpaw.plugins.channel_bootstrap import (
        default_channel_preset,
        resolve_default_channel_runtime,
        runtime_manifest,
    )

    bundle = installed_cli
    executable, support, sites, identity, preset = runtime_manifest()
    assert executable == bundle.python
    assert support == bundle.site
    assert sites == (bundle.site,)
    assert identity == bundle.manifest["python"]
    assert preset == default_channel_preset() == "channels-full"
    settings = resolve_default_channel_runtime()
    assert Path(settings.python_executable) == bundle.python
    assert settings.support_root == bundle.site
    assert settings.dependency_paths[0] == bundle.site
    assert settings.dependency_install_target.is_relative_to(bundle.working)
    assert settings.dependency_install_target.is_dir()


def test_installed_click_preset_apply_persists_config(installed_cli):
    from qwenpaw.cli.main import cli

    result = CliRunner().invoke(
        cli,
        ["plugins", "preset", "apply", "channels-full", "--offline"],
    )
    assert result.exit_code == 0, repr(result.exception)
    config = json.loads((installed_cli.working / "config.json").read_text())
    assert config["channel_plugin_state"]["preset"] == "channels-full"


def launcher_context(bundle):
    return dict(
        zip(
            CONTEXT,
            (
                str(bundle.root),
                str(bundle.manifest_path),
                str(bundle.python),
                str(bundle.site),
                json.dumps([str(bundle.site)]),
            ),
        ),
    )


@pytest.mark.parametrize("key", CONTEXT)
@pytest.mark.parametrize("only_one", [True, False])
def test_partial_launcher_context_is_rejected(
    installed_cli,
    monkeypatch,
    key,
    only_one,
):
    from qwenpaw.plugins.channel_bootstrap import runtime_manifest

    for name, value in launcher_context(installed_cli).items():
        if (name == key) == only_one:
            monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="CHANNEL_RUNTIME_MANIFEST_INVALID"):
        runtime_manifest()


@pytest.mark.parametrize("key", CONTEXT)
@pytest.mark.parametrize("value", ["", " "])
def test_blank_launcher_context_is_rejected(
    installed_cli,
    monkeypatch,
    key,
    value,
):
    from qwenpaw.plugins.channel_bootstrap import runtime_manifest

    context = launcher_context(installed_cli)
    context[key] = value
    for name, item in context.items():
        monkeypatch.setenv(name, item)
    with pytest.raises(ValueError, match="CHANNEL_RUNTIME_MANIFEST_INVALID"):
        runtime_manifest()


def test_complete_launcher_context_is_supported(installed_cli, monkeypatch):
    from qwenpaw.plugins.channel_bootstrap import runtime_manifest

    for name, value in launcher_context(installed_cli).items():
        monkeypatch.setenv(name, value)
    assert runtime_manifest()[:3] == (
        installed_cli.python,
        installed_cli.site,
        (installed_cli.site,),
    )


@pytest.mark.parametrize("key", CONTEXT[2:])
def test_explicit_paths_cannot_disagree_with_manifest(
    installed_cli,
    monkeypatch,
    key,
):
    from qwenpaw.plugins.channel_bootstrap import runtime_manifest

    context = launcher_context(installed_cli)
    other = str(installed_cli.root / "other")
    context[key] = json.dumps([other]) if key == CONTEXT[-1] else other
    for name, value in context.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="CHANNEL_RUNTIME_MANIFEST_MISMATCH"):
        runtime_manifest()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("host_version", "incompatible-host"),
        ("python_executable", "../outside/python.exe"),
        ("support_root", "../outside/site"),
        ("dependency_paths", ["../outside/site"]),
    ],
)
def test_discovery_preserves_manifest_validation(installed_cli, field, value):
    from qwenpaw.plugins.channel_bootstrap import runtime_manifest

    installed_cli.manifest[field] = value
    installed_cli.save()
    with pytest.raises(ValueError, match="CHANNEL_RUNTIME_MANIFEST_INVALID"):
        runtime_manifest()


@pytest.mark.parametrize("missing", ["manifest_path", "python", "worker"])
def test_incomplete_installation_reports_runtime_error(installed_cli, missing):
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    getattr(installed_cli, missing).unlink()
    with pytest.raises((ValueError, OSError)):
        resolve_default_channel_runtime()


@pytest.mark.parametrize("escaped", ["manifest_path", "python", "worker"])
def test_discovery_rejects_symlinks_outside_installation(
    installed_cli,
    tmp_path,
    escaped,
):
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    path = getattr(installed_cli, escaped)
    outside = tmp_path / "outside"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows requires permission to create symlinks")
        raise
    with pytest.raises((ValueError, OSError)):
        resolve_default_channel_runtime()


def test_wrong_backend_layout_cannot_use_ambient_resources(
    installed_cli,
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    backend = tmp_path / "unrelated/qwenpaw.exe"
    backend.parent.mkdir()
    backend.write_text("# unrelated executable\n")
    monkeypatch.setattr(sys, "executable", str(backend))
    monkeypatch.setattr(
        sys,
        "_MEIPASS",
        str(installed_cli.root),
        raising=False,
    )
    monkeypatch.chdir(installed_cli.root)
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join(
            (
                str(installed_cli.root),
                str(installed_cli.backend.parent),
                str(installed_cli.python.parent),
            ),
        ),
    )
    with pytest.raises(ValueError, match="CHANNEL_RUNTIME_MANIFEST_INVALID"):
        resolve_default_channel_runtime()


def test_source_runtime_ignores_installed_layout(installed_cli, monkeypatch):
    from qwenpaw.plugins.channel_bootstrap import (
        default_channel_preset,
        resolve_default_channel_runtime,
        runtime_manifest,
    )

    installed_cli.manifest_path.write_text("invalid manifest")
    monkeypatch.setattr(sys, "frozen", False)
    assert default_channel_preset() == "light"
    with pytest.raises(ValueError, match="CHANNEL_RUNTIME_MANIFEST_INVALID"):
        runtime_manifest()
    settings = resolve_default_channel_runtime()
    assert settings.support_root != installed_cli.site
    assert settings.runtime_identity is None
