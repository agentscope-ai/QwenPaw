# -*- coding: utf-8 -*-
"""Knowledge base API."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from ..agent_context import get_agent_for_request
from ..knowledge import (
    DEFAULT_CHUNK_CONFIG,
    build_document_summary,
    build_knowledge_summary,
    chunk_text_with_model,
    delete_document_assets,
    delete_knowledge_assets,
    embed_texts,
    extract_upload_payload,
    find_chunk,
    find_document,
    find_knowledge_base,
    get_upload_capabilities,
    has_usable_embedding_model,
    list_chunks_paginated,
    load_knowledge_vector_config,
    load_soul_knowledge_config,
    load_store,
    normalize_chunk_config,
    normalize_retrieval_config,
    save_knowledge_vector_config,
    save_soul_knowledge_config,
    save_store,
    utc_now,
    validate_knowledge_id,
)


router = APIRouter(prefix="/workspace/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)


async def _process_uploaded_document(
    *,
    workspace_dir: Any,
    agent_id: str,
    knowledge_id: str,
    document_id: str,
    payload: dict[str, Any],
    chunk_config: dict[str, Any],
    retrieval_config: dict[str, Any],
    vector_model_summary: dict[str, Any],
) -> None:
    try:
        now = utc_now()
        vector_config = load_knowledge_vector_config(agent_id, include_secret=True)
        embedding_model_config = vector_config["embedding_model_config"]
        chunks = [
            {
                **chunk,
                "created_at": now,
                "updated_at": now,
            }
            for chunk in await chunk_text_with_model(
                payload["content"],
                chunk_config,
                agent_id=agent_id,
                assets=payload["assets"],
                fallback_to_heuristic=False,
                embedding_guided=(
                    retrieval_config["indexing_technique"] == "high_quality"
                    and has_usable_embedding_model(embedding_model_config)
                ),
                embedding_model_config=embedding_model_config if (
                    retrieval_config["indexing_technique"] == "high_quality"
                    and has_usable_embedding_model(embedding_model_config)
                ) else None,
            )
        ]
        if not chunks:
            raise RuntimeError("No chunkable content found.")

        if retrieval_config["indexing_technique"] == "high_quality":
            if not has_usable_embedding_model(embedding_model_config):
                raise RuntimeError(
                    "A usable vector model must be configured before uploading knowledge documents.",
                )
            embeddings = embed_texts(
                embedding_model_config,
                [chunk["content"] for chunk in chunks],
            )
            for chunk, embedding in zip(chunks, embeddings):
                chunk["embedding"] = embedding

        store = load_store(workspace_dir)
        knowledge = find_knowledge_base(store, knowledge_id)
        document = find_document(knowledge, document_id)
        document["chunks"] = chunks
        document["char_count"] = len(payload["content"])
        document["enabled"] = True
        document["status"] = "enabled"
        document["updated_at"] = utc_now()
        document["vector_model_summary"] = vector_model_summary
        document["error_message"] = ""
        knowledge["updated_at"] = document["updated_at"]
        save_store(workspace_dir, store)
    except Exception as exc:
        logger.exception(
            "Knowledge document processing failed: knowledge_id=%s document_id=%s",
            knowledge_id,
            document_id,
        )
        store = load_store(workspace_dir)
        knowledge = find_knowledge_base(store, knowledge_id)
        document = find_document(knowledge, document_id)
        document["chunks"] = []
        document["enabled"] = False
        document["status"] = "failed"
        document["updated_at"] = utc_now()
        document["error_message"] = str(exc)
        knowledge["updated_at"] = document["updated_at"]
        save_store(workspace_dir, store)


class ChunkUpdateRequest(BaseModel):
    name: str | None = None
    content: str | None = None
    enabled: bool | None = None


class DocumentUpdateRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    id: str | None = Field(default=None, max_length=32)


class KnowledgeBaseUpdateRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None


class KnowledgeReferenceItem(BaseModel):
    id: str
    priority: int = 1
    trigger: str = "always"
    retrieval_top_k: int = 3
    usage_rule: str = ""
    keywords: list[str] = Field(default_factory=list)


class KnowledgeConfigUpdateRequest(BaseModel):
    items: list[KnowledgeReferenceItem] = Field(default_factory=list)


class KnowledgeVectorConfigRequest(BaseModel):
    embedding_model_config: dict[str, Any] = Field(default_factory=dict)
    default_chunk_config: dict[str, Any] = Field(default_factory=dict)
    retrieval_config: dict[str, Any] = Field(default_factory=dict)


@router.get("")
async def list_knowledge_bases(request: Request) -> dict:
    workspace = await get_agent_for_request(request)
    store = load_store(workspace.workspace_dir)
    items = [
        build_knowledge_summary(knowledge, index + 1)
        for index, knowledge in enumerate(store["knowledge_bases"])
    ]
    return {"items": items}


@router.post("")
async def create_knowledge_base(payload: KnowledgeBaseCreateRequest, request: Request) -> dict:
    from fastapi import HTTPException

    workspace = await get_agent_for_request(request)
    store = load_store(workspace.workspace_dir)
    name = payload.name.strip()
    knowledge_id = validate_knowledge_id(payload.id)

    if any(item["id"] == knowledge_id for item in store["knowledge_bases"]):
        raise HTTPException(status_code=400, detail="Knowledge base ID already exists.")
    if any(item["name"] == name for item in store["knowledge_bases"]):
        raise HTTPException(status_code=400, detail="Knowledge base already exists.")

    knowledge = {
        "id": knowledge_id,
        "name": name,
        "slug": name.lower().replace(" ", "-"),
        "enabled": True,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "documents": [],
    }
    store["knowledge_bases"].append(knowledge)
    save_store(workspace.workspace_dir, store)
    return {"item": build_knowledge_summary(knowledge, len(store["knowledge_bases"]))}


@router.get("/upload-capabilities")
async def get_upload_options(request: Request) -> dict:
    workspace = await get_agent_for_request(request)
    return get_upload_capabilities(workspace.agent_id)


@router.get("/vector-config")
async def get_vector_config(request: Request) -> dict:
    workspace = await get_agent_for_request(request)
    return load_knowledge_vector_config(workspace.agent_id)


@router.put("/vector-config")
async def update_vector_config(payload: KnowledgeVectorConfigRequest, request: Request) -> dict:
    workspace = await get_agent_for_request(request)
    return save_knowledge_vector_config(workspace.agent_id, payload.model_dump())


@router.get("/config")
async def get_knowledge_config(request: Request) -> dict:
    workspace = await get_agent_for_request(request)
    return load_soul_knowledge_config(workspace.workspace_dir)


@router.put("/config")
async def update_knowledge_config(payload: KnowledgeConfigUpdateRequest, request: Request) -> dict:
    workspace = await get_agent_for_request(request)
    return save_soul_knowledge_config(
        workspace.workspace_dir,
        [item.model_dump() for item in payload.items],
    )


@router.get("/{knowledge_id}")
async def get_knowledge_base(knowledge_id: str, request: Request) -> dict:
    workspace = await get_agent_for_request(request)
    store = load_store(workspace.workspace_dir)
    knowledge = find_knowledge_base(store, knowledge_id)
    documents = [
        build_document_summary(document, index + 1)
        for index, document in enumerate(knowledge["documents"])
    ]
    return {
        "item": build_knowledge_summary(knowledge, store["knowledge_bases"].index(knowledge) + 1),
        "documents": documents,
    }


@router.put("/{knowledge_id}")
async def update_knowledge_base(knowledge_id: str, payload: KnowledgeBaseUpdateRequest, request: Request) -> dict:
    from fastapi import HTTPException

    workspace = await get_agent_for_request(request)
    store = load_store(workspace.workspace_dir)
    knowledge = find_knowledge_base(store, knowledge_id)

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Knowledge base name is required.")
        if any(item["name"] == name and item["id"] != knowledge_id for item in store["knowledge_bases"]):
            raise HTTPException(status_code=400, detail="Knowledge base already exists.")
        knowledge["name"] = name
        knowledge["slug"] = name.lower().replace(" ", "-")

    if payload.enabled is not None:
        knowledge["enabled"] = payload.enabled

    knowledge["updated_at"] = utc_now()
    save_store(workspace.workspace_dir, store)
    return {"item": build_knowledge_summary(knowledge, store["knowledge_bases"].index(knowledge) + 1)}


@router.delete("/{knowledge_id}")
async def delete_knowledge_base(knowledge_id: str, request: Request) -> dict:
    workspace = await get_agent_for_request(request)
    store = load_store(workspace.workspace_dir)
    knowledge = find_knowledge_base(store, knowledge_id)
    store["knowledge_bases"] = [item for item in store["knowledge_bases"] if item["id"] != knowledge_id]
    save_store(workspace.workspace_dir, store)
    delete_knowledge_assets(knowledge_id)
    return {"deleted": True, "name": knowledge["name"]}


@router.post("/{knowledge_id}/documents/upload")
async def upload_document(
    knowledge_id: str,
    request: Request,
    file: UploadFile = File(...),
    indexing_technique: str = Form("high_quality"),
    search_method: str = Form("hybrid"),
    top_k: int = Form(3),
    score_threshold_enabled: bool = Form(False),
    score_threshold: float = Form(0.0),
    reranking_enable: bool = Form(False),
    vector_weight: float = Form(0.7),
    keyword_weight: float = Form(0.3),
    mode: str = Form(DEFAULT_CHUNK_CONFIG["mode"]),
    granularity: str = Form(DEFAULT_CHUNK_CONFIG["granularity"]),
    separator: str = Form(DEFAULT_CHUNK_CONFIG["separator"]),
    normalize_whitespace: bool = Form(DEFAULT_CHUNK_CONFIG["normalize_whitespace"]),
    llm_grouping: bool = Form(DEFAULT_CHUNK_CONFIG["llm_grouping"]),
    chunk_size: int = Form(DEFAULT_CHUNK_CONFIG["chunk_size"]),
    chunk_overlap: int = Form(DEFAULT_CHUNK_CONFIG["chunk_overlap"]),
    parent_separator: str = Form(DEFAULT_CHUNK_CONFIG["parent_separator"]),
    parent_normalize_whitespace: bool = Form(
        DEFAULT_CHUNK_CONFIG["parent_normalize_whitespace"],
    ),
    parent_chunk_size: int = Form(DEFAULT_CHUNK_CONFIG["parent_chunk_size"]),
    parent_chunk_overlap: int = Form(DEFAULT_CHUNK_CONFIG["parent_chunk_overlap"]),
    child_separator: str = Form(DEFAULT_CHUNK_CONFIG["child_separator"]),
    child_normalize_whitespace: bool = Form(
        DEFAULT_CHUNK_CONFIG["child_normalize_whitespace"],
    ),
    child_chunk_size: int = Form(DEFAULT_CHUNK_CONFIG["child_chunk_size"]),
    child_chunk_overlap: int = Form(DEFAULT_CHUNK_CONFIG["child_chunk_overlap"]),
) -> dict:
    from fastapi import HTTPException

    workspace = await get_agent_for_request(request)
    store = load_store(workspace.workspace_dir)
    knowledge = find_knowledge_base(store, knowledge_id)

    capabilities = get_upload_capabilities(workspace.agent_id)
    if not capabilities["can_upload"]:
        raise HTTPException(status_code=400, detail="A usable vector model must be configured before uploading knowledge documents.")

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    document_id = uuid.uuid4().hex
    payload = extract_upload_payload(file, raw_bytes, knowledge_id, document_id, chunk_size)
    retrieval_config = normalize_retrieval_config(
        {
            "indexing_technique": indexing_technique,
            "search_method": search_method,
            "top_k": top_k,
            "score_threshold_enabled": score_threshold_enabled,
            "score_threshold": score_threshold,
            "reranking_enable": reranking_enable,
            "weights": {
                "vector_weight": vector_weight,
                "keyword_weight": keyword_weight,
            },
        }
    )
    chunk_config = normalize_chunk_config(
        {
            "mode": mode,
            "granularity": granularity,
            "separator": separator,
            "normalize_whitespace": normalize_whitespace,
            "llm_grouping": llm_grouping,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "parent_separator": parent_separator,
            "parent_normalize_whitespace": parent_normalize_whitespace,
            "parent_chunk_size": parent_chunk_size,
            "parent_chunk_overlap": parent_chunk_overlap,
            "child_separator": child_separator,
            "child_normalize_whitespace": child_normalize_whitespace,
            "child_chunk_size": child_chunk_size,
            "child_chunk_overlap": child_chunk_overlap,
        },
        retrieval_config["indexing_technique"],
    )
    now = utc_now()
    document = {
        "id": document_id,
        "name": file.filename or f"document-{uuid.uuid4().hex[:8]}",
        "char_count": len(payload["content"]),
        "uploaded_at": now,
        "updated_at": now,
        "enabled": False,
        "status": "processing",
        "content": payload["content"],
        "chunks": [],
        "source_filename": file.filename or "",
        "chunk_config": chunk_config,
        "vector_model_summary": capabilities["vector_model"],
        "retrieval_config": retrieval_config,
        "assets": payload["assets"],
        "error_message": "",
    }
    knowledge["documents"].append(document)
    knowledge["updated_at"] = now
    save_store(workspace.workspace_dir, store)

    asyncio.create_task(
        _process_uploaded_document(
            workspace_dir=workspace.workspace_dir,
            agent_id=workspace.agent_id,
            knowledge_id=knowledge_id,
            document_id=document_id,
            payload=payload,
            chunk_config=chunk_config,
            retrieval_config=retrieval_config,
            vector_model_summary=capabilities["vector_model"],
        )
    )
    return {"document": build_document_summary(document, len(knowledge["documents"]))}


@router.put("/{knowledge_id}/documents/{document_id}")
async def update_document(knowledge_id: str, document_id: str, payload: DocumentUpdateRequest, request: Request) -> dict:
    from fastapi import HTTPException

    workspace = await get_agent_for_request(request)
    store = load_store(workspace.workspace_dir)
    knowledge = find_knowledge_base(store, knowledge_id)
    document = find_document(knowledge, document_id)

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Document name is required.")
        document["name"] = name

    if payload.enabled is not None and document.get("status") not in {"processing", "failed"}:
        document["enabled"] = payload.enabled
        document["status"] = "enabled" if payload.enabled else "disabled"

    document["updated_at"] = utc_now()
    knowledge["updated_at"] = utc_now()
    save_store(workspace.workspace_dir, store)
    return {"document": build_document_summary(document, knowledge["documents"].index(document) + 1)}


@router.delete("/{knowledge_id}/documents/{document_id}")
async def delete_document(knowledge_id: str, document_id: str, request: Request) -> dict:
    workspace = await get_agent_for_request(request)
    store = load_store(workspace.workspace_dir)
    knowledge = find_knowledge_base(store, knowledge_id)
    document = find_document(knowledge, document_id)
    knowledge["documents"] = [item for item in knowledge["documents"] if item["id"] != document_id]
    knowledge["updated_at"] = utc_now()
    save_store(workspace.workspace_dir, store)
    delete_document_assets(knowledge_id, document_id)
    return {"deleted": True, "name": document["name"]}


@router.get("/{knowledge_id}/documents/{document_id}/chunks")
async def list_chunks(knowledge_id: str, document_id: str, request: Request, page: int = 1, page_size: int = 20, search: str = "") -> dict:
    workspace = await get_agent_for_request(request)
    store = load_store(workspace.workspace_dir)
    knowledge = find_knowledge_base(store, knowledge_id)
    document = find_document(knowledge, document_id)
    return list_chunks_paginated(document, page, page_size, search)


@router.put("/{knowledge_id}/documents/{document_id}/chunks/{chunk_id}")
async def update_chunk(knowledge_id: str, document_id: str, chunk_id: str, payload: ChunkUpdateRequest, request: Request) -> dict:
    from fastapi import HTTPException

    workspace = await get_agent_for_request(request)
    store = load_store(workspace.workspace_dir)
    knowledge = find_knowledge_base(store, knowledge_id)
    document = find_document(knowledge, document_id)
    chunk = find_chunk(document, chunk_id)

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Chunk name is required.")
        chunk["name"] = name
    if payload.content is not None:
        content = payload.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="Chunk content is required.")
        chunk["content"] = content
        chunk["char_count"] = len(content)
        vector_config = load_knowledge_vector_config(workspace.agent_id, include_secret=True)
        retrieval_config = vector_config["retrieval_config"]
        if retrieval_config["indexing_technique"] == "high_quality":
            try:
                embeddings = embed_texts(vector_config["embedding_model_config"], [content])
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Failed to refresh chunk embedding: {exc}") from exc
            chunk["embedding"] = embeddings[0] if embeddings else []
    if payload.enabled is not None:
        chunk["enabled"] = payload.enabled

    chunk["updated_at"] = utc_now()
    document["updated_at"] = utc_now()
    document["char_count"] = sum(item["char_count"] for item in document["chunks"])
    knowledge["updated_at"] = utc_now()
    save_store(workspace.workspace_dir, store)
    return {
        "chunk": {
            **find_chunk(document, chunk_id),
            "index": document["chunks"].index(chunk) + 1,
            "status": "enabled" if chunk["enabled"] else "disabled",
        },
    }


@router.delete("/{knowledge_id}/documents/{document_id}/chunks/{chunk_id}")
async def delete_chunk(knowledge_id: str, document_id: str, chunk_id: str, request: Request) -> dict:
    workspace = await get_agent_for_request(request)
    store = load_store(workspace.workspace_dir)
    knowledge = find_knowledge_base(store, knowledge_id)
    document = find_document(knowledge, document_id)
    chunk = find_chunk(document, chunk_id)
    document["chunks"] = [item for item in document["chunks"] if item["id"] != chunk_id]
    document["updated_at"] = utc_now()
    document["char_count"] = sum(item["char_count"] for item in document["chunks"])
    knowledge["updated_at"] = utc_now()
    save_store(workspace.workspace_dir, store)
    return {"deleted": True, "name": chunk["name"]}
