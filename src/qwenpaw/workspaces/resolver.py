# -*- coding: utf-8 -*-
"""从已授权资源标识解析受控工作区路径。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Mapping
from uuid import UUID

from ..constant import WORKING_DIR
from .layout import ensure_artifacts_directory

_SAFE_RESOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class WorkspaceKind(StrEnum):
    """平台支持的工作区语义。"""

    DRAFT = "draft"
    PUBLISHED_BASELINE = "published_baseline"
    USER_RUNTIME = "user_runtime"
    SHARED_APP_RUNTIME = "shared_app_runtime"
    LEGACY = "legacy"


class WorkspaceResolutionDenied(ValueError):
    """资源标识或逻辑路径不能安全解析。"""


@dataclass(frozen=True, slots=True)
class ResolvedWorkspace:
    """解析器签发、可交给运行时使用的工作区描述。"""

    path: Path
    workspace_key: str
    kind: WorkspaceKind
    resource_id: str
    actor_user_id: UUID | None
    read_only: bool
    legacy_registered: bool = False


class WorkspaceResolver:
    """只从受控资源 ID 和登记映射生成文件系统路径。"""

    def __init__(
        self,
        *,
        working_dir: Path = WORKING_DIR,
        legacy_workspaces: Mapping[str, str | Path] | None = None,
    ) -> None:
        self._working_dir = Path(working_dir).expanduser().resolve()
        self._legacy_workspaces = {
            resource_id: self._resolve_registered_path(path)
            for resource_id, path in (legacy_workspaces or {}).items()
        }
        for resource_id in self._legacy_workspaces:
            self._validate_resource_id(resource_id)

    def resolve(
        self,
        *,
        kind: WorkspaceKind,
        resource_id: str,
        actor_user_id: UUID | None = None,
        workspace_key: str | None = None,
    ) -> ResolvedWorkspace:
        """解析一个已完成授权判断的资源。"""
        self._validate_resource_id(resource_id)
        if kind is WorkspaceKind.LEGACY:
            return self._resolve_legacy(
                resource_id=resource_id,
                workspace_key=workspace_key,
            )

        expected_key = self._managed_workspace_key(
            kind=kind,
            resource_id=resource_id,
            actor_user_id=actor_user_id,
        )
        if workspace_key is not None:
            normalized_key = self._validate_workspace_key(workspace_key)
            if normalized_key != expected_key:
                raise WorkspaceResolutionDenied("workspace_key_mismatch")

        candidate = self._working_dir.joinpath(*PurePosixPath(expected_key).parts)
        self._validate_managed_candidate(candidate)
        return ResolvedWorkspace(
            path=candidate,
            workspace_key=expected_key,
            kind=kind,
            resource_id=resource_id,
            actor_user_id=actor_user_id,
            read_only=kind is WorkspaceKind.PUBLISHED_BASELINE,
        )

    def ensure(self, resolved: ResolvedWorkspace) -> Path:
        """在再次校验边界后创建可写工作区目录。"""
        if resolved.read_only:
            if not resolved.path.is_dir():
                raise WorkspaceResolutionDenied(
                    "published_workspace_not_found",
                )
            return resolved.path
        if resolved.kind is WorkspaceKind.LEGACY:
            resolved.path.mkdir(parents=True, exist_ok=True)
            return resolved.path
        self._validate_managed_candidate(resolved.path)
        current = self._working_dir
        for part in resolved.path.relative_to(self._working_dir).parts:
            current /= part
            if current.is_symlink():
                raise WorkspaceResolutionDenied("workspace_symlink_denied")
            current.mkdir(exist_ok=True)
        return resolved.path

    def resolve_shared_app_runtime(
        self,
        *,
        user_id: UUID,
        shared_app_id: UUID,
        publication_id: UUID,
        workspace_key: str | None = None,
    ) -> ResolvedWorkspace:
        """仅从服务端 UUID 解析共享应用的每用户每版本空间。"""
        expected_key = (
            f"user_workspaces/{user_id}/apps/{shared_app_id}/{publication_id}"
        )
        if workspace_key is not None:
            normalized_key = self._validate_workspace_key(workspace_key)
            if normalized_key != expected_key:
                raise WorkspaceResolutionDenied("workspace_key_mismatch")
        candidate = self._working_dir.joinpath(*PurePosixPath(expected_key).parts)
        self._validate_managed_candidate(candidate)
        return ResolvedWorkspace(
            path=candidate,
            workspace_key=expected_key,
            kind=WorkspaceKind.SHARED_APP_RUNTIME,
            resource_id=str(publication_id),
            actor_user_id=user_id,
            read_only=False,
        )

    def ensure_standard_directories(self, resolved: ResolvedWorkspace) -> Path:
        """创建个人运行和可写 Agent 工作区使用的标准资料目录。"""
        if resolved.read_only:
            raise WorkspaceResolutionDenied("published_workspace_read_only")
        root = self.ensure(resolved)
        for name in ("media",):
            target = root / name
            if target.is_symlink():
                raise WorkspaceResolutionDenied("workspace_symlink_denied")
            target.mkdir(exist_ok=True)
        try:
            ensure_artifacts_directory(root)
        except ValueError as exc:
            raise WorkspaceResolutionDenied(str(exc)) from exc
        return root

    def _managed_workspace_key(
        self,
        *,
        kind: WorkspaceKind,
        resource_id: str,
        actor_user_id: UUID | None,
    ) -> str:
        if kind is WorkspaceKind.DRAFT:
            return f"workspaces/{resource_id}"
        if kind is WorkspaceKind.PUBLISHED_BASELINE:
            return f"published_workspaces/{resource_id}"
        if kind is WorkspaceKind.USER_RUNTIME:
            if actor_user_id is None:
                raise WorkspaceResolutionDenied("authenticated_user_required")
            return f"user_workspaces/{actor_user_id}/{resource_id}"
        raise WorkspaceResolutionDenied("unsupported_workspace_kind")

    def _resolve_legacy(
        self,
        *,
        resource_id: str,
        workspace_key: str | None,
    ) -> ResolvedWorkspace:
        registered = self._legacy_workspaces.get(resource_id)
        if registered is None:
            raise WorkspaceResolutionDenied("legacy_workspace_not_registered")
        if workspace_key is not None:
            supplied = self._resolve_registered_path(workspace_key)
            if supplied != registered:
                raise WorkspaceResolutionDenied("legacy_workspace_key_mismatch")
        if registered.is_symlink():
            raise WorkspaceResolutionDenied("workspace_symlink_denied")
        return ResolvedWorkspace(
            path=registered,
            workspace_key=str(registered),
            kind=WorkspaceKind.LEGACY,
            resource_id=resource_id,
            actor_user_id=None,
            read_only=False,
            legacy_registered=True,
        )

    def _validate_managed_candidate(self, candidate: Path) -> None:
        current = self._working_dir
        try:
            relative = candidate.relative_to(self._working_dir)
        except ValueError as exc:
            raise WorkspaceResolutionDenied("workspace_path_escape") from exc
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise WorkspaceResolutionDenied("workspace_symlink_denied")
        try:
            candidate.resolve().relative_to(self._working_dir)
        except ValueError as exc:
            raise WorkspaceResolutionDenied("workspace_path_escape") from exc

    @staticmethod
    def _validate_workspace_key(workspace_key: str) -> str:
        if not isinstance(workspace_key, str) or not workspace_key:
            raise WorkspaceResolutionDenied("invalid_workspace_key")
        if "\\" in workspace_key:
            raise WorkspaceResolutionDenied("invalid_workspace_key")
        if workspace_key.startswith(("/", "//")):
            raise WorkspaceResolutionDenied("absolute_workspace_key_denied")
        if len(workspace_key) >= 2 and workspace_key[1] == ":":
            raise WorkspaceResolutionDenied("absolute_workspace_key_denied")
        parts = workspace_key.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise WorkspaceResolutionDenied("invalid_workspace_key")
        return PurePosixPath(*parts).as_posix()

    def _resolve_registered_path(self, value: str | Path) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self._working_dir / path
        absolute_path = path.absolute()
        if any(
            candidate.exists() and candidate.is_symlink()
            for candidate in (absolute_path, *absolute_path.parents)
        ):
            raise WorkspaceResolutionDenied("workspace_symlink_denied")
        return path.resolve()

    @staticmethod
    def _validate_resource_id(resource_id: str) -> None:
        if (
            not isinstance(resource_id, str)
            or resource_id in {".", ".."}
            or not _SAFE_RESOURCE_ID.fullmatch(resource_id)
        ):
            raise WorkspaceResolutionDenied("invalid_resource_id")
