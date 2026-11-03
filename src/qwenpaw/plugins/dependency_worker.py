# -*- coding: utf-8 -*-
"""Run by absolute path with -I -B -S: never import the environment being changed."""

from __future__ import annotations

import importlib
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
    command = operation.get("continuation_command")
    code = (
        "import asyncio,sys;sys.path.insert(0,sys.argv[1]);"
        "from qwenpaw.plugins.dependency_upgrade import continue_operation;"
        "asyncio.run(continue_operation(sys.argv[2],preflight=sys.argv[3]=='1'))"
    )
    result = subprocess.run(
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
        ],
        stdin=subprocess.DEVNULL,
        check=False,
        timeout=300,
    )
    if result.returncode:
        raise RuntimeError(
            "DEPENDENCY_VERIFICATION_FAILED"
            if preflight
            else "DEPENDENCY_CONTINUATION_FAILED",
        )


def run(directory=None):
    """An operation derives its location from the copied trusted script."""
    directory = Path(
        directory or Path(__file__).resolve().parent.parent,
    ).resolve()
    maintenance, transaction = _modules()
    operation = json.loads((directory / "operation.json").read_text())
    transaction.authenticate_plan(directory, operation)
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
        mutated = False
        try:
            with maintenance.maintenance(
                operation["payload"]["sites"],
                operation["id"],
                operation["capability"],
            ):
                mutated = True
                if recovering:
                    transaction.rollback(directory)
                    transaction.restore_source(directory, operation)
                    transaction.finish(directory, operation, committed=False)
                    raise RuntimeError(
                        "DEPENDENCY_INTERRUPTED: interrupted transaction was restored.",
                    )
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
            if mutated:
                try:
                    if maintenance.live_readers(operation["payload"]["sites"]):
                        raise RuntimeError("DEPENDENCY_REPAIR_REQUIRED")
                    transaction.rollback(directory)
                    transaction.restore_source(directory, operation)
                    transaction.finish(directory, operation, committed=False)
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
        raise SystemExit(run())
    except Exception as error:
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
