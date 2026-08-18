# -*- coding: utf-8 -*-
"""HTTP exception mappings shared by the application entrypoint."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..exceptions import AgentConfigConflictError


async def agent_config_conflict_handler(
    _request: Request,
    exc: AgentConfigConflictError,
) -> JSONResponse:
    """Return a stable response for optimistic config conflicts."""
    return JSONResponse(
        status_code=409,
        content={
            "detail": {
                "code": exc.error_code,
                "message": exc.message,
            },
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register application-specific exception mappings."""
    app.add_exception_handler(
        AgentConfigConflictError,
        agent_config_conflict_handler,
    )
