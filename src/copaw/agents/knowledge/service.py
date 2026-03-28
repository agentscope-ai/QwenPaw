# -*- coding: utf-8 -*-
"""Service layer for knowledge import API orchestration."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .chunker import chunk_text
from .exceptions import (
    EmptyParsedContentError,
    UnsupportedFileTypeError,
    UploadNotFoundError,
)
from .models import (
    ParsedDocument,
    FailedKnowledgeImport,
    KnowledgeImportRequest,
    KnowledgeImportResponse,
    SkippedKnowledgeImport,
)
from .normalizer import normalize_document_text
from .parsers import BaseKnowledgeParser, resolve_parsers_for_path
from .repository import KnowledgeRepository


class KnowledgeImportService:
    """Coordinates knowledge import actions."""

    def __init__(
        self,
        workspace_dir: Path,
        media_dir: Path | None = None,
    ):
        self.workspace_dir = Path(workspace_dir).expanduser()
        self.media_dir = (
            Path(media_dir).expanduser()
            if media_dir is not None
            else self.workspace_dir / "media"
        )
        self.repo = KnowledgeRepository(self.workspace_dir)
        self.repo.ensure_dirs()

    async def import_uploads(
        self,
        request: KnowledgeImportRequest,
    ) -> KnowledgeImportResponse:
        """Import uploaded console files into the knowledge workspace."""
        imported = []
        skipped = []
        failed = []
        seen_upload_ids: set[str] = set()
        index = self.repo.load_index()

        for item in request.uploads:
            if item.upload_id in seen_upload_ids:
                skipped.append(
                    SkippedKnowledgeImport(
                        upload_id=item.upload_id,
                        file_name=item.file_name,
                        code="DUPLICATE_UPLOAD_IN_REQUEST",
                        reason="Duplicate upload_id in the same request",
                    ),
                )
                continue
            seen_upload_ids.add(item.upload_id)

            try:
                source_path = self._resolve_upload_path(item.upload_id)
                source_hash = self._hash_bytes(source_path.read_bytes())

                existing_by_source = self.repo.find_doc_by_source_hash(
                    index,
                    source_hash,
                )
                if existing_by_source:
                    skipped.append(
                        SkippedKnowledgeImport(
                            upload_id=item.upload_id,
                            file_name=item.file_name,
                            code="DUPLICATE_SOURCE",
                            reason=(
                                "Source file already imported as "
                                f"{existing_by_source}"
                            ),
                        ),
                    )
                    continue

                parsers = resolve_parsers_for_path(source_path)
                parsed = self._parse_with_fallback(source_path, parsers)
                normalized_text = normalize_document_text(parsed.raw_text)
                if not normalized_text:
                    raise EmptyParsedContentError(
                        "Parsed content is empty after normalization",
                    )

                content_hash = self._hash_text(normalized_text)
                existing_by_content = self.repo.find_doc_by_content_hash(
                    index,
                    content_hash,
                )
                if existing_by_content:
                    skipped.append(
                        SkippedKnowledgeImport(
                            upload_id=item.upload_id,
                            file_name=item.file_name,
                            code="DUPLICATE_CONTENT",
                            reason=(
                                "Equivalent content already imported as "
                                f"{existing_by_content}"
                            ),
                        ),
                    )
                    continue

                chunks = chunk_text(normalized_text)
                imported_doc = self.repo.persist_document(
                    index=index,
                    source_path=source_path,
                    upload_id=item.upload_id,
                    source_file_name=item.file_name,
                    title=parsed.title,
                    source_type=parsed.source_type,
                    normalized_text=normalized_text,
                    chunks=chunks,
                    source_hash=source_hash,
                    content_hash=content_hash,
                )
                imported.append(imported_doc)

            except UploadNotFoundError as exc:
                failed.append(
                    FailedKnowledgeImport(
                        upload_id=item.upload_id,
                        file_name=item.file_name,
                        code="UPLOAD_NOT_FOUND",
                        message=str(exc),
                    ),
                )
            except UnsupportedFileTypeError as exc:
                failed.append(
                    FailedKnowledgeImport(
                        upload_id=item.upload_id,
                        file_name=item.file_name,
                        code="UNSUPPORTED_FILE_TYPE",
                        message=str(exc),
                    ),
                )
            except EmptyParsedContentError as exc:
                failed.append(
                    FailedKnowledgeImport(
                        upload_id=item.upload_id,
                        file_name=item.file_name,
                        code="EMPTY_PARSED_CONTENT",
                        message=str(exc),
                    ),
                )
            except Exception as exc:  # pragma: no cover - guard rail
                failed.append(
                    FailedKnowledgeImport(
                        upload_id=item.upload_id,
                        file_name=item.file_name,
                        code="IMPORT_FAILED",
                        message=str(exc),
                    ),
                )

        self.repo.save_index(index)
        return KnowledgeImportResponse(
            success=len(failed) == 0,
            requested=len(request.uploads),
            imported_count=len(imported),
            skipped_count=len(skipped),
            failed_count=len(failed),
            imported=imported,
            skipped=skipped,
            failed=failed,
        )

    def _resolve_upload_path(self, upload_id: str) -> Path:
        safe_upload_id = Path(upload_id).name
        if safe_upload_id != upload_id:
            raise UploadNotFoundError(
                "upload_id must be a filename without path separators",
            )
        candidate = (self.media_dir / safe_upload_id).resolve()
        media_root = self.media_dir.resolve()
        try:
            candidate.relative_to(media_root)
        except ValueError as exc:
            raise UploadNotFoundError(
                f"upload_id points outside media directory: {upload_id}",
            ) from exc

        if not candidate.exists() or not candidate.is_file():
            raise UploadNotFoundError(
                f"Upload file not found for upload_id: {upload_id}",
            )
        return candidate

    @staticmethod
    def _hash_bytes(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _hash_text(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_with_fallback(
        source_path: Path,
        parsers: tuple[BaseKnowledgeParser, ...],
    ) -> ParsedDocument:
        last_exc: Exception | None = None
        for parser in parsers:
            try:
                return parser.parse(source_path)
            except Exception as exc:  # pragma: no cover - fallback flow
                last_exc = exc
                continue
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("No parser candidates resolved for source path")
