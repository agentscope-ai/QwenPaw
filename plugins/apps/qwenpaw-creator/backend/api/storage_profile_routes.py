# -*- coding: utf-8 -*-
"""Read-only storage profile: what the runtime keeps, and what it released."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query

from schemas.storage import StorageProfileData
from services.media_files.task_scratch import project_storage_profile
from services.project_files.facade import CreatorFileServices

from .dependencies import CreatorErrorRoute, project_file_services


router = APIRouter(
    prefix="/storage",
    tags=["creator-storage"],
    route_class=CreatorErrorRoute,
)


@router.get("/profile", response_model=StorageProfileData)
async def get_storage_profile(
    include_orphans: bool = Query(False, alias="includeOrphans"),
    services: CreatorFileServices = Depends(project_file_services),
) -> StorageProfileData:
    """Report every Project's footprint split at its release baseline.

    Scanning is a walk over the runtime tree, so it runs off the event loop;
    the orphan scan additionally reads the Asset index and is opt-in.
    """

    profile = await asyncio.to_thread(
        project_storage_profile,
        services,
        include_orphans=include_orphans,
    )
    return StorageProfileData.model_validate(profile)
