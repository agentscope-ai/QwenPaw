# -*- coding: utf-8 -*-
"""Bridge to the user-configured ASR model for objective facts.

Sentence-level timestamps feed the AV-sync and speech-presence facts.
Whatever ASR model the user configured is used; without a configured
key — or on any failure/timeout — the caller receives ``None`` and the
ASR-backed operators record themselves as skipped. Facts degrade, the
review never does.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from utils.logger import setup_logger

logger = setup_logger("creator.run_review.objective.asr")

ASR_TIMEOUT_SECONDS = 90.0


async def transcript_sentences(
    media_path: Path,
) -> list[dict[str, Any]] | None:
    """ASR sentence segments for one media file; None when unavailable."""
    try:
        from models.config import get_asr_api_key

        if not get_asr_api_key():
            return None
        from models import asr_model

        result = await asyncio.wait_for(
            asr_model.transcribe(media_path.as_uri()),
            timeout=ASR_TIMEOUT_SECONDS,
        )
        return [
            {
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "text": segment.text,
            }
            for segment in result.segments
        ]
    except Exception:  # noqa: BLE001 - facts are advisory-only
        logger.warning("ASR transcript for review facts unavailable")
        return None


__all__ = ["ASR_TIMEOUT_SECONDS", "transcript_sentences"]
