# -*- coding: utf-8 -*-
"""Background auto-verification of configured reranker services.

Periodically sweeps the enabled agents, and for any whose reranker service
is enabled with a positive ``auto_verify_interval_hours`` and whose last
verification is older than that interval, runs the probe suite and appends
the result to the persistent history.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

_AUTO_PROBE_SWEEP_SECONDS = 1800.0


async def _sweep_once() -> None:
    from ...config.config import load_agent_config, load_config
    from ...utils.io_utils import run_sync_io

    from .reranker_history import (
        append_record,
        get_history,
        make_record,
        service_fingerprint,
    )
    from .reme_reranker import test_reranker_model

    config = await run_sync_io(load_config)
    profiles = config.agents.profiles
    now = time.time()

    for agent_id in profiles:
        try:
            agent_config = await run_sync_io(load_agent_config, agent_id)
        except Exception:
            logger.exception("reranker auto-probe: failed to load agent %s", agent_id)
            continue

        reranker = getattr(agent_config, "reranker_config", None)
        if reranker is None or not reranker.enabled:
            continue
        interval_hours = getattr(reranker, "auto_verify_interval_hours", 0) or 0
        if interval_hours <= 0:
            continue

        try:
            fingerprint = service_fingerprint(reranker)
            history = get_history(fingerprint, limit=1)
            last_ts = history[-1]["ts"] / 1000.0 if history else 0.0
            if now - last_ts < interval_hours * 3600:
                continue

            result = await test_reranker_model(reranker)
            if result.success:
                append_record(
                    fingerprint,
                    make_record(
                        latency_ms=result.latency_ms,
                        precision=result.precision,
                        correct_count=result.correct_count,
                        total=result.total,
                    ),
                )
                logger.info(
                    "reranker auto-probe %s: precision=%s (%s/%s)",
                    agent_id,
                    result.precision,
                    result.correct_count,
                    result.total,
                )
            else:
                logger.warning(
                    "reranker auto-probe %s failed: %s",
                    agent_id,
                    result.message,
                )
        except Exception:
            logger.exception("reranker auto-probe error for agent %s", agent_id)


async def run_reranker_auto_probe_loop() -> None:
    while True:
        try:
            await _sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("reranker auto-probe sweep crashed")
        await asyncio.sleep(_AUTO_PROBE_SWEEP_SECONDS)
