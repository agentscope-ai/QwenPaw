# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .paths import (
    knowledge_base_root,
    knowledge_document_chunks_path,
    knowledge_document_content_path,
    knowledge_document_dir,
    knowledge_document_meta_path,
    knowledge_documents_dir,
    knowledge_entry_dir,
    knowledge_entry_meta_path,
    knowledge_meta_path,
    legacy_workspace_store_path,
)
from .vector_config import normalize_chunk_config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-")
    return slug.lower() or "knowledge"


def validate_knowledge_id(value: str | None) -> str:
    if not value:
        return uuid.uuid4().hex
    normalized = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9-]{6,32}", normalized):
        raise HTTPException(
            status_code=400,
            detail="Knowledge base ID must contain 6-32 lowercase letters, digits, or hyphens.",
        )
    return normalized


def default_store() -> dict[str, Any]:
    return {"knowledge_bases": []}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read knowledge store: {exc}") from exc


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save knowledge store: {exc}") from exc


def _normalize_chunk(raw_chunk: dict[str, Any], fallback_updated_at: str) -> dict[str, Any]:
    content = str(raw_chunk.get("content") or "")
    created_at = raw_chunk.get("created_at") or fallback_updated_at
    updated_at = raw_chunk.get("updated_at") or created_at
    return {
        "id": str(raw_chunk.get("id") or uuid.uuid4().hex),
        "name": str(raw_chunk.get("name") or "Chunk").strip() or "Chunk",
        "content": content,
        "char_count": int(raw_chunk.get("char_count") or len(content)),
        "enabled": bool(raw_chunk.get("enabled", True)),
        "created_at": created_at,
        "updated_at": updated_at,
        "assets": [asset for asset in (raw_chunk.get("assets") or []) if isinstance(asset, dict)],
        "embedding": [float(value) for value in (raw_chunk.get("embedding") or [])],
    }


def _normalize_document(raw_document: dict[str, Any]) -> dict[str, Any]:
    uploaded_at = raw_document.get("uploaded_at") or utc_now()
    updated_at = raw_document.get("updated_at") or uploaded_at
    content = str(raw_document.get("content") or "")
    chunk_config = raw_document.get("chunk_config") or {}
    chunks = [_normalize_chunk(chunk, uploaded_at) for chunk in (raw_document.get("chunks") or []) if isinstance(chunk, dict)]
    document_enabled = bool(raw_document.get("enabled", True))
    document_status = raw_document.get("status")
    if document_status not in {"processing", "enabled", "disabled", "failed"}:
        document_status = "enabled" if document_enabled else "disabled"
    return {
        "id": str(raw_document.get("id") or uuid.uuid4().hex),
        "name": str(raw_document.get("name") or "Document").strip() or "Document",
        "char_count": int(raw_document.get("char_count") or len(content)),
        "uploaded_at": uploaded_at,
        "updated_at": updated_at,
        "enabled": document_enabled,
        "status": document_status,
        "content": content,
        "chunks": chunks,
        "source_filename": raw_document.get("source_filename") or raw_document.get("name") or "",
        "chunk_config": normalize_chunk_config(chunk_config),
        "vector_model_summary": raw_document.get("vector_model_summary") or {},
        "retrieval_config": raw_document.get("retrieval_config") or {},
        "assets": [asset for asset in (raw_document.get("assets") or []) if isinstance(asset, dict)],
        "error_message": str(raw_document.get("error_message") or "").strip(),
    }


def _normalize_knowledge(raw_item: dict[str, Any]) -> dict[str, Any]:
    knowledge_id = str(raw_item.get("id") or uuid.uuid4().hex)
    name = str(raw_item.get("name") or knowledge_id).strip() or knowledge_id
    created_at = raw_item.get("created_at") or utc_now()
    updated_at = raw_item.get("updated_at") or created_at
    return {
        "id": knowledge_id,
        "name": name,
        "slug": slugify(str(raw_item.get("slug") or name)),
        "enabled": bool(raw_item.get("enabled", True)),
        "created_at": created_at,
        "updated_at": updated_at,
        "documents": [_normalize_document(doc) for doc in (raw_item.get("documents") or []) if isinstance(doc, dict)],
    }


def normalize_knowledge_store(store: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(store, dict):
        return default_store()
    raw_items = store.get("knowledge_bases")
    if not isinstance(raw_items, list):
        return default_store()
    return {"knowledge_bases": [_normalize_knowledge(item) for item in raw_items if isinstance(item, dict)]}


def migrate_legacy_store(workspace_dir: Path) -> None:
    if knowledge_meta_path().exists():
        return
    legacy_path = legacy_workspace_store_path(workspace_dir)
    if not legacy_path.exists():
        return
    legacy_store = _read_json(legacy_path, default_store())
    save_store(workspace_dir, normalize_knowledge_store(legacy_store))


def load_store(workspace_dir: Path) -> dict[str, Any]:
    migrate_legacy_store(workspace_dir)
    meta = _read_json(knowledge_meta_path(), default_store())
    normalized_meta = normalize_knowledge_store(meta)
    store = default_store()
    for raw_knowledge in normalized_meta["knowledge_bases"]:
        knowledge = {**raw_knowledge, "documents": []}
        documents_dir = knowledge_documents_dir(knowledge["id"])
        if documents_dir.exists():
            for document_dir in sorted(child for child in documents_dir.iterdir() if child.is_dir()):
                document_id = document_dir.name
                document_meta = _read_json(knowledge_document_meta_path(knowledge["id"], document_id), {})
                if not isinstance(document_meta, dict):
                    continue
                content_path = knowledge_document_content_path(knowledge["id"], document_id)
                try:
                    content = content_path.read_text(encoding="utf-8") if content_path.exists() else ""
                except OSError as exc:
                    raise HTTPException(status_code=500, detail=f"Failed to read knowledge document content: {exc}") from exc
                chunks = _read_json(knowledge_document_chunks_path(knowledge["id"], document_id), [])
                knowledge["documents"].append(
                    _normalize_document({
                        **document_meta,
                        "content": content,
                        "chunks": chunks,
                    })
                )
        store["knowledge_bases"].append(knowledge)
    return store


def save_store(workspace_dir: Path, store: dict[str, Any]) -> None:
    _ = workspace_dir
    normalized = normalize_knowledge_store(store)
    root = knowledge_base_root()
    root.mkdir(parents=True, exist_ok=True)

    summary_items = []
    expected_kb_ids = set()
    for knowledge in normalized["knowledge_bases"]:
        knowledge_id = knowledge["id"]
        expected_kb_ids.add(knowledge_id)
        summary_items.append({
            "id": knowledge_id,
            "name": knowledge["name"],
            "slug": knowledge["slug"],
            "enabled": knowledge["enabled"],
            "created_at": knowledge["created_at"],
            "updated_at": knowledge["updated_at"],
        })

        _write_json(knowledge_entry_meta_path(knowledge_id), summary_items[-1])
        documents_root = knowledge_documents_dir(knowledge_id)
        documents_root.mkdir(parents=True, exist_ok=True)
        expected_document_ids = set()
        for document in knowledge["documents"]:
            document_id = document["id"]
            expected_document_ids.add(document_id)
            _write_json(
                knowledge_document_meta_path(knowledge_id, document_id),
                {
                    "id": document_id,
                    "name": document["name"],
                    "char_count": document["char_count"],
                    "uploaded_at": document["uploaded_at"],
                    "updated_at": document["updated_at"],
                    "enabled": document["enabled"],
                    "status": document["status"],
                    "source_filename": document["source_filename"],
                    "chunk_config": document["chunk_config"],
                    "vector_model_summary": document["vector_model_summary"],
                    "retrieval_config": document.get("retrieval_config") or {},
                    "assets": document.get("assets") or [],
                    "error_message": document.get("error_message") or "",
                },
            )
            content_path = knowledge_document_content_path(knowledge_id, document_id)
            content_path.parent.mkdir(parents=True, exist_ok=True)
            content_path.write_text(document["content"], encoding="utf-8")
            _write_json(
                knowledge_document_chunks_path(knowledge_id, document_id),
                [
                    {
                        **chunk,
                        "assets": chunk.get("assets") or [],
                    }
                    for chunk in document["chunks"]
                ],
            )

        for existing in documents_root.iterdir() if documents_root.exists() else []:
            if existing.is_dir() and existing.name not in expected_document_ids:
                shutil.rmtree(existing, ignore_errors=True)

    _write_json(knowledge_meta_path(), {"knowledge_bases": summary_items})

    for existing in root.iterdir():
        if not existing.is_dir():
            continue
        if existing.name not in expected_kb_ids:
            shutil.rmtree(existing, ignore_errors=True)


def find_knowledge_base(store: dict[str, Any], knowledge_id: str) -> dict[str, Any]:
    for knowledge in store["knowledge_bases"]:
        if knowledge["id"] == knowledge_id:
            return knowledge
    raise HTTPException(status_code=404, detail="Knowledge base not found.")


def find_document(knowledge: dict[str, Any], document_id: str) -> dict[str, Any]:
    for document in knowledge["documents"]:
        if document["id"] == document_id:
            return document
    raise HTTPException(status_code=404, detail="Knowledge document not found.")


def find_chunk(document: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    for chunk in document["chunks"]:
        if chunk["id"] == chunk_id:
            return chunk
    raise HTTPException(status_code=404, detail="Knowledge chunk not found.")


def build_chunk_summary(chunk: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "id": chunk["id"],
        "index": index,
        "name": chunk["name"],
        "content": chunk["content"],
        "char_count": chunk["char_count"],
        "enabled": chunk["enabled"],
        "status": "enabled" if chunk["enabled"] else "disabled",
        "created_at": chunk.get("created_at") or utc_now(),
        "updated_at": chunk.get("updated_at") or utc_now(),
        "assets": chunk.get("assets") or [],
    }


def build_document_summary(document: dict[str, Any], index: int) -> dict[str, Any]:
    status = document.get("status") or ("enabled" if document["enabled"] else "disabled")
    enabled_chunk_count = sum(1 for chunk in document["chunks"] if chunk.get("enabled", False))
    return {
        "id": document["id"],
        "index": index,
        "name": document["name"],
        "char_count": document["char_count"],
        "uploaded_at": document["uploaded_at"],
        "updated_at": document["updated_at"],
        "status": status,
        "enabled": bool(document["enabled"]),
        "chunk_count": len(document["chunks"]),
        "enabled_chunk_count": enabled_chunk_count,
        "source_filename": document.get("source_filename") or document["name"],
        "chunk_config": document.get("chunk_config") or {},
        "asset_count": len(document.get("assets") or []),
        "retrieval_config": document.get("retrieval_config") or {},
        "error_message": document.get("error_message") or "",
    }


def build_knowledge_summary(knowledge: dict[str, Any], index: int) -> dict[str, Any]:
    enabled_docs = sum(1 for doc in knowledge["documents"] if doc["status"] == "enabled")
    processing_docs = sum(1 for doc in knowledge["documents"] if doc["status"] == "processing")
    return {
        "id": knowledge["id"],
        "index": index,
        "name": knowledge["name"],
        "slug": knowledge["slug"],
        "enabled": knowledge["enabled"],
        "status": "enabled" if knowledge["enabled"] else "disabled",
        "document_count": len(knowledge["documents"]),
        "enabled_document_count": enabled_docs,
        "processing_document_count": processing_docs,
        "created_at": knowledge["created_at"],
        "updated_at": knowledge["updated_at"],
    }


def list_chunks_paginated(document: dict[str, Any], page: int, page_size: int, search: str) -> dict[str, Any]:
    keyword = search.strip().lower()
    source_chunks = document["chunks"]
    if keyword:
        source_chunks = [
            chunk
            for chunk in source_chunks
            if keyword in chunk["name"].lower() or keyword in chunk["content"].lower()
        ]

    total = len(source_chunks)
    safe_page = max(1, page)
    safe_page_size = min(max(1, page_size), 200)
    start = (safe_page - 1) * safe_page_size
    items = source_chunks[start : start + safe_page_size]
    return {
        "items": [build_chunk_summary(chunk, start + index + 1) for index, chunk in enumerate(items)],
        "total": total,
        "page": safe_page,
        "page_size": safe_page_size,
        "has_more": start + safe_page_size < total,
    }