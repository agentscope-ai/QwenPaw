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
import math
import threading
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ...constant import WORKING_DIR
from ...config.config import RerankerConfig

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_MAX_ENTRIES = 200
_DEFAULT_HISTORY_LIMIT = 50
_HISTORY_FILE = "reranker_history.json"
_FINGERPRINT_PREFIX = "sha256:"


def _validate_finite_int(value: Any, *, allow_float: bool = False) -> int:
    """Accept finite numeric values (excluding booleans) as integers."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid integer")
    if isinstance(value, int):
        return value
    if allow_float and isinstance(value, float) and math.isfinite(value):
        return int(value)
    if (
        isinstance(value, float)
        and math.isfinite(value)
        and value.is_integer()
    ):
        return int(value)
    raise ValueError("expected a finite integer")


class RerankerHistoryRecord(BaseModel):
    """One recorded reranker verification run.

    Shared by persistent storage and both workspace API endpoints (GET history
    and POST probe) so every read/write path enforces the exact same schema.
    """

    model_config = ConfigDict(extra="ignore")

    ts: int
    latency_ms: int = 0
    precision: float | None = None
    correct_count: int = 0
    total: int = 0

    @field_validator("ts", mode="before")
    @classmethod
    def _validate_ts(cls, value: Any) -> int:
        return _validate_finite_int(value, allow_float=True)

    @field_validator("latency_ms", "correct_count", "total", mode="before")
    @classmethod
    def _validate_counts(cls, value: Any) -> int:
        parsed = _validate_finite_int(value, allow_float=False)
        if parsed < 0:
            raise ValueError("count must be non-negative")
        return parsed

    @field_validator("precision", mode="before")
    @classmethod
    def _validate_precision(cls, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("precision must be a finite number or null")
        numeric = float(value)
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            raise ValueError("precision must be between 0.0 and 1.0")
        return numeric


def parse_history_record(raw: Any) -> RerankerHistoryRecord | None:
    """Validate one raw history record, returning ``None`` if malformed."""
    if isinstance(raw, RerankerHistoryRecord):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return RerankerHistoryRecord.model_validate(raw)
    except ValidationError:
        return None


def parse_history_series(raw_series: Any) -> list[RerankerHistoryRecord]:
    """Filter and validate a sequence of raw history records."""
    if not isinstance(raw_series, list):
        return []
    records: list[RerankerHistoryRecord] = []
    for item in raw_series:
        record = parse_history_record(item)
        if record is not None:
            records.append(record)
    return records


def _canonical_timeout(timeout: Any) -> str:
    """Normalize a timeout to a canonical decimal string for fingerprinting.

    Preserves fractional values (six decimals, trailing zeros stripped) so a
    timeout such as ``1.5`` stays distinct from ``1`` and ``2`` and remains
    reachable across restarts.
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
    """Opaque SHA-256 digest of a normalized reranker service configuration.

    Hashes the canonical JSON array ``[base_url, api_key, model,
    canonical_timeout]``, so changing any service field starts a new history
    series while the API key never appears in URLs, access logs, or disk files.
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
    # credentials on disk. Also drop malformed entries (non-list series or
    # corrupt records such as null). Persist the cleaned file so neither
    # credentials nor corrupt records survive the next restart.
    cleaned: dict[str, list[dict[str, Any]]] = {}
    dropped_keys = 0
    dropped_records = 0
    for key, value in data.items():
        if not _is_current_key(key) or not isinstance(value, list):
            dropped_keys += 1
            continue
        valid_records = parse_history_series(value)
        dropped_records += len(value) - len(valid_records)
        cleaned[key] = [record.model_dump() for record in valid_records]

    if dropped_keys or dropped_records:
        logger.warning(
            "reranker history: dropped %d legacy/malformed key(s) and "
            "%d malformed record(s)",
            dropped_keys,
            dropped_records,
        )
        try:
            _write(cleaned)
        except OSError:
            logger.warning(
                "reranker history: failed to persist history cleanup",
                exc_info=True,
            )
    return cleaned


def _write(data: dict[str, list[dict[str, Any]]]) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def append_record(
    fingerprint: str,
    record: RerankerHistoryRecord | dict[str, Any],
    limit: int = _DEFAULT_HISTORY_LIMIT,
) -> list[RerankerHistoryRecord]:
    """Append one validated verification record and return recent records."""
    validated = parse_history_record(record)
    if validated is None:
        raise ValueError("Invalid reranker history record")
    with _LOCK:
        data = _load()
        series = parse_history_series(data.get(fingerprint, []))
        series.append(validated)
        if len(series) > _MAX_ENTRIES:
            del series[: len(series) - _MAX_ENTRIES]
        data[fingerprint] = [item.model_dump() for item in series]
        _write(data)
        return series[-limit:] if limit > 0 else []


def get_history(
    fingerprint: str,
    limit: int = _DEFAULT_HISTORY_LIMIT,
) -> list[RerankerHistoryRecord]:
    """Return the most recent valid records for a fingerprint."""
    with _LOCK:
        data = _load()
        series = parse_history_series(data.get(fingerprint, []))
        return series[-limit:] if limit > 0 else []


def make_record(
    *,
    latency_ms: int,
    precision: float | None,
    correct_count: int,
    total: int,
) -> RerankerHistoryRecord:
    """Build a validated history record for one verification run."""
    return RerankerHistoryRecord(
        ts=int(time.time() * 1000),
        latency_ms=latency_ms,
        precision=precision,
        correct_count=correct_count,
        total=total,
    )
