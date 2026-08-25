# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""FastAPI dependencies for Creator storage and request infrastructure."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
import logging
import time
from uuid import uuid4

from fastapi import Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from domain.errors import (
    ConflictError,
    CreatorError,
    RuntimeBusyError,
    ValidationError,
)
from services.project_files.facade import (
    CreatorFileServices,
    creator_file_services,
)
from services.observability import (
    bind_trace_context,
    report_error,
    stable_trace_id,
    trace_event,
    trace_span,
)
from services.storage_root import require_creator_data_root
from services.runtime_files.errors import LockTimeoutError

logger = logging.getLogger("qwenpaw.creator.api.errors")


def project_file_services() -> CreatorFileServices:
    """Return the process-shared filesystem Project authority and poll cache."""

    return creator_file_services(require_creator_data_root())


ProjectFileServicesDep = Depends(project_file_services)


async def bind_creator_trace_request(
    request: Request,
    response: Response,
) -> AsyncIterator[None]:
    """Persist one correlated span around every Creator API request."""

    if getattr(request.state, "creator_trace_managed", False):
        response.headers["X-Creator-Trace-ID"] = request.state.creator_trace_id
        response.headers["X-Request-ID"] = request.state.creator_request_id
        yield
        return
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


_NOISY_POLL_SUFFIXES = (
    "/session",
    "/events",
    "/tasks",
    "/specialist-runs",
    "/execution-authorizations",
    "/work-graph",
    "/runtime/reviews/active",
    "/observability/traces",
)


def _is_noisy_poll(request: Request) -> bool:
    return request.method == "GET" and request.url.path.endswith(
        _NOISY_POLL_SUFFIXES,
    )


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
    request: Request,
    error: CreatorError,
) -> JSONResponse:
    cause: BaseException | None = error
    seen: set[int] = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, LockTimeoutError):
            mapped = _lock_error(cause)
            mapped.__cause__ = error
            error = mapped
            break
        cause = cause.__cause__ or cause.__context__
    request_id = getattr(request.state, "creator_request_id", None) or (
        request.headers.get("X-Request-ID") or f"request-{uuid4().hex}"
    )
    trace_id = getattr(
        request.state,
        "creator_trace_id",
        None,
    ) or stable_trace_id(
        "requestId",
        request_id,
    )
    request.state.creator_request_id = request_id
    request.state.creator_trace_id = trace_id
    with bind_trace_context(traceId=trace_id, requestId=request_id):
        report = report_error(
            component="api",
            code=error.code,
            message=error.message,
            error=error,
            retryable=error.retryable,
            details={
                **error.details,
                "method": request.method,
                "path": request.url.path,
                "statusCode": error.status_code,
            },
        )
    log = logger.error if error.status_code >= 500 else logger.warning
    log(
        "Creator request failed error_id=%s trace_id=%s request_id=%s "
        "status=%s code=%s method=%s path=%s details=%r",
        report["errorId"],
        trace_id,
        request_id,
        error.status_code,
        error.code,
        request.method,
        request.url.path,
        error.details,
        exc_info=error.status_code >= 500,
    )
    return JSONResponse(
        status_code=error.status_code,
        content={
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
            "details": error.details,
            "errorId": report["errorId"],
            "traceId": trace_id,
            "requestId": request_id,
            "occurredAt": datetime.now(UTC).isoformat(),
        },
        headers={
            "X-Creator-Error-ID": str(report["errorId"]),
            "X-Creator-Trace-ID": trace_id,
            "X-Request-ID": request_id,
        },
    )


def _validation_error(error: RequestValidationError) -> ValidationError:
    issues = [
        {
            "location": [str(part) for part in item.get("loc", ())],
            "message": str(item.get("msg") or "invalid value"),
            "type": str(item.get("type") or "validation_error"),
        }
        for item in error.errors()
    ]
    return ValidationError("请求参数校验失败", details={"issues": issues})


def _http_error(error: HTTPException) -> CreatorError:
    message = str(error.detail or f"HTTP {error.status_code}")
    mapped = CreatorError(message, details={"statusCode": error.status_code})
    mapped.status_code = error.status_code
    mapped.code = f"HTTP_{error.status_code}"
    mapped.retryable = error.status_code >= 500
    return mapped


def _lock_error(error: LockTimeoutError) -> RuntimeBusyError:
    return RuntimeBusyError(
        "Creator Runtime 协调锁等待超时",
        details=error.details,
    )


def _unexpected_error(error: Exception) -> CreatorError:
    status_code = getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    if (
        isinstance(status_code, int)
        and 400 <= status_code <= 599
        and isinstance(code, str)
        and code
    ):
        details: dict[str, object] = {"errorType": type(error).__name__}
        for attribute, key in (
            ("model_name", "modelName"),
            ("operation", "operation"),
            ("agent_name", "agentName"),
        ):
            value = getattr(error, attribute, None)
            if value not in (None, ""):
                details[key] = str(value)
        # codeql[py/stack-trace-exposure]: this branch only admits
        # AppError-style domain errors whose messages are curated at
        # raise time (credentials redacted, no stack frames); truly
        # unexpected exceptions take the INTERNAL_ERROR branch below
        # and never expose their text.
        mapped = CreatorError(str(error), details=details)
        mapped.status_code = status_code
        mapped.code = code
        mapped.retryable = bool(getattr(error, "retryable", False))
        mapped.__cause__ = error
        return mapped
    internal = CreatorError(
        "Creator 内部错误，请使用错误编号查询日志和 Trace",
        details={"errorType": type(error).__name__},
    )
    internal.status_code = 500
    internal.code = "INTERNAL_ERROR"
    internal.__cause__ = error
    return internal


class CreatorErrorRoute(APIRoute):
    """Keep Creator domain failures structured when mounted in any host app."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        route_handler = super().get_route_handler()

        async def structured_handler(request: Request) -> Response:
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
            attributes = {
                "method": request.method,
                "path": request.url.path,
                "queryKeys": sorted(set(request.query_params.keys())),
            }
            request.state.creator_request_id = request_id
            request.state.creator_trace_id = trace_id
            request.state.creator_trace_managed = True
            noisy_poll = _is_noisy_poll(request)
            started_ns = time.perf_counter_ns()
            with bind_trace_context(
                traceId=trace_id,
                requestId=request_id,
                **path_context,
            ):
                try:
                    if noisy_poll:
                        response = await route_handler(request)
                    else:
                        async with trace_span(
                            "creator.http.request",
                            component="api",
                            attributes=attributes,
                        ):
                            response = await route_handler(request)
                            attributes["statusCode"] = response.status_code
                except CreatorError as error:
                    response = await creator_error_handler(request, error)
                except RequestValidationError as error:
                    response = await creator_error_handler(
                        request,
                        _validation_error(error),
                    )
                except HTTPException as error:
                    response = await creator_error_handler(
                        request,
                        _http_error(error),
                    )
                except LockTimeoutError as error:
                    response = await creator_error_handler(
                        request,
                        _lock_error(error),
                    )
                except Exception as error:  # pylint: disable=broad-except
                    response = await creator_error_handler(
                        request,
                        _unexpected_error(error),
                    )
                else:
                    if noisy_poll and response.status_code >= 400:
                        trace_event(
                            "creator.http.request.finished",
                            component="api",
                            status="error",
                            attributes={
                                **attributes,
                                "statusCode": response.status_code,
                                "durationMs": round(
                                    (time.perf_counter_ns() - started_ns)
                                    / 1_000_000,
                                    3,
                                ),
                            },
                        )
            trace_id = getattr(request.state, "creator_trace_id", None)
            request_id = getattr(request.state, "creator_request_id", None)
            if trace_id:
                response.headers.setdefault("X-Creator-Trace-ID", trace_id)
            if request_id:
                response.headers.setdefault("X-Request-ID", request_id)
            return response

        return structured_handler
