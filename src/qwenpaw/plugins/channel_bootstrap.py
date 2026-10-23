# -*- coding: utf-8 -*-
"""Trusted channel interpreter and resource policy, with no passive probes."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from pathlib import Path
import sys

from .channel_adapter import ChannelRuntimeSettings


def _resource_path(root, value):
    if (
        not isinstance(value, str)
        or not value
        or Path(value).is_absolute()
        or "\\" in value
        or ":" in value
    ):
        raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    path = root / value
    if ".." in Path(value).parts or not path.resolve().is_relative_to(root):
        raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    return path.resolve()


def _runtime_resource_context():
    """Use complete launcher paths or the frozen executable's fixed layout."""
    keys = (
        "QWENPAW_TAURI_RESOURCE_DIR",
        "QWENPAW_CHANNEL_RUNTIME_MANIFEST",
        "QWENPAW_DESKTOP_PY_RUNTIME",
        "QWENPAW_CHANNEL_SUPPORT_ROOT",
        "QWENPAW_CHANNEL_DEPENDENCY_PATHS",
    )
    values = tuple(os.environ.get(key) for key in keys)
    if any(value is not None for value in values):
        if any(value is None or not value.strip() for value in values):
            raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
        return Path(values[0]), Path(values[1]), values[2:]
    executable = Path(sys.executable)
    if not getattr(sys, "frozen", False) or not executable.is_absolute():
        raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    executable = executable.resolve()
    if (
        executable.parent.name != "qwenpaw-backend"
        or executable.parent.parent.name != "binaries"
    ):
        raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    root = executable.parent.parent.parent
    return root, root / "binaries/channel-runtime/runtime.json", None


def runtime_manifest():
    """Read the launcher resource manifest, never workspace configuration."""
    # pylint: disable=too-many-branches
    from ..__version__ import __version__

    root, path, launcher_paths = _runtime_resource_context()
    if not root.is_absolute():
        raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    root = root.resolve()
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not path.resolve().is_relative_to(root)
        or path.stat().st_size > 1024 * 1024
    ):
        raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or data.get("host_version") != __version__
    ):
        raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    if set(data) != {
        "schema_version",
        "host_version",
        "preset",
        "python_executable",
        "support_root",
        "dependency_paths",
        "python",
        "python_runtime_release",
        "host_wheel_sha256",
        "official_index_sha256",
    }:
        raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    for key in ("host_wheel_sha256", "official_index_sha256"):
        digest = data[key]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    executable = _resource_path(root, data["python_executable"])
    support = _resource_path(root, data["support_root"])
    sites = tuple(
        _resource_path(root, value) for value in data["dependency_paths"]
    )
    if launcher_paths is not None and (
        str(executable) != str(Path(launcher_paths[0]).resolve())
        or str(support) != str(Path(launcher_paths[1]).resolve())
        or sites
        != tuple(
            Path(item).resolve() for item in json.loads(launcher_paths[2])
        )
    ):
        raise ValueError("CHANNEL_RUNTIME_MANIFEST_MISMATCH")
    index_path = support / "qwenpaw/official_channels/index.json"
    if not index_path.resolve().is_relative_to(root):
        raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    with index_path.open("rb") as stream:
        index_bytes = stream.read(64 * 1024 + 1)
    if (
        len(index_bytes) > 64 * 1024
        or hashlib.sha256(index_bytes).hexdigest()
        != data["official_index_sha256"]
    ):
        raise ValueError("CHANNEL_RUNTIME_INDEX_MISMATCH")
    identity = data["python"]
    version = identity["version"]
    # Closed trusted manifest shape, including bool rejection for versions.
    # pylint: disable=too-many-boolean-expressions
    if (
        not isinstance(version, list)
        or len(version) != 2
        or any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0
            for item in version
        )
        or any(
            not isinstance(identity.get(key), str) or not identity[key]
            for key in (
                "implementation",
                "cache_tag",
                "sys_platform",
                "system",
                "machine",
            )
        )
        or not isinstance(identity.get("supported_tags"), list)
        or not identity["supported_tags"]
        or any(
            not isinstance(tag, str) or not tag
            for tag in identity["supported_tags"]
        )
    ):
        raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    for value in (identity["system"], identity["machine"]):
        if not all(char.isalnum() or char in "_-" for char in value):
            raise ValueError("CHANNEL_RUNTIME_MANIFEST_INVALID")
    preset = data.get("preset")
    if (
        preset not in {"light", "channels-full"}
        or os.environ.get("QWENPAW_CHANNEL_PRESET", preset) != preset
    ):
        raise ValueError("CHANNEL_PRESET_MISMATCH")
    if (
        not executable.is_file()
        or not support.is_dir()
        or any(not site.is_dir() for site in sites)
    ):
        raise ValueError("CHANNEL_RUNTIME_MISSING")
    return executable, support, sites, identity, preset


def default_channel_preset():
    """Use trusted deployment defaults only when initializing policy."""
    if getattr(sys, "frozen", False):
        return runtime_manifest()[-1]
    preset = os.environ.get("QWENPAW_CHANNEL_PRESET", "light")
    if preset not in {"light", "channels-full"}:
        raise ValueError("CHANNEL_PRESET_INVALID")
    return preset


def resolve_default_channel_runtime():
    """Provision an empty managed site under the environment lock."""
    from ..__version__ import __version__
    from ..config.utils import get_config_path, _read_config_data
    from .install_lock import (
        environment_install_lock_path,
        plugin_install_lock,
    )

    if getattr(sys, "frozen", False):
        executable, support, sites, identity, _preset = runtime_manifest()
    else:
        from .execution.environment import shared_dependency_paths

        executable = Path(sys.executable).absolute()
        support = Path(__file__).resolve().parents[2]
        sites = shared_dependency_paths()
        identity = {
            "version": list(sys.version_info[:2]),
            "system": platform.system(),
            "machine": platform.machine(),
        }
    worker = support / "qwenpaw/channel_protocol/shared_worker.py"
    if not worker.is_file() or not worker.resolve().is_relative_to(support):
        raise ValueError("CHANNEL_RUNTIME_MISSING")
    major, minor = identity["version"]
    bucket = (
        f"py{major}.{minor}-{identity['system'].lower()}-"
        f"{identity['machine'].lower()}"
    )
    config_path = get_config_path()
    data = _read_config_data(config_path) if config_path.exists() else {}
    send_timeouts = (data or {}).get("channel_send_timeouts", {})
    target = config_path.parent / "plugin_runtime" / bucket / "site"
    with plugin_install_lock(environment_install_lock_path(target)):
        if target.is_symlink():
            raise ValueError("CHANNEL_RUNTIME_TARGET_INVALID")
        target.mkdir(parents=True, exist_ok=True)
    return ChannelRuntimeSettings(
        python_executable=str(executable),
        support_root=support,
        qwenpaw_version=__version__,
        selected_channels=None,
        dependency_paths=tuple(dict.fromkeys((*sites, target.resolve()))),
        dependency_install_target=target.resolve(),
        runtime_identity=identity if getattr(sys, "frozen", False) else None,
        send_timeouts=send_timeouts,
    )


def validate_runtime_identity(snapshot, identity, executable=None):
    """Reject the wrong child before admission writes dependencies."""
    if identity is None:
        return
    if (
        executable is not None
        and Path(snapshot.executable).resolve() != Path(executable).resolve()
    ):
        raise ValueError("CHANNEL_RUNTIME_IDENTITY_MISMATCH")
    env = snapshot.marker_environment
    if identity["implementation"] == "cpython" and identity["cache_tag"] != (
        "cpython-" + "".join(map(str, identity["version"]))
    ):
        raise ValueError("CHANNEL_RUNTIME_IDENTITY_MISMATCH")
    expected = {
        "python_version": ".".join(map(str, identity["version"])),
        "implementation_name": identity["implementation"],
        "sys_platform": identity["sys_platform"],
        "platform_system": identity["system"],
        "platform_machine": identity["machine"],
    }
    if (
        any(env.get(key) != value for key, value in expected.items())
        or tuple(identity["supported_tags"]) != snapshot.supported_tags
    ):
        raise ValueError("CHANNEL_RUNTIME_IDENTITY_MISMATCH")
