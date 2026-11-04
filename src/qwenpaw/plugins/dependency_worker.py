# -*- coding: utf-8 -*-
"""Run by absolute path with -I -B -S: never import the environment being changed."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types


def _modules():
    package = types.ModuleType("_qwenpaw_dependency_repair")
    package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules[package.__name__] = package
    return (
        importlib.import_module(package.__name__ + ".dependency_maintenance"),
        importlib.import_module(package.__name__ + ".dependency_transaction"),
    )


def _process_tree_module():
    path = Path(__file__).resolve().parent / "execution/process_tree.py"
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(
            "DEPENDENCY_PLAN_STALE: retained process custody is missing.",
        )
    spec = importlib.util.spec_from_file_location(
        "_qwenpaw_retained_process_tree",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("DEPENDENCY_PLAN_STALE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _alive(pid):
    if os.name == "nt":
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x00000102
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _continue(directory, operation, *, preflight=False):
    if operation.get("dependency_policy") is not None:
        command = [
            operation["worker_python"],
            "-I",
            "-B",
            "-S",
            str(Path(__file__).resolve()),
            "--managed-continue",
            str(directory),
            "1" if preflight else "0",
            str(os.getpid()),
        ]
        tree_module = _process_tree_module()
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            start_new_session=os.name != "nt",
        )
        tree = None
        try:
            tree = tree_module.ProcessTree(process.pid)
            process.stdin.write(b"1")
            process.stdin.close()
            returncode = process.wait(timeout=300)
        finally:
            try:
                if tree is not None:
                    if tree.alive():
                        tree.signal(force=True)
                    process.wait(timeout=5)
                    deadline = time.monotonic() + 5
                    while tree.alive() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    if tree.alive():
                        raise RuntimeError(
                            "continuation descendants did not exit",
                        )
                    tree.close()
                elif process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            except BaseException as error:
                raise RuntimeError(
                    "DEPENDENCY_REPAIR_REQUIRED: "
                    "continuation cleanup is unverified.",
                ) from error
        if returncode:
            raise RuntimeError("DEPENDENCY_CONTINUATION_FAILED")
        return
    command = operation.get("continuation_command")
    code = (
        "import asyncio,sys;sys.path.insert(0,sys.argv[1]);"
        "from qwenpaw.plugins.dependency_upgrade import continue_operation;"
        "asyncio.run(continue_operation(sys.argv[2],preflight=sys.argv[3]=='1'))"
    )
    result = subprocess.run(
        (
            [*command, "1" if preflight else "0"]
            if command
            else [
                operation["continuation_python"],
                "-I",
                "-B",
                "-c",
                code,
                operation["support_root"],
                str(directory),
                "1" if preflight else "0",
            ]
        ),
        stdin=subprocess.DEVNULL,
        check=False,
        timeout=300,
    )
    if result.returncode:
        raise RuntimeError(
            (
                "DEPENDENCY_VERIFICATION_FAILED"
                if preflight
                else "DEPENDENCY_CONTINUATION_FAILED"
            ),
        )


def _managed_continue(directory, phase, parent):
    """Authenticate and bind exact retained roots before importing the host."""
    if (
        not sys.flags.no_site
        or phase not in {"0", "1"}
        or int(parent) != os.getppid()
    ):
        raise RuntimeError("DEPENDENCY_APPROVAL_REQUIRED")
    if sys.stdin.buffer.read(1) != b"1":
        raise RuntimeError("DEPENDENCY_APPROVAL_REQUIRED")
    directory = Path(directory).resolve()
    maintenance, transaction = _modules()
    tree_module = _process_tree_module()
    tree_module.watch_parent(int(parent))
    maintenance.restore_managed_interpreter_prefix()
    operation = json.loads((directory / "operation.json").read_text())
    transaction.authenticate_plan(directory, operation)
    if (
        not operation.get("approved")
        or operation.get("worker_pid") != int(parent)
        or maintenance.current_capability()
        != operation["id"] + ":" + operation["capability"]
    ):
        raise RuntimeError("DEPENDENCY_APPROVAL_REQUIRED")
    os.environ["QWENPAW_DEPENDENCY_STATE_DIR"] = operation[
        "dependency_state_dir"
    ]
    maintenance.state_root()
    if not all(
        maintenance.authorized(site) for site in operation["payload"]["sites"]
    ):
        raise RuntimeError("DEPENDENCY_APPROVAL_REQUIRED")
    context_module = importlib.import_module(
        "_qwenpaw_dependency_repair.dependency_context",
    )
    context = context_module.DependencyEnvironmentContext.from_mapping(
        operation["dependency_context"],
    )
    context_module.verify_dependency_policy(
        operation["dependency_policy"],
        context,
    )
    if (
        Path(sys.executable).resolve()
        != Path(context.python_executable).resolve()
    ):
        raise RuntimeError("DEPENDENCY_PLAN_STALE: interpreter changed.")
    for relative in (
        "qwenpaw/__init__.py",
        "qwenpaw/plugins/dependency_upgrade.py",
        "qwenpaw/plugins/loader.py",
        "qwenpaw/plugins/execution/worker.py",
        "qwenpaw/plugins/execution/process_tree.py",
    ):
        path = context.support_root / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(
                "DEPENDENCY_PLAN_STALE: trusted support is incomplete.",
            )
    # -S has excluded all native site and .pth execution. Keep only its stdlib
    # paths, then add authenticated support/base/target without executing .pth.
    sys.path[:] = context_module.dependency_import_paths(
        [str(context.support_root), *sys.path],
        context,
    )
    os.environ.pop("QWENPAW_DEPENDENCY_ENVIRONMENT", None)
    sys.modules["qwenpaw.plugins.dependency_maintenance"] = maintenance
    # Retained stdlib verification above uses a private package. Bind the same
    # trusted asset under its real package before any of its heavy methods run.
    spec = importlib.util.spec_from_file_location(
        "qwenpaw.plugins.dependency_context",
        Path(__file__).with_name("dependency_context.py"),
    )
    selected = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = selected
    spec.loader.exec_module(selected)
    context = selected.DependencyEnvironmentContext.from_mapping(
        operation["dependency_context"],
    )
    selected._SELECTED_ENVIRONMENT = context
    selected._SELECTED_POLICY = dict(operation["dependency_policy"])
    maintenance.lease_environment(context.dependency_paths)
    import asyncio
    from qwenpaw.plugins.dependency_upgrade import continue_operation

    asyncio.run(continue_operation(directory, preflight=phase == "1"))
    return 0


def run(directory=None):
    """An operation derives its location from the copied trusted script."""
    directory = Path(
        directory or Path(__file__).resolve().parent.parent,
    ).resolve()
    maintenance, transaction = _modules()
    operation = json.loads((directory / "operation.json").read_text())
    transaction.authenticate_plan(directory, operation)
    if operation.get("dependency_policy") is not None:
        os.environ["QWENPAW_DEPENDENCY_STATE_DIR"] = operation[
            "dependency_state_dir"
        ]
        maintenance.state_root()
        context_module = importlib.import_module(
            "_qwenpaw_dependency_repair.dependency_context",
        )
        with context_module.dependency_policy_operation(
            operation["dependency_policy"],
        ):
            return _run(directory, maintenance, transaction, operation)
    return _run(directory, maintenance, transaction, operation)


def _clear_preflight_barrier(maintenance, operation):
    """Release only an unchanged operation's verified, unused barriers."""
    sites = operation["payload"]["sites"]
    if any(
        str(maintenance.canonical(site)) != str(Path(site))
        or maintenance.repair_marker(site).exists()
        for site in sites
    ):
        raise RuntimeError("DEPENDENCY_REPAIR_REQUIRED")
    with maintenance.maintenance(
        sites,
        operation["id"],
        operation["capability"],
    ):
        if maintenance.live_readers(sites) or any(
            maintenance.repair_marker(site).exists()
            or not maintenance.authorized(site)
            for site in sites
        ):
            raise RuntimeError("DEPENDENCY_REPAIR_REQUIRED")
        maintenance.clear_maintenance(sites, operation["id"])
        if any(maintenance.marker(site).exists() for site in sites):
            raise RuntimeError("DEPENDENCY_REPAIR_REQUIRED")


def _run(directory, maintenance, transaction, operation):
    if state_dir := operation.get("dependency_state_dir"):
        os.environ["QWENPAW_DEPENDENCY_STATE_DIR"] = state_dir
    maintenance.state_root()
    if transaction.reconcile_commit(directory, operation):
        return 0
    if directory.name != operation["id"] or not operation.get("approved"):
        raise RuntimeError("DEPENDENCY_APPROVAL_REQUIRED")
    os.environ["QWENPAW_DEPENDENCY_MAINTENANCE"] = (
        operation["id"] + ":" + operation["capability"]
    )
    deadline = time.monotonic() + 60
    parent = operation.get("backend_pid")
    while parent and _alive(parent):
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_BUSY: backend has not exited.",
            )
        time.sleep(0.1)
    with maintenance.file_lock(directory / "operation.lock"):
        # A prior interrupted write always restores old bytes before admitting
        # any backend. Recovery works even when importing qwenpaw is blocked.
        journal = directory / "journal.json"
        recovering = journal.exists() and (
            json.loads(journal.read_text())["phase"]
            not in {"committed", "rolled_back"}
            or any(
                maintenance.marker(site).exists()
                or maintenance.repair_marker(site).exists()
                for site in operation["payload"]["sites"]
            )
        )
        operation.update(
            status="applying",
            worker_pid=os.getpid(),
            message="Applying shared dependencies in offline maintenance.",
        )
        transaction.atomic_json(directory / "operation.json", operation)
        barrier_established = False
        mutated = False
        try:
            managed = operation.get("dependency_policy") is not None
            if managed and not recovering:
                # Persistent markers keep ordinary consumers out while an
                # authenticated child obtains its own observation gates.
                # The parent retains the active-policy lock throughout.
                with maintenance.maintenance(
                    operation["payload"]["sites"],
                    operation["id"],
                    operation["capability"],
                ):
                    barrier_established = True
                _continue(directory, operation, preflight=True)
            with maintenance.maintenance(
                operation["payload"]["sites"],
                operation["id"],
                operation["capability"],
            ):
                barrier_established = managed
                # Preserve the existing non-managed recovery boundary. Managed
                # preflight and source backup do not mutate dependency bytes.
                mutated = not managed or recovering
                if recovering:
                    transaction.rollback(directory)
                    transaction.restore_source(directory, operation)
                    transaction.finish(directory, operation, committed=False)
                    raise RuntimeError(
                        "DEPENDENCY_INTERRUPTED: interrupted transaction was restored.",
                    )
                if not managed:
                    _continue(directory, operation, preflight=True)
                if maintenance.live_readers(operation["payload"]["sites"]):
                    raise RuntimeError(
                        "DEPENDENCY_CONSUMER_BUSY: verification child did not exit.",
                    )
                target = (
                    Path(operation["plugin_dirs"][0]) / operation["plugin_id"]
                )
                operation["source_before"] = transaction.backup_source(
                    directory,
                    target,
                )
                transaction.atomic_json(
                    directory / "operation.json",
                    operation,
                )
                mutated = True
                transaction.publish(directory, operation)
            _continue(directory, operation)
            if maintenance.live_readers(operation["payload"]["sites"]):
                raise RuntimeError(
                    "DEPENDENCY_CONSUMER_BUSY: continuation descendants did not exit.",
                )
            transaction.commit_result(
                directory,
                operation,
                json.loads((directory / "continuation.json").read_text()),
            )
        except BaseException as exc:
            if journal.exists() and json.loads(journal.read_text())[
                "phase"
            ] in {
                "committing",
                "committed",
            }:
                transaction.reconcile_commit(directory, operation)
                return 0
            code = str(exc).split(":", 1)[0]
            if mutated and code != "DEPENDENCY_REPAIR_REQUIRED":
                try:
                    if maintenance.live_readers(operation["payload"]["sites"]):
                        raise RuntimeError("DEPENDENCY_REPAIR_REQUIRED")
                    transaction.rollback(directory)
                    transaction.restore_source(directory, operation)
                    transaction.finish(directory, operation, committed=False)
                except BaseException:
                    code = "DEPENDENCY_REPAIR_REQUIRED"
            elif barrier_established and code != "DEPENDENCY_REPAIR_REQUIRED":
                try:
                    _clear_preflight_barrier(maintenance, operation)
                except BaseException:
                    code = "DEPENDENCY_REPAIR_REQUIRED"
            operation.update(
                status="failed",
                message=(
                    "Dependency maintenance failed; recovery is required."
                    if code == "DEPENDENCY_REPAIR_REQUIRED"
                    else "Dependency maintenance failed; previous packages were preserved or restored."
                ),
                error={"code": code, "message": code},
                retryable=code != "DEPENDENCY_REPAIR_REQUIRED",
            )
        finally:
            operation.pop("worker_pid", None)
            transaction.atomic_json(directory / "operation.json", operation)
    restart = operation.get("restart")
    if (
        restart
        and (operation.get("error") or {}).get("code")
        != "DEPENDENCY_REPAIR_REQUIRED"
    ):
        environment = dict(os.environ)
        environment.pop("QWENPAW_DEPENDENCY_MAINTENANCE", None)
        subprocess.Popen(
            restart["command"],
            cwd=restart["cwd"],
            env=environment,
            stdin=subprocess.DEVNULL,
        )
    return 0 if operation["status"] == "succeeded" else 1


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--managed-continue":
            if len(sys.argv) != 5:
                raise RuntimeError("DEPENDENCY_APPROVAL_REQUIRED")
            raise SystemExit(_managed_continue(*sys.argv[2:]))
        raise SystemExit(run())
    except Exception as error:
        if len(sys.argv) > 1 and sys.argv[1] == "--managed-continue":
            # An unauthenticated child request never authorizes a write beside
            # the trusted script (which may live in signed, read-only support).
            sys.stderr.write(str(error).split(":", 1)[0] + "\n")
            raise SystemExit(1) from None
        try:
            directory = Path(__file__).resolve().parent.parent
            maintenance, transaction = _modules()
            with maintenance.file_lock(directory / "operation.lock"):
                operation = json.loads(
                    (directory / "operation.json").read_text(),
                )
                transaction.authenticate_plan(directory, operation)
                if (
                    operation.get("approved")
                    and operation.get("worker_pid") in {None, os.getpid()}
                    and operation.get("status") != "succeeded"
                ):
                    operation.pop("worker_pid", None)
                    code = str(error).split(":", 1)[0]
                    if not code.startswith("DEPENDENCY_"):
                        code = "DEPENDENCY_MAINTENANCE_FAILED"
                    operation.update(
                        status="failed",
                        retryable=True,
                        message="Offline maintenance could not start; installed packages were preserved.",
                        error={"code": code, "message": code},
                    )
                    transaction.atomic_json(
                        directory / "operation.json",
                        operation,
                    )
        except Exception:
            pass
        sys.stderr.write(str(error).split(":", 1)[0] + "\n")
        raise SystemExit(1) from None
