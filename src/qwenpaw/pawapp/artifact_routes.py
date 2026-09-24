# -*- coding: utf-8 -*-
"""Authorized reads for immutable Host artifact versions."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import Response

from .tasks.contracts import TaskStoreError
from .tasks.routes import Scope

router = APIRouter(
    prefix="/pawapps/{app_id}/workspaces/{workspace_id}",
    tags=["pawapp-artifacts"],
)

_PREVIEW_TYPES = frozenset(
    {
        "application/pdf",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/html",
        "text/markdown",
        "text/plain",
    },
)


@router.get("/artifacts")
async def artifact_collection(
    request: Request,
    scope: Scope,
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = Query(None, max_length=512),
    task_id: str | None = Query(None, max_length=256),
    media_type: str | None = Query(None, max_length=256),
):
    store = getattr(request.app.state, "pawapp_artifacts", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="artifact_store_unavailable",
        )
    try:
        return await store.list(
            scope,
            limit=limit,
            cursor=cursor,
            task_id=task_id,
            media_type=media_type,
        )
    except TaskStoreError as exc:
        status = 422 if exc.code.startswith("invalid_artifact_") else 503
        raise HTTPException(status_code=status, detail=exc.code) from None


@router.get("/artifacts/{artifact_id}/versions/{version}/content")
async def artifact_content(
    request: Request,
    artifact_id: str,
    version: Annotated[int, Path(ge=1)],
    scope: Scope,
    disposition: str = Query("preview", pattern="^(preview|download)$"),
) -> Response:
    store = getattr(request.app.state, "pawapp_artifacts", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="artifact_store_unavailable",
        )
    try:
        ref, content = await store.read(scope, artifact_id, version)
    except TaskStoreError as exc:
        status = 404 if exc.code == "artifact_not_found" else 503
        raise HTTPException(status_code=status, detail=exc.code) from None
    preview = disposition == "preview" and ref.media_type in _PREVIEW_TYPES
    kind = "inline" if preview else "attachment"
    media_type = ref.media_type if preview else "application/octet-stream"
    filename = quote(ref.name, safe="")
    headers = {
        "Content-Disposition": f"{kind}; filename*=UTF-8''{filename}",
        "Content-Security-Policy": (
            "sandbox; default-src 'none'; style-src 'unsafe-inline'; "
            "img-src data:"
        ),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "ETag": f'"{ref.digest}"',
    }
    return Response(content=content, media_type=media_type, headers=headers)
