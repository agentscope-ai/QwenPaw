# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import io
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from types import SimpleNamespace

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from ...config import load_config, save_config
from ...config.config import KnowledgeConfig, KnowledgeSourceSpec, load_agent_config, save_agent_config
from ...constant import WORKING_DIR
from ...knowledge import GraphOpsManager, KnowledgeManager
from ...knowledge.module_skills import sync_knowledge_module_skills
from ..agent_context import get_agent_for_request

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _ensure_knowledge_enabled_flag(enabled: bool) -> None:
    if not bool(enabled):
        raise HTTPException(status_code=400, detail="KNOWLEDGE_DISABLED")


def _zip_path(path) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(path.rglob("*")):
            arcname = entry.relative_to(path).as_posix()
            if entry.is_file():
                zf.write(entry, arcname)
            elif entry.is_dir():
                zf.write(entry, arcname + "/")
    buf.seek(0)
    return buf


def _validate_zip_data(data: bytes) -> None:
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is not a valid zip archive",
        )
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            p = Path(name)
            if p.is_absolute() or ".." in p.parts:
                raise HTTPException(
                    status_code=400,
                    detail=f"Zip contains unsafe path: {name}",
                )


def _extract_zip_to_temp(data: bytes) -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix="copaw_knowledge_import_"))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(tmp_dir)
    return tmp_dir


def _detect_extract_root(tmp_dir: Path) -> Path:
    entries = [entry for entry in tmp_dir.iterdir() if not entry.name.startswith(".__")]
    if len(entries) == 1 and entries[0].is_dir() and (entries[0] / "sources").exists():
        return entries[0]
    return tmp_dir


def _clamp_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int((value or "").strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _manager() -> KnowledgeManager:
    return KnowledgeManager(WORKING_DIR)


def _manager_for_workspace(workspace_dir: Path | str) -> KnowledgeManager:
    return KnowledgeManager(workspace_dir)


def _effective_knowledge_config(
    knowledge_config: KnowledgeConfig,
    running_config,
) -> KnowledgeConfig:
    """Build request-scoped effective knowledge config.

    Runtime flags that are now agent-specific are projected from running config,
    while structural knowledge settings remain in root config.knowledge.
    """
    effective = knowledge_config.model_copy(deep=True)
    effective.enabled = bool(getattr(running_config, "knowledge_enabled", effective.enabled))
    effective.automation.knowledge_auto_collect_chat_files = bool(
        getattr(
            running_config,
            "knowledge_auto_collect_chat_files",
            effective.automation.knowledge_auto_collect_chat_files,
        ),
    )
    effective.automation.knowledge_auto_collect_chat_urls = bool(
        getattr(
            running_config,
            "knowledge_auto_collect_chat_urls",
            effective.automation.knowledge_auto_collect_chat_urls,
        ),
    )
    effective.automation.knowledge_auto_collect_long_text = bool(
        getattr(
            running_config,
            "knowledge_auto_collect_long_text",
            effective.automation.knowledge_auto_collect_long_text,
        ),
    )
    effective.automation.knowledge_long_text_min_chars = int(
        getattr(
            running_config,
            "knowledge_long_text_min_chars",
            effective.automation.knowledge_long_text_min_chars,
        ),
    )
    effective.index.chunk_size = int(
        getattr(
            running_config,
            "knowledge_chunk_size",
            effective.index.chunk_size,
        ),
    )
    return effective


async def _resolve_knowledge_request_context(request: Request | None):
    """Resolve root config + optional agent-scoped runtime/workspace context."""
    config = load_config()
    running_config = config.agents.running
    workspace_dir = WORKING_DIR
    agent_id: str | None = None

    if request is not None:
        try:
            workspace = await get_agent_for_request(request)
            running_config = workspace.config.running
            workspace_dir = workspace.workspace_dir
            agent_id = workspace.agent_id
        except HTTPException:
            # Backward compatibility for tests/legacy call sites without
            # initialized MultiAgentManager.
            pass

    knowledge_config = _effective_knowledge_config(config.knowledge, running_config)
    return config, knowledge_config, running_config, workspace_dir, agent_id


async def _resolve_knowledge_ws_context(websocket: WebSocket):
    """Resolve workspace for websocket calls using header/active agent fallback."""
    config = load_config()
    running_config = config.agents.running
    workspace_dir = WORKING_DIR
    agent_id = (
        websocket.headers.get("X-Agent-Id")
        or config.agents.active_agent
        or "default"
    )
    manager = getattr(websocket.app.state, "multi_agent_manager", None)
    if manager is not None:
        try:
            workspace = await manager.get_agent(agent_id)
            if workspace is not None:
                running_config = workspace.config.running
                workspace_dir = workspace.workspace_dir
        except Exception:
            pass

    knowledge_config = _effective_knowledge_config(config.knowledge, running_config)
    return config, knowledge_config, running_config, workspace_dir


def _find_source(config: KnowledgeConfig, source_id: str) -> Optional[KnowledgeSourceSpec]:
    for source in config.sources:
        if source.id == source_id:
            return source
    return None


@router.get("/config", response_model=KnowledgeConfig)
async def get_knowledge_config(request: Request) -> KnowledgeConfig:
    _, effective_knowledge, _, _, _ = await _resolve_knowledge_request_context(request)
    return effective_knowledge


@router.put("/config", response_model=KnowledgeConfig)
async def put_knowledge_config(
    request: Request,
    knowledge_config: KnowledgeConfig = Body(...),
) -> KnowledgeConfig:
    config, _, running_config, _, agent_id = await _resolve_knowledge_request_context(request)
    previous_enabled = bool(
        getattr(running_config, "knowledge_enabled", config.knowledge.enabled)
    )

    # Persist structural knowledge config in root config.
    config.knowledge = knowledge_config

    # Runtime knowledge toggles belong to the current agent in multi-agent mode.
    running_config.knowledge_enabled = knowledge_config.enabled
    running_config.knowledge_auto_collect_chat_files = (
        knowledge_config.automation.knowledge_auto_collect_chat_files
    )
    running_config.knowledge_auto_collect_chat_urls = (
        knowledge_config.automation.knowledge_auto_collect_chat_urls
    )
    running_config.knowledge_auto_collect_long_text = (
        knowledge_config.automation.knowledge_auto_collect_long_text
    )
    running_config.knowledge_long_text_min_chars = (
        knowledge_config.automation.knowledge_long_text_min_chars
    )
    running_config.knowledge_chunk_size = knowledge_config.index.chunk_size

    # Keep deprecated root automation fields in sync for backward compatibility.
    config.knowledge.enabled = running_config.knowledge_enabled
    config.knowledge.automation.knowledge_auto_collect_chat_files = (
        running_config.knowledge_auto_collect_chat_files
    )
    config.knowledge.automation.knowledge_auto_collect_chat_urls = (
        running_config.knowledge_auto_collect_chat_urls
    )
    config.knowledge.automation.knowledge_auto_collect_long_text = (
        running_config.knowledge_auto_collect_long_text
    )
    config.knowledge.automation.knowledge_long_text_min_chars = (
        running_config.knowledge_long_text_min_chars
    )
    config.knowledge.index.chunk_size = running_config.knowledge_chunk_size

    if agent_id:
        agent_config = load_agent_config(agent_id)
        agent_config.running = running_config
        save_agent_config(agent_id, agent_config)
    else:
        config.agents.running = running_config

    if previous_enabled != knowledge_config.enabled:
        sync_knowledge_module_skills(knowledge_config.enabled)
    save_config(config)
    return _effective_knowledge_config(config.knowledge, running_config)


@router.get("/sources")
async def list_sources(request: Request):
    _, knowledge_config, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    manager = _manager_for_workspace(workspace_dir)
    return {
        "enabled": bool(knowledge_config.enabled),
        "sources": manager.list_sources(knowledge_config),
    }


@router.put("/sources", response_model=KnowledgeSourceSpec)
async def upsert_source(
    request: Request,
    source: KnowledgeSourceSpec = Body(...),
) -> KnowledgeSourceSpec:
    config, knowledge_config, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    manager = _manager_for_workspace(workspace_dir)
    source = manager.normalize_source_name(source, knowledge_config)
    existing = _find_source(config.knowledge, source.id)
    if existing is None:
        config.knowledge.sources.append(source)
    else:
        index = config.knowledge.sources.index(existing)
        config.knowledge.sources[index] = source
    save_config(config)
    return source


@router.post("/upload/file")
async def upload_knowledge_file(
    request: Request,
    source_id: str = Form(...),
    file: UploadFile = File(...),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    _, _, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    saved_path = _manager_for_workspace(workspace_dir).save_uploaded_file(
        source_id=source_id,
        filename=file.filename or "knowledge-upload",
        data=data,
    )
    return {
        "location": str(saved_path),
        "filename": saved_path.name,
    }


@router.post("/upload/directory")
async def upload_knowledge_directory(
    request: Request,
    source_id: str = Form(...),
    relative_paths: list[str] = Form(...),
    files: list[UploadFile] = File(...),
):
    if len(files) != len(relative_paths):
        raise HTTPException(
            status_code=400,
            detail="files and relative_paths length mismatch",
        )
    saved_pairs = []
    for relative_path, upload in zip(relative_paths, files):
        saved_pairs.append((relative_path, await upload.read()))
    _, _, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    saved_root = _manager_for_workspace(workspace_dir).save_uploaded_directory(source_id, saved_pairs)
    return {
        "location": str(saved_root),
        "file_count": len(saved_pairs),
    }


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, request: Request):
    config, knowledge_config, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    _ensure_knowledge_enabled_flag(knowledge_config.enabled)
    source = _find_source(config.knowledge, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="KNOWLEDGE_SOURCE_NOT_FOUND")
    config.knowledge.sources = [
        item for item in config.knowledge.sources if item.id != source_id
    ]
    save_config(config)
    _manager_for_workspace(workspace_dir).delete_index(source_id)
    return {"deleted": True, "source_id": source_id}


@router.delete("/clear")
async def clear_knowledge(
    request: Request,
    confirm: bool = Query(default=False),
    remove_sources: bool = Query(default=True),
):
    """Clear all persisted knowledge data and optionally remove source configs."""
    if not confirm:
        raise HTTPException(status_code=400, detail="KNOWLEDGE_CLEAR_CONFIRM_REQUIRED")

    config, knowledge_config, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    _ensure_knowledge_enabled_flag(knowledge_config.enabled)
    result = _manager_for_workspace(workspace_dir).clear_knowledge(
        config.knowledge,
        remove_sources=remove_sources,
    )
    save_config(config)
    return result


@router.post("/sources/{source_id}/index")
async def index_source(source_id: str, request: Request):
    config, knowledge_config, running_config, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    _ensure_knowledge_enabled_flag(knowledge_config.enabled)
    source = _find_source(config.knowledge, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="KNOWLEDGE_SOURCE_NOT_FOUND")
    try:
        result = _manager_for_workspace(workspace_dir).index_source(
            source,
            config.knowledge,
            running_config,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@router.get("/sources/{source_id}/content")
async def get_source_content(source_id: str, request: Request):
    config, _, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    source = _find_source(config.knowledge, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="KNOWLEDGE_SOURCE_NOT_FOUND")
    return _manager_for_workspace(workspace_dir).get_source_documents(source_id)


@router.post("/index")
async def index_all_sources(request: Request):
    config, knowledge_config, running_config, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    _ensure_knowledge_enabled_flag(knowledge_config.enabled)
    try:
        return _manager_for_workspace(workspace_dir).index_all(config.knowledge, running_config)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/search")
async def search_knowledge(
    request: Request,
    q: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    source_ids: Optional[str] = Query(default=None),
    source_types: Optional[str] = Query(default=None),
):
    config, knowledge_config, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    _ensure_knowledge_enabled_flag(knowledge_config.enabled)
    ids = [item for item in (source_ids or "").split(",") if item]
    types = [item for item in (source_types or "").split(",") if item]
    return _manager_for_workspace(workspace_dir).search(
        query=q,
        config=config.knowledge,
        limit=limit,
        source_ids=ids or None,
        source_types=types or None,
    )


@router.get("/history-backfill/status")
async def get_history_backfill_status(request: Request):
    """Get history backfill status for knowledge enable flow and CTA display."""
    _, _, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    return _manager_for_workspace(workspace_dir).history_backfill_status()


@router.post("/history-backfill/run")
async def run_history_backfill_now(request: Request):
    """Run history backfill immediately regardless of runtime auto-backfill toggle."""
    config, knowledge_config, running, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    _ensure_knowledge_enabled_flag(knowledge_config.enabled)
    manager = _manager_for_workspace(workspace_dir)
    force_running = SimpleNamespace(
        knowledge_auto_collect_chat_files=running.knowledge_auto_collect_chat_files,
        knowledge_auto_collect_chat_urls=running.knowledge_auto_collect_chat_urls,
        knowledge_auto_collect_long_text=running.knowledge_auto_collect_long_text,
        knowledge_long_text_min_chars=running.knowledge_long_text_min_chars,
        knowledge_chunk_size=running.knowledge_chunk_size,
    )
    result = await asyncio.to_thread(
        manager.auto_backfill_history_data,
        knowledge_config,
        force_running,
    )
    if result.get("changed"):
        save_config(config)
    return {
        "result": result,
        "status": manager.history_backfill_status(),
    }


@router.get("/memify/jobs/{job_id}")
async def get_memify_job_status(job_id: str, request: Request):
    """Get status of a memify enrichment job."""
    normalized_job_id = (job_id or "").strip()
    if not normalized_job_id:
        raise HTTPException(status_code=400, detail="MEMIFY_JOB_ID_REQUIRED")

    config, knowledge_config, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    _ensure_knowledge_enabled_flag(knowledge_config.enabled)
    if not knowledge_config.enabled:
        raise HTTPException(status_code=400, detail="KNOWLEDGE_DISABLED")
    if not bool(getattr(knowledge_config, "memify_enabled", False)):
        raise HTTPException(status_code=400, detail="MEMIFY_DISABLED")

    manager = GraphOpsManager(workspace_dir)
    payload = manager.get_memify_status(normalized_job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="MEMIFY_JOB_NOT_FOUND")
    return payload


@router.websocket("/history-backfill/progress/ws")
async def stream_history_backfill_progress(websocket: WebSocket):
    """Stream history backfill progress to console with WebSocket."""
    await websocket.accept()
    interval_ms = _clamp_int(
        websocket.query_params.get("interval_ms"),
        default=1000,
        minimum=300,
        maximum=3000,
    )

    _, _, _, workspace_dir = await _resolve_knowledge_ws_context(websocket)
    manager = _manager_for_workspace(workspace_dir)

    last_fingerprint: str | None = None
    try:
        while True:
            progress = manager.get_history_backfill_progress()
            fingerprint = json.dumps(
                progress,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if fingerprint != last_fingerprint:
                await websocket.send_json(
                    {
                        "type": "snapshot",
                        "progress": progress,
                    }
                )
                last_fingerprint = fingerprint
            await asyncio.sleep(interval_ms / 1000)
    except WebSocketDisconnect:
        return


@router.get("/backup")
async def backup_knowledge(request: Request):
    _, _, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    manager = _manager_for_workspace(workspace_dir)
    if not manager.root_dir.exists():
        raise HTTPException(status_code=404, detail="KNOWLEDGE_NOT_FOUND")

    buf = await asyncio.to_thread(_zip_path, manager.root_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"copaw_knowledge_{timestamp}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/backup/{source_id}")
async def backup_knowledge_source(source_id: str, request: Request):
    _, _, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    manager = _manager_for_workspace(workspace_dir)
    source_dir = manager.get_source_storage_dir(source_id)
    if not source_dir.exists() or not source_dir.is_dir():
        raise HTTPException(status_code=404, detail="KNOWLEDGE_SOURCE_NOT_FOUND")

    buf = await asyncio.to_thread(_zip_path, source_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = manager._safe_name(source_id)
    filename = f"copaw_knowledge_{safe_name}_{timestamp}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/restore")
async def restore_knowledge_backup(
    request: Request,
    file: UploadFile = File(...),
    replace_existing: bool = Query(default=True),
):
    if file.content_type and file.content_type not in {
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    }:
        raise HTTPException(
            status_code=400,
            detail=f"Expected a zip file, got content-type: {file.content_type}",
        )

    data = await file.read()
    _validate_zip_data(data)

    config, _, _, workspace_dir, _ = await _resolve_knowledge_request_context(request)
    manager = _manager_for_workspace(workspace_dir)
    tmp_dir: Path | None = None
    try:
        tmp_dir = await asyncio.to_thread(_extract_zip_to_temp, data)
        extract_root = _detect_extract_root(tmp_dir)
        if not (extract_root / "sources").is_dir():
            raise HTTPException(
                status_code=400,
                detail="Invalid knowledge backup: missing sources directory",
            )

        if replace_existing and manager.root_dir.exists():
            shutil.rmtree(manager.root_dir, ignore_errors=True)

        manager.root_dir.mkdir(parents=True, exist_ok=True)
        for item in extract_root.iterdir():
            dest = manager.root_dir / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            else:
                if dest.exists() and dest.is_file():
                    dest.unlink()
                shutil.copytree(item, dest, dirs_exist_ok=True)

        manager.sources_dir.mkdir(parents=True, exist_ok=True)
        manager.uploads_dir.mkdir(parents=True, exist_ok=True)
        manager.remote_blob_dir.mkdir(parents=True, exist_ok=True)
        manager.remote_meta_dir.mkdir(parents=True, exist_ok=True)

        config.knowledge.sources = manager.list_sources_from_storage()
        save_config(config)

        return {
            "success": True,
            "replace_existing": replace_existing,
            "restored_sources": len(config.knowledge.sources),
        }
    finally:
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)