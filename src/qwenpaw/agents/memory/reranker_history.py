# -*- coding: utf-8 -*-
"""Persistent history for reranker probe results.

Each verification run appends one record keyed by the service fingerprint
(a SHA-256 digest of the normalized configuration). The JSON file lives under
the QwenPaw working dir so it survives restarts and is shared across browser
sessions. The key never contains the API key itself, so it is safe to expose
in request URLs and access logs.
"""

from __future__ import annotations

import hashlib
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


def _canonical_timeout(timeout: Any) -> str:
    """Normalize a timeout to a shared decimal string.

    Both sides of the fingerprint contract (here and the console helper) hash
    the same six-decimal, trailing-zero-stripped text so a fractional timeout
    such as ``1.5`` produces an identical digest instead of being truncated
    to ``int`` by one side only.
    """
    try:
        value = float(timeout or 0)
    except (TypeError, ValueError):
        value = 0.0
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def service_fingerprint(config: RerankerConfig) -> str:
    """Digest of a reranker service config, mirroring the console helper.

    Kept in sync with console/src/pages/Agent/Config/components/
    rerankerUtils.ts (getRerankerServiceFingerprint): both sides SHA-256 the
    same canonical JSON array [base_url, api_key, model, timeout] so a config
    change starts a new history series while the API key never appears in
    URLs, access logs, or the history file.
    """
    base_url = (config.base_url or "").strip().rstrip("/")
    model_name = (config.model_name or "").strip()
    canonical = json.dumps(
        [
            base_url,
            config.api_key or "",
            model_name,
            _canonical_timeout(config.timeout),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def append_record(
    fingerprint: str,
    record: dict[str, Any],
) -> list[dict[str, Any]]:
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
