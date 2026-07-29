# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""FastAPI dependencies for Creator storage and request infrastructure."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import uuid4

from fastapi import Depends, Request, Response
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse

from domain.errors import (
    ConflictError,
    CreatorError,
    ValidationError,
)
from services.project_files.facade import (
    CreatorFileServices,
    creator_file_services,
)
from services.observability import (
    bind_trace_context,
    stable_trace_id,
    trace_span,
)
from services.storage_root import require_creator_data_root


def project_file_services() -> CreatorFileServices:
    """Return the process-shared filesystem Project authority and poll cache."""

    return creator_file_services(require_creator_data_root())


ProjectFileServicesDep = Depends(project_file_services)


async def bind_creator_trace_request(
    request: Request,
    response: Response,
) -> AsyncIterator[None]:
    """Persist one correlated span around every Creator API request."""

    request_id = (
        request.headers.get("X-Request-ID") or f"request-{uuid4().hex}"
    )
    trace_id = stable_trace_id("requestId", request_id)
    path_context = {
        target: request.path_params.get(source)
        for source, target in (
            ("project_id", "projectId"),
            ("session_id", "sessionId"),
            ("run_id", "runId"),
            ("task_id", "taskId"),
        )
        if request.path_params.get(source)
    }
    request.state.creator_request_id = request_id
    request.state.creator_trace_id = trace_id
    response.headers["X-Creator-Trace-ID"] = trace_id
    response.headers["X-Request-ID"] = request_id
    with bind_trace_context(
        traceId=trace_id,
        requestId=request_id,
        **path_context,
    ):
        async with trace_span(
            "creator.http.request",
            component="api",
            attributes={
                "method": request.method,
                "path": request.url.path,
                "queryKeys": sorted(set(request.query_params.keys())),
            },
        ):
            yield


def resolve_idempotency_key(
    header_value: str | None,
    *,
    stable_client_id: str | None = None,
) -> str:
    header = (header_value or "").strip()
    stable = (stable_client_id or "").strip()
    if header and stable and header != stable:
        raise ConflictError(
            "Idempotency-Key 与请求中的稳定 client id 不一致",
            details={"idempotencyKey": header, "stableClientId": stable},
        )
    key = header or stable
    if not key:
        raise ValidationError("写请求需要 Idempotency-Key")
    if len(key) > 192:
        raise ValidationError("Idempotency-Key 最长为 192 个字符")
    return key


async def creator_error_handler(
    _request: Request,
    error: CreatorError,
) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
            "details": error.details,
        },
    )


class CreatorErrorRoute(APIRoute):
    """Keep Creator domain failures structured when mounted in any host app."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        route_handler = super().get_route_handler()

        async def structured_handler(request: Request) -> Response:
            try:
                response = await route_handler(request)
            except CreatorError as error:
                response = await creator_error_handler(request, error)
            trace_id = getattr(request.state, "creator_trace_id", None)
            request_id = getattr(request.state, "creator_request_id", None)
            if trace_id:
                response.headers.setdefault("X-Creator-Trace-ID", trace_id)
            if request_id:
                response.headers.setdefault("X-Request-ID", request_id)
            return response

        return structured_handler
