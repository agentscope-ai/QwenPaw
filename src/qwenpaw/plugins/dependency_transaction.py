# -*- coding: utf-8 -*-
"""Standard-library ownership, durable files, and dependency transactions."""

from __future__ import annotations

import base64
from contextlib import contextmanager
import csv
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys

_PLAN_FIELDS = (
    "id",
    "plugin_id",
    "force",
    "source_revision",
    "environment",
    "environment_fingerprint",
    "consumers",
    "reviewed_usage",
    "requires_restart",
    "proposed",
    "payload",
    "capability",
    "plugin_dirs",
    "runtime",
    "changes",
    "continuation_python",
    "worker_python",
    "support_root",
)


def authenticate_plan(directory, operation, *, seal=False):
    """Bind the reviewed plan to the server's private operation namespace."""
    key_path = directory.parent / ".key"
    if seal and not key_path.exists():
        try:
            descriptor = os.open(
                key_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(os.urandom(32))
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            pass
    if key_path.is_symlink() or directory.name != operation.get("id"):
        raise RuntimeError(
            "DEPENDENCY_PLAN_STALE: invalid operation identity.",
        )
    message = json.dumps(
        {key: operation[key] for key in _PLAN_FIELDS},
        sort_keys=True,
    ).encode()
    signature = hmac.new(
        key_path.read_bytes(),
        message,
        hashlib.sha256,
    ).hexdigest()
    if seal:
        operation["signature"] = signature
    elif not hmac.compare_digest(signature, operation.get("signature", "")):
        raise RuntimeError(
            "DEPENDENCY_PLAN_STALE: retained plan changed after review.",
        )


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + os.urandom(8).hex() + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
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


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def environment_fingerprint(snapshot):
    """Include exact metadata bytes, not just selected distribution versions."""
    evidence = {"environment": snapshot, "metadata": {}}
    for name, row in snapshot["distributions"].items():
        root = Path(row["metadata_path"])
        evidence["metadata"][name] = {
            path.relative_to(root).as_posix(): _hash(path)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }
    return hashlib.sha256(
        json.dumps(evidence, sort_keys=True).encode(),
    ).hexdigest()


def _owned(row, prefix):
    site = Path(row["metadata_path"]).parent.resolve()
    record = Path(row["metadata_path"]) / "RECORD"
    if record.is_symlink() or not record.is_file():
        raise RuntimeError(
            "DEPENDENCY_PLAN_UNVERIFIED: installed RECORD is required.",
        )
    files = {}
    scripts = {
        Path(prefix).resolve() / "bin",
        Path(prefix).resolve() / "Scripts",
    }
    for entry in csv.reader(record.read_text(encoding="utf-8").splitlines()):
        if (
            len(entry) != 3
            or not entry[0]
            or "\\" in entry[0]
            or ":" in entry[0]
        ):
            raise RuntimeError(
                "DEPENDENCY_PLAN_UNVERIFIED: invalid installed ownership.",
            )
        relative = PurePosixPath(entry[0])
        path = site.joinpath(*relative.parts)
        resolved = path.resolve()
        if (
            relative.is_absolute()
            or not (
                resolved.is_relative_to(site) or resolved.parent in scripts
            )
            or any(parent.is_symlink() for parent in (path, *path.parents))
        ):
            raise RuntimeError(
                "DEPENDENCY_PLAN_UNVERIFIED: unsafe installed ownership.",
            )
        if resolved in files:
            raise RuntimeError(
                "DEPENDENCY_PLAN_UNVERIFIED: duplicate installed ownership.",
            )
        if not path.exists():
            if path.suffix == ".pyc":
                continue
            raise RuntimeError(
                "DEPENDENCY_PLAN_UNVERIFIED: an installed owned file is missing.",
            )
        if not path.is_file():
            raise RuntimeError(
                "DEPENDENCY_PLAN_UNVERIFIED: invalid installed file.",
            )
        content = path.read_bytes()
        if entry[1]:
            algorithm, separator, digest = entry[1].partition("=")
            try:
                actual = (
                    base64.urlsafe_b64encode(
                        hashlib.new(algorithm, content).digest(),
                    )
                    .decode()
                    .rstrip("=")
                )
            except ValueError:
                actual = None
            if not separator or actual != digest:
                raise RuntimeError(
                    "DEPENDENCY_PLAN_STALE: installed file differs from RECORD.",
                )
        if entry[2] and int(entry[2]) != len(content):
            raise RuntimeError(
                "DEPENDENCY_PLAN_STALE: installed file length differs from RECORD.",
            )
        files[resolved] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "mode": stat.S_IMODE(path.stat().st_mode),
        }
        if path.suffix == ".py":
            for cache in path.parent.glob(
                "__pycache__/" + path.stem + ".*.pyc",
            ):
                if not cache.is_symlink():
                    files[cache.resolve()] = {
                        "sha256": _hash(cache),
                        "mode": stat.S_IMODE(cache.stat().st_mode),
                    }
    if record.resolve() not in files:
        raise RuntimeError(
            "DEPENDENCY_PLAN_UNVERIFIED: RECORD does not own itself.",
        )
    return files


def prepare_payload(directory, snapshot, changed, destinations, files, wheels):
    """Authorize individual files only; never delete a package directory."""
    from email.parser import BytesParser

    old_files, ownership = {}, {}
    for name, row in snapshot["distributions"].items():
        if name in changed:
            owned = _owned(row, snapshot["prefix"])
            for path, evidence in owned.items():
                if str(path) in old_files:
                    raise RuntimeError(
                        "DEPENDENCY_PLAN_UNVERIFIED: shared installed file ownership.",
                    )
                old_files[str(path)] = evidence
                ownership.setdefault(str(path), set()).add(name)
        else:
            record = Path(row["metadata_path"]) / "RECORD"
            if record.is_file():
                for entry in csv.reader(
                    record.read_text(encoding="utf-8").splitlines(),
                ):
                    if entry:
                        path = (record.parent.parent / entry[0]).resolve()
                        ownership.setdefault(str(path), set()).add(name)
    for path in old_files:
        if len(ownership[path]) != 1 or not ownership[path].issubset(changed):
            raise RuntimeError(
                "DEPENDENCY_PLAN_UNVERIFIED: shared installed ownership.",
            )
    new_files = {}
    for wheel in wheels:
        import zipfile

        with zipfile.ZipFile(wheel["path"]) as archive:
            metadata_path = next(
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            )
            name = BytesParser().parsebytes(archive.read(metadata_path))[
                "Name"
            ]
            name = re.sub(r"[-_.]+", "-", name).lower()
        site = Path(destinations[name]).resolve()
        prefix = Path(snapshot["prefix"]).resolve()
        if (
            (prefix / "conda-meta").exists()
            or not (
                (prefix / "pyvenv.cfg").is_file()
                and site.is_relative_to(prefix)
            )
            and not site.is_relative_to(
                directory.parent.parent / "plugin_runtime",
            )
        ):
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_PROTECTED: use the environment owner's package manager.",
            )
        if not os.access(site, os.W_OK) or not os.access(site.parent, os.W_OK):
            raise RuntimeError(
                "DEPENDENCY_ENVIRONMENT_PROTECTED: dependency site is not writable.",
            )
        info = metadata_path.split("/", 1)[0]
        owned_tops = {
            path.split("/", 1)[0]
            for path in files
            if path.split("/", 1)[0] == info
        }
        # Wheels have disjoint validated top-level providers except script dirs.
        with zipfile.ZipFile(wheel["path"]) as archive:
            tops = {
                name.split("/", 1)[0]
                for name in archive.namelist()
                if not name.split("/", 1)[0].endswith(".data")
            }
        for top in tops - {info}:
            stem = top.split(".", 1)[0]
            for visible in snapshot["sites"]:
                root = Path(visible)
                for provider in root.glob(stem + ".*"):
                    if (
                        provider.suffix.lower()
                        in {".py", ".pyc", ".so", ".pyd"}
                        and str(provider.resolve()) not in old_files
                    ):
                        raise RuntimeError(
                            "DEPENDENCY_PLAN_UNVERIFIED: another import provider would be shadowed.",
                        )
                package = root / stem
                if package.is_symlink():
                    raise RuntimeError(
                        "DEPENDENCY_PLAN_UNVERIFIED: import provider is a symlink.",
                    )
                if package.is_dir():
                    initializers = list(package.glob("__init__.*"))
                    if any(
                        str(path.resolve()) not in old_files
                        for path in initializers
                    ):
                        raise RuntimeError(
                            "DEPENDENCY_PLAN_UNVERIFIED: another package would be shadowed.",
                        )
                    if f"{stem}/__init__.py" in files and any(
                        path.is_file()
                        and "__pycache__" not in path.parts
                        and str(path.resolve()) not in old_files
                        for path in package.rglob("*")
                    ):
                        raise RuntimeError(
                            "DEPENDENCY_PLAN_UNVERIFIED: namespace sibling ownership would change.",
                        )
        owned_tops.update(tops)
        external_scripts = {
            path: evidence
            for path, evidence in old_files.items()
            if ownership[path] == {name}
            and not Path(path).is_relative_to(site)
        }
        relocated = set()
        if external_scripts:
            # pip-generated launchers are outside site-packages. Preserve them
            # when entry-point declarations are unchanged; wheel .data scripts
            # instead use their verified new bytes at the existing location.
            old_info = Path(snapshot["distributions"][name]["metadata_path"])
            old_entrypoints = old_info / "entry_points.txt"
            old_declarations = (
                old_entrypoints.read_bytes()
                if old_entrypoints.is_file()
                else b""
            )
            record_path = f"{info}/RECORD"
            record_rows = list(
                csv.reader(files[record_path].decode().splitlines()),
            )
            for path, evidence in external_scripts.items():
                script = Path(path)
                relative = (
                    ("Scripts" if script.parent.name == "Scripts" else "bin")
                    + "/"
                    + script.name
                )
                if relative in files:
                    content = files[relative]
                    relocated.add(relative)
                    record_rows = [
                        row for row in record_rows if row[0] != relative
                    ]
                else:
                    if old_declarations != files.get(
                        f"{info}/entry_points.txt",
                        b"",
                    ):
                        raise RuntimeError(
                            "DEPENDENCY_PLAN_UNVERIFIED: changed external "
                            "entry points need the environment owner's "
                            "installer.",
                        )
                    content = script.read_bytes()
                digest = (
                    base64.urlsafe_b64encode(hashlib.sha256(content).digest())
                    .decode()
                    .rstrip("=")
                )
                record_rows.append(
                    (
                        Path(os.path.relpath(script, site)).as_posix(),
                        "sha256=" + digest,
                        str(len(content)),
                    ),
                )
                payload = directory / "payload" / str(len(new_files))
                payload.parent.mkdir(exist_ok=True)
                payload.write_bytes(content)
                new_files[path] = {
                    "payload": str(payload.relative_to(directory)),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "mode": evidence["mode"],
                }
            import io

            rows = io.StringIO(newline="")
            csv.writer(rows, lineterminator="\n").writerows(record_rows)
            files[record_path] = rows.getvalue().encode()
        for relative, content in files.items():
            if relative in relocated:
                continue
            if relative.split("/", 1)[0] not in owned_tops:
                # Relocated scripts are matched against the wheel's data dir.
                if relative.split("/", 1)[0] not in {"bin", "Scripts"}:
                    continue
                script_name = Path(relative).name
                with zipfile.ZipFile(wheel["path"]) as archive:
                    if not any(
                        item.endswith(".data/scripts/" + script_name)
                        for item in archive.namelist()
                    ):
                        continue
            destination = site / relative
            if str(destination) in new_files or any(
                parent.is_symlink()
                for parent in (destination, *destination.parents)
            ):
                raise RuntimeError(
                    "DEPENDENCY_PLAN_UNVERIFIED: unsafe or duplicate publication path.",
                )
            for visible in snapshot["sites"]:
                collision = Path(visible) / relative
                if (
                    collision.exists()
                    and str(collision.resolve()) not in old_files
                ):
                    raise RuntimeError(
                        "DEPENDENCY_PLAN_UNVERIFIED: unowned dependency collision.",
                    )
            payload = directory / "payload" / str(len(new_files))
            payload.parent.mkdir(exist_ok=True)
            payload.write_bytes(content)
            new_files[str(destination)] = {
                "payload": str(payload.relative_to(directory)),
                "sha256": hashlib.sha256(content).hexdigest(),
                "mode": (
                    0o755
                    if relative in getattr(files, "executable_paths", ())
                    else 0o644
                ),
            }
    return {
        "old": old_files,
        "new": new_files,
        "wheels": wheels,
        "sites": sorted(set(destinations.values())),
    }


def imported_changes(payload):
    """An imported owned file requires a fresh backend process."""
    owned = {str(Path(path).resolve()) for path in payload["old"]}
    imported = []
    for name, module in tuple(sys.modules.items()):
        value = getattr(module, "__dict__", {}).get("__file__")
        if isinstance(value, str) and str(Path(value).resolve()) in owned:
            imported.append(name)
    return imported


@contextmanager
def operation_lock(directory):
    from .install_lock import plugin_install_lock

    with plugin_install_lock(directory / "operation.lock", timeout=0):
        yield


def verify_payload(directory, operation):
    for path, evidence in operation["payload"]["old"].items():
        file = Path(path)
        if (
            not file.is_file()
            or file.is_symlink()
            or _hash(file) != evidence["sha256"]
            or stat.S_IMODE(file.stat().st_mode) != evidence["mode"]
        ):
            raise RuntimeError(
                "DEPENDENCY_PLAN_STALE: installed dependency files changed after review.",
            )
    for path, evidence in operation["payload"]["new"].items():
        payload = directory / evidence["payload"]
        if (
            not payload.resolve().is_relative_to(directory.resolve())
            or payload.is_symlink()
            or _hash(payload) != evidence["sha256"]
        ):
            raise RuntimeError(
                "DEPENDENCY_PLAN_STALE: retained wheel payload changed after review.",
            )
        destination = Path(path)
        if any(
            parent.is_symlink()
            for parent in (destination, *destination.parents)
        ):
            raise RuntimeError(
                "DEPENDENCY_PLAN_STALE: publication destination changed.",
            )
        if destination.exists() and path not in operation["payload"]["old"]:
            raise RuntimeError(
                "DEPENDENCY_PLAN_STALE: a new dependency file now collides.",
            )
    for wheel in operation["payload"]["wheels"]:
        if _hash(Path(wheel["path"])) != wheel["sha256"]:
            raise RuntimeError(
                "DEPENDENCY_PLAN_STALE: retained wheel changed after review.",
            )


def _write_file(path, content, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise RuntimeError(
            "DEPENDENCY_REPAIR_REQUIRED: publication path is unsafe.",
        )
    with path.open("wb") as stream:
        os.chmod(path, mode)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directories(paths):
    if os.name == "nt":
        return
    for path in sorted(
        {Path(value) for value in paths},
        key=lambda value: len(value.parts),
        reverse=True,
    ):
        if path.is_dir():
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def _source_files(root):
    files = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(
                "DEPENDENCY_REPAIR_REQUIRED: source backup contains a symlink.",
            )
        if path.is_file():
            files[path.relative_to(root).as_posix()] = {
                "sha256": _hash(path),
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
    return files


def _sync_source(root):
    for path in root.rglob("*"):
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    _sync_directories(
        {
            root,
            root.parent,
            *(path for path in root.rglob("*") if path.is_dir()),
        },
    )


def backup_source(directory, target):
    """Retain a durable exact source image before dependency publication."""
    before = {"target": str(target), "existed": target.is_dir()}
    if target.exists() and not target.is_dir():
        raise RuntimeError(
            "DEPENDENCY_PLAN_STALE: plugin source destination changed.",
        )
    if before["existed"]:
        before["files"] = _source_files(target)
        backup = directory / "previous_source"
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(target, backup)
        if _source_files(backup) != before["files"]:
            raise RuntimeError(
                "DEPENDENCY_PLAN_STALE: plugin source changed during backup.",
            )
        _sync_source(backup)
    return before


def restore_source(directory, operation):
    """Idempotently finish source recovery before declaring rollback complete."""
    before = operation.get("source_before")
    if not before:
        return
    target = Path(before["target"])
    if before["existed"]:
        backup = directory / "previous_source"
        if not backup.is_dir() or _source_files(backup) != before["files"]:
            raise RuntimeError(
                "DEPENDENCY_REPAIR_REQUIRED: source backup is damaged.",
            )
        staging = directory / "restored_source"
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(backup, staging)
        _sync_source(staging)
    if target.is_symlink():
        raise RuntimeError(
            "DEPENDENCY_REPAIR_REQUIRED: source destination became a symlink.",
        )
    if target.exists():
        shutil.rmtree(target)
    if before["existed"]:
        os.replace(staging, target)
    _sync_directories((target.parent, directory))


def publish(directory, operation):
    """Journal and backup precede every installed-file mutation."""
    from .dependency_maintenance import repair_marker

    verify_payload(directory, operation)
    backup = directory / "backup"
    backup.mkdir(exist_ok=True)
    entries = []
    owned = dict(operation["payload"]["old"])
    for path in tuple(owned):
        source = Path(path)
        if source.suffix == ".py":
            for cache in source.parent.glob(
                "__pycache__/" + source.stem + ".*.pyc",
            ):
                if cache.is_symlink():
                    raise RuntimeError(
                        "DEPENDENCY_PLAN_STALE: dependency cache became a symlink.",
                    )
                owned[str(cache)] = {
                    "sha256": _hash(cache),
                    "mode": stat.S_IMODE(cache.stat().st_mode),
                }
    for number, (path, evidence) in enumerate(owned.items()):
        saved = backup / str(number)
        _write_file(saved, Path(path).read_bytes(), evidence["mode"])
        entries.append(
            {
                "path": path,
                "backup": str(saved.relative_to(directory)),
                **evidence,
            },
        )
    _sync_directories((backup, directory))
    journal = {
        "phase": "prepared",
        "old": entries,
        "new": operation["payload"]["new"],
        "sites": operation["payload"]["sites"],
    }
    atomic_json(directory / "journal.json", journal)
    for site in journal["sites"]:
        marker = repair_marker(site)
        _write_file(
            marker,
            (
                "Dependency transaction "
                + operation["id"]
                + " requires verification.\n"
            ).encode(),
            0o600,
        )
    journal["phase"] = "writing"
    atomic_json(directory / "journal.json", journal)
    for entry in entries:
        Path(entry["path"]).unlink()
    for path, evidence in operation["payload"]["new"].items():
        _write_file(
            Path(path),
            (directory / evidence["payload"]).read_bytes(),
            evidence["mode"],
        )
    # Remove empty old dist-info directories only. Package/namespace parent
    # directories are shared structure and are never deletion authority.
    for row in operation["environment"]["distributions"].values():
        metadata = Path(row["metadata_path"])
        for child in sorted(
            metadata.rglob("*"),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            if child.is_dir():
                try:
                    child.rmdir()
                except OSError:
                    pass
        if metadata.is_dir():
            try:
                metadata.rmdir()
            except OSError:
                pass
    _sync_directories(
        {Path(path).parent for path in (*owned, *operation["payload"]["new"])}
        | {Path(site) for site in journal["sites"]},
    )
    journal["phase"] = "published"
    atomic_json(directory / "journal.json", journal)


def rollback(directory):
    """Idempotently restore exact prior bytes and modes after any phase."""
    path = directory / "journal.json"
    if not path.is_file():
        return True
    journal = json.loads(path.read_text())
    if journal["phase"] in {"committing", "committed"}:
        return False
    journal["phase"] = "rolling_back"
    atomic_json(path, journal)
    for destination, evidence in journal["new"].items():
        file = Path(destination)
        if file.suffix == ".py":
            for cache in file.parent.glob(
                "__pycache__/" + file.stem + ".*.pyc",
            ):
                if cache.is_symlink():
                    raise RuntimeError(
                        "DEPENDENCY_REPAIR_REQUIRED: dependency cache became a symlink.",
                    )
                cache.unlink()
        if file.exists():
            if file.is_symlink():
                raise RuntimeError(
                    "DEPENDENCY_REPAIR_REQUIRED: rollback path became a symlink.",
                )
            file.unlink()
    for row in journal["old"]:
        saved = directory / row["backup"]
        if _hash(saved) != row["sha256"]:
            raise RuntimeError(
                "DEPENDENCY_REPAIR_REQUIRED: rollback backup is damaged.",
            )
        _write_file(Path(row["path"]), saved.read_bytes(), row["mode"])
    for site in journal["sites"]:
        for metadata in Path(site).glob("*.dist-info"):
            try:
                metadata.rmdir()
            except OSError:
                pass
    journal["phase"] = "dependencies_restored"
    _sync_directories(
        {Path(row["path"]).parent for row in journal["old"]}
        | {Path(site) for site in journal["sites"]},
    )
    atomic_json(path, journal)
    return True


def finish(directory, operation, *, committed):
    from .dependency_maintenance import clear_maintenance, repair_marker

    path = directory / "journal.json"
    if not committed:
        operation.update(status="failed", retryable=True)
        if not operation.get("error"):
            operation["error"] = {
                "code": "DEPENDENCY_INTERRUPTED",
                "message": "DEPENDENCY_INTERRUPTED",
            }
        atomic_json(directory / "operation.json", operation)
    if path.exists():
        journal = json.loads(path.read_text())
        journal["phase"] = "committed" if committed else "rolled_back"
        atomic_json(path, journal)
    for site in operation["payload"]["sites"]:
        repair_marker(site).unlink(missing_ok=True)
    clear_maintenance(operation["payload"]["sites"], operation["id"])


def reconcile_commit(directory, operation):
    """Commit intent includes the verified result before barriers disappear."""
    path = directory / "journal.json"
    if not path.is_file():
        return False
    journal = json.loads(path.read_text())
    if journal["phase"] not in {"committing", "committed"} or not journal.get(
        "result",
    ):
        return False
    from .dependency_maintenance import marker, repair_marker

    if (
        operation.get("status") == "succeeded"
        and operation.get("result") == journal["result"]
        and journal["phase"] == "committed"
        and not any(
            marker(site).exists() or repair_marker(site).exists()
            for site in operation["payload"]["sites"]
        )
    ):
        return True
    operation.update(
        status="succeeded",
        result=journal["result"],
        error=None,
        retryable=False,
        message="Shared dependencies upgraded and plugin installation completed.",
    )
    operation.pop("worker_pid", None)
    atomic_json(directory / "operation.json", operation)
    finish(directory, operation, committed=True)
    return True


def commit_result(directory, operation, result):
    path = directory / "journal.json"
    journal = json.loads(path.read_text())
    journal.update(phase="committing", result=result)
    atomic_json(path, journal)
    reconcile_commit(directory, operation)


def _error_code(exc):
    return (
        getattr(exc, "reason_code", None) or str(exc).split(":", 1)[0]
        if str(exc).startswith("DEPENDENCY_")
        else "DEPENDENCY_UPGRADE_FAILED"
    )


async def apply_operation(manager, operation_id):
    """Stop exact consumers, replace bytes, verify, and resume installation."""
    import asyncio
    from .dependency_maintenance import maintenance, capability_context
    from .dependency_upgrade import _source_hash, install_result
    from .execution.dependencies import DependencySnapshot
    from .execution.process import _settle
    from .lifecycle import UnloadMode

    directory = manager._directory(operation_id)
    loader = manager.loader
    with operation_lock(directory):
        operation = manager._read(operation_id)
        if operation["status"] in {"succeeded", "cancelled"}:
            return manager._public(operation)
        if operation.get("worker_pid") or operation["status"] == "applying":
            return manager._public(operation)
        stopped_records, leases, rebased = [], [], []
        mutated = False
        token = None
        try:
            source = directory / "source"
            if _source_hash(source) != operation["source_revision"]:
                raise RuntimeError(
                    "DEPENDENCY_PLAN_STALE: retained source changed after review.",
                )
            binding = await manager._binding(source)
            fresh = await binding.backend.audit_dependencies(
                binding.description,
            )
            if (
                environment_fingerprint(fresh.to_mapping())
                != operation["environment_fingerprint"]
            ):
                raise RuntimeError(
                    "DEPENDENCY_PLAN_STALE: dependency environment changed after review.",
                )
            verify_payload(directory, operation)
            consumers = await manager._consumers(binding, fresh)
            manager._check_reviewed_usage(operation, consumers)
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
            if not operation["requires_restart"] and imported_changes(
                operation["payload"],
            ):
                raise RuntimeError(
                    "DEPENDENCY_PLAN_STALE: a host import now requires a backend restart; prepare a new confirmation.",
                )
            operation["approved"] = True
            if operation["requires_restart"]:
                from .dependency_upgrade import schedule_maintenance

                schedule_maintenance(manager, directory, operation)
                return manager._public(operation)
            operation.update(
                status="preparing",
                message="Stopping shared dependency consumers.",
                error=None,
            )
            manager._save(directory, operation)
            owners = loader.registry.runtime_owners
            affected = {
                (row["plugin_id"], row["instance_id"], row["generation"])
                for row in operation["affected_instances"]
                if row["instance_id"] is not None
            }
            leases = [
                lease
                for lease in owners.dependency_leases()
                if (lease.plugin_id, lease.instance_id, lease.generation)
                in affected
                or lease.plugin_id == operation["plugin_id"]
            ]
            for lease in leases:
                if lease.key.kind == "preparation":
                    continue
                record = loader.get_loaded_plugin(lease.plugin_id)
                instance = loader.lifecycle.get_instance(lease.plugin_id)
                if (
                    record is None
                    or instance is None
                    or not isinstance(instance.config, dict)
                    or Path(record.source_path).resolve() != lease.code_root
                ):
                    raise RuntimeError(
                        "DEPENDENCY_CONSUMER_UNRESTORABLE: an active consumer lacks lifecycle restart custody.",
                    )
            admissions = loader.registry.dependency_usage.capture_admissions(
                leases,
            )
            ids = {lease.plugin_id for lease in leases}
            ids.update(
                row["plugin_id"]
                for row in consumers
                if row["active"] and row["origin"] != "host"
            )
            for plugin_id in sorted(ids):
                record = loader.get_loaded_plugin(plugin_id)
                if record is not None:
                    instance = loader.lifecycle.get_instance(plugin_id)
                    stopped_records.append(
                        (record, dict(instance.config if instance else {})),
                    )
                    report = await loader.lifecycle.unload(
                        plugin_id,
                        UnloadMode.UNLOAD,
                        delete_files=False,
                    )
                    if (
                        not report.clean
                        or not report.quiescent
                        or report.needs_restart
                    ):
                        raise RuntimeError(
                            "DEPENDENCY_CONSUMER_BUSY: a shared consumer could not stop safely.",
                        )
            for lease in leases:
                if (
                    not (await owners.stop(lease)).stopped
                    or lease in owners.leases()
                ):
                    raise RuntimeError(
                        "DEPENDENCY_CONSUMER_BUSY: exact process exit proof is unavailable.",
                    )
            # Capture the prior source independently of the loader's short-lived
            # swap backup, because dependency commit includes continuation.
            _, target = loader._install_paths(operation["plugin_id"], None)
            operation["source_before"] = await asyncio.to_thread(
                backup_source,
                directory,
                target,
            )
            operation.update(
                status="applying",
                message="Applying and verifying shared dependencies.",
            )
            manager._save(directory, operation)
            # The marker outlives this gate. Only the private continuation
            # capability can admit fresh verification while it remains set.
            with maintenance(
                operation["payload"]["sites"],
                operation_id,
                operation["capability"],
                ignore_pid=os.getpid(),
            ):
                token = capability_context.set(
                    operation_id + ":" + operation["capability"],
                )
                mutated = True
                verified = await binding.backend.audit_dependencies(
                    binding.description,
                )
                if (
                    environment_fingerprint(verified.to_mapping())
                    != operation["environment_fingerprint"]
                ):
                    raise RuntimeError(
                        "DEPENDENCY_PLAN_STALE: environment changed while consumers stopped.",
                    )
                current = await manager._consumers(binding, verified)
                manager._check_reviewed_usage(
                    operation,
                    current,
                    allow_stopped=True,
                )
                if imported_changes(operation["payload"]):
                    raise RuntimeError(
                        "DEPENDENCY_PLAN_STALE: a host import appeared during preparation; prepare a new confirmation.",
                    )
                writer = asyncio.create_task(
                    asyncio.to_thread(publish, directory, operation),
                )
                try:
                    await asyncio.shield(writer)
                except asyncio.CancelledError:
                    await _settle(writer)
                    raise
            fresh = await binding.backend.audit_dependencies(
                binding.description,
            )
            for change in operation["changes"]:
                actual = fresh.distributions.get(change["name"])
                proposed = operation["proposed"][change["name"]]
                if (
                    actual is None
                    or actual["version"] != change["target_version"]
                    or actual["metadata_path"] != proposed["metadata_path"]
                ):
                    raise RuntimeError(
                        "DEPENDENCY_VERIFICATION_FAILED: installed version or origin differs.",
                    )
            manager._compatible(
                binding.description.requirements,
                fresh.distributions,
                fresh.marker_environment,
            )
            rebased = loader.registry.dependency_usage.rebase_stopped(
                leases,
                fresh,
                admissions,
            )
            record = await loader.load_plugin_from_path(
                source,
                force=operation["force"],
            )
            if record.status not in {"active", "inactive", "registered"}:
                raise RuntimeError(
                    "DEPENDENCY_CONTINUATION_FAILED: plugin installation did not complete.",
                )
            for previous, config in stopped_records:
                if previous.manifest.id != operation["plugin_id"]:
                    restored = await loader.load_plugin(
                        previous.manifest,
                        previous.source_path,
                        config,
                    )
                    if restored.status not in {
                        "active",
                        "inactive",
                        "registered",
                    }:
                        raise RuntimeError(
                            "DEPENDENCY_RESTORE_FAILED: previous consumer did not resume.",
                        )
            commit_result(directory, operation, install_result(record))
        except BaseException as exc:
            journal_path = directory / "journal.json"
            if journal_path.exists() and json.loads(journal_path.read_text())[
                "phase"
            ] in {"committing", "committed"}:
                reconcile_commit(directory, operation)
                return manager._public(operation)
            failure_code = _error_code(exc)
            operation.update(
                status="failed",
                error={"code": failure_code, "message": failure_code},
            )
            repair = False
            if mutated:
                try:
                    # A failed source continuation may still own a new child;
                    # its stop proof is required before restoring old packages.
                    for plugin_id in {
                        operation["plugin_id"],
                        *(row[0].manifest.id for row in stopped_records),
                    }:
                        if loader.get_loaded_plugin(
                            plugin_id,
                        ) is not None or loader.registry.runtime_owners.leases(
                            plugin_id,
                        ):
                            report = await loader.lifecycle.unload(
                                plugin_id,
                                UnloadMode.UNLOAD,
                                delete_files=False,
                            )
                            if (
                                not report.quiescent
                                or report.needs_restart
                                or loader.registry.runtime_owners.leases(
                                    plugin_id,
                                )
                            ):
                                raise RuntimeError(
                                    "DEPENDENCY_REPAIR_REQUIRED: new consumer remains active.",
                                )
                    await asyncio.to_thread(rollback, directory)
                    loader.registry.dependency_usage.restore_rebased(rebased)
                    await asyncio.to_thread(
                        restore_source,
                        directory,
                        operation,
                    )
                    finish(directory, operation, committed=False)
                except BaseException:
                    repair = True
            if not repair:
                for previous, config in stopped_records:
                    if loader.get_loaded_plugin(previous.manifest.id) is None:
                        try:
                            await loader.load_plugin(
                                previous.manifest,
                                previous.source_path,
                                config,
                            )
                        except Exception:
                            repair = True
            code = "DEPENDENCY_REPAIR_REQUIRED" if repair else _error_code(exc)
            operation.update(
                status="failed",
                retryable=not repair,
                message=(
                    "Dependency upgrade requires recovery."
                    if repair
                    else "Dependency upgrade did not complete; installed packages were preserved or restored."
                ),
                error={
                    "code": code,
                    "message": (
                        str(exc)
                        if code.startswith("DEPENDENCY_PLAN_")
                        else code
                    ),
                },
            )
            manager._save(directory, operation)
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            if token is not None:
                capability_context.reset(token)
        return manager._public(operation)
