# -*- coding: utf-8 -*-
"""Background auto-verification of configured reranker services.

Periodically sweeps the enabled agents, and for any whose reranker service is
enabled with a positive ``auto_verify_interval_hours`` and whose last
verification is older than that interval, runs the probe suite and appends the
result to the persistent history.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...config.config import RerankerConfig
    from .reme_reranker import RerankerTestResult

logger = logging.getLogger(__name__)

_AUTO_PROBE_SWEEP_SECONDS = 1800.0


async def probe_and_record(
    reranker: RerankerConfig,
    *,
    allow_private: bool = False,
) -> RerankerTestResult:
    """Run one probe suite and append a successful run to the history.

    Shared by the console endpoint and the background sweep so manual and
    scheduled verification use exactly the same probe-and-record contract.
    Failed runs are reported to the caller but never recorded as history.
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
    if result.success:
        append_record(
            service_fingerprint(reranker),
            make_record(
                latency_ms=result.latency_ms,
                precision=result.precision,
                correct_count=result.correct_count,
                total=result.total,
            ),
        )
    return result


async def _sweep_once() -> None:
    from ...config.utils import load_config
    from ...utils.io_utils import run_sync_io

    from .reme_reranker import load_reranker_config
    from .reranker_history import get_history, service_fingerprint

    config = await run_sync_io(load_config)
    profiles = config.agents.profiles
    now = time.time()

    for agent_id in profiles:
        try:
            # Reuse the runtime loader: the reranker lives under
            # running.reme_light_memory_config, and reading it from the
            # profile root silently disabled the whole sweep.
            reranker = await load_reranker_config(agent_id)
        except Exception:
            logger.exception(
                "reranker auto-probe: failed to load agent %s",
                agent_id,
            )
            continue

        if reranker is None:
            continue
        interval_hours = (
            getattr(reranker, "auto_verify_interval_hours", 0) or 0
        )
        if interval_hours <= 0:
            continue

        try:
            fingerprint = service_fingerprint(reranker)
            history = get_history(fingerprint, limit=1)
            last_ts = (
                float(history[-1].get("ts", 0)) / 1000.0 if history else 0.0
            )
            if now - last_ts < interval_hours * 3600:
                continue

            # Operator-saved config: probe the same endpoint the runtime
            # would call, including a local/private deployment.
            result = await probe_and_record(reranker, allow_private=True)
            if result.success:
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
            logger.exception(
                "reranker auto-probe error for agent %s",
                agent_id,
            )


async def run_reranker_auto_probe_loop() -> None:
    while True:
        try:
            await _sweep_once()
        except Exception:
            logger.exception("reranker auto-probe sweep crashed")
        await asyncio.sleep(_AUTO_PROBE_SWEEP_SECONDS)
