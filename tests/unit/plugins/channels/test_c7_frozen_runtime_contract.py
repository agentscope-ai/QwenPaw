# -*- coding: utf-8 -*-
"""C7 simulated Desktop resource contract through the actual C6 resolver."""

# pylint: disable=protected-access

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture(name="c7_frozen_resources")
def _c7_frozen_resources(tmp_path, monkeypatch):
    from qwenpaw.__version__ import __version__
    from qwenpaw.config import utils as config_utils

    resource_dir = tmp_path / "resources"
    site = resource_dir / "binaries/channel-runtime/site"
    worker = site / "qwenpaw/channel_protocol/shared_worker.py"
    worker.parent.mkdir(parents=True)
    worker.write_text("# controlled readable support path\n")
    index = site / "qwenpaw/official_channels/index.json"
    index.parent.mkdir(parents=True)
    index.write_text('{"schema_version":1}', encoding="utf-8")
    executable = resource_dir / "binaries/python-runtime/python/bin/python3"
    executable.parent.mkdir(parents=True)
    shutil.copy2(sys.executable, executable)
    manifest_path = resource_dir / "binaries/channel-runtime/runtime.json"
    identity = {
        "version": list(sys.version_info[:2]),
        "implementation": "cpython",
        "cache_tag": sys.implementation.cache_tag,
        "sys_platform": sys.platform,
        "system": platform.system(),
        "machine": platform.machine(),
        "supported_tags": ["py3-none-any"],
    }
    manifest = {
        "schema_version": 1,
        "host_version": __version__,
        "preset": "channels-full",
        "python_executable": "binaries/python-runtime/python/bin/python3",
        "support_root": "binaries/channel-runtime/site",
        "dependency_paths": ["binaries/channel-runtime/site"],
        "python": identity,
        "python_runtime_release": "local-simulation",
        "host_wheel_sha256": "0" * 64,
        "official_index_sha256": hashlib.sha256(
            index.read_bytes(),
        ).hexdigest(),
    }

    def save():
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    save()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_utils, "WORKING_DIR", tmp_path / "working")
    monkeypatch.setenv("QWENPAW_TAURI_RESOURCE_DIR", str(resource_dir))
    monkeypatch.setenv("QWENPAW_CHANNEL_RUNTIME_MANIFEST", str(manifest_path))
    monkeypatch.setenv("QWENPAW_DESKTOP_PY_RUNTIME", str(executable))
    monkeypatch.setenv("QWENPAW_CHANNEL_SUPPORT_ROOT", str(site))
    monkeypatch.setenv(
        "QWENPAW_CHANNEL_DEPENDENCY_PATHS",
        json.dumps([str(site)]),
    )
    monkeypatch.setenv("QWENPAW_CHANNEL_PRESET", "channels-full")
    return SimpleNamespace(
        resource_dir=resource_dir,
        site=site,
        executable=executable,
        manifest=manifest,
        manifest_path=manifest_path,
        save=save,
        working=tmp_path / "working",
    )


def test_c7_frozen_resolver_uses_child_resource_and_writable_target(
    c7_frozen_resources,
) -> None:
    from qwenpaw.plugins.channel_bootstrap import (
        default_channel_preset,
        resolve_default_channel_runtime,
    )

    resource = c7_frozen_resources
    settings = resolve_default_channel_runtime()
    assert default_channel_preset() == "channels-full"
    assert Path(settings.python_executable) == resource.executable
    assert settings.support_root == resource.site
    assert settings.selected_channels is None
    assert settings.allows("sample_chat")
    assert settings.dependency_paths[0] == resource.site
    assert settings.dependency_paths[-1] == settings.dependency_install_target
    assert settings.dependency_install_target.is_relative_to(resource.working)
    assert settings.dependency_install_target.is_dir()
    assert not settings.dependency_install_target.is_relative_to(
        resource.resource_dir,
    )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        (
            "python_executable",
            "../outside/python",
            "CHANNEL_RUNTIME_MANIFEST_INVALID",
        ),
        ("support_root", "/tmp/outside", "CHANNEL_RUNTIME_MANIFEST_INVALID"),
        ("preset", "light", "CHANNEL_PRESET_MISMATCH"),
    ],
)
def test_c7_frozen_resolver_rejects_untrusted_manifest(
    c7_frozen_resources,
    field,
    value,
    expected,
) -> None:
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    c7_frozen_resources.manifest[field] = value
    c7_frozen_resources.save()
    with pytest.raises(ValueError, match=expected):
        resolve_default_channel_runtime()


def test_c7_frozen_resolver_reports_missing_index(
    c7_frozen_resources,
) -> None:
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    (
        c7_frozen_resources.site / "qwenpaw/official_channels/index.json"
    ).unlink()
    with pytest.raises(FileNotFoundError):
        resolve_default_channel_runtime()


def test_c7_frozen_official_bundle_uses_validated_support_site(
    c7_frozen_resources,
) -> None:
    from qwenpaw.plugins import official_channels

    expected = c7_frozen_resources.site / "qwenpaw/official_channels"
    assert official_channels._resource_root() == expected


def test_c7_manifest_identity_rejects_wrong_child_snapshot() -> None:
    from qwenpaw.plugins.channel_bootstrap import validate_runtime_identity

    identity = {
        "version": [3, 11],
        "implementation": "cpython",
        "cache_tag": "cpython-311",
        "sys_platform": "darwin",
        "system": "Darwin",
        "machine": "arm64",
        "supported_tags": ["cp311-cp311-macosx_11_0_arm64"],
    }
    snapshot = SimpleNamespace(
        executable="/controlled/python",
        marker_environment={
            "python_version": "3.11",
            "implementation_name": "cpython",
            "sys_platform": "darwin",
            "platform_system": "Darwin",
            "platform_machine": "x86_64",
        },
        supported_tags=tuple(identity["supported_tags"]),
    )
    with pytest.raises(ValueError, match="CHANNEL_RUNTIME_IDENTITY_MISMATCH"):
        validate_runtime_identity(snapshot, identity, "/controlled/python")
