# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=no-else-raise,too-many-return-statements,too-many-branches
"""Small, dependency-free tracing layer for the complete Creator runtime.

The runtime persists business authority in ``project.json`` and scoped Runtime
JSON/JSONL files.  These traces serve a different purpose: one chronological,
correlation-friendly account of how an HTTP intent moved through Creator, its
agent loops, SpecialistRuns, runtime actions, durable Tasks, and providers.
They remain diagnostic evidence rather than a second source of truth.
"""

from __future__ import annotations

import asyncio
import hashlib
import heapq
import json
import os
import re
import time
import traceback
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, ParamSpec, TypeVar
from uuid import uuid4

from services.storage_root import require_creator_data_root
from utils.logger import (
    register_creator_log_project_resolver,
    setup_logger,
)

from .config import (
    load_observability_config,
    project_observability_directory,
    trace_root,
)

_P = ParamSpec("_P")
_R = TypeVar("_R")
_TRACE_LOGGER = setup_logger("tracing")
_CONTEXT: ContextVar[dict[str, str]] = ContextVar(
    "creator_trace_context",
    default={},
)
_SECRET_KEY = re.compile(
    r"(api[-_]?key|authorization|cookie|secret|password|token)$",
    re.I,
)
_ID_KEYS = frozenset(
    {
        "requestId",
        "errorId",
        "projectId",
        "sessionId",
        "conversationId",
        "goalId",
        "transactionId",
        "assistantMessageId",
        "actionId",
        "runId",
        "taskId",
        "modelRunId",
        "providerTaskId",
        "workerId",
    },
)
_MAX_VALUE_CHARS = 4_000
_MAX_COLLECTION_ITEMS = 50
_RETENTION_LOCK = threading.Lock()
_RETENTION_CLEANED: dict[Path, str] = {}


def _enabled() -> bool:
    try:
        return load_observability_config().enabled
    except Exception:
        # Diagnostics must never become a runtime dependency. Startup paths and
        # isolated unit tests may intentionally have no Creator Data Workspace.
        return False


def _trace_root(*, project_id: str | None = None) -> Path:
    return trace_root(project_id=project_id)


def _json_safe(
    value: Any,
    *,
    capture_content: bool,
    key: str = "",
    depth: int = 0,
) -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if depth > 6:
        return "[MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if not capture_content and key.lower() in {
            "content",
            "prompt",
            "systemprompt",
            "rawtext",
            "thinking",
            "delta",
        }:
            return {"redacted": True, "chars": len(value)}
        return (
            value
            if len(value) <= _MAX_VALUE_CHARS
            else value[:_MAX_VALUE_CHARS] + "...[TRUNCATED]"
        )
    if isinstance(value, Mapping):
        return {
            str(item_key): _json_safe(
                item_value,
                capture_content=capture_content,
                key=str(item_key),
                depth=depth + 1,
            )
            for item_key, item_value in list(value.items())[
                :_MAX_COLLECTION_ITEMS
            ]
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _json_safe(
                item,
                capture_content=capture_content,
                key=key,
                depth=depth + 1,
            )
            for item in list(value)[:_MAX_COLLECTION_ITEMS]
        ]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return _json_safe(
        str(value),
        capture_content=capture_content,
        key=key,
        depth=depth + 1,
    )


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def stable_trace_id(*parts: object) -> str:
    raw = "\x00".join(str(part) for part in parts if part not in (None, ""))
    if not raw:
        return _new_id("trace")
    return f"trace-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


def _trace_id_for(context: Mapping[str, object]) -> str:
    """Choose one stable logical-work anchor, not a changing combination of ids."""

    for key in (
        "requestId",
        "goalId",
        "sessionId",
        "runId",
        "taskId",
        "projectId",
    ):
        value = context.get(key)
        if value not in (None, ""):
            return stable_trace_id(key, value)
    return stable_trace_id()


def current_trace_context() -> dict[str, str]:
    return dict(_CONTEXT.get())


def report_error(
    *,
    component: str,
    code: str,
    message: str,
    error: BaseException | None = None,
    retryable: bool = False,
    details: Mapping[str, Any] | None = None,
    **context: object,
) -> dict[str, Any]:
    """Emit one correlated diagnostic and return fields safe to persist.

    User-visible records carry ``errorId`` while the trace retains the type,
    cause chain and structured details needed to diagnose the same incident.
    """

    error_id = _new_id("error")
    inherited = current_trace_context()
    correlation = {
        **inherited,
        **{
            key: str(value)
            for key, value in context.items()
            if value not in (None, "")
        },
    }
    trace_id = correlation.get("traceId") or _trace_id_for(correlation)
    cause_chain: list[dict[str, str]] = []
    current = error
    seen: set[int] = set()
    while (
        current is not None
        and id(current) not in seen
        and len(cause_chain) < 6
    ):
        seen.add(id(current))
        cause_chain.append(
            {
                "type": type(current).__name__,
                "message": str(current)[:2000],
            },
        )
        current = current.__cause__ or current.__context__
    attributes = {
        "errorId": error_id,
        "errorCode": code,
        "errorType": type(error).__name__ if error is not None else None,
        "message": message[:4000],
        "retryable": retryable,
        "details": dict(details or {}),
        "causeChain": cause_chain,
        "stack": (
            "".join(
                traceback.format_exception(
                    type(error),
                    error,
                    error.__traceback__,
                ),
            )[-12_000:]
            if error is not None
            else ""
        ),
    }
    trace_event(
        "creator.error.reported",
        component=component,
        status="error",
        attributes=attributes,
        errorId=error_id,
        traceId=trace_id,
        **{
            key: value
            for key, value in context.items()
            if key not in {"errorId", "traceId"}
        },
    )
    return {
        "errorId": error_id,
        "traceId": trace_id,
        "requestId": correlation.get("requestId"),
        "code": code,
        "message": message[:4000],
        "retryable": retryable,
        "details": dict(details or {}),
    }


register_creator_log_project_resolver(
    lambda: current_trace_context().get("projectId"),
)


@contextmanager
def bind_trace_context(**values: object) -> Iterator[dict[str, str]]:
    merged = current_trace_context()
    for key, value in values.items():
        if value not in (None, ""):
            merged[key] = str(value)
    token = _CONTEXT.set(merged)
    try:
        yield merged
    finally:
        _CONTEXT.reset(token)


def _write(record: Mapping[str, Any]) -> None:
    if not _enabled():
        return

    try:
        config = load_observability_config()
        safe = _json_safe(
            record,
            capture_content=config.capture_content,
        )
        line = json.dumps(
            safe,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        project_id = safe.get("projectId")
        if isinstance(project_id, str) and project_id:
            try:
                path = (
                    _trace_root(
                        project_id=project_id,
                    )
                    / f"creator-trace-{day}.jsonl"
                )
            except Exception:
                path = _trace_root() / f"creator-trace-{day}.jsonl"
        else:
            path = _trace_root() / f"creator-trace-{day}.jsonl"

        _cleanup_expired_trace_files(path.parent, config.retention_days)

        try:
            descriptor = os.open(
                path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                os.write(descriptor, (line + "\n").encode("utf-8"))
            finally:
                os.close(descriptor)
        except Exception:
            _TRACE_LOGGER.exception(
                f"failed to write creator trace to {str(path)}",
                exc_info=True,
            )
    except Exception:
        # Bad diagnostic data (for example a NaN provider metric) must never
        # fail the business operation that attempted to emit it.
        _TRACE_LOGGER.exception("failed to create trace data", exc_info=True)


def _cleanup_expired_trace_files(root: Path, retention_days: int) -> None:
    """Best-effort once-daily retention without entering business locks."""

    today = datetime.now(timezone.utc).date().isoformat()
    with _RETENTION_LOCK:
        if _RETENTION_CLEANED.get(root) == today:
            return
        _RETENTION_CLEANED[root] = today
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    for path in root.glob("creator-trace-*.jsonl"):
        try:
            modified = datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            )
            if modified < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            _TRACE_LOGGER.warning(
                "failed to apply trace retention to %s",
                path,
                exc_info=True,
            )


def trace_event(
    name: str,
    *,
    component: str,
    status: str = "ok",
    attributes: Mapping[str, Any] | None = None,
    **context: object,
) -> None:
    record = _event_record(
        name,
        component=component,
        status=status,
        attributes=attributes,
        **context,
    )
    if record is not None:
        _write(record)


async def _trace_event_offloaded(
    name: str,
    *,
    component: str,
    status: str = "ok",
    attributes: Mapping[str, Any] | None = None,
    **context: object,
) -> None:
    """Run the complete event emission (config stat, build, write) off the
    event loop; ``to_thread`` copies contextvars so the trace context binds.
    """

    await asyncio.to_thread(
        trace_event,
        name,
        component=component,
        status=status,
        attributes=attributes,
        **context,
    )


def _event_record(
    name: str,
    *,
    component: str,
    status: str = "ok",
    attributes: Mapping[str, Any] | None = None,
    **context: object,
) -> dict[str, Any] | None:
    if not _enabled():
        return None
    inherited = current_trace_context()
    inherited.update(
        {
            key: str(value)
            for key, value in context.items()
            if value not in (None, "")
        },
    )
    trace_id = inherited.get("traceId") or _trace_id_for(inherited)
    inherited["traceId"] = trace_id
    return {
        "schemaVersion": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": "event",
        "name": name,
        "component": component,
        "status": status,
        **{
            key: value
            for key, value in inherited.items()
            if key in _ID_KEYS or key in {"traceId", "spanId", "parentSpanId"}
        },
        "attributes": dict(attributes or {}),
    }


@asynccontextmanager
async def trace_span(
    name: str,
    *,
    component: str,
    attributes: Mapping[str, Any] | None = None,
    **context: object,
):
    inherited = current_trace_context()
    parent_span_id = inherited.get("spanId")
    trace_id = inherited.get("traceId") or _trace_id_for(context)
    span_id = _new_id("span")
    started_ns = time.perf_counter_ns()
    with bind_trace_context(
        **context,
        traceId=trace_id,
        parentSpanId=parent_span_id,
        spanId=span_id,
    ):
        await _trace_event_offloaded(
            f"{name}.started",
            component=component,
            attributes=attributes,
        )
        try:
            yield current_trace_context()
        except BaseException as exc:
            await _trace_event_offloaded(
                f"{name}.finished",
                component=component,
                status="error",
                attributes={
                    **dict(attributes or {}),
                    "durationMs": round(
                        (time.perf_counter_ns() - started_ns) / 1_000_000,
                        3,
                    ),
                    "errorType": type(exc).__name__,
                    "error": str(exc),
                    "stack": "".join(
                        traceback.format_exception(
                            type(exc),
                            exc,
                            exc.__traceback__,
                        ),
                    )[-12_000:],
                },
            )
            raise
        else:
            await _trace_event_offloaded(
                f"{name}.finished",
                component=component,
                attributes={
                    **dict(attributes or {}),
                    "durationMs": round(
                        (time.perf_counter_ns() - started_ns) / 1_000_000,
                        3,
                    ),
                },
            )


def traced_async(
    name: str,
    *,
    component: str,
    context: Callable[..., Mapping[str, object]] | None = None,
    attributes: Callable[..., Mapping[str, Any]] | None = None,
) -> Callable[[Callable[_P, Any]], Callable[_P, Any]]:
    def decorate(function: Callable[_P, Any]) -> Callable[_P, Any]:
        @wraps(function)
        async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> Any:
            correlation = dict(context(*args, **kwargs)) if context else {}
            details = dict(attributes(*args, **kwargs)) if attributes else {}
            async with trace_span(
                name,
                component=component,
                attributes=details,
                **correlation,
            ):
                return await function(*args, **kwargs)

        return wrapped

    return decorate


def read_trace_records(  # pylint: disable=too-many-branches
    *,
    filters: Mapping[str, str] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Read newest matching records directly from diagnostic JSONL files."""

    if limit < 1 or limit > 2_000:
        raise ValueError("trace limit must be between 1 and 2000")
    wanted = {
        key: value for key, value in dict(filters or {}).items() if value
    }
    matches: list[tuple[str, int, dict[str, Any]]] = []
    roots: list[Path] = []
    try:
        roots.append(_trace_root())
    except Exception:
        pass
    project_id = wanted.get("projectId")
    if project_id:
        try:
            roots.insert(0, _trace_root(project_id=project_id))
        except Exception:
            pass
    else:
        try:
            data_root = require_creator_data_root()
            for candidate in data_root.iterdir():
                try:
                    trace_directory = project_observability_directory(
                        candidate.name,
                        "traces",
                        data_root=data_root,
                        create=False,
                    )
                except Exception:
                    continue
                if trace_directory.is_dir():
                    roots.append(trace_directory)
        except Exception:
            pass
    paths = sorted(
        {
            path
            for root in roots
            for path in root.glob("creator-trace-*.jsonl")
        },
        key=lambda path: (path.name, str(path)),
        reverse=True,
    )
    sequence = 0
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if all(
                str(record.get(key) or "") == value
                for key, value in wanted.items()
            ):
                sequence += 1
                candidate = (
                    str(record.get("timestamp") or ""),
                    sequence,
                    record,
                )
                if len(matches) < limit:
                    heapq.heappush(matches, candidate)
                elif candidate[:2] > matches[0][:2]:
                    heapq.heapreplace(matches, candidate)
    return [item[2] for item in sorted(matches)]
