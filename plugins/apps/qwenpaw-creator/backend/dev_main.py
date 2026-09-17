# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,ungrouped-imports
"""Standalone FastAPI app for local Creator UI development."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from utils.env import load_project_env

load_project_env()

from api.dependencies import creator_error_handler  # noqa: E402
from api.router import router as creator_router  # noqa: E402
from domain.errors import CreatorError  # noqa: E402
from services.file_agent_runtime.registry import (  # noqa: E402
    start_creator_agent_runtime,
    stop_creator_agent_runtime,
)
from services.media_files import (  # noqa: E402
    shutdown_file_media_execution_services,
    start_file_media_execution_services,
)
from services.observability import trace_event  # noqa: E402
from services.project_files.facade import (  # noqa: E402
    clear_creator_file_service_registry,
    creator_file_services,
)
from services.runtime_files.runtime_dependencies import (  # noqa: E402
    ensure_creator_runtime_dependencies,
)
from services.storage_root import require_creator_data_root  # noqa: E402
from services.source_analysis import (  # noqa: E402
    recover_interrupted_source_analysis,
    shutdown_source_analysis_services,
)
from utils.logger import configure_creator_file_logging  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Construction performs Project and Review journal recovery before the API
    # accepts traffic.  No database migration or SQL runtime is part of boot.
    data_root = require_creator_data_root()
    log_path = configure_creator_file_logging(data_root)
    trace_event(
        "creator.runtime.starting",
        component="standalone",
        attributes={
            "dataRoot": str(data_root),
            "logPath": str(log_path),
        },
    )
    try:
        await asyncio.to_thread(ensure_creator_runtime_dependencies)
        services = creator_file_services(data_root)
        recover_interrupted_source_analysis(services)
    except BaseException as exc:
        trace_event(
            "creator.runtime.startup_failed",
            component="standalone",
            status="error",
            attributes={
                "errorType": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
    try:
        await start_file_media_execution_services(services)
        await start_creator_agent_runtime(services)
        trace_event(
            "creator.runtime.started",
            component="standalone",
            attributes={"dataRoot": str(data_root)},
        )
        yield
    finally:
        trace_event(
            "creator.runtime.stopping",
            component="standalone",
        )
        try:
            await shutdown_file_media_execution_services()
        finally:
            try:
                await shutdown_source_analysis_services()
            finally:
                try:
                    await stop_creator_agent_runtime()
                finally:
                    clear_creator_file_service_registry()
                    trace_event(
                        "creator.runtime.stopped",
                        component="standalone",
                    )


app = FastAPI(title="QwenPaw-Creator Local Dev Backend", lifespan=lifespan)
app.add_exception_handler(CreatorError, creator_error_handler)
app.include_router(creator_router, prefix="/api/qwenpaw-creator")
