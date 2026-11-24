# -*- coding: utf-8 -*-
"""Recover recorded additive writes without importing a blocked environment.

Only the exceptional recovery path reads file contents or starts an audit.
The retained copy can also run by absolute path with Python -I -S.
"""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import hmac
import importlib
import errno
import json
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import types
from uuid import uuid4


def _maintenance():
    if __package__:
        return importlib.import_module(__package__ + ".dependency_maintenance")
    package = types.ModuleType("_qwenpaw_addition_recovery")
    package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules[package.__name__] = package
    return importlib.import_module(
        package.__name__ + ".dependency_maintenance",
    )


def _refuse(message):
    raise RuntimeError("DEPENDENCY_REPAIR_REQUIRED: " + message)


def _atomic(path, value):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _json(path):
    if path.is_symlink():
        _refuse("recovery evidence became a symlink")
    return json.loads(path.read_text(encoding="utf-8"))


def _signature(plan, root):
    key = root / ".key"
    if key.is_symlink():
        _refuse("invalid recovery key")
    return hmac.new(
        key.read_bytes(),
        json.dumps(plan, sort_keys=True).encode(),
        hashlib.sha256,
    ).hexdigest()


def _path(site, relative):
    parts = PurePosixPath(relative)
    if (
        parts.is_absolute()
        or "\\" in relative
        or not parts.parts
        or any(part in {".", ".."} for part in parts.parts)
    ):
        _refuse("invalid recorded publication path")
    path = site.joinpath(*parts.parts)
    if not path.resolve().is_relative_to(site) or any(
        parent.is_symlink()
        for parent in (path, *path.parents)
        if parent.is_relative_to(site)
    ):
        _refuse("publication path changed during recovery")
    return path


def begin_additions(site, files, context):
    """Called only after wheel validation, under the existing writer gates."""
    maintenance = _maintenance()
    site = maintenance.canonical(site)
    for name in files:
        if _path(site, name).exists():
            _refuse("an addition already exists before publication")
    root = maintenance.state_root() / "additions"
    root.mkdir(mode=0o700, exist_ok=True)
    key = root / ".key"
    with maintenance.file_lock(root / ".key.lock", timeout=5):
        try:
            with os.fdopen(
                os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600),
                "wb",
            ) as stream:
                stream.write(os.urandom(32))
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            pass
    operation_id, capability = uuid4().hex, uuid4().hex
    directory = root / operation_id
    directory.mkdir(mode=0o700)
    worker = directory / "worker"
    worker.mkdir(mode=0o700)
    candidates = (
        Path(__file__).resolve().parent,
        Path(context["support_root"]) / "qwenpaw/plugins",
    )
    for name in ("dependency_recovery.py", "dependency_maintenance.py"):
        source = next(
            (p / name for p in candidates if (p / name).is_file()),
            None,
        )
        if source is None or source.is_symlink():
            _refuse("trusted recovery worker is unavailable")
        shutil.copyfile(source, worker / name)
    plan = {
        **context,
        "schema": 1,
        "id": operation_id,
        "site": str(site),
        "capability": capability,
        "directories": sorted(
            {
                parent.relative_to(site).as_posix()
                for name in files
                for parent in _path(site, name).parents
                if parent != site
                and parent.is_relative_to(site)
                and not parent.exists()
            },
            key=lambda name: (-len(PurePosixPath(name).parts), name),
        ),
        "files": {
            name: {
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "executable": name in getattr(files, "executable_paths", ()),
            }
            for name, data in files.items()
        },
    }
    operation = {
        "plan": plan,
        "signature": _signature(plan, root),
        "phase": "writing",
    }
    _atomic(directory / "operation.json", operation)
    _atomic(
        maintenance.repair_marker(site),
        {
            "kind": "additions",
            "id": operation_id,
            "token_hash": hashlib.sha256(capability.encode()).hexdigest(),
        },
    )
    return directory, operation


def record_phase(record, phase, error=None):
    directory, operation = record
    operation["phase"] = phase
    operation["error"] = (
        {
            "type": type(error).__name__,
            "message": str(error).replace(
                operation["plan"]["capability"],
                "[redacted]",
            )[:2000],
        }
        if error is not None
        else None
    )
    _atomic(directory / "operation.json", operation)


def _load(site, maintenance):
    try:
        marker = _json(maintenance.repair_marker(site))
    except ValueError:
        _refuse("legacy marker has no trusted additive recovery evidence")
    if not isinstance(marker, dict):
        _refuse("invalid additive recovery marker")
    identity = marker.get("id", "")
    if (
        marker.get("kind") != "additions"
        or len(identity) != 32
        or any(c not in "0123456789abcdef" for c in identity)
    ):
        _refuse("trusted additive recovery evidence is unavailable")
    root = maintenance.state_root() / "additions"
    directory = root / identity
    if directory.is_symlink():
        _refuse("invalid recovery directory")
    operation = _json(directory / "operation.json")
    plan = operation["plan"]
    if (
        not hmac.compare_digest(operation["signature"], _signature(plan, root))
        or plan["schema"] != 1
        or plan["id"] != identity
        or plan["site"] != str(site)
        or marker["token_hash"]
        != hashlib.sha256(
            plan["capability"].encode(),
        ).hexdigest()
    ):
        _refuse("recovery evidence does not match this environment")
    return directory, operation


def _verify_files(site, plan, *, allow_missing=False):
    existing = []
    for name, expected in plan["files"].items():
        path = _path(site, name)
        if allow_missing and not path.exists():
            continue
        info = path.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size != expected["size"]
            or hashlib.sha256(path.read_bytes()).hexdigest()
            != expected["sha256"]
            or (
                os.name != "nt"
                and expected["executable"]
                and not info.st_mode & 0o111
            )
        ):
            _refuse("published files changed; retain the recovery evidence")
        existing.append(path)
    return existing


_AUDIT = """
import json,os,sys,types
from pathlib import Path
plan=json.load(sys.stdin)
sys.path[:0]=list(dict.fromkeys([plan['support_root'],*plan['sites']]))
# Match the generic audit worker: metadata verification must not recursively
# run application bootstrap or import any candidate plugin code.
package=types.ModuleType('qwenpaw')
package.__path__=[str(Path(plan['support_root'])/'qwenpaw')]
sys.modules['qwenpaw']=package
from qwenpaw.plugins import dependency_maintenance as maintenance
maintenance.lease_environment(plan['sites'], parent_pid=os.getppid())
from qwenpaw.plugins.execution.dependencies import observe_dependencies
from qwenpaw.plugins.dependency_gate import evaluate_shared_dependencies
snapshot=observe_dependencies({'code_root':sys.argv[1],
    '_audit_sites':plan['sites'],'_requirements':plan['requirements']})
if {'executable':snapshot.executable,'prefix':snapshot.prefix,
        'supported_tags':list(snapshot.supported_tags)} != plan['interpreter']:
    raise RuntimeError('DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED')
decision=evaluate_shared_dependencies(None,snapshot,plugin_id=plan['plugin_id'],
    extra_requirements=plan['requirements'])
if not decision.already_satisfied:
    raise RuntimeError(decision.reason_code)
for name,origin in plan['providers'].items():
    if Path(snapshot.distributions[name]['metadata_path']) != Path(origin):
        raise RuntimeError('DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED')
"""


def _verify_dependencies(directory, plan, maintenance):
    environment = dict(os.environ)
    environment["QWENPAW_DEPENDENCY_STATE_DIR"] = str(maintenance.state_root())
    environment["QWENPAW_DEPENDENCY_MAINTENANCE"] = (
        plan["id"] + ":" + plan["capability"]
    )
    # The capability travels only in the child environment, never argv/logs.
    public = {
        k: plan[k]
        for k in (
            "plugin_id",
            "support_root",
            "sites",
            "requirements",
            "providers",
            "interpreter",
        )
    }
    result = subprocess.run(
        [plan["python_executable"], "-I", "-B", "-c", _AUDIT, str(directory)],
        input=json.dumps(public),
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        _refuse("dependency verification failed: " + result.stderr[-2000:])


def recover_additions(sites, *, rollback=False, timeout=5):
    """Verify completed additions; explicit offline rollback never overwrites."""
    maintenance = _maintenance()
    for raw in sites:
        if not raw:
            continue
        site = maintenance.canonical(raw)
        marker = maintenance.repair_marker(site)
        if not marker.exists() or maintenance.authorized(site):
            continue
        try:
            with ExitStack() as locks:
                locks.enter_context(
                    maintenance.file_lock(
                        maintenance._gate(site),
                        timeout=timeout,
                    ),
                )
                locks.enter_context(
                    maintenance.file_lock(
                        maintenance._admission_gate(site),
                        timeout=timeout,
                    ),
                )
                maintenance.check_admission(site, check_repair=False)
                if not marker.exists():
                    continue
                record = _load(site, maintenance)
                directory, operation = record
                plan = operation["plan"]
                if rollback and maintenance.live_readers((site,)):
                    _refuse("stop environment consumers before rollback")
                files = _verify_files(site, plan, allow_missing=rollback)
                if rollback:
                    for path in files:
                        path.unlink()
                    for name in plan["directories"]:
                        try:
                            _path(site, name).rmdir()
                        except OSError as exc:
                            if exc.errno not in {
                                errno.ENOENT,
                                errno.ENOTEMPTY,
                                errno.EEXIST,
                            }:
                                raise
                else:
                    _verify_dependencies(directory, plan, maintenance)
                    _verify_files(site, plan)
                # Never remove another operation's marker after verification.
                if _load(site, maintenance)[1]["plan"] != plan:
                    _refuse("recovery operation changed during verification")
                record_phase(record, "rolled_back" if rollback else "verified")
                marker.unlink()
                logging.getLogger(__name__).info(
                    "Recovered additive dependency publication: plugin=%s phase=%s",
                    plan["plugin_id"],
                    operation["phase"],
                )
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            subprocess.SubprocessError,
        ) as exc:
            _refuse(
                "additive recovery could not verify the environment: "
                + str(exc),
            )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if Path(__file__).parent.name == "worker":
        os.environ["QWENPAW_DEPENDENCY_STATE_DIR"] = str(
            Path(__file__).resolve().parents[3],
        )
    recover_additions((args.site,), rollback=args.rollback)
