# -*- coding: utf-8 -*-
"""HTTP exception mappings shared by the application entrypoint."""

import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..exceptions import AgentConfigConflictError


def _replace_non_finite_numbers(value: Any) -> Any:
    """Replace values that strict JSON responses cannot serialize."""
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {
            key: _replace_non_finite_numbers(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_non_finite_numbers(item) for item in value]
    return value


async def request_validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Return validation errors even when rejected inputs are non-finite."""
    detail = _replace_non_finite_numbers(jsonable_encoder(exc.errors()))
    return JSONResponse(status_code=422, content={"detail": detail})


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
        RequestValidationError,
        request_validation_error_handler,
    )
    app.add_exception_handler(
        AgentConfigConflictError,
        agent_config_conflict_handler,
    )
