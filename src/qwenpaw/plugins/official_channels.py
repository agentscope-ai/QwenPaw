# -*- coding: utf-8 -*-
"""Offline official sources through the existing plugin lifecycle."""

from __future__ import annotations

from contextlib import ExitStack, asynccontextmanager, contextmanager
from copy import deepcopy
from functools import lru_cache
import hashlib
from importlib import resources
import io
import json
import logging
import shutil
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import zipfile

from .official_channel_catalog import (
    official_channel_owners,
    official_channel_for_plugin,
)
from .channel_bootstrap import (
    resolve_default_channel_runtime,
)

__all__ = [
    "resolve_default_channel_runtime",
    "provision_bundled_channels",
    "bundled_channel_source",
    "bundled_channel_description",
    "prepare_channel_upgrade",
]


def _resource_root():
    if getattr(sys, "frozen", False):
        from .channel_bootstrap import runtime_manifest

        return runtime_manifest()[1] / "qwenpaw/official_channels"
    return resources.files("qwenpaw").joinpath("official_channels")


def _digest(content):
    return hashlib.sha256(content).hexdigest()


def _bundled_index(root):
    """Validate the small, closed C7 resource index before selecting a ZIP."""
    from ..__version__ import __version__

    with root.joinpath("index.json").open("rb") as stream:
        content = stream.read(64 * 1024 + 1)
    if len(content) > 64 * 1024:
        raise ValueError("Official index exceeds limits")
    index = json.loads(content)
    # Closed resource identity requires all these independent checks.
    # pylint: disable=too-many-boolean-expressions
    if (
        not isinstance(index, dict)
        or set(index) != {"schema_version", "host_version", "plugins"}
        or index["schema_version"] != 1
        or index["host_version"] != __version__
        or not isinstance(index["plugins"], list)
        or any(not isinstance(row, dict) for row in index["plugins"])
        or [row.get("plugin_id") for row in index["plugins"]]
        != sorted(official_channel_owners().values())
    ):
        raise ValueError("Official index identity mismatch")
    for row in index["plugins"]:
        if set(row) != {
            "plugin_id",
            "version",
            "filename",
            "sha256",
            "descriptor_sha256",
            "requirements_sha256",
            "qwenpaw_version",
        }:
            raise ValueError("Official index fields mismatch")
        if (
            not isinstance(row["filename"], str)
            or Path(row["filename"]).name != row["filename"]
            or any(char in row["filename"] for char in ("\\", ":"))
            or not row["filename"].endswith(".zip")
        ):
            raise ValueError("Official archive filename invalid")
        for key in ("sha256", "descriptor_sha256", "requirements_sha256"):
            if (
                not isinstance(row[key], str)
                or len(row[key]) != 64
                or any(char not in "0123456789abcdef" for char in row[key])
            ):
                raise ValueError("Official archive digest invalid")
    return index


def _bundled_archive(root, row):
    with root.joinpath(row["filename"]).open("rb") as stream:
        payload = stream.read(64 * 1024 * 1024 + 1)
    if len(payload) > 64 * 1024 * 1024 or _digest(payload) != row["sha256"]:
        raise ValueError("Official archive digest mismatch")
    return payload


@contextmanager
def _extracted_channel_source(plugin_id, row, payload, *, retain=None):
    """Validate an authenticated archive in a private temporary directory."""
    from .architecture import PluginManifest
    from .archive import safe_extract_zip
    from .channel_adapter import describe_channel

    official = official_channel_for_plugin(plugin_id)
    if official is None:
        raise ValueError("Unknown official channel")
    target = Path(tempfile.mkdtemp(prefix="qwenpaw-official-"))
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if any(
                not name.startswith(plugin_id + "/")
                for name in archive.namelist()
            ):
                raise ValueError("Official archive root mismatch")
            safe_extract_zip(archive, target)
        source = target / plugin_id
        raw = json.loads((source / "plugin.json").read_text(encoding="utf-8"))
        manifest = PluginManifest.from_dict(raw)
        if (
            manifest.id != plugin_id
            or manifest.version != row["version"]
            or raw.get("qwenpaw_version") != row["qwenpaw_version"]
        ):
            raise ValueError("Official manifest identity mismatch")
        from .._version_compat import check_plugin_version_compat

        compatible, reason = check_plugin_version_compat(manifest)
        if not compatible:
            raise ValueError(reason)
        description = describe_channel(source, manifest)
        if (
            description.descriptor.channel_key != official["channel_key"]
            or _digest(description.descriptor_path.read_bytes())
            != row["descriptor_sha256"]
            or _digest(description.requirements_path.read_bytes())
            != row["requirements_sha256"]
        ):
            raise ValueError("Official source digest mismatch")
        yield source
    finally:
        if retain is None or not retain(target):
            shutil.rmtree(target)


@contextmanager
def bundled_channel_source(plugin_id, *, retain=None):
    """Verify installed resource bytes and yield a private extracted source."""
    if official_channel_for_plugin(plugin_id) is None:
        raise ValueError("Unknown official channel")
    root = _resource_root()
    index = _bundled_index(root)
    row = {row["plugin_id"]: row for row in index["plugins"]}[plugin_id]
    payload = _bundled_archive(root, row)
    with _extracted_channel_source(
        plugin_id,
        row,
        payload,
        retain=retain,
    ) as source:
        yield source


@asynccontextmanager
async def async_bundled_channel_source(plugin_id, *, retain=None):
    """Extract off-loop while keeping source custody decisions on the loop."""
    from ..utils.io_utils import run_sync_io

    stack = ExitStack()
    source_root = None
    retained = False

    def enter():
        nonlocal source_root
        source = stack.enter_context(
            bundled_channel_source(plugin_id, retain=lambda _root: retained),
        )
        source_root = source.parent
        return source

    try:
        yield await run_sync_io(enter)
    finally:
        try:
            if source_root is not None and retain is not None:
                # Preserve uncertain custody if the owner's check fails.
                retained = True
                retained = bool(retain(source_root))
        finally:
            await run_sync_io(stack.close)


@lru_cache(maxsize=64)
def _metadata_slot(root_identity, plugin_id):
    """Keep the most recent passive snapshot for this resource and channel."""
    return {}


def bundled_channel_description(plugin_id: str):
    """Cache authenticated passive fields, never paths or executable data."""
    from ..__version__ import __version__
    from ..utils.io_utils import get_sync_path_lock
    from .architecture import PluginManifest
    from .channel_adapter import describe_channel

    if official_channel_for_plugin(plugin_id) is None:
        raise ValueError("Unknown official channel")
    root = _resource_root()
    with get_sync_path_lock(str(root) + "/" + plugin_id):
        cached = _metadata_slot((type(root), str(root)), plugin_id)
        index = _bundled_index(root)
        row = {row["plugin_id"]: row for row in index["plugins"]}[plugin_id]
        payload = _bundled_archive(root, row)
        identity = (__version__, json.dumps(index, sort_keys=True))
        if cached.get("identity") != identity:
            with _extracted_channel_source(plugin_id, row, payload) as source:
                manifest = PluginManifest.from_dict(
                    json.loads(
                        (source / "plugin.json").read_text(encoding="utf-8"),
                    ),
                )
                description = describe_channel(source, manifest)
                descriptor = description.descriptor
                metadata = SimpleNamespace(
                    plugin_id=description.plugin_id,
                    version=description.version,
                    descriptor=SimpleNamespace(
                        channel_key=descriptor.channel_key,
                        label=dict(descriptor.label),
                        config_schema=deepcopy(descriptor.config_schema),
                        config_fields=descriptor.config_fields,
                        capabilities=descriptor.capabilities,
                        process_mode=descriptor.process_mode,
                    ),
                    name=description.name,
                    description=description.description,
                )
            cached.update(identity=identity, metadata=metadata)
        return deepcopy(cached["metadata"])


def _persisted_channel_enabled(data, key):
    channels = data.get("channels", {})
    legacy_key = "weixin" if key == "wechat" else key
    return (
        channels.get(key, channels.get(legacy_key, {})).get("enabled") is True
    )


async def prepare_channel_upgrade():
    """Prepare only persisted enabled channels during an explicit upgrade."""
    from ..utils.io_utils import run_sync_io

    from ..constant import EnvVarLoader
    from ..config.utils import get_config_path, get_plugins_dir
    from .lifecycle import UnloadMode
    from .loader import PluginLoader
    from .settings import is_plugin_enabled

    path = get_config_path()
    raw = (
        json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    )
    saved = [raw]
    for profile in raw.get("agents", {}).get("profiles", {}).values():
        workspace = profile.get("workspace_dir")
        if workspace:
            agent_path = Path(workspace).expanduser() / "agent.json"
            if agent_path.is_file():
                saved.append(
                    json.loads(agent_path.read_text(encoding="utf-8")),
                )
    settings = raw.get("plugins", {})
    removed = raw.get("channel_plugin_state", {}).get("uninstalled", [])
    owners = official_channel_owners()
    allowed = set(owners)
    enabled = EnvVarLoader.get_str("QWENPAW_ENABLED_CHANNELS", "").strip()
    disabled = EnvVarLoader.get_str("QWENPAW_DISABLED_CHANNELS", "")
    if enabled:
        allowed.intersection_update(key.strip() for key in enabled.split(","))
    else:
        allowed.difference_update(key.strip() for key in disabled.split(","))
    selected = {
        plugin_id: key
        for key, plugin_id in owners.items()
        if key in allowed
        and plugin_id not in removed
        and is_plugin_enabled(settings.get(plugin_id))
        and any(_persisted_channel_enabled(data, key) for data in saved)
    }
    if not selected:
        return {}

    loader = await PluginLoader.create(
        [get_plugins_dir()],
        channel_runtime=await run_sync_io(resolve_default_channel_runtime),
    )
    errors = {}
    try:
        for plugin_id, key in sorted(selected.items()):
            try:
                source = loader.find_installed_plugin_dir(plugin_id)
                if source is None:
                    async with async_bundled_channel_source(
                        plugin_id,
                    ) as bundled:
                        record = await loader.seed_bundled_channel(
                            bundled,
                            settings.get(plugin_id),
                        )
                    source = record.source_path
                async with loader.plugin_lifecycle(plugin_id):
                    _, manifest = await run_sync_io(
                        loader._read_source_manifest,
                        source,
                    )
                    compatible, _ = loader._check_version_compatibility(
                        manifest,
                    )
                    if not compatible:
                        errors[plugin_id] = "PLUGIN_VERSION_INCOMPATIBLE"
                        continue
                    binding = await run_sync_io(
                        loader.backend_resolver.resolve,
                        source,
                        manifest,
                    )
                    if (
                        manifest.id != plugin_id
                        or binding.description.payload.descriptor.channel_key
                        != key
                    ):
                        errors[
                            plugin_id
                        ] = "OFFICIAL_CHANNEL_IDENTITY_MISMATCH"
                        continue
                    await loader.lifecycle.preflight_backend(
                        binding,
                        allow_install=True,
                        probe=True,
                    )
            except Exception as exc:
                # Child/SDK exception text can contain endpoint credentials.
                decision = getattr(exc, "decision", None)
                errors[plugin_id] = (
                    getattr(exc, "reason_code", None)
                    or getattr(decision, "reason_code", None)
                    or type(exc).__name__
                )
    finally:
        reports = await loader.lifecycle.unload_all(UnloadMode.SHUTDOWN)
        for report in reports:
            if (
                not report.clean
                or not report.quiescent
                or report.needs_restart
            ):
                errors[report.plugin_id] = "CHANNEL_CLEANUP_INCOMPLETE"
    return errors


def initialize_channel_policy():
    """Capture legacy intent once from raw persisted files, never defaults."""
    from ..config.utils import get_config_path, mutate_config
    from .channel_bootstrap import default_channel_preset
    from ..constant import WORKING_DIR
    from .official_execution_context import capture_official_legacy

    # Capture raw historical ownership before config/default migrations.
    failed = capture_official_legacy(
        config_path=get_config_path(),
        legacy_state_dir=WORKING_DIR,
        working_dir=Path.cwd(),
    )
    for diagnostic in failed.values():
        logging.getLogger(__name__).warning("%s", diagnostic)

    def apply(config):
        state = config.channel_plugin_state
        captured = set(state.legacy_captured)
        # Version 1 inspected exactly these historical channels. Do not
        # recapture their enabled settings and resurrect removed plugins.
        if state.version == 1:
            captured.update({"feishu", "dingtalk"})
        owners = official_channel_owners()
        if failed:
            state.legacy_pending = [
                item
                for item in state.legacy_pending
                if item not in {owners.get(key) for key in failed}
            ]
        unseen = set(owners) - captured
        if not unseen:
            state.legacy_captured = sorted(captured)
            state.version = max(state.version, 1)
            return
        path = get_config_path()
        raw = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.is_file()
            else {}
        )
        saved = [raw]
        for profile in raw.get("agents", {}).get("profiles", {}).values():
            workspace = profile.get("workspace_dir")
            if not workspace:
                continue
            agent_path = Path(workspace).expanduser() / "agent.json"
            if agent_path.is_file():
                saved.append(
                    json.loads(agent_path.read_text(encoding="utf-8")),
                )
        pending = set(state.legacy_pending)
        for key in unseen:
            if key in failed:
                continue
            plugin_id = owners[key]
            if plugin_id not in state.uninstalled and any(
                _persisted_channel_enabled(data, key) for data in saved
            ):
                pending.add(plugin_id)
        state.legacy_pending = sorted(pending - set(state.uninstalled))
        state.legacy_captured = sorted(captured | (unseen - set(failed)))
        if state.version == 0:
            state.preset = default_channel_preset()
        state.version = max(state.version, 1)

    mutate_config(apply)


async def provision_bundled_channels(loader):
    """Seed absent sources, retaining finite migration retry intent."""
    from ..config.utils import load_config, mutate_config
    from ..utils.io_utils import run_sync_io

    await run_sync_io(initialize_channel_policy)
    config = await run_sync_io(load_config)
    state = config.channel_plugin_state
    requested = set(state.legacy_pending)
    if state.preset == "channels-full":
        requested.update(official_channel_owners().values())
    errors = {}
    for plugin_id in sorted(requested - set(state.uninstalled)):
        try:
            if loader.find_installed_plugin_dir(plugin_id) is None:
                async with async_bundled_channel_source(plugin_id) as source:
                    await loader.seed_bundled_channel(
                        source,
                        config.plugins.get(plugin_id),
                    )

            def completed(root, key=plugin_id):
                root.channel_plugin_state.legacy_pending = [
                    item
                    for item in root.channel_plugin_state.legacy_pending
                    if item != key
                ]

            await run_sync_io(mutate_config, completed)
        except Exception as exc:  # A resource failure must not stop Console.
            errors[plugin_id] = str(exc)
    return errors
