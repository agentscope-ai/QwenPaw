# -*- coding: utf-8 -*-
"""Persistent history for reranker probe results.

Each verification run appends one record keyed by the service fingerprint
(base URL + API key + model + timeout). The JSON file lives under the QwenPaw
working dir so it survives restarts and is shared across browser sessions.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from ...constant import WORKING_DIR
from ...config.config import RerankerConfig

_LOCK = threading.Lock()
_MAX_ENTRIES = 200
_HISTORY_FILE = "reranker_history.json"


def service_fingerprint(config: RerankerConfig) -> str:
    """Fingerprint of a reranker service, mirroring the console helper.

    Kept in sync with console/src/pages/Agent/Config/components/rerankerUtils.ts
    (getRerankerServiceFingerprint): base URL normalized, key/model/timeout
    included so a config change starts a new history series.
    """
    base_url = (config.base_url or "").strip().rstrip("/")
    model_name = (config.model_name or "").strip()
    return json.dumps(
        [base_url, config.api_key or "", model_name, int(config.timeout or 0)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _history_path() -> Path:
    return Path(WORKING_DIR) / _HISTORY_FILE


def _load() -> dict[str, list[dict[str, Any]]]:
    path = _history_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _save(data: dict[str, list[dict[str, Any]]]) -> None:
    path = _history_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def append_record(fingerprint: str, record: dict[str, Any]) -> list[dict[str, Any]]:
    """Append one verification record and return the capped series."""
    with _LOCK:
        data = _load()
        series = data.setdefault(fingerprint, [])
        series.append(record)
        if len(series) > _MAX_ENTRIES:
            del series[: len(series) - _MAX_ENTRIES]
        _save(data)
        return list(series)


def get_history(fingerprint: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent records for a fingerprint."""
    with _LOCK:
        data = _load()
        series = data.get(fingerprint, [])
        return list(series[-limit:])


def make_record(
    *,
    latency_ms: int,
    precision: float | None,
    correct_count: int,
    total: int,
) -> dict[str, Any]:
    """Build a history record for one verification run."""
    return {
        "ts": int(time.time() * 1000),
        "latency_ms": latency_ms,
        "precision": precision,
        "correct_count": correct_count,
        "total": total,
    }
