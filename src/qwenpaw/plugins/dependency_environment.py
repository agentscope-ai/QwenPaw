# -*- coding: utf-8 -*-
"""Offline dependency generation coordination; executable with python -I -S.

Only stdlib modules are loaded until the candidate's approved paths are bound.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import stat
import time
import sys
import types
from uuid import uuid4


def _modules():
    name = __package__
    if not name:
        name = "_qwenpaw_environment"
        package = types.ModuleType(name)
        package.__path__ = [str(Path(__file__).resolve().parent)]
        sys.modules[name] = package
    modules = tuple(
        importlib.import_module(name + "." + suffix)
        for suffix in (
            "dependency_context",
            "dependency_maintenance",
            "dependency_transaction",
        )
    )
    if sys.flags.no_site:
        modules[1].restore_managed_interpreter_prefix()
    return modules


def _read(path):
    if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_POLICY_INVALID")
    return json.loads(path.read_text(encoding="utf-8"))


def _previous(path):
    return _read(path) if path.exists() else None


def _tree_identity(root):
    """Activation checks current candidate bytes, including unowned additions."""
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes(),
            ).hexdigest()
    return result


def _source_identity(root):
    # This is an offline boundary. Retain every source byte, not an import-based
    # guess at the declaration or executable subset.
    return _tree_identity(root)


def _offline_tree():
    context_module, _, _ = _modules()
    worker = importlib.import_module(
        context_module.__package__ + ".dependency_worker",
    )
    return worker._process_tree_module()


def _run_offline(command, *, timeout, env=None):
    """Own the verifier before releasing it, and settle its tree and readers."""
    _, maintenance, _ = _modules()
    environment = dict(os.environ if env is None else env)
    scope = os.urandom(32).hex()
    environment["QWENPAW_DEPENDENCY_READER_SCOPE"] = scope
    environment["QWENPAW_DEPENDENCY_STATE_DIR"] = str(maintenance.state_root())
    command = [*command, "--parent-pid", str(os.getpid())]
    process = subprocess.Popen(
        command,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=os.name != "nt",
    )
    tree = None
    try:
        tree = _offline_tree().ProcessTree(process.pid)
        stdout, stderr = process.communicate(input="1", timeout=timeout)
    finally:
        if tree is not None:
            if tree.alive():
                tree.signal(force=True)
            process.wait(timeout=5)
            deadline = time.monotonic() + 5
            while True:
                readers = False
                for path in maintenance.state_root().glob(
                    "*/.*.dependencies-readers/" + scope + "/*.lease",
                ):
                    if path.is_symlink():
                        raise RuntimeError("DEPENDENCY_REPAIR_REQUIRED")
                    try:
                        descriptor = os.open(
                            path,
                            os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                        )
                    except FileNotFoundError:
                        continue
                    try:
                        readers |= not maintenance._try_lock(descriptor)
                    finally:
                        os.close(descriptor)
                if not tree.alive() and not readers:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "DEPENDENCY_REPAIR_REQUIRED: offline descendants did not exit.",
                    )
                time.sleep(0.01)
            tree.close()
        elif process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    return subprocess.CompletedProcess(
        command,
        process.returncode,
        stdout,
        stderr,
    )


def prepare_environment(
    policy_path,
    *,
    active_policy_path,
    extra_requirements=None,
    plugin_dirs=None,
):
    """Build and verify an independent generation without changing active policy."""
    context_module, _, _ = _modules()
    source = context_module.policy_path(policy_path)
    active = context_module.policy_path(active_policy_path)
    # Validate before spawning; the child repeats validation before any write.
    context_module.read_dependency_policy(source, prepared=True)
    # A scoped verifier can lock only parent-provisioned coordination files.
    with context_module.dependency_policy_lock(active):
        pass
    command = [
        sys.executable,
        "-I",
        "-B",
        "-S",
        str(Path(__file__).resolve()),
        "_prepare",
        str(source),
        "--active-policy",
        str(active),
    ]
    if extra_requirements is not None:
        command += ["--requirements", str(Path(extra_requirements).absolute())]
    for root in plugin_dirs or ():
        command += ["--plugin-dir", str(Path(root).absolute())]
    result = _run_offline(
        command,
        timeout=600,
    )
    if result.returncode:
        code = next(
            (
                line
                for line in reversed(result.stderr.splitlines())
                if line.startswith("DEPENDENCY_")
            ),
            "DEPENDENCY_ENVIRONMENT_PREPARATION_FAILED",
        )
        raise RuntimeError(code)
    report = Path(result.stdout.strip().splitlines()[-1])
    if not report.is_absolute() or not report.is_file():
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_PREPARATION_FAILED")
    return report


def _trusted_tools(context):
    """Candidate-only binding; no prepared-state or active-policy bypass flag."""
    if not sys.flags.no_site:
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_CLEAN_PROCESS_REQUIRED")
    context_module, maintenance, _ = _modules()
    maintenance.restore_managed_interpreter_prefix()
    if scope := os.environ.get("QWENPAW_DEPENDENCY_READER_SCOPE"):
        maintenance.prepare_reader_scope(context.dependency_paths, scope)
    sys.path[:] = context_module.dependency_import_paths(
        [str(context.support_root), *sys.path],
        context,
    )
    for name, path in (
        ("qwenpaw", context.support_root / "qwenpaw"),
        ("qwenpaw.plugins", context.support_root / "qwenpaw/plugins"),
    ):
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        package.__package__ = name
        sys.modules[name] = package
    selected = importlib.import_module("qwenpaw.plugins.dependency_context")
    context = selected.DependencyEnvironmentContext.from_mapping(
        context.to_mapping(),
    )
    selected._SELECTED_ENVIRONMENT = context
    # Candidate is not active and carries no installation policy authority.
    selected._SELECTED_POLICY = None
    return context


def _collect_sources(plugin_dirs):
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.dependency_gate import (
        combined_requirements,
        parse_requirements_file,
    )
    from qwenpaw.plugins.dependency_maintenance import canonical
    from qwenpaw.constant import WORKING_DIR
    from qwenpaw.config.utils import get_config_path
    from qwenpaw.plugins.settings import is_plugin_enabled

    config_path = get_config_path()
    settings = (
        _read(config_path).get("plugins", {}) if config_path.is_file() else {}
    )
    if not isinstance(settings, dict):
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_DECLARATION_UNSUPPORTED: invalid plugin settings.",
        )

    if plugin_dirs is None:
        plugin_dirs = (
            [WORKING_DIR / "plugins"]
            if (WORKING_DIR / "plugins").is_dir()
            else []
        )
        bundle = Path(__file__).resolve().parents[3] / "plugins/bundle"
        if bundle.is_dir():
            plugin_dirs.append(bundle)
    sources, requirements, index_urls = [], [], []
    for value in plugin_dirs:
        root = Path(value)
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_SOURCE_UNAVAILABLE: plugin directory missing.",
            )
        root = canonical(root)
        children = (
            [root]
            if (root / "plugin.json").exists()
            else sorted(root.iterdir())
        )
        for source in children:
            if not source.is_dir():
                continue
            manifest_file = source / "plugin.json"
            if source.is_symlink() or not manifest_file.is_file():
                raise RuntimeError(
                    "DEPENDENCY_ENVIRONMENT_SOURCE_UNAVAILABLE: plugin declaration missing.",
                )
            manifest = PluginManifest.model_validate(_read(manifest_file))
            with combined_requirements(source) as declarations:
                parsed = parse_requirements_file(declarations)
            if parsed.unsupported:
                raise RuntimeError(
                    "DEPENDENCY_ENVIRONMENT_DECLARATION_UNSUPPORTED: "
                    + manifest.id,
                )
            requirements.extend(str(value) for value in parsed.requirements)
            index_urls.extend(parsed.index_urls)
            sources.append(
                {
                    "path": str(source),
                    "identity": _source_identity(source),
                    "plugin_id": manifest.id,
                    "enabled": is_plugin_enabled(settings.get(manifest.id)),
                },
            )
    return sources, requirements, list(map(str, plugin_dirs)), index_urls


async def _verify_plugins(context, sources):
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.lifecycle import UnloadMode
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.__version__ import __version__

    runtime = ChannelRuntimeSettings(
        context.python_executable,
        context.support_root,
        __version__,
        selected_channels=None,
        dependency_paths=context.dependency_paths,
        dependency_install_target=context.install_target,
    )
    loader = await PluginLoader.create([], channel_runtime=runtime)
    try:
        for source in sources:
            _, manifest = loader.read_source_manifest(Path(source["path"]))
            binding = loader.backend_resolver.resolve(
                Path(source["path"]),
                manifest,
            )
            await loader.lifecycle.preflight_backend(
                binding,
                allow_install=False,
                probe=True,
            )
    finally:
        reports = await loader.lifecycle.unload_all(UnloadMode.SHUTDOWN)
        if any(
            not row.clean or not row.quiescent or row.needs_restart
            for row in reports
        ):
            raise RuntimeError(
                "DEPENDENCY_CONSUMER_BUSY: candidate verification did not exit.",
            )


async def _prepare_candidate(
    policy_path,
    active_policy_path,
    extra_requirements,
    plugin_dirs,
):
    context_module, maintenance, transaction = _modules()
    data = context_module.read_dependency_policy(policy_path, prepared=True)
    # Even a repair of the same base gets independent bytes and identity.
    data["generation"] = uuid4().hex
    context = context_module.context_for_policy(data)
    active = context_module.policy_path(active_policy_path)
    with context_module.dependency_policy_lock(active):
        previous = _previous(active)
    context.install_target.mkdir(parents=True, exist_ok=False)
    context = _trusted_tools(context)
    from qwenpaw.plugins.dependency_gate import parse_requirements_file
    from qwenpaw.plugins.dependency_upgrade import (
        prepare_environment_dependencies,
    )
    from qwenpaw.plugins.execution.dependencies import _installed_metadata

    sources, requirements, plugin_dirs, index_urls = _collect_sources(
        plugin_dirs,
    )
    extras = None
    if extra_requirements:
        path = Path(extra_requirements)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_DECLARATION_UNSUPPORTED",
            )
        parsed = parse_requirements_file(path)
        if parsed.unsupported:
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_DECLARATION_UNSUPPORTED",
            )
        requirements.extend(str(value) for value in parsed.requirements)
        index_urls.extend(parsed.index_urls)
        extras = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    # Legacy extras are never guessed using freeze. A supplied manifest is the
    # administrator's explicit authoritative replacement inventory.
    old_rows, old_invalid, _ = _installed_metadata(
        tuple(Path(p) for p in data["legacy_sites"]),
    )
    if (old_rows or old_invalid) and extra_requirements is None:
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_DECLARATIONS_REQUIRED: provide the "
            "complete additional requirements, or an explicit empty file "
            "for packages retained outside this application.",
        )
    rows, invalid, _ = _installed_metadata(context.immutable_roots)
    if invalid:
        raise RuntimeError("DEPENDENCY_METADATA_INVALID")
    if "qwenpaw" not in rows:
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_HOST_UNAVAILABLE: base must contain installed host metadata.",
        )
    requirements = list(dict.fromkeys(["qwenpaw", *requirements]))
    index_urls = list(dict.fromkeys(index_urls))
    if len(index_urls) > 1:
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_INDEX_CONFLICT: declarations select different indexes.",
        )
    work = context.install_target.parent / "preparation"
    work.mkdir()
    snapshot = await prepare_environment_dependencies(
        context,
        requirements,
        work,
        index_urls=index_urls,
    )
    await _verify_plugins(context, sources)
    # Child and all probe processes have exited before activation is possible.
    report = context.install_target.parent / "prepared.json"
    record = {
        "schema_version": 1,
        "phase": "prepared",
        "id": uuid4().hex,
        "policy": data,
        "policy_sha256": context_module._digest(data),
        "active_policy_path": str(active),
        "previous_policy": previous,
        "previous_sha256": context_module._digest(previous),
        "dependency_context": context.to_mapping(),
        "sources": sources,
        "plugin_dirs": plugin_dirs,
        "extra_requirements": extras,
        "requirements": requirements,
        "index_identity": context_module._digest(index_urls),
        "legacy_inventory": {"providers": old_rows, "invalid": old_invalid},
        "validation": {
            "environment": snapshot.to_mapping(),
            "files": _tree_identity(context.install_target),
            "base_metadata_identity": context_module.dependency_metadata_identity(
                context.immutable_roots,
                "managed-prepare",
            ),
        },
    }
    record["validation"]["providers"] = {
        name: transaction._owned(row, snapshot.prefix)
        for name, row in snapshot.distributions.items()
        if maintenance.canonical(Path(row["metadata_path"]).parent)
        == context.install_target
    }
    transaction.atomic_json(report, record)
    return report


def _revalidate(record, active):
    context_module, maintenance, _ = _modules()
    if record.get("schema_version") != 1 or record.get(
        "active_policy_path",
    ) != str(active):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_PLAN_STALE")
    data = context_module._validate_policy_data(record["policy"])
    context = context_module.context_for_policy(data)
    if (
        data != record["policy"]
        or context_module._digest(data) != record["policy_sha256"]
        or context.to_mapping() != record["dependency_context"]
    ):
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_PLAN_STALE")
    if _tree_identity(context.install_target) != record["validation"]["files"]:
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_PLAN_STALE: candidate bytes changed.",
        )
    if (
        context_module.dependency_metadata_identity(
            context.immutable_roots,
            "managed-prepare",
        )
        != record["validation"]["base_metadata_identity"]
    ):
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_PLAN_STALE: base metadata changed.",
        )
    for source in record["sources"]:
        if _source_identity(Path(source["path"])) != source["identity"]:
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_PLAN_STALE: plugin source changed.",
            )
    extra = record["extra_requirements"]
    if (
        extra
        and hashlib.sha256(Path(extra["path"]).read_bytes()).hexdigest()
        != extra["sha256"]
    ):
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_PLAN_STALE: requirements changed.",
        )
    for root in context.dependency_paths:
        maintenance.check_admission(root)
    for files in record["validation"]["providers"].values():
        for name, evidence in files.items():
            path = Path(name)
            if (
                path.is_symlink()
                or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest()
                != evidence["sha256"]
                or stat.S_IMODE(path.stat().st_mode) != evidence["mode"]
            ):
                raise RuntimeError(
                    "DEPENDENCY_ENVIRONMENT_PLAN_STALE: provider bytes changed.",
                )
    return context


async def _verify_candidate(prepared_path):
    context_module, _, _ = _modules()
    record = _read(Path(prepared_path))
    context = context_module.DependencyEnvironmentContext.from_mapping(
        record["dependency_context"],
    )
    context = _trusted_tools(context)
    from qwenpaw.plugins.dependency_gate import parse_requirements_file
    from qwenpaw.plugins.dependency_upgrade import DependencyUpgradeManager
    from qwenpaw.plugins.execution.dependencies import _installed_metadata

    sources, requirements, _, index_urls = _collect_sources(
        record["plugin_dirs"],
    )
    if sources != record["sources"]:
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_PLAN_STALE: installed source inventory changed.",
        )
    if record["extra_requirements"]:
        parsed = parse_requirements_file(
            Path(record["extra_requirements"]["path"]),
        )
        if parsed.unsupported:
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_PLAN_STALE")
        requirements.extend(map(str, parsed.requirements))
        index_urls.extend(parsed.index_urls)
    if (
        context_module._digest(list(dict.fromkeys(index_urls)))
        != record["index_identity"]
    ):
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_PLAN_STALE: resolver configuration changed.",
        )
    requirements = list(dict.fromkeys(["qwenpaw", *requirements]))
    if requirements != record["requirements"]:
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_PLAN_STALE: dependency declarations changed.",
        )
    rows, invalid, _ = _installed_metadata(context.dependency_paths)
    if invalid:
        raise RuntimeError("DEPENDENCY_METADATA_INVALID")
    DependencyUpgradeManager._compatible(
        requirements,
        rows,
        record["validation"]["environment"]["marker_environment"],
    )
    context.inspect_executor()
    await _verify_plugins(context, sources)


def _validate_clean(prepared_path, active):
    _, maintenance, _ = _modules()
    environment = dict(os.environ)
    environment.pop("QWENPAW_DEPENDENCY_ENVIRONMENT", None)
    environment["QWENPAW_DEPENDENCY_STATE_DIR"] = str(maintenance.state_root())
    environment[
        "QWENPAW_DEPENDENCY_MAINTENANCE"
    ] = maintenance.current_capability()
    command = [
        sys.executable,
        "-I",
        "-B",
        "-S",
        str(Path(__file__).resolve()),
        "_verify",
        str(Path(prepared_path).absolute()),
        "--active-policy",
        str(active),
    ]
    result = _run_offline(
        command,
        env=environment,
        timeout=300,
    )
    if result.returncode:
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_PLAN_STALE: fresh candidate verification failed.",
        )


def activate_environment(
    prepared_path,
    *,
    active_policy_path,
    consumer_shutdown_confirmed=False,
):
    """Revalidate under policy/maintenance locks and atomically publish policy."""
    if consumer_shutdown_confirmed is not True:
        raise RuntimeError(
            "DEPENDENCY_ENVIRONMENT_SHUTDOWN_REQUIRED: stop all consumers "
            "through their service managers and explicitly confirm.",
        )
    context_module, maintenance, transaction = _modules()
    active = context_module.policy_path(active_policy_path)
    record = _read(Path(prepared_path))
    with context_module.dependency_policy_lock(active):
        if (
            context_module._digest(_previous(active))
            != record["previous_sha256"]
        ):
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_PLAN_STALE: active policy changed.",
            )
        context = _revalidate(record, active)
        old = record["previous_policy"]
        sites = [
            context.install_target,
            *(Path(p) for p in record["policy"]["legacy_sites"]),
        ]
        if old is not None:
            sites.append(context_module.context_for_policy(old).install_target)
        sites = tuple(
            Path(key)
            for key in sorted(
                {str(maintenance.canonical(p)) for p in sites if p.is_dir()},
            )
        )
        operation = record["id"]
        capability = os.urandom(32).hex()
        journal_path = active.parent / ("." + active.name + ".migration.json")
        if journal_path.exists() and _read(journal_path).get("phase") not in {
            "committed",
            "aborted",
        }:
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_RECOVERY_REQUIRED")
        journal = {
            "id": operation,
            "phase": "prepared",
            "report": str(Path(prepared_path).absolute()),
            "previous_policy": old,
            "previous_sha256": record["previous_sha256"],
            "policy_sha256": record["policy_sha256"],
            "sites": list(map(str, sites)),
            "consumer_shutdown_confirmed": True,
            "capability": capability,
        }
        # The existing maintenance protocol fences all real readers, including
        # those outside the selected application. Shared base is read-only.
        with ExitStack() as control:
            token = maintenance.capability_context.set(
                operation + ":" + capability,
            )
            control.callback(maintenance.capability_context.reset, token)
            transaction.atomic_json(journal_path, journal)
            try:
                with maintenance.maintenance(sites, operation, capability):
                    _revalidate(record, active)
            except BaseException:
                journal["phase"] = "aborted"
                transaction.atomic_json(journal_path, journal)
                raise
            try:
                # Keep persistent barriers and the policy lock, release site
                # gates while the clean verifier takes ordinary read custody.
                _validate_clean(prepared_path, active)
                control.enter_context(
                    maintenance.maintenance(sites, operation, capability),
                )
                _revalidate(record, active)
                if (
                    context_module._digest(_previous(active))
                    != record["previous_sha256"]
                ):
                    raise RuntimeError("DEPENDENCY_ENVIRONMENT_PLAN_STALE")
                journal["phase"] = "switching"
                transaction.atomic_json(journal_path, journal)
                if old is not None:
                    transaction.atomic_json(
                        active.with_name(active.name + ".previous"),
                        old,
                    )
                transaction.atomic_json(active, record["policy"])
                if (
                    context_module._digest(_read(active))
                    != record["policy_sha256"]
                ):
                    raise RuntimeError(
                        "DEPENDENCY_ENVIRONMENT_RECOVERY_REQUIRED",
                    )
                maintenance.clear_maintenance(sites, operation)
                journal["phase"] = "committed"
                transaction.atomic_json(journal_path, journal)
            except BaseException:
                # Keep owned maintenance and the switching journal for explicit
                # recovery; never erase a genuine repair marker.
                raise


def recover_environment(*, active_policy_path):
    context_module, maintenance, transaction = _modules()
    active = context_module.policy_path(active_policy_path)
    path = active.parent / ("." + active.name + ".migration.json")
    with context_module.dependency_policy_lock(active):
        journal = _read(path)
        if journal["phase"] == "committed":
            return
        current = context_module._digest(_previous(active))
        if current not in {
            journal["previous_sha256"],
            journal["policy_sha256"],
        }:
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_RECOVERY_REQUIRED: active policy has an unrelated change.",
            )
        sites = journal["sites"]
        with ExitStack() as locks:
            for site in sites:
                locks.enter_context(
                    maintenance.file_lock(maintenance._gate(site)),
                )
            if maintenance.live_readers(sites) or any(
                maintenance.repair_marker(site).exists() for site in sites
            ):
                raise RuntimeError("DEPENDENCY_ENVIRONMENT_RECOVERY_REQUIRED")
            record = _read(Path(journal["report"]))
            # Own markers prevent normal admission; validate bytes and sources
            # independently before clearing only this operation's markers.
            for site in sites:
                marker = maintenance.marker(site)
                if marker.exists() and (
                    _read(marker).get("id") != journal["id"]
                    or _read(marker).get("token_hash")
                    != hashlib.sha256(
                        journal["capability"].encode(),
                    ).hexdigest()
                ):
                    raise RuntimeError(
                        "DEPENDENCY_ENVIRONMENT_RECOVERY_REQUIRED",
                    )
            if current == journal["policy_sha256"]:
                if (
                    record["policy_sha256"] != journal["policy_sha256"]
                    or record["previous_sha256"] != journal["previous_sha256"]
                ):
                    raise RuntimeError(
                        "DEPENDENCY_ENVIRONMENT_RECOVERY_REQUIRED",
                    )
                token = maintenance.capability_context.set(
                    journal["id"] + ":" + journal["capability"],
                )
                try:
                    # switching was durably written only after the clean
                    # executable verification. Recheck all its bound source,
                    # provider, candidate and context evidence before commit.
                    _revalidate(record, active)
                finally:
                    maintenance.capability_context.reset(token)
            maintenance.clear_maintenance(sites, journal["id"])
            journal["phase"] = (
                "committed"
                if current == journal["policy_sha256"]
                else "aborted"
            )
            transaction.atomic_json(path, journal)


def restore_previous_environment(
    *,
    active_policy_path,
    consumer_shutdown_confirmed=False,
):
    """Review and activate the retained previously verified generation."""
    if consumer_shutdown_confirmed is not True:
        raise RuntimeError("DEPENDENCY_ENVIRONMENT_SHUTDOWN_REQUIRED")
    context_module, _, transaction = _modules()
    active = context_module.policy_path(active_policy_path)
    with context_module.dependency_policy_lock(active):
        journal = _read(
            active.parent / ("." + active.name + ".migration.json"),
        )
        current = _previous(active)
        old = journal.get("previous_policy")
        if (
            journal.get("phase") != "committed"
            or old is None
            or context_module._digest(current) != journal["policy_sha256"]
            or context_module._digest(old) != journal["previous_sha256"]
        ):
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_PLAN_STALE: no bound previous generation.",
            )
        context = context_module.context_for_policy(old)
        record = _read(context.install_target.parent / "prepared.json")
        if record.get("policy_sha256") != context_module._digest(old):
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_PLAN_STALE: previous generation was not verified.",
            )
        # This is a new review of the old generation, not new authority for an
        # old dependency-upgrade operation. The same activation verifier still
        # checks current sources, candidate bytes, closure and stopped readers.
        record.update(
            id=uuid4().hex,
            previous_policy=current,
            previous_sha256=context_module._digest(current),
        )
        report = active.parent / (
            "." + active.name + ".restore-" + record["id"] + ".json"
        )
        transaction.atomic_json(report, record)
    activate_environment(
        report,
        active_policy_path=active,
        consumer_shutdown_confirmed=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "prepare",
            "_prepare",
            "_verify",
            "activate",
            "recover",
            "restore-previous",
        ),
    )
    parser.add_argument("path", nargs="?")
    parser.add_argument("--active-policy", required=True)
    parser.add_argument("--requirements")
    parser.add_argument("--plugin-dir", action="append", default=None)
    parser.add_argument("--consumers-stopped", action="store_true")
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    if args.parent_pid is not None:
        if (
            args.action not in {"_prepare", "_verify"}
            or sys.stdin.buffer.read(1) != b"1"
        ):
            raise RuntimeError("DEPENDENCY_APPROVAL_REQUIRED")
        _offline_tree().watch_parent(args.parent_pid)
    if args.action == "activate":
        activate_environment(
            args.path,
            active_policy_path=args.active_policy,
            consumer_shutdown_confirmed=args.consumers_stopped,
        )
    elif args.action == "recover":
        recover_environment(active_policy_path=args.active_policy)
    elif args.action == "restore-previous":
        restore_previous_environment(
            active_policy_path=args.active_policy,
            consumer_shutdown_confirmed=args.consumers_stopped,
        )
    elif args.action == "_verify":
        import asyncio

        asyncio.run(_verify_candidate(args.path))
    elif args.action == "_prepare":
        import asyncio

        print(
            asyncio.run(
                _prepare_candidate(
                    args.path,
                    args.active_policy,
                    args.requirements,
                    args.plugin_dir,
                ),
            ),
        )
    else:
        print(
            prepare_environment(
                args.path,
                active_policy_path=args.active_policy,
                extra_requirements=args.requirements,
                plugin_dirs=args.plugin_dir,
            ),
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        code = str(error)
        sys.stderr.write(
            (
                code
                if code.startswith("DEPENDENCY_")
                else "DEPENDENCY_ENVIRONMENT_PREPARATION_FAILED: "
                + type(error).__name__
            )
            + "\n",
        )
        raise SystemExit(1) from None
