# -*- coding: utf-8 -*-
"""Write query-handler error log and agent/memory state to a temp JSON file."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import traceback
from datetime import datetime, timezone
from typing import Any

from ..channels.schema import DEFAULT_CHANNEL

logger = logging.getLogger(__name__)


def _safe_json_serialize(obj: object) -> object:
    """Convert object to JSON-serializable form; use str() for unknowns."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe_json_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _safe_json_serialize(v) for k, v in obj.items()}
    return str(obj)


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


def write_query_error_dump(
    request: Any,
    exc: BaseException,
    locals_: dict,
) -> str | None:
    """Write error log, traceback and agent/memory state to a temp JSON file.

    Returns the temp file path, or None if write failed.
    """
    try:
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
        agent_state = None
        agent = locals_.get("agent")
        if agent is not None:
            try:
                if hasattr(agent, "state_dict"):
                    agent_state = _safe_json_serialize(agent.state_dict())
            except Exception as state_err:
                agent_state = {"_serialize_error": str(state_err)}
        payload = {
            "trace": trace_str,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "request_info": request_info,
            "request": request_full,
            "agent_state": agent_state,
            "ts_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ",
            ),
        }
        fd, path = tempfile.mkstemp(
            prefix="qwenpaw_query_error_",
            suffix=".json",
            dir=tempfile.gettempdir(),
            text=True,
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            return path
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
    except Exception as dump_err:
        logger.warning("Failed to write query error dump: %s", dump_err)
        return None
