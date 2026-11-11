# -*- coding: utf-8 -*-
"""Write query-handler error log and agent/memory state to a JSON file.

Diagnostic dumps are best-effort: a persistent model outage fails every turn,
so the dump directory is bounded by file count, total size, and age, a single
dump is capped in size, and identical failures are written at most once per
cooldown window. Without those limits one recurring error filled the system
temp directory with hundreds of megabytes of conversation snapshots.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic, time
from typing import Any

from ..channels.schema import DEFAULT_CHANNEL

logger = logging.getLogger(__name__)

DUMP_PREFIX = "qwenpaw_query_error_"
DUMP_SUFFIX = ".json"

DEFAULT_MAX_FILES = 40
DEFAULT_MAX_TOTAL_MB = 50
DEFAULT_MAX_FILE_MB = 8
DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_MIN_INTERVAL_SECONDS = 60

_TRACE_TAIL_CHARS = 20_000
_MINIMAL_TRACE_CHARS = 1_000
_MINIMAL_MESSAGE_CHARS = 500
_AGENT_STATE_KEY_SAMPLE = 20
_MAX_TRACKED_DUMPS = 256
_TEMP_SUFFIX = ".json.tmp"

_MAX_FILES_ENV = "QWENPAW_QUERY_ERROR_DUMP_MAX_FILES"
_MAX_TOTAL_MB_ENV = "QWENPAW_QUERY_ERROR_DUMP_MAX_TOTAL_MB"
_MAX_FILE_MB_ENV = "QWENPAW_QUERY_ERROR_DUMP_MAX_FILE_MB"
_MAX_AGE_DAYS_ENV = "QWENPAW_QUERY_ERROR_DUMP_MAX_AGE_DAYS"
_MIN_INTERVAL_ENV = "QWENPAW_QUERY_ERROR_DUMP_MIN_INTERVAL_SECONDS"
_AGENT_STATE_ENV = "QWENPAW_QUERY_ERROR_DUMP_AGENT_STATE"
_DIR_ENV = "QWENPAW_QUERY_ERROR_DUMP_DIR"

_prune_lock = threading.Lock()
_recent_lock = threading.Lock()
_recent_dumps: dict[tuple[str, str, str, str], tuple[float, str]] = {}


@dataclass(frozen=True)
class DumpPolicy:
    """Resolved limits for writing and retaining diagnostic dumps."""

    max_files: int
    max_total_bytes: int
    max_file_bytes: int
    max_age_seconds: int
    min_interval_seconds: int
    include_agent_state: bool


def _int_env(name: str, default: int) -> int:
    """Read a non-negative integer env var, or the default when invalid."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; using %s", name, raw, default)
        return default
    if value < 0:
        logger.warning(
            "Ignoring out-of-range %s=%r; using %s",
            name,
            raw,
            default,
        )
        return default
    return value


def _bool_env(name: str, default: bool) -> bool:
    """Read a boolean env var, or the default when invalid."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    logger.warning("Ignoring invalid %s=%r; using %s", name, raw, default)
    return default


def _resolve_policy() -> DumpPolicy:
    """Resolve the dump policy from the environment.

    Values are read per call so operators can change the policy without a
    restart. Setting a numeric limit to ``0`` disables it.
    """
    return DumpPolicy(
        max_files=_int_env(_MAX_FILES_ENV, DEFAULT_MAX_FILES),
        max_total_bytes=(
            _int_env(_MAX_TOTAL_MB_ENV, DEFAULT_MAX_TOTAL_MB) * 1024**2
        ),
        max_file_bytes=(
            _int_env(_MAX_FILE_MB_ENV, DEFAULT_MAX_FILE_MB) * 1024**2
        ),
        max_age_seconds=(
            _int_env(_MAX_AGE_DAYS_ENV, DEFAULT_MAX_AGE_DAYS) * 86400
        ),
        min_interval_seconds=_int_env(
            _MIN_INTERVAL_ENV,
            DEFAULT_MIN_INTERVAL_SECONDS,
        ),
        include_agent_state=_bool_env(_AGENT_STATE_ENV, True),
    )


def _dump_directory() -> str:
    """Return the configured dump directory, creating it when needed."""
    configured = os.getenv(_DIR_ENV, "").strip()
    if not configured:
        return tempfile.gettempdir()
    directory = os.path.abspath(os.path.expanduser(configured))
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "Cannot create %s=%r (%s); falling back to %s",
            _DIR_ENV,
            configured,
            exc,
            tempfile.gettempdir(),
        )
        return tempfile.gettempdir()
    return directory


def _encoded_size(value: Any) -> int:
    """Return the size of ``value`` as indented UTF-8 JSON."""
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return len(text.encode("utf-8"))


def _safe_json_serialize(obj: object) -> object:
    """Convert object to JSON-serializable form; use str() for unknowns."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe_json_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _safe_json_serialize(v) for k, v in obj.items()}
    return str(obj)


def _agent_state_summary(state: Any) -> dict[str, Any]:
    """Summarize an omitted agent state without its bulky payload."""
    summary: dict[str, Any] = {
        "_omitted": "agent_state exceeded the per-file size limit",
        "_bytes": _encoded_size(state),
    }
    if isinstance(state, dict):
        summary["_keys"] = sorted(map(str, state))[:_AGENT_STATE_KEY_SAMPLE]
    return summary


def _bounded_agent_state(agent: Any, budget: int) -> tuple[Any, bool]:
    """Serialize agent state, replacing an oversized snapshot by a summary.

    ``state_dict()`` is normally the bulk of a dump (often >95%). Keeping a
    summary preserves the diagnostic value without writing megabytes.

    Returns the serialized state and whether it was replaced by a summary.
    """
    if agent is None or not hasattr(agent, "state_dict"):
        return None, False
    try:
        state = _safe_json_serialize(agent.state_dict())
    except Exception as state_err:
        return {"_serialize_error": str(state_err)}, False

    if not budget or _encoded_size(state) <= budget:
        return state, False
    return _agent_state_summary(state), True


def _request_to_dict(request: Any) -> Any:
    """Serialize request to a JSON-serializable dict (Pydantic or vars)."""
    if request is None:
        return None
    try:
        raw: dict[str, Any]
        if hasattr(request, "model_dump"):
            raw = request.model_dump()
        elif hasattr(request, "dict"):
            raw = request.dict()
        else:
            raw = dict(vars(request))
        if not isinstance(raw, dict):
            raw = dict(vars(request))
        return _safe_json_serialize(raw)
    except Exception:
        return {"_serialize_error": str(request)}


def _json_text_size(payload: Any) -> int:
    """Return the byte size of the JSON text written for ``payload``."""
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return len(text.encode("utf-8"))


def _fits(payload: Any, max_bytes: int) -> bool:
    return _json_text_size(payload) <= max_bytes


def _summarize_agent_state(
    payload: dict[str, Any],
    _trace_str: str,
) -> dict[str, Any]:
    """Replace a full agent state with its summary (first reduction)."""
    state = payload.get("agent_state")
    if state is None:
        return payload
    if isinstance(state, dict) and "_omitted" in state:
        return payload
    shrunk = dict(payload)
    shrunk["agent_state"] = _agent_state_summary(state)
    shrunk["truncated"] = True
    return shrunk


def _truncate_trace(
    payload: dict[str, Any],
    trace_str: str,
) -> dict[str, Any]:
    """Keep only the tail of the traceback."""
    shrunk = dict(payload)
    shrunk["trace"] = trace_str[-_TRACE_TAIL_CHARS:]
    shrunk["truncated"] = True
    return shrunk


def _drop_request(
    payload: dict[str, Any],
    _trace_str: str,
) -> dict[str, Any]:
    """Replace the request body with an omission marker."""
    shrunk = dict(payload)
    shrunk["request"] = {
        "_omitted": "request exceeded the per-file size limit",
    }
    shrunk["truncated"] = True
    return shrunk


def _drop_agent_state(
    payload: dict[str, Any],
    _trace_str: str,
) -> dict[str, Any]:
    """Drop the remaining agent state."""
    shrunk = dict(payload)
    shrunk["agent_state"] = None
    return shrunk


def _keep_identifying_fields(
    payload: dict[str, Any],
    trace_str: str,
) -> dict[str, Any]:
    """Last resort: keep only fields that identify the failure."""
    return {
        "trace": trace_str[-_MINIMAL_TRACE_CHARS:],
        "exception_type": payload.get("exception_type"),
        "exception_message": str(
            payload.get("exception_message") or "",
        )[:_MINIMAL_MESSAGE_CHARS],
        "request_info": payload.get("request_info") or {},
        "request": None,
        "agent_state": None,
        "ts_utc": payload.get("ts_utc"),
        "truncated": True,
    }


_SHRINK_STEPS = (
    _summarize_agent_state,
    _truncate_trace,
    _drop_request,
    _drop_agent_state,
    _keep_identifying_fields,
)


def _shrink_payload(
    payload: dict[str, Any],
    trace_str: str,
    max_file_bytes: int,
) -> dict[str, Any]:
    """Drop fields in a fixed order until the dump fits the size cap.

    Order: agent_state summary, trace tail, request details, remaining
    agent_state, and finally everything except identifying fields.
    """
    if not max_file_bytes:
        return payload
    shrunk = dict(payload)
    for reduce in _SHRINK_STEPS:
        if _fits(shrunk, max_file_bytes):
            return shrunk
        shrunk = reduce(shrunk, trace_str)
    return shrunk


def _collect_dumps(directory: str) -> list[tuple[str, float, int]] | None:
    """List regular dump files as (path, mtime, size), or None on failure."""
    entries: list[tuple[str, float, int]] = []
    try:
        with os.scandir(directory) as scan:
            for entry in scan:
                if not entry.name.startswith(DUMP_PREFIX):
                    continue
                if not entry.name.endswith(DUMP_SUFFIX):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if not stat.S_ISREG(info.st_mode):
                    continue
                entries.append((entry.path, info.st_mtime, info.st_size))
    except OSError as exc:
        logger.warning(
            "Cannot scan query error dump dir %s: %s",
            directory,
            exc,
        )
        return None
    return entries


def _exceeds_limits(
    policy: DumpPolicy,
    age: float,
    kept: int,
    total: int,
    size: int,
) -> bool:
    """Return whether keeping this dump would violate a retention limit."""
    if policy.max_age_seconds and age > policy.max_age_seconds:
        return True
    if policy.max_files and kept >= policy.max_files:
        return True
    return bool(policy.max_total_bytes) and (
        total + size > policy.max_total_bytes
    )


def _prune_dumps(
    directory: str,
    policy: DumpPolicy,
    keep_path: str | None = None,
) -> None:
    """Delete old dumps so the directory stays within its configured bounds.

    The newest dump is always retained even when it alone exceeds the total
    budget. Dumps are written atomically, so every matching file is complete.
    """
    if not (
        policy.max_files or policy.max_total_bytes or policy.max_age_seconds
    ):
        return

    with _prune_lock:
        entries = _collect_dumps(directory)
        if entries is None:
            return

        entries.sort(key=lambda item: item[1], reverse=True)
        now = time()
        kept = 0
        total = 0
        pruned = 0
        for path, mtime, size in entries:
            age = now - mtime
            removable = path != keep_path and _exceeds_limits(
                policy, age, kept, total, size
            )
            if removable:
                try:
                    os.unlink(path)
                    pruned += 1
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    logger.warning(
                        "Cannot remove query error dump %s: %s",
                        path,
                        exc,
                    )
                continue
            kept += 1
            total += size

        if pruned > 1:
            logger.info(
                "Pruned %s query error dump(s) from %s",
                pruned,
                directory,
            )
        elif pruned:
            logger.debug("Pruned an old query error dump from %s", directory)


def _throttle_key(
    directory: str,
    request: Any,
    exc: BaseException,
) -> tuple[str, str, str, str]:
    """Identify an error that should not produce a second dump right away."""
    session_id = getattr(request, "session_id", "") if request else ""
    return (
        directory,
        str(session_id or ""),
        type(exc).__name__,
        str(exc)[:200],
    )


def _recent_dump_path(
    key: tuple[str, str, str, str],
    window_seconds: int,
) -> str | None:
    """Return the previous dump path when the cooldown window is still open."""
    if window_seconds <= 0:
        return None
    now = monotonic()
    with _recent_lock:
        entry = _recent_dumps.get(key)
        if entry is None:
            return None
        recorded, path = entry
        if now - recorded < window_seconds and os.path.isfile(path):
            return path
        _recent_dumps.pop(key, None)
        return None


def _remember_dump(
    key: tuple[str, str, str, str],
    path: str,
    window_seconds: int,
) -> None:
    """Track a fresh dump so identical errors can reuse it."""
    if window_seconds <= 0:
        return
    now = monotonic()
    with _recent_lock:
        _recent_dumps[key] = (now, path)
        if len(_recent_dumps) > _MAX_TRACKED_DUMPS:
            oldest = min(_recent_dumps.items(), key=lambda item: item[1][0])
            _recent_dumps.pop(oldest[0], None)


def _build_payload(
    request: Any,
    exc: BaseException,
    locals_: dict,
    policy: DumpPolicy,
) -> dict[str, Any]:
    """Assemble the dump payload and fit it within the per-file cap."""
    request_info: dict[str, Any] = {}
    request_full: dict[str, Any] | None = None
    if request is not None:
        request_info = {
            "session_id": getattr(request, "session_id", None),
            "user_id": getattr(request, "user_id", None),
            "channel": getattr(request, "channel", DEFAULT_CHANNEL),
        }
        request_full = _request_to_dict(request)

    trace_str = traceback.format_exc()
    agent = locals_.get("agent")
    if policy.include_agent_state:
        agent_state, state_omitted = _bounded_agent_state(
            agent,
            policy.max_file_bytes // 2,
        )
    else:
        agent_state, state_omitted = None, False

    payload: dict[str, Any] = {
        "trace": trace_str,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "request_info": request_info,
        "request": request_full,
        "agent_state": agent_state,
        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if state_omitted:
        payload["truncated"] = True
    return _shrink_payload(payload, trace_str, policy.max_file_bytes)


def _write_payload(directory: str, payload: dict[str, Any]) -> str:
    """Write the payload atomically, removing it if the write fails."""
    fd, temp_path = tempfile.mkstemp(
        prefix=DUMP_PREFIX,
        suffix=_TEMP_SUFFIX,
        dir=directory,
        text=True,
    )
    final_path = temp_path[: -len(_TEMP_SUFFIX)] + DUMP_SUFFIX
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, final_path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return final_path


def _prune_guarded(
    directory: str,
    policy: DumpPolicy,
    keep_path: str,
) -> None:
    """Prune dumps without letting cleanup failures lose the new dump."""
    try:
        _prune_dumps(directory, policy, keep_path=keep_path)
    except Exception:
        logger.warning(
            "Failed to prune query error dumps in %s",
            directory,
            exc_info=True,
        )


def write_query_error_dump(
    request: Any,
    exc: BaseException,
    locals_: dict,
) -> str | None:
    """Write error log, traceback and agent/memory state to a JSON file.

    Returns the path of the dump covering this failure, or None if the write
    failed. Identical failures inside the cooldown window reuse the previous
    dump instead of writing another copy.
    """
    try:
        policy = _resolve_policy()
        directory = _dump_directory()
        throttle_key = _throttle_key(directory, request, exc)
        previous = _recent_dump_path(
            throttle_key,
            policy.min_interval_seconds,
        )
        if previous:
            logger.debug(
                "Suppressed duplicate query error dump; reusing %s",
                previous,
            )
            return previous

        payload = _build_payload(request, exc, locals_, policy)
        path = _write_payload(directory, payload)
        _remember_dump(throttle_key, path, policy.min_interval_seconds)
        _prune_guarded(directory, policy, path)
        return path
    except Exception as dump_err:
        logger.warning("Failed to write query error dump: %s", dump_err)
        return None
