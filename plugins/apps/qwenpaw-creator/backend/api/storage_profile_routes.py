# -*- coding: utf-8 -*-
"""Storage accounting, plus the on-demand sweep that frees settled history."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from domain.errors import BadRequestError, ConflictError, NotFoundError
from schemas.storage import (
    HistoryReclaimRequest,
    HistoryReclaimResultData,
    StorageProfileData,
)
from services.media_files.task_scratch import project_storage_profile
from services.project_files.facade import CreatorFileServices
from services.project_files.storage_reclaim import reclaim_project_history
from services.project_files.store import ProjectNotFound

from .dependencies import CreatorErrorRoute, project_file_services

router = APIRouter(
    prefix="/storage",
    tags=["creator-storage"],
    route_class=CreatorErrorRoute,
)

PROFILE_TTL_ENV = "CREATOR_STORAGE_PROFILE_TTL_SECONDS"
DEFAULT_PROFILE_TTL_SECONDS = 60.0
# (data root, includeOrphans) -> (monotonic deadline, profile payload).
# The root is part of the key: two data roots must never serve each other's
# numbers, whether in a test process or after CREATOR_DATA_ROOT moves.
_profile_revision = 0
_profile_cache: dict[tuple[str, bool], tuple[float, dict[str, Any]]] = {}


def _profile_ttl_seconds() -> float:
    """How long one scan may serve; ``0`` scans on every request again."""

    raw = os.environ.get(PROFILE_TTL_ENV, "").strip()
    try:
        return float(raw) if raw else DEFAULT_PROFILE_TTL_SECONDS
    except ValueError:
        return DEFAULT_PROFILE_TTL_SECONDS


def invalidate_storage_profile_cache(root: str | None = None) -> None:
    """Drop cached scans so the next reader sees freed bytes at once.

    A reclaim changes exactly what the home page's release notice is waiting to
    hear, so serving a stale scan would bring back the "released but the button
    is still there" defect the confirmation path was built to close. Pass a
    *root* to clear only that data root's entries.
    """

    global _profile_revision
    _profile_revision += 1
    if root is None:
        _profile_cache.clear()
        return
    for key in [k for k in _profile_cache if k[0] == root]:
        _profile_cache.pop(key, None)


@router.get("/profile", response_model=StorageProfileData)
async def get_storage_profile(
    include_orphans: bool = Query(False, alias="includeOrphans"),
    services: CreatorFileServices = Depends(project_file_services),
) -> StorageProfileData:
    """Report every Project's footprint split at its release baseline.

    Scanning is a walk over the runtime tree, so it runs off the event loop;
    the orphan scan additionally reads the Asset index and is opt-in.

    Measured on the field's data root (40 GB, 8 Projects) a single scan cost
    1.4 s idle and up to 41 s while the process was busy, and the home page
    asks for it on load and again on every return from a Project -- which is
    how "open a Project, go back" ended up waiting 20+ seconds. The result is
    therefore cached briefly; a reclaim clears the cache so the notice cannot
    go stale.
    """

    ttl = _profile_ttl_seconds()
    cache_key = (str(services.root), bool(include_orphans))
    now = time.monotonic()
    cached = _profile_cache.get(cache_key)
    if ttl > 0 and cached is not None and now - cached[0] < ttl:
        return StorageProfileData.model_validate(cached[1])

    revision = _profile_revision
    profile = await asyncio.to_thread(
        project_storage_profile,
        services,
        include_orphans=include_orphans,
    )
    if ttl > 0 and revision == _profile_revision:
        _profile_cache[cache_key] = (time.monotonic(), profile)
    return StorageProfileData.model_validate(profile)


@router.post(
    "/projects/{project_id}/reclaim-history",
    response_model=HistoryReclaimResultData,
)
async def reclaim_history(
    project_id: str,
    payload: HistoryReclaimRequest,
    services: CreatorFileServices = Depends(project_file_services),
) -> HistoryReclaimResultData:
    """Reclaim one project's eligible scratch and settled transactions once."""

    if not payload.confirm:
        raise BadRequestError("回收历史需要显式确认（confirm=true）")
    try:
        result = await asyncio.to_thread(
            reclaim_project_history,
            services,
            project_id,
        )
    except ProjectNotFound as exc:
        raise NotFoundError(str(exc)) from exc
    if result.history_kept:
        raise ConflictError("该项目已选择保留历史数据，未执行回收")
    invalidate_storage_profile_cache(str(services.root))
    return HistoryReclaimResultData.model_validate(
        {
            "projectId": result.project_id,
            "historyKept": result.history_kept,
            "confirmedAt": (
                result.confirmed_at.isoformat()
                if result.confirmed_at
                else None
            ),
            "removedTransactions": result.removed_transactions,
            "transactionBytes": result.transaction_bytes,
            "releasedFiles": result.released_files,
            "releasedBytes": result.released_bytes,
        },
    )
