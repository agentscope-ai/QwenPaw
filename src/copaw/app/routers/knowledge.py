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

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from ...config import load_config, save_config
from ...config.config import KnowledgeConfig, KnowledgeSourceSpec
from ...constant import WORKING_DIR
from ...knowledge import GraphOpsManager, KnowledgeManager

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


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


def _find_source(config: KnowledgeConfig, source_id: str) -> Optional[KnowledgeSourceSpec]:
    for source in config.sources:
        if source.id == source_id:
            return source
    return None


@router.get("/config", response_model=KnowledgeConfig)
async def get_knowledge_config() -> KnowledgeConfig:
    return load_config().knowledge


@router.put("/config", response_model=KnowledgeConfig)
async def put_knowledge_config(
    knowledge_config: KnowledgeConfig = Body(...),
) -> KnowledgeConfig:
    config = load_config()
    config.knowledge = knowledge_config
    save_config(config)
    return config.knowledge


@router.get("/sources")
async def list_sources():
    config = load_config()
    return {
        "enabled": config.knowledge.enabled,
        "sources": _manager().list_sources(config.knowledge),
    }


@router.put("/sources", response_model=KnowledgeSourceSpec)
async def upsert_source(
    source: KnowledgeSourceSpec = Body(...),
) -> KnowledgeSourceSpec:
    config = load_config()
    manager = _manager()
    source = manager.normalize_source_name(source, config.knowledge)
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
    source_id: str = Form(...),
    file: UploadFile = File(...),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    saved_path = _manager().save_uploaded_file(
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
    saved_root = _manager().save_uploaded_directory(source_id, saved_pairs)
    return {
        "location": str(saved_root),
        "file_count": len(saved_pairs),
    }


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str):
    config = load_config()
    source = _find_source(config.knowledge, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="KNOWLEDGE_SOURCE_NOT_FOUND")
    config.knowledge.sources = [
        item for item in config.knowledge.sources if item.id != source_id
    ]
    save_config(config)
    _manager().delete_index(source_id)
    return {"deleted": True, "source_id": source_id}


@router.delete("/clear")
async def clear_knowledge(
    confirm: bool = Query(default=False),
    remove_sources: bool = Query(default=True),
):
    """Clear all persisted knowledge data and optionally remove source configs."""
    if not confirm:
        raise HTTPException(status_code=400, detail="KNOWLEDGE_CLEAR_CONFIRM_REQUIRED")

    config = load_config()
    result = _manager().clear_knowledge(
        config.knowledge,
        remove_sources=remove_sources,
    )
    save_config(config)
    return result


@router.post("/sources/{source_id}/index")
async def index_source(source_id: str):
    config = load_config()
    source = _find_source(config.knowledge, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="KNOWLEDGE_SOURCE_NOT_FOUND")
    try:
        result = _manager().index_source(
            source,
            config.knowledge,
            config.agents.running,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


@router.get("/sources/{source_id}/content")
async def get_source_content(source_id: str):
    config = load_config()
    source = _find_source(config.knowledge, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="KNOWLEDGE_SOURCE_NOT_FOUND")
    return _manager().get_source_documents(source_id)


@router.post("/index")
async def index_all_sources():
    config = load_config()
    try:
        return _manager().index_all(config.knowledge, config.agents.running)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/search")
async def search_knowledge(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    source_ids: Optional[str] = Query(default=None),
    source_types: Optional[str] = Query(default=None),
):
    config = load_config()
    ids = [item for item in (source_ids or "").split(",") if item]
    types = [item for item in (source_types or "").split(",") if item]
    return _manager().search(
        query=q,
        config=config.knowledge,
        limit=limit,
        source_ids=ids or None,
        source_types=types or None,
    )


@router.get("/history-backfill/status")
async def get_history_backfill_status():
    """Get history backfill status for knowledge enable flow and CTA display."""
    return _manager().history_backfill_status()


@router.post("/history-backfill/run")
async def run_history_backfill_now():
    """Run history backfill immediately regardless of runtime auto-backfill toggle."""
    config = load_config()
    manager = _manager()
    running = config.agents.running
    force_running = SimpleNamespace(
        auto_collect_chat_files=running.auto_collect_chat_files,
        auto_collect_chat_urls=running.auto_collect_chat_urls,
        auto_collect_long_text=running.auto_collect_long_text,
        long_text_min_chars=running.long_text_min_chars,
        knowledge_chunk_size=running.knowledge_chunk_size,
    )
    result = await asyncio.to_thread(
        manager.auto_backfill_history_data,
        config.knowledge,
        force_running,
    )
    if result.get("changed"):
        save_config(config)
    return {
        "result": result,
        "status": manager.history_backfill_status(),
    }


@router.get("/memify/jobs/{job_id}")
async def get_memify_job_status(job_id: str):
    """Get status of a memify enrichment job."""
    normalized_job_id = (job_id or "").strip()
    if not normalized_job_id:
        raise HTTPException(status_code=400, detail="MEMIFY_JOB_ID_REQUIRED")

    config = load_config()
    if not config.knowledge.enabled:
        raise HTTPException(status_code=400, detail="KNOWLEDGE_DISABLED")
    if not bool(getattr(config.knowledge, "memify_enabled", False)):
        raise HTTPException(status_code=400, detail="MEMIFY_DISABLED")

    manager = GraphOpsManager(WORKING_DIR)
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

    last_fingerprint: str | None = None
    try:
        while True:
            progress = _manager().get_history_backfill_progress()
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
async def backup_knowledge():
    manager = _manager()
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
async def backup_knowledge_source(source_id: str):
    manager = _manager()
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

    manager = _manager()
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

        config = load_config()
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