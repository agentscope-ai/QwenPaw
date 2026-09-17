# -*- coding: utf-8 -*-
"""Portable production backup manifests and safe file restoration helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


MANIFEST_NAME = "manifest.json"
FORMAT_VERSION = 1
SENSITIVE_NAME_PARTS = (
    "PASSWORD",
    "TOKEN",
    "SECRET",
    "KEY",
    "CREDENTIAL",
    "DATABASE_URL",
)


class BackupValidationError(ValueError):
    """The backup or restore target does not satisfy the safety contract."""


@dataclass(frozen=True)
class DeploymentBackupManifest:
    format_version: int
    created_at: str
    source_commit: str
    image_digest: str
    alembic_version: str
    files: dict[str, str]
    environment: dict[str, str]


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    errors: tuple[str, ...] = ()


def sanitize_environment(env: Mapping[str, str]) -> dict[str, str]:
    """Return deployment metadata without copying secret values."""

    clean: dict[str, str] = {}
    for name, value in sorted(env.items()):
        upper = name.upper()
        clean[name] = (
            "<redacted>"
            if any(part in upper for part in SENSITIVE_NAME_PARTS)
            else str(value)
        )
    return clean


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def new_manifest(
    root: Path,
    *,
    environment: Mapping[str, str],
    source_commit: str = "unknown",
    image_digest: str = "unknown",
    alembic_version: str = "unknown",
) -> DeploymentBackupManifest:
    files = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != MANIFEST_NAME
    }
    return DeploymentBackupManifest(
        format_version=FORMAT_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(),
        source_commit=source_commit,
        image_digest=image_digest,
        alembic_version=alembic_version,
        files=files,
        environment=sanitize_environment(environment),
    )


def write_manifest(root: Path, manifest: DeploymentBackupManifest) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    destination = root / MANIFEST_NAME
    destination.write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return destination


def read_manifest(root: Path) -> DeploymentBackupManifest:
    try:
        payload = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
        return DeploymentBackupManifest(**payload)
    except (OSError, ValueError, TypeError) as exc:
        raise BackupValidationError("备份清单不存在或格式无效") from exc


def verify_manifest(root: Path) -> VerificationResult:
    try:
        manifest = read_manifest(root)
    except BackupValidationError as exc:
        return VerificationResult(False, (str(exc),))
    errors: list[str] = []
    if manifest.format_version != FORMAT_VERSION:
        errors.append(f"不支持的备份格式版本：{manifest.format_version}")
    for relative, expected in manifest.files.items():
        path = root / relative
        try:
            actual = sha256_file(path)
        except OSError:
            errors.append(f"备份文件缺失：{relative}")
            continue
        if actual != expected:
            errors.append(f"备份文件校验失败：{relative}")
    return VerificationResult(not errors, tuple(errors))


def ensure_empty_directory(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise BackupValidationError(f"恢复目标必须为空：{path.name}")


def preflight_restore(backup_root: Path, target_data_root: Path) -> DeploymentBackupManifest:
    verification = verify_manifest(backup_root)
    if not verification.ok:
        raise BackupValidationError("；".join(verification.errors))
    for name in ("working", "secrets"):
        ensure_empty_directory(target_data_root / name)
    manifest = read_manifest(backup_root)
    required = {"database.dump", "working.tar.gz", "secrets.tar.gz"}
    missing = required.difference(manifest.files)
    if missing:
        raise BackupValidationError(f"备份缺少必要文件：{', '.join(sorted(missing))}")
    return manifest


def create_tree_archive(source: Path, destination: Path) -> None:
    """Archive one directory while keeping a stable top-level name."""

    with tarfile.open(destination, "w:gz") as archive:
        if source.exists():
            archive.add(source, arcname=source.name, recursive=True)
        else:
            info = tarfile.TarInfo(source.name)
            info.type = tarfile.DIRTYPE
            info.mode = 0o700
            archive.addfile(info)


def _safe_members(archive: tarfile.TarFile, target: Path):
    target_resolved = target.resolve()
    for member in archive.getmembers():
        if member.issym() or member.islnk():
            raise BackupValidationError("备份归档包含不允许的链接")
        destination = (target / member.name).resolve()
        if destination != target_resolved and target_resolved not in destination.parents:
            raise BackupValidationError("备份归档包含越界路径")
        yield member


def extract_tree_archive(archive_path: Path, target_data_root: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(target_data_root, members=_safe_members(archive, target_data_root))


def atomic_publish_directory(temp_root: Path, target: Path) -> None:
    source = temp_root / target.name
    if not source.is_dir():
        raise BackupValidationError(f"归档中缺少目录：{target.name}")
    if target.exists():
        target.rmdir()
    os.replace(source, target)
