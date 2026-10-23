# -*- coding: utf-8 -*-
"""Explicit, durable upgrades for the shared plugin dependency environment."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
from uuid import uuid4

from packaging.utils import parse_wheel_filename

from .dependency_gate import (
    GateDecision,
    SharedDependencyError,
    parse_requirements_file,
)
from .execution.dependencies import DependencySnapshot, _dependency_closure
from .wheel_additions import WheelAddition, validate_additions


class DependencyUpgradeRequired(RuntimeError):
    """The source is retained, but replacing packages needs explicit apply."""

    def __init__(self, operation):
        self.operation = operation
        super().__init__(operation["message"])


def _refuse(code, message):
    raise SharedDependencyError(
        GateDecision(False, False, reason=message, reason_code=code),
    )


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()


def _source_hash(root):
    from .execution.bootstrap import _hash_code_root

    for path in root.rglob("*"):
        if path.is_symlink():
            _refuse(
                "DEPENDENCY_PLAN_UNVERIFIED",
                "Plugin source contains a symlink.",
            )
    return _hash_code_root(root)


def install_result(record):
    """Use the ordinary install response after resumed source publication."""
    manifest = record.manifest
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "author": manifest.author,
        "loaded": record.status == "active",
        "status": record.status,
        "enabled": record.enabled,
        "diagnostics": list(record.diagnostics or []),
        "message": f"Plugin '{manifest.name}' installation: {record.status}.",
    }


def dependency_upgrades(loader):
    """One manager and operation namespace for HTTP and CLI callers."""
    manager = getattr(loader, "_dependency_upgrade_manager", None)
    if manager is None:
        manager = DependencyUpgradeManager(loader)
        loader._dependency_upgrade_manager = manager
    return manager


async def install_with_upgrade(loader, source_path, **kwargs):
    """Retain extracted uploads before their request staging is cleaned up."""
    try:
        return await loader.load_plugin_from_path(
            source_path=source_path,
            **kwargs,
        )
    except RuntimeError as exc:
        await stage_dependency_refusal(
            loader,
            source_path,
            exc,
            force=kwargs.get("force", False),
        )


async def stage_dependency_refusal(loader, source_path, error, *, force=False):
    """Install and repair share source retention and replacement decisions."""
    code = getattr(error, "reason_code", "") or getattr(
        getattr(error, "decision", None),
        "reason_code",
        "",
    )
    if code not in {
        "DEPENDENCY_RESTART_REQUIRED",
        "DEPENDENCY_UNSATISFIED",
    } and not any(
        value in str(error)
        for value in ("DEPENDENCY_RESTART_REQUIRED", "DEPENDENCY_UNSATISFIED")
    ):
        raise error
    operation = await dependency_upgrades(loader).stage(
        source_path,
        force=force,
    )
    raise DependencyUpgradeRequired(operation) from error


class DependencyUpgradeManager:
    """Stage immutable wheels; publish only an explicitly approved operation."""

    def __init__(self, loader):
        from ..config.utils import get_config_path

        self.loader = loader
        self.root = get_config_path().parent / "dependency_upgrades"
        self._locks = {}

    def _directory(self, operation_id):
        if (
            not isinstance(operation_id, str)
            or len(operation_id) != 32
            or any(char not in "0123456789abcdef" for char in operation_id)
        ):
            raise FileNotFoundError("Dependency operation not found.")
        path = self.root / operation_id
        if path.is_symlink() or not (path / "operation.json").is_file():
            raise FileNotFoundError("Dependency operation not found.")
        return path

    def _read(self, operation_id):
        from .dependency_transaction import authenticate_plan

        directory = self._directory(operation_id)
        operation = json.loads((directory / "operation.json").read_text())
        authenticate_plan(directory, operation)
        from .dependency_transaction import reconcile_commit

        reconcile_commit(directory, operation)
        return operation

    @staticmethod
    def _save(directory, operation):
        from .dependency_transaction import atomic_json

        atomic_json(directory / "operation.json", operation)

    @staticmethod
    def _public(operation):
        keys = (
            "id",
            "plugin_id",
            "status",
            "changes",
            "affected_instances",
            "requires_restart",
            "result",
            "message",
            "error",
            "retryable",
            "instructions",
        )
        return {key: operation.get(key) for key in keys}

    def status(self, operation_id):
        return self._public(self._read(operation_id))

    def cancel(self, operation_id):
        directory = self._directory(operation_id)
        from .dependency_transaction import operation_lock

        with operation_lock(directory):
            operation = self._read(operation_id)
            if operation["status"] == "cancelled":
                return self._public(operation)
            if operation["status"] not in {
                "needs_confirmation",
                "waiting_restart",
            } or operation.get("worker_pid"):
                raise RuntimeError(
                    "Dependency operation cannot be cancelled while applying.",
                )
            operation.update(
                status="cancelled",
                message="Dependency upgrade cancelled.",
                retryable=False,
            )
            self._save(directory, operation)
            for name in ("source", "wheels", "payload"):
                shutil.rmtree(directory / name, ignore_errors=True)
            return self._public(operation)

    async def _binding(self, source):
        _, manifest = self.loader.read_source_manifest(source)
        compatible, message = self.loader._check_version_compatibility(
            manifest,
        )
        if not compatible:
            _refuse("DEPENDENCY_PLAN_UNVERIFIED", message)
        return self.loader.backend_resolver.resolve(source, manifest)

    async def _consumers(self, binding, snapshot):
        """Installed declarations participate even when currently inactive."""
        consumers = []
        plugin_id = binding.description.manifest.id
        for manifest, source in self.loader.discover_plugins():
            if manifest.id == plugin_id:
                continue
            other = self.loader.backend_resolver.resolve(source, manifest)
            observed = await other.backend.audit_dependencies(
                other.description,
            )
            if set(observed.dependency_sites or ()).intersection(
                snapshot.dependency_sites or (),
            ):
                consumers.append(
                    {
                        "plugin_id": manifest.id,
                        "instance_id": None,
                        "generation": None,
                        "origin": "installed",
                        "active": False,
                        "source_revision": _source_hash(source),
                        "requirements": list(other.description.requirements),
                        "environment": observed.to_mapping(),
                    },
                )
        for use in self.loader.registry.dependency_usage.snapshot().uses:
            if use.plugin_id == plugin_id and use.origin != "host":
                continue
            if (
                use.environment is None
                or use.snapshot is None
                or use.requirements is None
            ):
                _refuse(
                    "DEPENDENCY_PLAN_UNVERIFIED",
                    "A shared consumer has incomplete dependency evidence.",
                )
            if set(use.environment.sites).intersection(
                snapshot.dependency_sites or (),
            ):
                consumers.append(
                    {
                        "plugin_id": use.plugin_id,
                        "instance_id": use.instance_id,
                        "generation": use.generation,
                        "origin": use.origin,
                        "active": use.active,
                        "source_revision": use.source_revision,
                        "requirements": list(use.requirements),
                        "environment": use.snapshot.to_mapping(),
                    },
                )
        host = snapshot.distributions.get("qwenpaw")
        if host:
            consumers.append(
                {
                    "plugin_id": "qwenpaw",
                    "instance_id": None,
                    "generation": None,
                    "origin": "host",
                    "active": True,
                    "source_revision": host["version"],
                    "requirements": [f"qwenpaw=={host['version']}"],
                    "environment": snapshot.to_mapping(),
                },
            )
        return consumers

    def _reviewed_usage(self, consumers, *, offline=False, sites=()):
        """Bind confirmation to declarations and exact runtime generations."""

        def identity(row):
            environment = row.get("environment")
            if environment is not None:
                environment = {
                    "executable": environment["executable"],
                    "sites": sorted(environment["dependency_sites"] or ()),
                    "marker_environment": environment["marker_environment"],
                }
            return {
                **{
                    key: row.get(key)
                    for key in (
                        "plugin_id",
                        "source_revision",
                        "instance_id",
                        "generation",
                        "origin",
                        "active",
                        "pending",
                    )
                },
                "requirements": sorted(row.get("requirements") or ()),
                "environment": environment,
            }

        rows = [
            identity(row)
            for row in consumers
            if not offline
            or row["origin"] == "installed"
            or (row["origin"] == "host" and row["plugin_id"] == "qwenpaw")
        ]
        uses = []
        if not offline:
            for use in self.loader.registry.dependency_usage.snapshot().uses:
                environment = use.environment
                if (
                    sites
                    and environment is not None
                    and not set(environment.sites).intersection(sites)
                ):
                    continue
                uses.append(
                    identity(
                        {
                            "plugin_id": use.plugin_id,
                            "source_revision": use.source_revision,
                            "instance_id": use.instance_id,
                            "generation": use.generation,
                            "origin": use.origin,
                            "active": use.active,
                            "pending": use.pending,
                            "requirements": use.requirements,
                            "environment": (
                                {
                                    "executable": environment.executable,
                                    "dependency_sites": environment.sites,
                                    "marker_environment": dict(
                                        environment.marker_environment,
                                    ),
                                }
                                if environment is not None
                                else None
                            ),
                        },
                    ),
                )
        normalize = lambda values: sorted(
            {json.dumps(value, sort_keys=True) for value in values},
        )
        return {"consumers": normalize(rows), "uses": normalize(uses)}

    def _check_reviewed_usage(
        self,
        operation,
        consumers,
        *,
        offline=False,
        allow_stopped=False,
    ):
        current = self._reviewed_usage(
            consumers,
            offline=offline,
            sites=operation["environment"]["dependency_sites"],
        )
        if offline:
            reviewed = self._reviewed_usage(
                operation["consumers"],
                offline=True,
            )
        else:
            reviewed = operation["reviewed_usage"]
        matches = all(
            (
                set(current[key]) <= set(reviewed[key])
                if allow_stopped
                else current[key] == reviewed[key]
            )
            for key in current
        )
        if not matches:
            raise RuntimeError(
                "DEPENDENCY_PLAN_STALE: shared consumers changed after review; prepare a new confirmation.",
            )

    @staticmethod
    def _compatible(requirements, inventory, markers):
        try:
            for name, requirement in _dependency_closure(
                requirements,
                inventory,
                markers,
            ):
                row = inventory.get(name)
                if row is None or not requirement.specifier.contains(
                    row["version"],
                    prereleases=True,
                ):
                    _refuse(
                        "DEPENDENCY_CONFLICT",
                        f"Shared requirements cannot be satisfied: {requirement}.",
                    )
        except (ValueError, TypeError, KeyError):
            _refuse(
                "DEPENDENCY_PLAN_UNVERIFIED",
                "Shared requirement metadata cannot be verified.",
            )

    async def stage(self, source_path, force=False):
        source_path = Path(source_path).resolve()
        revision = _source_hash(source_path)
        operation_id = uuid4().hex
        directory = self.root / operation_id
        directory.mkdir(parents=True, mode=0o700)
        try:
            source = directory / "source"
            await asyncio.to_thread(shutil.copytree, source_path, source)
            if _source_hash(source) != revision:
                _refuse(
                    "DEPENDENCY_PLAN_STALE",
                    "Plugin source changed during preparation; retry installation.",
                )
            binding = await self._binding(source)
            plugin_id = binding.description.manifest.id
            parsed = parse_requirements_file(
                binding.description.requirements_path,
            )
            if parsed.unsupported:
                _refuse(
                    "DEPENDENCY_PLAN_UNVERIFIED",
                    "Unsupported dependency declarations: "
                    + ", ".join(parsed.unsupported),
                )
            snapshot = await binding.backend.audit_dependencies(
                binding.description,
            )
            if (
                not isinstance(snapshot, DependencySnapshot)
                or not snapshot.dependency_sites
            ):
                _refuse(
                    "DEPENDENCY_PLAN_UNVERIFIED",
                    "Actual dependency environment is unavailable.",
                )
            consumers = await self._consumers(binding, snapshot)
            target = binding.backend.dependency_install_target(
                binding.description,
                snapshot,
            )
            if target is None:
                _refuse(
                    "DEPENDENCY_PLAN_UNVERIFIED",
                    "The dependency installation site is ambiguous.",
                )
            requirements = list(binding.description.requirements)
            from .dependency_transaction import environment_fingerprint

            fingerprint = environment_fingerprint(snapshot.to_mapping())
            wheels_dir = directory / "wheels"
            wheels_dir.mkdir()
            resolver = directory / "requirements.txt"
            # Resolve host dependencies without acquiring a new QwenPaw wheel.
            resolver.write_text(
                "".join(str(value) + "\n" for value in requirements)
                + "".join(
                    value + "\n"
                    for consumer in consumers
                    for value in (
                        consumer["environment"]["distributions"]["qwenpaw"][
                            "requires_dist"
                        ]
                        if consumer["origin"] == "host"
                        and consumer["plugin_id"] == "qwenpaw"
                        else consumer["requirements"]
                    )
                ),
                encoding="utf-8",
            )
            closure = {
                name
                for name, _ in _dependency_closure(
                    requirements,
                    snapshot.distributions,
                    snapshot.marker_environment,
                )
            }
            constraints = directory / "constraints.txt"
            constraints.write_text(
                "".join(
                    f"{name}=={row['version']}\n"
                    for name, row in snapshot.distributions.items()
                    if name not in closure
                ),
                encoding="utf-8",
            )
            command = [
                snapshot.executable,
                "-I",
                "-m",
                "pip",
                "wheel",
                "--disable-pip-version-check",
                "--no-input",
                "--wheel-dir",
                str(wheels_dir),
                "--constraint",
                str(constraints),
                "-r",
                str(resolver),
                "-r",
                str(binding.description.requirements_path),
            ]
            task = asyncio.create_task(
                asyncio.to_thread(
                    self.loader._run_subprocess_with_streaming_log,
                    command,
                    timeout=300,
                    plugin_id=plugin_id,
                ),
            )
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError:
                from .execution.process import _settle

                await _settle(task)
                raise
            if result.returncode:
                _refuse(
                    "DEPENDENCY_CONFLICT",
                    "A complete compatible wheel plan could not be prepared; check the plugin and shared requirements.",
                )
            wheels = []
            changed = {}
            for path in sorted(wheels_dir.glob("*.whl")):
                name, version, _, _ = parse_wheel_filename(path.name)
                name = str(name)
                old = snapshot.distributions.get(name)
                if old and old["version"] == str(version):
                    continue
                if name in changed:
                    _refuse(
                        "DEPENDENCY_PLAN_UNVERIFIED",
                        "Duplicate wheel provider in dependency plan.",
                    )
                changed[name] = old
                wheels.append(
                    WheelAddition(
                        path,
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    ),
                )
            if not changed:
                _refuse(
                    "DEPENDENCY_PLAN_UNVERIFIED",
                    "No dependency replacement was resolved.",
                )
            # Archive validation is shared with online additions. Physical
            # collisions are checked below against exact installed ownership.
            clean = replace(
                snapshot,
                sites=(),
                distributions={
                    name: row
                    for name, row in snapshot.distributions.items()
                    if name not in changed
                },
            )
            files, proposed = validate_additions(
                tuple(wheels),
                clean,
                Path(target),
            )
            destinations = {}
            changes = []
            for name in changed:
                old, row = changed[name], proposed.distributions[name]
                site = (
                    Path(old["metadata_path"]).parent if old else Path(target)
                )
                destinations[name] = str(site.resolve())
                proposed.distributions[name]["metadata_path"] = str(
                    site / Path(row["metadata_path"]).name,
                )
                changes.append(
                    {
                        "name": name,
                        "current_version": old["version"] if old else None,
                        "target_version": row["version"],
                    },
                )
            inventory = dict(proposed.distributions)
            self._compatible(
                requirements,
                inventory,
                snapshot.marker_environment,
            )
            for consumer in consumers:
                evidence = consumer["environment"]
                visible = set(evidence["dependency_sites"])
                merged = dict(evidence["distributions"])
                merged.update(
                    {
                        name: row
                        for name, row in inventory.items()
                        if str(Path(row["metadata_path"]).parent) in visible
                    },
                )
                self._compatible(
                    consumer["requirements"],
                    merged,
                    evidence["marker_environment"],
                )
            from .dependency_transaction import (
                prepare_payload,
                imported_changes,
            )

            payload = prepare_payload(
                directory,
                snapshot.to_mapping(),
                changed,
                destinations,
                files,
                [
                    (
                        item.to_mapping()
                        if hasattr(item, "to_mapping")
                        else {
                            "path": str(item.path),
                            "sha256": item.sha256,
                        }
                    )
                    for item in wheels
                ],
            )
            requires_restart = bool(imported_changes(payload)) or any(
                consumer["origin"] == "host"
                and set(changed).intersection(
                    name
                    for name, _ in _dependency_closure(
                        consumer["requirements"],
                        inventory,
                        consumer["environment"]["marker_environment"],
                    )
                )
                for consumer in consumers
            )
            runtime = getattr(self.loader.registry, "channel_runtime", None)
            runtime_data = None
            if runtime is not None:
                from dataclasses import asdict

                runtime_data = asdict(runtime)
                runtime_data = json.loads(
                    json.dumps(
                        runtime_data,
                        default=lambda value: (
                            list(value)
                            if isinstance(value, frozenset)
                            else str(value)
                        ),
                    ),
                )
            operation = {
                "id": operation_id,
                "plugin_id": plugin_id,
                "status": "needs_confirmation",
                "changes": changes,
                "affected_instances": [
                    {
                        key: consumer[key]
                        for key in (
                            "plugin_id",
                            "instance_id",
                            "generation",
                            "origin",
                            "active",
                        )
                    }
                    for consumer in consumers
                ],
                "requires_restart": requires_restart,
                "result": None,
                "message": "Review and apply the shared dependency upgrade to continue installation.",
                "error": None,
                "retryable": True,
                "instructions": [],
                "force": bool(force),
                "source_revision": revision,
                "environment": snapshot.to_mapping(),
                "environment_fingerprint": fingerprint,
                "consumers": consumers,
                "reviewed_usage": self._reviewed_usage(
                    consumers,
                    sites=snapshot.dependency_sites,
                ),
                "proposed": inventory,
                "payload": payload,
                "capability": secrets.token_hex(32),
                "plugin_dirs": [
                    str(path.resolve()) for path in self.loader.plugin_dirs
                ],
                "runtime": runtime_data,
                "approved": False,
            }
            retain_maintenance_assets(directory, operation, self.loader)
            from .dependency_transaction import authenticate_plan

            authenticate_plan(directory, operation, seal=True)
            self._save(directory, operation)
            return self._public(operation)
        except BaseException as exc:
            shutil.rmtree(directory, ignore_errors=True)
            if (
                isinstance(exc, RuntimeError)
                and not isinstance(exc, SharedDependencyError)
                and str(exc).startswith("DEPENDENCY_")
            ):
                _refuse(str(exc).split(":", 1)[0], str(exc))
            raise

    async def apply(self, operation_id):
        from .dependency_transaction import apply_operation

        lock = self._locks.setdefault(operation_id, asyncio.Lock())
        if lock.locked():
            return self.status(operation_id)
        async with lock:
            return await apply_operation(self, operation_id)


def retain_maintenance_assets(directory, operation, loader):
    """Recovery must remain executable before any online file can change."""
    runtime = getattr(loader.registry, "channel_runtime", None)
    candidates = [Path(__file__).resolve().parent]
    if runtime is not None:
        candidates.append(Path(runtime.support_root) / "qwenpaw/plugins")
    names = (
        "dependency_worker.py",
        "dependency_transaction.py",
        "dependency_maintenance.py",
    )
    assets = next(
        (
            root
            for root in candidates
            if all(
                (root / name).is_file() and not (root / name).is_symlink()
                for name in names
            )
        ),
        None,
    )
    if assets is None:
        _refuse(
            "DEPENDENCY_INSTALLER_UNAVAILABLE",
            "Trusted offline maintenance assets are unavailable.",
        )
    worker = directory / "worker"
    worker.mkdir(exist_ok=True)
    for name in names:
        shutil.copy2(assets / name, worker / name)
    frozen = bool(getattr(sys, "frozen", False))
    executable = (
        runtime.python_executable
        if frozen and runtime is not None
        else sys.executable
    )
    operation.update(
        continuation_python=os.path.abspath(executable),
        worker_python=os.path.abspath(executable),
        support_root=str(assets.parents[1]),
    )


def schedule_maintenance(manager, directory, operation):
    """Explicit apply persists approval before handing off to a fresh worker."""
    import shlex
    import subprocess

    worker = directory / "worker"
    operation.update(
        status="waiting_restart",
        requires_restart=True,
        message="The backend must exit before this shared dependency upgrade can apply.",
        backend_pid=os.getpid(),
    )
    shutdown = getattr(manager.loader, "dependency_upgrade_shutdown", None)
    restart = getattr(manager.loader, "dependency_upgrade_restart", None)
    operation["restart"] = restart
    script = worker / "dependency_worker.py"
    command = [operation["worker_python"], "-I", "-S", str(script)]
    operation["instructions"] = [
        "Stop this backend and its channel processes through their service manager, "
        "and keep them stopped during maintenance. For Supervisor's app program: "
        "supervisorctl -c /path/to/supervisord.conf stop app "
        "(use your actual config and program name).",
        "Then run the retained worker: " + shlex.join(command),
        "The worker applies the retained plan and resumes installation. After success "
        "or confirmed safe rollback, restart through the original launcher or service "
        "manager. For Supervisor: supervisorctl -c /path/to/supervisord.conf start app.",
        "If DEPENDENCY_REPAIR_REQUIRED is reported, keep the backend stopped and "
        "recover using the same retained worker. Never edit operation.json or run "
        "pip outside the retained transaction.",
    ]
    manager._save(directory, operation)
    if shutdown is not None and restart is not None:
        options = (
            {"start_new_session": True}
            if os.name != "nt"
            else {
                "creationflags": getattr(
                    subprocess,
                    "CREATE_NEW_PROCESS_GROUP",
                    0,
                ),
            }
        )
        log = (directory / "worker.log").open("ab")
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                **options,
            )
        finally:
            log.close()
        operation["worker_pid"] = process.pid
        operation[
            "message"
        ] = "Restarting the backend to apply shared dependencies and resume installation."
        operation["instructions"] = []
        manager._save(directory, operation)
        asyncio.get_running_loop().call_later(0.25, shutdown)


async def continue_operation(directory, *, preflight=False):
    """Fresh-process verification and offline source publication for a worker."""
    from .channel_adapter import ChannelRuntimeSettings
    from .loader import PluginLoader
    from .lifecycle import UnloadMode
    from .dependency_transaction import (
        environment_fingerprint,
        verify_payload,
        atomic_json,
    )

    directory = Path(directory).resolve()
    operation = json.loads((directory / "operation.json").read_text())
    from .dependency_transaction import authenticate_plan

    authenticate_plan(directory, operation)
    runtime = operation["runtime"]
    if runtime is not None:
        runtime = dict(runtime)
        runtime["support_root"] = Path(runtime["support_root"])
        runtime["dependency_paths"] = tuple(
            Path(path) for path in runtime["dependency_paths"]
        )
        if runtime["dependency_install_target"]:
            runtime["dependency_install_target"] = Path(
                runtime["dependency_install_target"],
            )
        if runtime["selected_channels"] is not None:
            runtime["selected_channels"] = frozenset(
                runtime["selected_channels"],
            )
        runtime = ChannelRuntimeSettings(**runtime)
    loader = PluginLoader(
        [Path(path) for path in operation["plugin_dirs"]],
        channel_runtime=runtime,
    )
    manager = DependencyUpgradeManager(loader)
    try:
        source = directory / "source"
        if _source_hash(source) != operation["source_revision"]:
            raise RuntimeError(
                "DEPENDENCY_PLAN_STALE: retained source changed.",
            )
        binding = await manager._binding(source)
        observed = await binding.backend.audit_dependencies(
            binding.description,
        )
        if preflight:
            if (
                environment_fingerprint(observed.to_mapping())
                != operation["environment_fingerprint"]
            ):
                raise RuntimeError(
                    "DEPENDENCY_PLAN_STALE: environment changed after review.",
                )
            verify_payload(directory, operation)
            consumers = await manager._consumers(binding, observed)
            manager._check_reviewed_usage(operation, consumers, offline=True)
            for consumer in consumers:
                evidence = consumer["environment"]
                inventory = dict(evidence["distributions"])
                inventory.update(
                    {
                        name: row
                        for name, row in operation["proposed"].items()
                        if str(Path(row["metadata_path"]).parent)
                        in evidence["dependency_sites"]
                    },
                )
                manager._compatible(
                    consumer["requirements"],
                    inventory,
                    evidence["marker_environment"],
                )
            return
        for change in operation["changes"]:
            actual = observed.distributions.get(change["name"])
            if (
                actual is None
                or actual != operation["proposed"][change["name"]]
            ):
                # Transport arrays and persisted tuples have equivalent data.
                if actual is None or _digest(dict(actual)) != _digest(
                    operation["proposed"][change["name"]],
                ):
                    raise RuntimeError(
                        "DEPENDENCY_VERIFICATION_FAILED: fresh dependency provider differs.",
                    )
        manager._compatible(
            binding.description.requirements,
            observed.distributions,
            observed.marker_environment,
        )
        await loader.lifecycle.prepare_backend(
            binding,
            allow_install=False,
            probe=True,
        )
        record = await loader.install_plugin_files(
            source,
            force=operation["force"],
        )
        atomic_json(directory / "continuation.json", install_result(record))
    finally:
        reports = await loader.lifecycle.unload_all(UnloadMode.SHUTDOWN)
        if any(
            not report.clean or not report.quiescent or report.needs_restart
            for report in reports
        ):
            raise RuntimeError(
                "DEPENDENCY_REPAIR_REQUIRED: continuation child cleanup failed.",
            )
