# -*- coding: utf-8 -*-
"""Filesystem helpers for knowledge import workspace layout."""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .chunker import KnowledgeChunk
from .models import ImportedKnowledgeDoc, KnowledgeDocumentSummary

logger = logging.getLogger(__name__)


class KnowledgeRepository:
    """Manages knowledge workspace directories and document listing."""

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self.knowledge_dir = workspace_dir / "knowledge"
        self.memory_dir = workspace_dir / "memory"
        self.raw_dir = self.knowledge_dir / "raw"
        self.docs_dir = self.knowledge_dir / "docs"
        self.chunks_dir = self.knowledge_dir / "chunks"
        self.state_dir = self.knowledge_dir / "state"
        self.index_path = self.state_dir / "index.json"

    def ensure_dirs(self) -> None:
        """Create knowledge workspace directories if missing."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def load_index(self) -> dict[str, Any]:
        """Load knowledge state index."""
        self.ensure_dirs()
        if not self.index_path.exists():
            return {
                "version": 1,
                "updated_at": _utc_now_iso(),
                "documents": {},
                "source_hash_to_doc_id": {},
                "content_hash_to_doc_id": {},
            }

        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning(
                "Failed to load knowledge index from %s, returning default.",
                self.index_path,
                exc_info=True,
            )
            return {
                "version": 1,
                "updated_at": _utc_now_iso(),
                "documents": {},
                "source_hash_to_doc_id": {},
                "content_hash_to_doc_id": {},
            }

        data.setdefault("version", 1)
        data.setdefault("updated_at", _utc_now_iso())
        data.setdefault("documents", {})
        data.setdefault("source_hash_to_doc_id", {})
        data.setdefault("content_hash_to_doc_id", {})
        return data

    def save_index(self, index: dict[str, Any]) -> None:
        """Persist knowledge state index atomically."""
        index["updated_at"] = _utc_now_iso()
        self._write_json(self.index_path, index)

    def find_doc_by_source_hash(
        self,
        index: dict[str, Any],
        source_hash: str,
    ) -> str | None:
        """Find existing doc id by source file hash."""
        return index.get("source_hash_to_doc_id", {}).get(source_hash)

    def find_doc_by_content_hash(
        self,
        index: dict[str, Any],
        content_hash: str,
    ) -> str | None:
        """Find existing doc id by normalized content hash."""
        return index.get("content_hash_to_doc_id", {}).get(content_hash)

    def persist_document(
        self,
        *,
        index: dict[str, Any],
        source_path: Path,
        upload_id: str,
        source_file_name: str,
        title: str,
        source_type: str,
        normalized_text: str,
        chunks: list[KnowledgeChunk],
        source_hash: str,
        content_hash: str,
    ) -> ImportedKnowledgeDoc:
        """Write knowledge document artifacts and update index."""
        self.ensure_dirs()

        doc_id = self._build_doc_id(
            source_file_name=source_file_name,
            source_hash=source_hash,
            documents=index.get("documents", {}),
        )
        safe_file_name = _safe_file_name(source_file_name)
        raw_ext = source_path.suffix.lower()

        raw_path = self.raw_dir / f"{doc_id}_{safe_file_name}"
        if raw_ext and raw_ext not in raw_path.suffixes:
            raw_path = self.raw_dir / f"{doc_id}_{safe_file_name}{raw_ext}"

        markdown_path = self.docs_dir / f"{doc_id}.md"
        chunks_path = self.chunks_dir / f"{doc_id}.json"
        state_path = self.state_dir / f"{doc_id}.json"
        mirror_path = self.memory_dir / f"knowledge__{doc_id}.md"
        imported_at = _utc_now_iso()

        shutil.copyfile(source_path, raw_path)

        markdown_body = self._build_doc_markdown(
            title=title,
            source_file_name=source_file_name,
            source_type=source_type,
            upload_id=upload_id,
            imported_at=imported_at,
            normalized_text=normalized_text,
        )
        mirror_body = self._build_memory_markdown(
            title=title,
            doc_id=doc_id,
            source_file_name=source_file_name,
            source_type=source_type,
            imported_at=imported_at,
            normalized_text=normalized_text,
        )

        markdown_path.write_text(markdown_body, encoding="utf-8")
        mirror_path.write_text(mirror_body, encoding="utf-8")

        chunks_payload = {
            "doc_id": doc_id,
            "source_hash": source_hash,
            "content_hash": content_hash,
            "chunk_count": len(chunks),
            "chunks": chunks,
        }
        self._write_json(chunks_path, chunks_payload)

        state_payload: dict[str, Any] = {
            "doc_id": doc_id,
            "title": title,
            "source_file": source_file_name,
            "source_type": source_type,
            "upload_id": upload_id,
            "imported_at": imported_at,
            "source_hash": source_hash,
            "content_hash": content_hash,
            "chunk_count": len(chunks),
            "paths": {
                "raw": str(raw_path.relative_to(self.workspace_dir)),
                "markdown": str(markdown_path.relative_to(self.workspace_dir)),
                "chunks": str(chunks_path.relative_to(self.workspace_dir)),
                "mirror": str(mirror_path.relative_to(self.workspace_dir)),
            },
        }
        self._write_json(state_path, state_payload)

        documents = index.setdefault("documents", {})
        source_map = index.setdefault("source_hash_to_doc_id", {})
        content_map = index.setdefault("content_hash_to_doc_id", {})
        documents[doc_id] = state_payload
        source_map[source_hash] = doc_id
        content_map[content_hash] = doc_id

        return ImportedKnowledgeDoc(
            doc_id=doc_id,
            file_name=source_file_name,
            source_type=source_type,
            markdown_path=str(markdown_path.relative_to(self.workspace_dir)),
            indexed=True,
        )

    def list_documents(self) -> list[KnowledgeDocumentSummary]:
        """List known knowledge docs from state index (fallback: docs dir)."""
        self.ensure_dirs()
        index = self.load_index()
        documents = index.get("documents", {})
        results: list[KnowledgeDocumentSummary] = []

        for doc_id, meta in documents.items():
            paths = meta.get("paths") or {}
            results.append(
                KnowledgeDocumentSummary(
                    doc_id=doc_id,
                    title=str(meta.get("title") or doc_id),
                    source_file=str(meta.get("source_file") or ""),
                    source_type=str(meta.get("source_type") or "unknown"),
                    imported_at=str(meta.get("imported_at") or ""),
                    markdown_path=str(
                        paths.get("markdown") or f"knowledge/docs/{doc_id}.md",
                    ),
                ),
            )

        if results:
            results.sort(key=lambda item: item.imported_at, reverse=True)
            return results

        # Backward-compatible fallback for old layouts without state index.
        for md_file in sorted(self.docs_dir.glob("*.md")):
            stat = md_file.stat()
            imported_at = (
                datetime.fromtimestamp(
                    stat.st_mtime,
                    tz=timezone.utc,
                )
                .isoformat()
                .replace("+00:00", "Z")
            )
            results.append(
                KnowledgeDocumentSummary(
                    doc_id=md_file.stem,
                    title=md_file.stem,
                    source_file=md_file.name,
                    source_type="md",
                    imported_at=imported_at,
                    markdown_path=str(md_file.relative_to(self.workspace_dir)),
                ),
            )

        return results

    def load_document_chunks(
        self,
        doc_id: str,
        meta: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Load one document's chunk list from knowledge storage.

        Prefer the indexed chunks path when available, then fall back to
        ``knowledge/chunks/{doc_id}.json``.
        """
        self.ensure_dirs()
        candidates: list[Path] = []
        chunk_path = ((meta or {}).get("paths") or {}).get("chunks")
        if isinstance(chunk_path, str) and chunk_path.strip():
            candidates.append(self.workspace_dir / chunk_path)
        candidates.append(self.chunks_dir / f"{doc_id}.json")

        payload: dict[str, Any] | None = None
        for path in candidates:
            if not path.exists() or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                break
            except Exception:
                logger.warning(
                    "Failed to load chunk file %s, skipping.",
                    path,
                    exc_info=True,
                )
                continue

        if not isinstance(payload, dict):
            return []
        chunks = payload.get("chunks")
        if not isinstance(chunks, list):
            return []
        return [item for item in chunks if isinstance(item, dict)]

    def _build_doc_id(
        self,
        *,
        source_file_name: str,
        source_hash: str,
        documents: dict[str, Any],
    ) -> str:
        stem = _safe_doc_stem(Path(source_file_name).stem)
        base = f"{stem}-{source_hash[:12]}"
        if base not in documents:
            return base

        suffix = 2
        while True:
            candidate = f"{base}-{suffix}"
            if candidate not in documents:
                return candidate
            suffix += 1

    def _build_doc_markdown(
        self,
        *,
        title: str,
        source_file_name: str,
        source_type: str,
        upload_id: str,
        imported_at: str,
        normalized_text: str,
    ) -> str:
        metadata = [
            f"# {title}",
            "",
            f"- Source file: `{source_file_name}`",
            f"- Source type: `{source_type}`",
            f"- Upload id: `{upload_id}`",
            f"- Imported at (UTC): `{imported_at}`",
            "",
            "---",
            "",
        ]
        body = normalized_text.strip()
        return "\n".join(metadata) + (f"{body}\n" if body else "")

    def _build_memory_markdown(
        self,
        *,
        title: str,
        doc_id: str,
        source_file_name: str,
        source_type: str,
        imported_at: str,
        normalized_text: str,
    ) -> str:
        metadata = [
            f"# Knowledge Memory: {title}",
            "",
            f"- Doc id: `{doc_id}`",
            f"- Source file: `{source_file_name}`",
            f"- Source type: `{source_type}`",
            f"- Imported at (UTC): `{imported_at}`",
            f"- Canonical doc: `knowledge/docs/{doc_id}.md`",
            "",
            "---",
            "",
        ]
        body = normalized_text.strip()
        return "\n".join(metadata) + (f"{body}\n" if body else "")

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        shutil.move(str(tmp_path), str(path))


def _safe_doc_stem(stem: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-_").lower()
    return (cleaned or "document")[:48]


def _safe_file_name(name: str) -> str:
    base = Path(name).name if name else "file"
    cleaned = re.sub(r"[^\w.\-]", "_", base).strip("._")
    return cleaned or "file"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
