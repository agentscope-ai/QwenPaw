# -*- coding: utf-8 -*-
"""个人资料库的文件一致性服务。"""

from __future__ import annotations

import hashlib
import os
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from ..app.chats.repo.conversation import AttachmentRecord
from ..access.agent_repository import agent_database_id
from ..constant import WORKING_DIR
from ..services.workspace_files import (
    InvalidWorkspacePath,
    resolve_workspace_path,
    save_text_file,
)
from ..workspaces.layout import ARTIFACTS_DIRECTORY, LEGACY_ARTIFACTS_DIRECTORY
from ..workspaces.resolver import WorkspaceKind, WorkspaceResolver
from .models import PersonalLibraryDocument, PersonalLibraryDocumentContent
from .paths import PersonalLibraryPathDenied, PersonalLibraryPathResolver
from .content_extractor import SEARCHABLE_EXTENSIONS, extract_searchable_text


class PersonalLibraryNotFound(FileNotFoundError):
    """当前用户无权访问资料，或资料不存在。"""


class PersonalLibraryConflict(RuntimeError):
    """资料目标路径已存在且用户未确认覆盖。"""


class PersonalLibrarySourceDenied(ValueError):
    """资料库导入来源不属于当前用户，或不在允许根目录内。"""


class PersonalLibraryRepository(Protocol):
    """文件服务所需的最小元数据仓储契约。"""

    async def get_document(
        self,
        *,
        owner_user_id: UUID,
        agent_id: UUID,
        document_id: UUID,
    ) -> PersonalLibraryDocument | None: ...

    async def get_by_path(
        self,
        *,
        owner_user_id: UUID,
        agent_id: UUID,
        relative_path: str,
    ) -> PersonalLibraryDocument | None: ...

    async def save_document(
        self,
        document: PersonalLibraryDocument,
    ) -> PersonalLibraryDocument: ...

    async def list_documents(
        self,
        *,
        owner_user_id: UUID,
        agent_id: UUID,
    ) -> list[PersonalLibraryDocument]: ...

    async def delete_document(
        self,
        *,
        owner_user_id: UUID,
        agent_id: UUID,
        document_id: UUID,
    ) -> bool: ...


class AttachmentRepository(Protocol):
    """导入附件时所需的最小对话仓储契约。"""

    async def get_attachment(
        self,
        *,
        attachment_id: UUID,
        owner_user_id: UUID,
    ) -> AttachmentRecord | None: ...


@dataclass(frozen=True, slots=True)
class PersonalLibrarySearchHit:
    document: PersonalLibraryDocument
    excerpt: str
    score: int


class PersonalLibraryService:
    """协调资料文件系统与用户归属元数据。"""

    def __init__(
        self,
        *,
        repository: PersonalLibraryRepository,
        attachment_repository: AttachmentRepository | None = None,
        working_dir: Path = WORKING_DIR,
    ) -> None:
        self._repository = repository
        self._working_dir = Path(working_dir)
        self._paths = PersonalLibraryPathResolver(working_dir=self._working_dir)
        self._attachment_repository = attachment_repository

    async def list_directory(
        self,
        *,
        owner_user_id: UUID,
        path: str = "",
        agent_key: str = "default",
    ) -> list[PersonalLibraryDocument]:
        """列出当前用户资料库某个目录的直接文件。"""
        directory = self._paths.resolve(
            user_id=owner_user_id,
            agent_id=agent_database_id(agent_key),
            relative_path=path,
            allow_root=True,
        )
        root = self._paths.ensure_root(owner_user_id, agent_database_id(agent_key))
        relative_directory = "" if directory == root else directory.relative_to(root).as_posix()
        prefix = f"{relative_directory}/" if relative_directory else ""
        documents = await self._repository.list_documents(
            owner_user_id=owner_user_id,
            agent_id=agent_database_id(agent_key),
        )
        if not relative_directory:
            return sorted(
                documents,
                key=lambda document: (document.relative_path.casefold(), document.relative_path),
            )
        return sorted(
            (
                document
                for document in documents
                if document.relative_path.startswith(prefix)
                and "/" not in document.relative_path[len(prefix) :]
            ),
            key=lambda document: (document.name.casefold(), document.name),
        )

    async def create_text(
        self,
        *,
        owner_user_id: UUID,
        relative_path: str,
        content: str,
        overwrite: bool = False,
        agent_key: str = "default",
    ) -> PersonalLibraryDocument:
        """原子创建当前用户私有的 UTF-8 文本资料。"""
        agent_id = agent_database_id(agent_key)
        target = self._resolve(owner_user_id, agent_id, relative_path)
        existing = await self._repository.get_by_path(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            relative_path=relative_path,
        )
        if existing is not None and not overwrite:
            raise PersonalLibraryConflict("library_document_exists")

        root = self._paths.ensure_root(owner_user_id, agent_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        save_text_file(root, relative_path, content, None)
        payload = content.encode("utf-8")
        timestamp = datetime.now(UTC)
        document = PersonalLibraryDocument(
            id=existing.id if existing is not None else uuid4(),
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            relative_path=relative_path,
            name=target.name,
            media_type="text/markdown" if target.suffix.casefold() == ".md" else "text/plain",
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            created_at=existing.created_at if existing is not None else timestamp,
            updated_at=timestamp,
        )
        try:
            return await self._repository.save_document(document)
        except Exception:
            if existing is None:
                target.unlink(missing_ok=True)
            raise

    async def save_upload(
        self,
        *,
        owner_user_id: UUID,
        filename: str,
        content: bytes,
        media_type: str,
        agent_key: str = "default",
    ) -> PersonalLibraryDocument:
        """保存当前用户从本机上传的一个资料文件。"""
        normalized_name = filename.replace("\\", "/").rsplit("/", 1)[-1]
        if not normalized_name or normalized_name in {".", ".."}:
            raise ValueError("invalid_library_filename")
        agent_id = agent_database_id(agent_key)
        destination = self._resolve(owner_user_id, agent_id, normalized_name)
        existing = await self._repository.get_by_path(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            relative_path=normalized_name,
        )
        if existing is not None or destination.exists():
            raise PersonalLibraryConflict("library_document_exists")
        self._atomic_write(destination, content)
        timestamp = datetime.now(UTC)
        document = PersonalLibraryDocument(
            id=uuid4(),
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            relative_path=normalized_name,
            name=destination.name,
            media_type=media_type or self._media_type_for(destination),
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            created_at=timestamp,
            updated_at=timestamp,
        )
        try:
            return await self._repository.save_document(document)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    async def read_text(
        self,
        *,
        owner_user_id: UUID,
        document_id: UUID,
        offset: int = 0,
        limit: int = 65_536,
        agent_key: str = "default",
    ) -> PersonalLibraryDocumentContent:
        """读取当前用户的一段 UTF-8 文本资料。"""
        if offset < 0 or not 1 <= limit <= 65_536:
            raise ValueError("invalid_library_read_range")
        agent_id = agent_database_id(agent_key)
        document = await self._repository.get_document(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            document_id=document_id,
        )
        if document is None:
            raise PersonalLibraryNotFound("library_document_not_found")
        target = self._resolve_existing(owner_user_id, agent_id, document.relative_path)
        if not target.is_file() or target.is_symlink():
            raise PersonalLibraryNotFound("library_document_not_found")
        data = self._searchable_payload(target)
        actual_offset = offset
        while actual_offset < len(data) and data[actual_offset] & 0xC0 == 0x80:
            actual_offset += 1
        chunk = data[actual_offset : actual_offset + limit]
        while chunk:
            try:
                content = chunk.decode("utf-8")
                break
            except UnicodeDecodeError as exc:
                if exc.reason != "unexpected end of data":
                    content = chunk.decode("utf-8", errors="replace")
                    break
                chunk = chunk[: exc.start]
        else:
            content = ""
        next_offset = actual_offset + len(chunk)
        truncated = next_offset < len(data)
        return PersonalLibraryDocumentContent(
            document=document,
            content=content,
            offset=actual_offset,
            next_offset=next_offset if truncated else None,
            truncated=truncated,
        )

    async def move(
        self,
        *,
        owner_user_id: UUID,
        document_id: UUID,
        destination_path: str,
        overwrite: bool = False,
        agent_key: str = "default",
    ) -> PersonalLibraryDocument:
        """移动当前用户的资料；写入目标并更新元数据后才移除来源。"""
        agent_id = agent_database_id(agent_key)
        document = await self._repository.get_document(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            document_id=document_id,
        )
        if document is None:
            raise PersonalLibraryNotFound("library_document_not_found")
        source = self._resolve_existing(owner_user_id, agent_id, document.relative_path)
        destination = self._resolve(owner_user_id, agent_id, destination_path)
        if not source.is_file() or source.is_symlink():
            raise PersonalLibraryNotFound("library_document_not_found")
        existing = await self._repository.get_by_path(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            relative_path=destination_path,
        )
        if existing is not None and existing.id != document.id and not overwrite:
            raise PersonalLibraryConflict("library_document_exists")
        if destination.exists() and not overwrite and destination != source:
            raise PersonalLibraryConflict("library_document_exists")
        payload = source.read_bytes()
        self._atomic_write(destination, payload)
        timestamp = datetime.now(UTC)
        moved = PersonalLibraryDocument(
            id=document.id,
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            relative_path=destination_path,
            name=destination.name,
            media_type=document.media_type,
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            created_at=document.created_at,
            updated_at=timestamp,
        )
        try:
            saved = await self._repository.save_document(moved)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if source != destination:
            source.unlink(missing_ok=True)
        return saved

    async def delete(
        self,
        *,
        owner_user_id: UUID,
        document_id: UUID,
        agent_key: str = "default",
    ) -> None:
        """删除当前用户资料库中已登记的一个文件。"""
        agent_id = agent_database_id(agent_key)
        document = await self._repository.get_document(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            document_id=document_id,
        )
        if document is None:
            raise PersonalLibraryNotFound("library_document_not_found")
        target = self._resolve_existing(owner_user_id, agent_id, document.relative_path)
        if not target.is_file() or target.is_symlink():
            raise PersonalLibraryNotFound("library_document_not_found")
        if not await self._repository.delete_document(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            document_id=document_id,
        ):
            raise PersonalLibraryNotFound("library_document_not_found")
        target.unlink()

    async def search_text(
        self, *, owner_user_id: UUID, agent_key: str, query: str, max_results: int = 5
    ) -> list[PersonalLibrarySearchHit]:
        if not 1 <= len(query.strip()) <= 256 or not 1 <= max_results <= 20:
            raise ValueError("invalid_library_search")
        needle = query.strip().casefold()
        terms = [term for term in needle.split() if term]
        hits: list[PersonalLibrarySearchHit] = []
        agent_id = agent_database_id(agent_key)
        for document in await self._repository.list_documents(owner_user_id=owner_user_id, agent_id=agent_id):
            if document.name.rsplit(".", 1)[-1].casefold() not in self._searchable_extensions():
                continue
            folded_path = document.relative_path.casefold()
            path_matches = [
                self._matches_search_term(term, folded_path) for term in terms
            ]
            # 文件名是第一阶段召回：全部查询词都命中文件名时无需先解析正文，
            # 后续 personal_library_read 仍会读取并返回真实文档内容。
            if all(path_matches):
                normalized_query = self._normalized_search_text(needle)
                normalized_path = self._normalized_search_text(folded_path)
                score = 100 + 10 * len(terms)
                if normalized_query and normalized_query in normalized_path:
                    score += 50
                hits.append(
                    PersonalLibrarySearchHit(
                        document=document,
                        excerpt="[按文件名匹配]",
                        score=score,
                    )
                )
                continue
            path = self._resolve_existing(owner_user_id, agent_id, document.relative_path)
            if not path.is_file() or path.is_symlink():
                continue
            try:
                text = self._searchable_payload(path).decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                continue
            folded_text = text.casefold()
            content_matches = [
                self._matches_search_term(term, folded_text) for term in terms
            ]
            if not all(
                path_match or content_match
                for path_match, content_match in zip(
                    path_matches, content_matches, strict=True
                )
            ):
                continue
            exact_content_indexes = [folded_text.find(term) for term in terms]
            content_indexes = [index for index in exact_content_indexes if index >= 0]
            if not content_indexes:
                excerpt = text[:512] if any(content_matches) else "[按文件名匹配]"
            else:
                index = min(content_indexes)
                matching_term = next(
                    term for term in terms if folded_text.find(term) == index
                )
                start = max(0, index - 180)
                end = min(len(text), index + len(matching_term) + 300)
                excerpt = text[start:end][:512]
            score = sum(
                10 for matched in path_matches if matched
            ) + sum(
                max(1, folded_text.count(term))
                for term, matched in zip(terms, content_matches, strict=True)
                if matched
            )
            hits.append(PersonalLibrarySearchHit(document=document, excerpt=excerpt, score=score))
        return sorted(hits, key=lambda hit: (-hit.score, hit.document.relative_path))[:max_results]

    async def reference_documents(self, *, owner_user_id: UUID, agent_key: str):
        """返回当前用户在当前 Agent 下的可读文本目录，包含子目录。"""
        result = []
        agent_id = agent_database_id(agent_key)
        for document in await self._repository.list_documents(owner_user_id=owner_user_id, agent_id=agent_id):
            if Path(document.name).suffix.lower().lstrip(".") not in self._searchable_extensions():
                continue
            try:
                path = self._resolve_existing(owner_user_id, agent_id, document.relative_path)
                if path.is_file() and not path.is_symlink():
                    result.append(document)
            except ValueError:
                continue
        return result

    async def match_prompt_documents(self, *, owner_user_id: UUID, agent_key: str, text: str):
        """仅匹配明确提到的文件名；同名歧义不自动带入。"""
        import unicodedata

        def normalized(value):
            return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())

        prompt = normalized(text)
        groups = {}
        for document in await self.reference_documents(owner_user_id=owner_user_id, agent_key=agent_key):
            name = normalized(Path(document.name).stem)
            if len(name) >= 4 and name in prompt:
                groups.setdefault(name, []).append(document)
        return [items[0] for items in groups.values() if len(items) == 1][:5]

    async def read_text_for_agent(
        self, *, owner_user_id: UUID, agent_key: str, document_id: UUID, offset: int = 0, limit: int = 65_536
    ) -> PersonalLibraryDocumentContent:
        agent_id = agent_database_id(agent_key)
        document = await self._repository.get_document(owner_user_id=owner_user_id, agent_id=agent_id, document_id=document_id)
        if document is None:
            raise PersonalLibraryNotFound("library_document_not_found")
        if document.name.rsplit(".", 1)[-1].casefold() not in self._searchable_extensions():
            raise ValueError("unsupported_library_document_type")
        return await self.read_text(owner_user_id=owner_user_id, agent_key=agent_key, document_id=document_id, offset=offset, limit=limit)

    @staticmethod
    def _searchable_extensions() -> frozenset[str]:
        return SEARCHABLE_EXTENSIONS

    @staticmethod
    def _normalized_search_text(value: str) -> str:
        return "".join(
            char
            for char in unicodedata.normalize("NFKC", value).casefold()
            if char.isalnum()
        )

    @staticmethod
    def _matches_search_term(term: str, haystack: str) -> bool:
        if term in haystack:
            return True
        # 中文产品名常会省略一个修饰词，例如查询“外墙装饰一体化系统”
        # 而资料写作“外墙防水装饰一体化系统”。以相邻双字覆盖率容忍这种
        # 小差异，同时保留所有拉丁字母/数字查询的精确匹配语义。
        if len(term) < 4 or not any("\u4e00" <= char <= "\u9fff" for char in term):
            return False
        pairs = [term[index : index + 2] for index in range(len(term) - 1)]
        matched = sum(pair in haystack for pair in pairs)
        return matched / len(pairs) >= 0.7

    @staticmethod
    def _searchable_payload(path: Path) -> bytes:
        """返回可检索的 UTF-8 内容；原始资料文件保持不变。"""
        return extract_searchable_text(path).encode("utf-8")

    async def copy_from_attachment(
        self,
        *,
        owner_user_id: UUID,
        attachment_id: UUID,
        destination_path: str,
        overwrite: bool = False,
        attachment_repository: AttachmentRepository | None = None,
        agent_key: str = "default",
    ) -> PersonalLibraryDocument:
        """复制当前用户自己的未删除附件，不改变附件生命周期或源文件。"""
        repository = attachment_repository or self._attachment_repository
        if repository is None:
            raise PersonalLibrarySourceDenied("attachment_import_unavailable")
        attachment = await repository.get_attachment(
            attachment_id=attachment_id,
            owner_user_id=owner_user_id,
        )
        if attachment is None or attachment.lifecycle == "deleted":
            raise PersonalLibraryNotFound("attachment_not_found")
        source = self._trusted_attachment_path(attachment)
        return await self._copy_from_source(
            owner_user_id=owner_user_id,
            agent_key=agent_key,
            source=source,
            destination_path=destination_path,
            media_type=attachment.media_type,
            overwrite=overwrite,
        )

    async def copy_from_runtime_file(
        self,
        *,
        owner_user_id: UUID,
        agent_id: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> PersonalLibraryDocument:
        """复制当前用户在指定 Agent 私人运行空间内的文件。"""
        runtime_root = self._runtime_root(owner_user_id=owner_user_id, agent_id=agent_id)
        source = self._resolve_runtime_source(runtime_root, source_path)
        return await self._copy_from_source(
            owner_user_id=owner_user_id,
            agent_key=agent_id,
            source=source,
            destination_path=destination_path,
            media_type=self._media_type_for(source),
            overwrite=overwrite,
        )

    async def copy_from_artifact(
        self,
        *,
        owner_user_id: UUID,
        agent_id: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> PersonalLibraryDocument:
        """仅复制当前用户私人运行空间 artifacts/ 下的产物文件。"""
        runtime_root = self._runtime_root(owner_user_id=owner_user_id, agent_id=agent_id)
        source = self._resolve_runtime_source(runtime_root, source_path)
        relative = source.relative_to(runtime_root).as_posix()
        if not relative.startswith(f"{ARTIFACTS_DIRECTORY}/") and not relative.startswith(
            f"{LEGACY_ARTIFACTS_DIRECTORY}/"
        ):
            raise PersonalLibrarySourceDenied("artifact_source_required")
        return await self._copy_from_source(
            owner_user_id=owner_user_id,
            agent_key=agent_id,
            source=source,
            destination_path=destination_path,
            media_type=self._media_type_for(source),
            overwrite=overwrite,
        )

    async def _copy_from_source(
        self,
        *,
        owner_user_id: UUID,
        agent_key: str,
        source: Path,
        destination_path: str,
        media_type: str,
        overwrite: bool,
    ) -> PersonalLibraryDocument:
        if not source.is_file() or source.is_symlink():
            raise PersonalLibraryNotFound("library_source_not_found")
        agent_id = agent_database_id(agent_key)
        destination = self._resolve(owner_user_id, agent_id, destination_path)
        existing = await self._repository.get_by_path(
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            relative_path=destination_path,
        )
        if (existing is not None or destination.exists()) and not overwrite:
            raise PersonalLibraryConflict("library_document_exists")
        payload = source.read_bytes()
        self._atomic_write(destination, payload)
        timestamp = datetime.now(UTC)
        document = PersonalLibraryDocument(
            id=existing.id if existing is not None else uuid4(),
            owner_user_id=owner_user_id,
            agent_id=agent_id,
            relative_path=destination_path,
            name=destination.name,
            media_type=media_type,
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            created_at=existing.created_at if existing is not None else timestamp,
            updated_at=timestamp,
        )
        try:
            return await self._repository.save_document(document)
        except Exception:
            if existing is None:
                destination.unlink(missing_ok=True)
            raise

    def _trusted_attachment_path(self, attachment: AttachmentRecord) -> Path:
        """将服务端登记的附件位置收窄为一个常规文件。"""
        try:
            source = Path(attachment.storage_key).resolve(strict=True)
        except OSError as exc:
            raise PersonalLibraryNotFound("attachment_not_found") from exc
        if not source.is_file() or source.is_symlink():
            raise PersonalLibraryNotFound("attachment_not_found")
        return source

    def _runtime_root(self, *, owner_user_id: UUID, agent_id: str) -> Path:
        try:
            resolved = WorkspaceResolver(working_dir=self._working_dir).resolve(
                kind=WorkspaceKind.USER_RUNTIME,
                resource_id=agent_id,
                actor_user_id=owner_user_id,
            )
            return WorkspaceResolver(working_dir=self._working_dir).ensure_standard_directories(resolved)
        except ValueError as exc:
            raise PersonalLibrarySourceDenied("invalid_runtime_source") from exc

    @staticmethod
    def _resolve_runtime_source(runtime_root: Path, source_path: str) -> Path:
        try:
            source = resolve_workspace_path(runtime_root, source_path, portable=True)
        except InvalidWorkspacePath as exc:
            raise PersonalLibrarySourceDenied("invalid_runtime_source") from exc
        if not source.is_file() or source.is_symlink():
            raise PersonalLibrarySourceDenied("runtime_source_not_found")
        return source

    @staticmethod
    def _media_type_for(path: Path) -> str:
        suffix = path.suffix.casefold()
        if suffix == ".md":
            return "text/markdown"
        if suffix in {".txt", ".log"}:
            return "text/plain"
        if suffix == ".json":
            return "application/json"
        return "application/octet-stream"

    @staticmethod
    def _atomic_write(target: Path, payload: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(
            f".{target.name}.{secrets.token_hex(8)}.qwenpaw.tmp"
        )
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _resolve(self, owner_user_id: UUID, agent_id: UUID, relative_path: str) -> Path:
        try:
            return self._paths.resolve(
                user_id=owner_user_id,
                agent_id=agent_id,
                relative_path=relative_path,
            )
        except PersonalLibraryPathDenied:
            raise

    def _resolve_existing(self, owner_user_id: UUID, agent_id: UUID, relative_path: str) -> Path:
        """读取旧资料时按需复制到 Agent 私有根，保留原文件用于安全回退。"""
        target = self._resolve(owner_user_id, agent_id, relative_path)
        if target.exists():
            return target
        legacy_root = self._working_dir.resolve() / "user_libraries" / str(owner_user_id)
        try:
            legacy = resolve_workspace_path(legacy_root, relative_path, portable=True)
        except InvalidWorkspacePath:
            return target
        if legacy.is_file() and not legacy.is_symlink():
            self._atomic_write(target, legacy.read_bytes())
        return target
