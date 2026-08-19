# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Composition root for the unique Creator API.

Routes in this router intentionally begin at ``/projects``.  The QwenPaw host
mounts the router at ``/qwenpaw-creator`` and standalone development mounts it at
``/api/qwenpaw-creator``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from services.project_files.facade import CreatorFileServices
from services.runtime_files.runtime_dependencies import (
    creator_runtime_dependency_health,
)

from .file_asset_routes import router as file_assets_router
from .example_routes import router as examples_router
from .file_execution_routes import router as file_execution_router
from .file_media_routes import router as file_media_router
from .file_session_routes import router as file_sessions_router
from .file_source_intelligence_routes import (
    router as file_source_intelligence_router,
)
from .model_routes import bind_creator_tool_config
from .model_routes import router as model_router
from .project_file_routes import router as project_files_router
from .project_routes import router as projects_router
from .work_graph_routes import router as work_graph_router
from .dependencies import (
    CreatorErrorRoute,
    bind_creator_trace_request,
    project_file_services,
)

router = APIRouter(
    dependencies=[
        Depends(bind_creator_trace_request),
        Depends(bind_creator_tool_config),
    ],
    route_class=CreatorErrorRoute,
)
router.include_router(projects_router)
router.include_router(examples_router)
router.include_router(project_files_router)
router.include_router(file_assets_router)
router.include_router(file_source_intelligence_router)
router.include_router(file_sessions_router)
router.include_router(file_execution_router)
router.include_router(file_media_router)
router.include_router(work_graph_router)
router.include_router(model_router)


@router.get("/health", tags=["infrastructure"])
async def health(
    services: CreatorFileServices = Depends(project_file_services),
) -> dict[str, Any]:
    project_errors = len(services.startup_recovery.integrity_errors)
    review_errors = len(services.startup_review_recovery.integrity_errors)
    dependencies = creator_runtime_dependency_health()
    return {
        "status": (
            "ok"
            if project_errors + review_errors == 0
            and dependencies["status"] == "ok"
            else "degraded"
        ),
        "runtime": "creator-filesystem",
        "projectRecoveryErrors": project_errors,
        "reviewRecoveryErrors": review_errors,
        "dependencies": dependencies,
    }
