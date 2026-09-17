# -*- coding: utf-8 -*-
"""Creator Data Workspace-backed observability configuration."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from domain.errors import ValidationError
from schemas.observability import ObservabilityConfigData
from services.storage_root import require_creator_data_root

_LEGACY_ENV = {
    "enabled": "CREATOR_TRACING_ENABLED",
    "traceDirectory": "CREATOR_TRACE_DIR",
    "logLevel": "CREATOR_TRACE_LOG_LEVEL",
    "captureContent": "CREATOR_TRACE_CAPTURE_CONTENT",
}


def observability_config_path() -> Path:
    return require_creator_data_root() / "config" / "observability.json"


def _legacy_bool(value: str, *, default: bool) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _legacy_payload() -> dict[str, Any]:
    payload = ObservabilityConfigData().model_dump(mode="json", by_alias=True)
    if value := os.environ.get(_LEGACY_ENV["enabled"], ""):
        payload["enabled"] = _legacy_bool(value, default=True)
    if value := os.environ.get(_LEGACY_ENV["traceDirectory"], "").strip():
        payload["traceDirectory"] = value
    if value := os.environ.get(_LEGACY_ENV["logLevel"], "").strip().upper():
        payload["logLevel"] = value
    if value := os.environ.get(_LEGACY_ENV["captureContent"], ""):
        payload["captureContent"] = _legacy_bool(value, default=False)
    return payload


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"可观测配置文件不可解析: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"可观测配置文件必须是 JSON object: {path.name}")
    return value


def _secure_create(path: Path, data: ObservabilityConfigData) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            data.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)


@lru_cache(maxsize=32)
def _load_cached(
    path_text: str,
    modified_ns: int,
    size: int,
) -> ObservabilityConfigData:
    del modified_ns, size
    return ObservabilityConfigData.model_validate(
        _read_payload(Path(path_text)),
    )


def load_observability_config() -> ObservabilityConfigData:
    """Load the authoritative file, bootstrapping it from legacy env once."""

    path = observability_config_path()
    if not path.exists():
        try:
            migrated = ObservabilityConfigData.model_validate(
                _legacy_payload(),
            )
        except ValueError as exc:
            raise ValidationError("旧可观测环境变量配置非法") from exc
        _secure_create(path, migrated)
    try:
        stat = path.stat()
    except OSError as exc:
        raise ValidationError("无法读取 Creator 可观测配置") from exc
    return _load_cached(str(path), stat.st_mtime_ns, stat.st_size)


def save_observability_config(data: ObservabilityConfigData) -> None:
    path = observability_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(
                descriptor,
                (
                    json.dumps(
                        data.model_dump(mode="json", by_alias=True),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                ).encode("utf-8"),
            )
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
    _load_cached.cache_clear()


def project_observability_root(
    project_id: str,
    *,
    data_root: Path | None = None,
    create: bool = True,
) -> Path:
    """Resolve diagnostics inside one real, already-published Project."""

    from services.project_files.store import ProjectStore

    store = ProjectStore(data_root or require_creator_data_root())
    project_root = store.project_root(project_id)
    if (
        not project_root.exists()
        or project_root.is_symlink()
        or not project_root.is_dir()
    ):
        raise ValidationError(f"Project 可观测目录不存在: {project_id}")
    project_json = project_root / "project.json"
    if (
        not project_json.exists()
        or project_json.is_symlink()
        or not project_json.is_file()
    ):
        raise ValidationError(f"Project 可观测目录缺少 project.json: {project_id}")
    resolved = project_root.resolve(strict=True)
    try:
        resolved.relative_to(store.root)
    except ValueError as exc:
        raise ValidationError(
            "Project 可观测目录越出 Creator Data Workspace",
        ) from exc
    return _local_directory(resolved, "observability", create=create)


def _local_directory(
    parent: Path,
    name: str,
    *,
    create: bool,
) -> Path:
    target = parent / name
    if create:
        target.mkdir(mode=0o700, exist_ok=True)
    if not target.exists():
        return target
    if target.is_symlink() or not target.is_dir():
        raise ValidationError(f"Creator 可观测路径不是安全目录: {target}")
    resolved = target.resolve(strict=True)
    try:
        resolved.relative_to(parent.resolve(strict=True))
    except ValueError as exc:
        raise ValidationError("Creator 可观测目录越出所属 Project") from exc
    return resolved


def project_observability_directory(
    project_id: str,
    directory: str,
    *,
    data_root: Path | None = None,
    create: bool = True,
) -> Path:
    """Resolve one safe logs/traces directory inside a real Project."""

    if directory not in {"logs", "traces"}:
        raise ValidationError(f"不支持的 Project 可观测目录: {directory}")
    root = project_observability_root(
        project_id,
        data_root=data_root,
        create=create,
    )
    return _local_directory(root, directory, create=create)


def trace_root(
    config: ObservabilityConfigData | None = None,
    *,
    project_id: str | None = None,
) -> Path:
    if project_id:
        return project_observability_directory(project_id, "traces")

    configured = (
        config or load_observability_config()
    ).trace_directory.strip()
    candidate = Path(configured).expanduser()
    root = (
        candidate
        if candidate.is_absolute()
        else require_creator_data_root() / candidate
    )
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


__all__ = [
    "load_observability_config",
    "observability_config_path",
    "project_observability_directory",
    "project_observability_root",
    "save_observability_config",
    "trace_root",
]
