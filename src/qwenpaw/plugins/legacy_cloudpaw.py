# -*- coding: utf-8 -*-
"""Compatibility for installed CloudPaw copies that patched unload_plugin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils.io_utils import run_sync_io, write_json_atomic
from .custody import ConnectionCloser
from .provision import file_sha256, provisions_dir
from .safe_fs import safe_remove

_AGENTS = {
    "cloud-orchestrator": "CloudPaw-Master",
    "cloud-executor": "CloudPaw-Executor",
    "cloud-verifier": "CloudPaw-Verifier",
}
_SKILLS = ("alicloud_cli", "terraform-cli-setup", "terraform-skill")


def is_legacy_source(source: Path | None) -> bool:
    """Recognize only the old CloudPaw unload patch, without importing it."""
    if source is None:
        return False
    path = source / "plugin.py"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return all(
        token in text
        for token in (
            "def _patch_plugin_loader_unload(",
            "_cloudpaw_patched",
            "PluginLoader.unload_plugin = _patched_unload_plugin",
        )
    )


def restore_unload(loader: Any) -> bool:
    """Undo the identified legacy patch; do not retry arbitrary TypeErrors."""
    cls = type(loader)
    wrapper = cls.unload_plugin
    original = getattr(wrapper, "_original", None)
    if (
        getattr(wrapper, "_cloudpaw_patched", False)
        and getattr(wrapper, "__module__", "")
        in {"plugin_cloudpaw", "plugin_cloudpaw.plugin"}
        and getattr(wrapper, "__qualname__", "")
        == "_patch_plugin_loader_unload.<locals>._patched_unload_plugin"
        and callable(original)
    ):
        cls.unload_plugin = original
        return True
    return False


def _marker() -> Path:
    path = provisions_dir() / "compat"
    path.mkdir(exist_ok=True)
    return path / "cloudpaw.json"


def has_pending_cleanup() -> bool:
    return _marker().is_file()


def has_pending_stops(loader: Any) -> bool:
    manager = loader.registry.get_workspace_manager()
    return bool(getattr(loader, "_legacy_cloudpaw_closers", {})) or bool(
        manager is not None
        and set(_AGENTS).intersection(
            getattr(manager, "_uninstalling_agents", set()),
        ),
    )


def has_pending_uninstall(loader: Any) -> bool:
    """A normal registration marker is not an unfinished uninstall."""
    return has_pending_stops(loader) or (
        _marker().is_file()
        and json.loads(_marker().read_text()).get("uninstall_started", False)
    )


def _identity(path: Path) -> list[int] | None:
    if any(parent.is_symlink() for parent in path.parents):
        return None
    if path.is_symlink() or not path.exists():
        return None
    stat = path.stat()
    return [stat.st_dev, stat.st_ino]


def snapshot() -> dict[str, Any]:
    from ..constant import WORKING_DIR

    def before(path: Path) -> list[int] | None:
        identity = _identity(path)
        return identity or (
            [-1, -1] if path.exists() or path.is_symlink() else None
        )

    return {
        agent_id: before(Path(WORKING_DIR) / "workspaces" / agent_id)
        for agent_id in _AGENTS
    }


def _remember_file(
    data: dict,
    factory: Path,
    target: Path,
    anchor: Path,
) -> None:
    identity = _identity(target)
    anchor_identity = _identity(anchor)
    if not target.is_file() or identity is None or anchor_identity is None:
        return
    digest = file_sha256(factory)
    if file_sha256(target) == digest:
        data["files"].setdefault(
            str(target),
            {
                "hash": digest,
                "identity": identity,
                "anchor": str(anchor),
                "anchor_identity": anchor_identity,
            },
        )


def remember(source: Path, before: dict[str, Any] | None = None) -> dict:
    """Persist association and factory file identities before any deletion."""
    from ..agents.skill_system import get_skill_pool_dir
    from ..config.utils import load_config
    from ..constant import WORKING_DIR

    path = _marker()
    data = (
        json.loads(path.read_text())
        if path.is_file()
        else {
            "agents": {},
            "files": {},
        }
    )
    config = load_config()
    for agent_id, name in _AGENTS.items():
        ref = config.agents.profiles.get(agent_id)
        expected = Path(WORKING_DIR) / "workspaces" / agent_id
        if ref is None or Path(ref.workspace_dir).absolute() != expected:
            continue
        agent_file = expected / "agent.json"
        identity = _identity(expected)
        if identity is None or not agent_file.is_file():
            continue
        profile = json.loads(agent_file.read_text())
        if profile.get("id") != agent_id or profile.get("name") != name:
            continue
        row = data["agents"].setdefault(
            agent_id,
            {
                "path": str(expected),
                "identity": identity,
                "owned": before is not None and before.get(agent_id) is None,
            },
        )
        if not row["owned"]:
            # Legacy association does not authorize deleting user history.
            for factory in (source / "agents").rglob("*.md"):
                _remember_file(
                    data,
                    factory,
                    expected / factory.name,
                    expected,
                )
    pool = get_skill_pool_dir()
    manifest = pool / "skill.json"
    skills = (
        json.loads(manifest.read_text()).get("skills", {})
        if manifest.is_file()
        else {}
    )
    for name in _SKILLS:
        if skills.get(name, {}).get("source") != "plugin:cloudpaw":
            continue
        for factory in (source / "skills" / name).rglob("*"):
            if not factory.is_file() or factory.is_symlink():
                continue
            target = (
                pool / name / factory.relative_to(source / "skills" / name)
            )
            _remember_file(data, factory, target, pool / name)
    write_json_atomic(path, data)
    return data


async def _stop_agent(manager: Any, agent_id: str) -> None:
    from .custody import CONNECTION_STOP_SECONDS

    retired = [
        workspace
        for workspace in getattr(manager, "_retired_instances", {}).values()
        if workspace.agent_id == agent_id
    ]
    current = manager.agents.get(agent_id)
    for workspace in ([current] if current is not None else []) + retired:
        tracker = getattr(workspace, "task_tracker", None)
        if tracker is not None:
            active = await tracker.snapshot_active_tasks(owner=workspace)
            if not await tracker.wait_tasks_done(
                list(active.values()),
                timeout=CONNECTION_STOP_SECONDS,
            ):
                raise RuntimeError(
                    f"CloudPaw agent '{agent_id}' still has active requests",
                )
    if agent_id in manager.agents:
        await manager.stop_agent(agent_id)
        if agent_id in manager.agents:
            raise RuntimeError(f"CloudPaw agent '{agent_id}' did not stop")
    for workspace in retired:
        # The manager retains failed retired instances for retry.
        # pylint: disable=protected-access
        if not await manager._stop_retired_instance(workspace, agent_id):
            raise RuntimeError(
                f"CloudPaw retired agent '{agent_id}' did not stop",
            )


async def prepare_uninstall(loader: Any, source: Path | None) -> dict | None:
    """Stop associated agents with retained, bounded close operations."""
    if not _marker().is_file() and not is_legacy_source(source):
        return None
    data = (
        await run_sync_io(remember, source)
        if source is not None
        else (await run_sync_io(lambda: json.loads(_marker().read_text())))
    )
    data["uninstall_started"] = True
    await run_sync_io(write_json_atomic, _marker(), data)
    manager = loader.registry.get_workspace_manager()
    if manager is None:
        return data
    await run_sync_io(_validate_agents, data)
    manager.reserve_agent_uninstall(data["agents"])
    closers = getattr(loader, "_legacy_cloudpaw_closers", None)
    if closers is None:
        closers = loader._legacy_cloudpaw_closers = {}
    for agent_id in data["agents"]:
        # Startup/replacement is not owned by this compatibility layer.
        # Keep the uninstall retryable instead of racing a new workspace.
        if agent_id in getattr(
            manager,
            "_pending_starts",
            {},
        ) or agent_id in getattr(manager, "_reloading_agents", set()):
            raise RuntimeError(
                f"CloudPaw agent '{agent_id}' is still starting",
            )
        retired = [
            workspace
            for workspace in getattr(
                manager,
                "_retired_instances",
                {},
            ).values()
            if workspace.agent_id == agent_id
        ]
        if (
            agent_id not in manager.agents
            and not retired
            and agent_id not in closers
        ):
            continue
        if agent_id not in closers:

            async def close(agent_id=agent_id):
                await _stop_agent(manager, agent_id)

            client = type("AgentCloser", (), {"aclose": staticmethod(close)})()
            closers[agent_id] = ConnectionCloser(
                client,
                f"CloudPaw {agent_id}",
            )
        await closers[agent_id]()
        closers.pop(agent_id, None)
    return data


def cleanup(data: dict | None) -> None:
    """Remove confirmed legacy assets, retaining the marker on any error."""
    if data is None:
        return
    from ..config.utils import save_config

    config = _validate_agents(data)
    owned_paths = []
    for agent_id, row in data["agents"].items():
        path = Path(row["path"])
        ref = config.agents.profiles.get(agent_id)
        if ref is not None:
            del config.agents.profiles[agent_id]
        if (
            row["owned"]
            and row["identity"] is not None
            and _identity(path) == row["identity"]
        ):
            owned_paths.append(path)
    if config.agents.active_agent in data["agents"]:
        config.agents.active_agent = "default"
    config.agents.agent_order = [
        key for key in config.agents.agent_order if key not in data["agents"]
    ]
    save_config(config)
    for path in owned_paths:
        safe_remove(path, purpose="remove CloudPaw-created workspace")
    _cleanup_factory_files(data)


def _validate_agents(data: dict) -> Any:
    from ..config.utils import load_config

    config = load_config()
    for agent_id, row in data["agents"].items():
        if row["identity"] is None:
            raise RuntimeError(
                f"CloudPaw agent '{agent_id}' ownership is unknown",
            )
        ref = config.agents.profiles.get(agent_id)
        if ref is None:
            continue
        path = Path(row["path"])
        profile_path = path / "agent.json"
        if (
            Path(ref.workspace_dir).absolute() != path
            or _identity(path) != row["identity"]
            or not profile_path.is_file()
        ):
            raise RuntimeError(
                f"CloudPaw agent '{agent_id}' ownership changed",
            )
        profile = json.loads(profile_path.read_text())
        if (
            profile.get("id") != agent_id
            or profile.get("name") != _AGENTS[agent_id]
        ):
            raise RuntimeError(
                f"CloudPaw agent '{agent_id}' ownership changed",
            )
    return config


def _cleanup_factory_files(data: dict) -> None:
    from ..agents.skill_system import get_skill_pool_dir

    pool = get_skill_pool_dir()
    manifest_path = pool / "skill.json"
    manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.is_file()
        else {"skills": {}}
    )
    for raw, row in data["files"].items():
        if row["identity"] is None or row["anchor_identity"] is None:
            continue
        path = Path(raw)
        anchor = Path(row["anchor"])
        if (
            anchor.parent == pool
            and manifest["skills"]
            .get(
                anchor.name,
                {},
            )
            .get("source")
            != "plugin:cloudpaw"
        ):
            continue
        if (
            path.is_file()
            and _identity(path) == row["identity"]
            and _identity(Path(row["anchor"])) == row["anchor_identity"]
            and file_sha256(path) == row["hash"]
        ):
            safe_remove(path, purpose="remove unchanged CloudPaw factory file")
    owned_skills = {
        Path(row["anchor"]).name: row["anchor_identity"]
        for row in data["files"].values()
        if Path(row["anchor"]).parent == pool
        and row["anchor_identity"] is not None
    }
    for name, identity in owned_skills.items():
        path = pool / name
        if (
            path.is_symlink()
            or any(parent.is_symlink() for parent in path.parents)
            or (path.exists() and _identity(path) != identity)
            or manifest["skills"].get(name, {}).get("source")
            != "plugin:cloudpaw"
        ):
            continue
        if (
            _identity(path) is not None
            and manifest["skills"].get(name, {}).get("source")
            == "plugin:cloudpaw"
        ):
            for child in sorted(path.rglob("*"), reverse=True):
                if (
                    child.is_dir()
                    and _identity(child) is not None
                    and not any(child.iterdir())
                ):
                    child.rmdir()
        if (
            path.is_dir()
            and not path.is_symlink()
            and not any(path.rglob("*"))
        ):
            path.rmdir()
        if (
            not path.exists()
            and manifest["skills"].get(name, {}).get("source")
            == "plugin:cloudpaw"
        ):
            manifest["skills"].pop(name)
    if manifest_path.is_file():
        write_json_atomic(manifest_path, manifest)


def retire_agent_cleanup(instance: Any = None) -> None:
    """Replace only the old blanket agent teardown after managed cleanup."""
    from .provision import load_inventory, save_inventory

    data = load_inventory("cloudpaw")
    data["provisions"] = [
        row
        for row in data["provisions"]
        if row.get("kind") != "cloudpaw_agents"
    ]
    save_inventory("cloudpaw", data)
    if instance is not None:
        # pylint: disable=protected-access
        instance._install[:] = [
            entry
            for entry in instance._install
            if entry.kind != "cloudpaw_agents"
        ]


def finish_uninstall(loader: Any, data: dict | None) -> None:
    """Release the durable retry record only after the uninstall succeeded."""
    if data is None:
        return
    _marker().unlink(missing_ok=True)
    manager = loader.registry.get_workspace_manager()
    if manager is not None:
        manager.release_agent_uninstall(data["agents"])
