# -*- coding: utf-8 -*-
"""Scheduled and manual probe-and-record helpers for reranker services.

Scheduled verification runs as a ReMe workspace :class:`ServiceCronJob`, so
disabled agents and agents switched away from ReMe are never probed. Cooldown
is measured from the last attempt (including failed attempts) rather than only
from successful history entries, so a failing service waits the full configured
interval before retrying.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...config.config import RerankerConfig
    from .reme_reranker import RerankerTestResult
    from .reranker_history import RerankerHistoryRecord

logger = logging.getLogger(__name__)

RERANKER_AUTO_VERIFY_CRON = "*/30 * * * *"

# Tracks the latest scheduled probe attempt timestamp (epoch seconds) per
# service fingerprint, including failed attempts. Keeping this at module scope
# preserves cooldown across workspace reloads within the same process.
_LAST_ATTEMPT_TS: dict[str, float] = {}


@dataclass(frozen=True)
class RerankerProbeOutcome:
    """Result of probing a reranker service and persisting its history."""

    result: RerankerTestResult
    fingerprint: str
    history: list[RerankerHistoryRecord] | None = None
    history_error: str | None = None


def clear_attempt_timestamps() -> None:
    """Clear recorded scheduled-attempt timestamps (used in tests)."""
    _LAST_ATTEMPT_TS.clear()


def _format_history_error(exc: Exception, *, api_key: str = "") -> str:
    # Prefer OSError.strerror so server filesystem paths are not exposed to
    # HTTP clients while still surfacing why storage failed.
    if isinstance(exc, OSError) and exc.strerror:
        detail = exc.strerror.strip()
    else:
        detail = str(exc).strip()
    if api_key and detail:
        detail = detail.replace(api_key, "***")
    if detail:
        return f"Failed to save verification history: {detail}"
    return "Failed to save verification history"


async def probe_and_record(
    reranker: RerankerConfig,
    *,
    allow_private: bool = False,
) -> RerankerProbeOutcome:
    """Run one probe suite and append a successful run to the history.

    Shared by the console endpoint and the ReMe scheduled job so manual and
    scheduled verification use the same probe-and-record contract. Failed runs
    are reported to the caller but never recorded as history. History storage
    errors are captured in ``history_error`` rather than failing a successful
    probe with an unhandled exception.
    """
    from .reme_reranker import test_reranker_model
    from .reranker_history import (
        append_record,
        make_record,
        service_fingerprint,
    )

    result = await test_reranker_model(
        reranker,
        allow_private=allow_private,
    )
    fingerprint = service_fingerprint(reranker)
    history: list[RerankerHistoryRecord] | None = None
    history_error: str | None = None
    if result.success:
        try:
            history = append_record(
                fingerprint,
                make_record(
                    latency_ms=result.latency_ms,
                    precision=result.precision,
                    correct_count=result.correct_count,
                    total=result.total,
                ),
            )
        except Exception as exc:
            logger.warning(
                "reranker history: failed to persist probe result",
                exc_info=True,
            )
            history_error = _format_history_error(
                exc,
                api_key=reranker.api_key,
            )
    return RerankerProbeOutcome(
        result=result,
        fingerprint=fingerprint,
        history=history,
        history_error=history_error,
    )


async def probe_agent_reranker_if_due(
    agent_id: str,
    *,
    now: float | None = None,
) -> RerankerProbeOutcome | None:
    """Probe one active ReMe workspace's reranker if its interval has elapsed.

    Cooldown is computed from ``max(last_history_ts, last_attempt_ts)``, so a
    failed attempt does not remain due on the next cron tick.
    """
    from .reme_reranker import load_reranker_config
    from .reranker_history import get_history, service_fingerprint

    reranker = await load_reranker_config(agent_id)
    if reranker is None or not (reranker.base_url or "").strip():
        return None
    interval_hours = getattr(reranker, "auto_verify_interval_hours", 0) or 0
    if interval_hours <= 0:
        return None

    fingerprint = service_fingerprint(reranker)
    current_time = time.time() if now is None else now
    history = get_history(fingerprint, limit=1)
    last_history_ts = history[-1].ts / 1000.0 if history else 0.0
    last_attempt_ts = _LAST_ATTEMPT_TS.get(fingerprint, 0.0)
    last_ts = max(last_history_ts, last_attempt_ts)
    if current_time - last_ts < interval_hours * 3600:
        return None

    # Record the attempt before awaiting the probe so a failing or raising run
    # respects the configured interval instead of retrying every 30 minutes.
    _LAST_ATTEMPT_TS[fingerprint] = current_time

    # Operator-saved config: probe the same endpoint the runtime would call,
    # including a local/private deployment.
    outcome = await probe_and_record(
        reranker,
        allow_private=True,
    )
    result = outcome.result
    if result.success:
        logger.info(
            "reranker auto-probe %s: precision=%s (%s/%s)",
            agent_id,
            result.precision,
            result.correct_count,
            result.total,
        )
        if outcome.history_error:
            logger.warning(
                "reranker auto-probe %s history error: %s",
                agent_id,
                outcome.history_error,
            )
    else:
        logger.warning(
            "reranker auto-probe %s failed: %s",
            agent_id,
            result.message,
        )
    return outcome
