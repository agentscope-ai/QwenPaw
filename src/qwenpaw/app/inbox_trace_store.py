# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from ..constant import WORKING_DIR

_TRACE_DIR = WORKING_DIR / "inbox_traces"
_LOCK = asyncio.Lock()


def _trace_path(run_id: str) -> Path:
    return _TRACE_DIR / f"{run_id}.json"


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return _to_jsonable(value.model_dump(mode="json"))
    if hasattr(value, "dict"):
        return _to_jsonable(value.dict())
    return {"repr": repr(value)}


def _read_trace(run_id: str) -> dict[str, Any]:
    path = _trace_path(run_id)
    if not path.exists():
        return {
            "run_id": run_id,
            "created_at": time.time(),
            "completed_at": None,
            "status": "running",
            "meta": {},
            "events": [],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("invalid trace file")
    data.setdefault("events", [])
    return data


def _write_trace(run_id: str, payload: dict[str, Any]) -> None:
    _TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = _trace_path(run_id)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)


async def create_trace(
    run_id: str,
    *,
    meta: dict[str, Any] | None = None,
) -> None:
    async with _LOCK:
        payload = {
            "run_id": run_id,
            "created_at": time.time(),
            "completed_at": None,
            "status": "running",
            "meta": _to_jsonable(meta or {}),
            "events": [],
        }
        _write_trace(run_id, payload)


async def append_trace_event(run_id: str, event: Any) -> None:
    async with _LOCK:
        payload = _read_trace(run_id)
        events = payload.get("events", [])
        events.append(
            {
                "at": time.time(),
                "event": _to_jsonable(event),
            },
        )
        payload["events"] = events
        _write_trace(run_id, payload)


async def finalize_trace(
    run_id: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    async with _LOCK:
        payload = _read_trace(run_id)
        payload["status"] = status
        payload["completed_at"] = time.time()
        if error is not None:
            payload["error"] = error
        _write_trace(run_id, payload)


async def get_trace(run_id: str) -> dict[str, Any] | None:
    path = _trace_path(run_id)
    if not path.exists():
        return None
    async with _LOCK:
        return _read_trace(run_id)


async def delete_trace(run_id: str) -> bool:
    if not run_id:
        return False
    path = _trace_path(run_id)
    async with _LOCK:
        if not path.exists():
            return False
        path.unlink(missing_ok=True)
    return True
