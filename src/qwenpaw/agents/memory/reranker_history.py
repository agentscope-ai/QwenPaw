# -*- coding: utf-8 -*-
"""Persistent history for reranker probe results.

Each verification run appends one record keyed by the service fingerprint, a
SHA-256 digest of the normalized service configuration. The JSON file lives
under the QwenPaw working dir so it survives restarts and is shared across
browser sessions. Digest keys never contain the API key, so the value is safe
to expose in request URLs, access logs and this file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from ...constant import WORKING_DIR
from ...config.config import RerankerConfig

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_MAX_ENTRIES = 200
_HISTORY_FILE = "reranker_history.json"
_FINGERPRINT_PREFIX = "sha256:"


def _canonical_timeout(timeout: Any) -> str:
    """Normalize a timeout to the shared decimal text used by the digest.

    Both sides of the fingerprint contract (here and the console helper
    ``rerankerUtils.ts::canonicalTimeout``) hash the same six-decimal,
    trailing-zero-stripped text. Truncating to ``int`` on one side only made a
    fractional timeout such as ``1.5`` unreachable after a page refresh.
    """
    try:
        value = float(timeout or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value != value or value in (float("inf"), float("-inf")):
        value = 0.0
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def service_fingerprint(config: RerankerConfig) -> str:
    """Opaque digest of a reranker service configuration.

    Mirrors console/src/pages/Agent/Config/components/rerankerUtils.ts
    (``getRerankerServiceFingerprint``): both sides SHA-256 the same canonical
    JSON array ``[base_url, api_key, model, canonical_timeout]``, so a config
    change starts a new history series while the API key never appears in
    URLs, access logs or the history file.
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
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{_FINGERPRINT_PREFIX}{digest}"


def _history_path() -> Path:
    return Path(WORKING_DIR) / _HISTORY_FILE


def _is_current_key(key: Any) -> bool:
    """Whether *key* is a digest fingerprint, not a legacy plaintext key."""
    if not isinstance(key, str) or not key.startswith(_FINGERPRINT_PREFIX):
        return False
    digest = key[len(_FINGERPRINT_PREFIX) :]
    return len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


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

    # Legacy keys embedded the raw API key as part of the JSON array. They are
    # unreadable by the digest contract anyway, so drop them instead of keeping
    # credentials on disk. Also drop malformed entries (non-list series).
    # Persist the cleaned file so the secret does not survive the next restart.
    cleaned = {
        key: value
        for key, value in data.items()
        if _is_current_key(key) and isinstance(value, list)
    }
    if len(cleaned) != len(data):
        logger.warning(
            "reranker history: dropped %d legacy or malformed entr(ies)",
            len(data) - len(cleaned),
        )
        try:
            _write(cleaned)
        except OSError:
            logger.warning(
                "reranker history: failed to persist legacy key cleanup",
                exc_info=True,
            )
    return cleaned


def _write(data: dict[str, list[dict[str, Any]]]) -> None:
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
        _write(data)
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
