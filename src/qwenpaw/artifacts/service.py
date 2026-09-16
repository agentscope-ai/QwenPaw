"""受控的用户产物发布、读取和删除服务。"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from ..access.agent_repository import agent_database_id
from ..constant import WORKING_DIR
from ..services.workspace_files import resolve_workspace_path
from ..workspaces.layout import ensure_artifacts_directory
from ..workspaces.resolver import WorkspaceKind, WorkspaceResolver
from ..utils.io_utils import run_sync_io
from .models import AgentArtifact


class ArtifactNotFound(FileNotFoundError):
    """产物不存在，或不属于当前用户。"""


class ArtifactSourceDenied(ValueError):
    """尝试从用户私有运行空间之外发布文件。"""


@dataclass(frozen=True)
class ArtifactCollectionFailure:
    path: Path | None
    error: str


@dataclass(frozen=True)
class ArtifactCollectionResult:
    artifacts: tuple[AgentArtifact, ...] = ()
    failures: tuple[ArtifactCollectionFailure, ...] = ()


def reject_symlink_path(path: Path) -> None:
    """解析前检查整条路径，防止符号链接或 Windows junction 隐藏来源。"""
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ArtifactSourceDenied("artifact_symlink_denied")


class ArtifactService:
    def __init__(self, *, repository, working_dir: Path = WORKING_DIR) -> None:
        self._repository = repository
        self._working_dir = Path(working_dir)

    async def publish(
        self,
        *,
        owner_user_id: UUID,
        agent_key: str,
        source: Path,
        conversation_id: UUID | None = None,
        source_tool: str = "send_file_to_user",
        trusted_source_roots: tuple[Path, ...] = (),
    ) -> AgentArtifact:
        root = self._runtime_root(owner_user_id, agent_key)
        source = Path(source).expanduser().absolute()
        reject_symlink_path(source)
        source = Path(os.path.abspath(source))
        private_domain = self._working_dir.resolve() / "user_workspaces"
        if source.is_relative_to(private_domain) and not source.is_relative_to(root):
            raise ArtifactSourceDenied("artifact_private_source_denied")
        library_domain = self._working_dir.resolve() / "user_libraries"
        agent_id = agent_database_id(agent_key)
        own_library = library_domain / str(owner_user_id) / str(agent_id)
        if source.is_relative_to(library_domain) and not source.is_relative_to(own_library):
            raise ArtifactSourceDenied("artifact_private_source_denied")
        source = source.resolve(strict=True)
        allowed_roots = (root, *(Path(item).resolve() for item in trusted_source_roots if item is not None))
        if not source.is_file() or not any(source.is_relative_to(item) for item in allowed_roots):
            raise ArtifactSourceDenied("artifact_source_denied")
        artifacts = ensure_artifacts_directory(root).resolve()
        payload, digest = await run_sync_io(self._read_content, source)
        existing = await self._repository.find_active_by_content(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            sha256=digest,
        )
        if existing is not None:
            return existing
        if source_tool == "session_artifact_collector":
            deleted = await self._repository.find_deleted_by_content(
                owner_user_id=owner_user_id, agent_id=agent_id,
                conversation_id=conversation_id, sha256=digest,
            )
            if deleted is not None:
                return deleted
        # 独立快照使生成路径被重写时，已登记产物仍保持原内容；内容名允许失败后重试。
        archive_key = hashlib.sha256(f"{conversation_id}:{digest}".encode()).hexdigest()[:24]
        target = artifacts / ".registered" / archive_key / source.name
        if source != target:
            await run_sync_io(self._write_snapshot, target, payload, digest)
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        artifact = AgentArtifact(
            id=uuid4(), owner_user_id=owner_user_id,
            agent_id=agent_id, conversation_id=conversation_id,
            relative_path=target.relative_to(root).as_posix(),
            original_name=source.name, media_type=media_type, size=len(payload),
            sha256=digest, source_tool=source_tool,
            status="active", created_at=datetime.now(UTC), deleted_at=None,
        )
        return await self._repository.register(artifact)

    async def collect_session(
        self, *, owner_user_id: UUID, agent_key: str, conversation_id: UUID,
    ) -> ArtifactCollectionResult:
        """仅收集当前用户、Agent 和会话的明确产物目录；失败保留源文件供重试。"""
        folder = None
        try:
            folder = self._runtime_root(owner_user_id, agent_key) / "artifacts" / str(UUID(str(conversation_id)))
            reject_symlink_path(folder)
            if not folder.exists():
                return ArtifactCollectionResult()
            sources = await run_sync_io(self._session_files, folder)
        except Exception as exc:
            return ArtifactCollectionResult(failures=(ArtifactCollectionFailure(folder, f"artifact_collection_failed_retryable: {exc}"),))
        artifacts, failures = [], []
        for source in sources:
            try:
                artifact = await self.publish(owner_user_id=owner_user_id, agent_key=agent_key, conversation_id=conversation_id, source=source, source_tool="session_artifact_collector")
                if artifact.status == "active" and artifact.id not in {item.id for item in artifacts}:
                    artifacts.append(artifact)
            except Exception as exc:
                failures.append(ArtifactCollectionFailure(source, f"artifact_registration_failed_retryable: {exc}"))
        return ArtifactCollectionResult(tuple(artifacts), tuple(failures))

    @staticmethod
    def _session_files(folder: Path) -> list[Path]:
        skipped = {"tmp", "temp", "cache", "work", "working", "intermediate", "intermediates", "node_modules", "__pycache__"}
        result = []
        def scan_error(error):
            raise error
        for current, directories, filenames in os.walk(folder, followlinks=False, onerror=scan_error):
            directories[:] = sorted(name for name in directories if not name.startswith((".", "_")) and name.lower() not in skipped and not (Path(current) / name).is_symlink() and not (hasattr(Path(current) / name, "is_junction") and (Path(current) / name).is_junction()))
            result.extend(Path(current) / name for name in sorted(filenames) if not name.startswith((".", "~", "_")) and Path(name).suffix.lower() not in {".tmp", ".temp", ".part", ".partial", ".lock", ".pyc", ".swp"})
        return result

    @staticmethod
    def _read_content(source: Path) -> tuple[bytes, str]:
        reject_symlink_path(source)
        before = source.stat()
        payload = source.read_bytes()
        reject_symlink_path(source)
        after = source.stat()
        def identity(value):
            return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if identity(before) != identity(after) or len(payload) != after.st_size:
            raise ArtifactSourceDenied("artifact_source_changed_retryable")
        return payload, hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _write_snapshot(target: Path, payload: bytes, digest: str) -> None:
        reject_symlink_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # 先完成临时文件，再以排他硬链接发布；并发读者不会看见写到一半的归档。
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".snapshot-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
            try:
                os.link(temporary, target)
            except FileExistsError:
                reject_symlink_path(target)
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise ArtifactSourceDenied("artifact_archive_content_conflict")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    async def list_active(self, *, owner_user_id: UUID, agent_key: str) -> list[AgentArtifact]:
        artifacts = await self._repository.list_active(owner_user_id=owner_user_id, agent_id=agent_database_id(agent_key))
        result: list[AgentArtifact] = []
        seen: set[tuple[UUID | None, str]] = set()
        for artifact in artifacts:
            content_key = (artifact.conversation_id, artifact.sha256)
            if content_key in seen:
                continue
            seen.add(content_key)
            result.append(artifact)
        return result

    async def download_path(self, *, owner_user_id: UUID, agent_key: str, artifact_id: UUID) -> tuple[AgentArtifact, Path]:
        artifact = await self._repository.get(owner_user_id=owner_user_id, artifact_id=artifact_id)
        if artifact is None or artifact.owner_user_id != owner_user_id or artifact.agent_id != agent_database_id(agent_key) or artifact.status != "active":
            raise ArtifactNotFound("artifact_not_found")
        root = self._runtime_root(owner_user_id, agent_key)
        try:
            reject_symlink_path(root / artifact.relative_path)
            path = resolve_workspace_path(root, artifact.relative_path, portable=True)
        except ValueError as exc:
            raise ArtifactNotFound("artifact_not_found") from exc
        if not path.is_file() or path.is_symlink():
            raise ArtifactNotFound("artifact_not_found")
        return artifact, path

    async def delete(self, *, owner_user_id: UUID, agent_key: str, artifact_id: UUID) -> AgentArtifact:
        artifact, path = await self.download_path(owner_user_id=owner_user_id, agent_key=agent_key, artifact_id=artifact_id)
        updated = await self._repository.mark_deleted(owner_user_id=owner_user_id, artifact_id=artifact.id, deleted_at=datetime.now(UTC))
        if updated is None:
            raise ArtifactNotFound("artifact_not_found")
        path.unlink()
        return updated

    def _runtime_root(self, owner_user_id: UUID, agent_key: str) -> Path:
        resolved = WorkspaceResolver(working_dir=self._working_dir).resolve(
            kind=WorkspaceKind.USER_RUNTIME, resource_id=agent_key, actor_user_id=owner_user_id,
        )
        return WorkspaceResolver(working_dir=self._working_dir).ensure_standard_directories(resolved)
