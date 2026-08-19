# -*- coding: utf-8 -*-
"""Render self-review module (code-level switch, advisory, frontend-free).

Enabled only through the ``CREATOR_SELF_REVIEW_ENABLED`` environment switch
(``models.config.is_self_review_enabled``); with the switch off the module is
never imported into any execution path's behavior.
"""

from services.render_review.frames import (
    RenderReviewError,
    extract_review_frames,
    probe_audio_profile,
)
from services.render_review.protocol import MAX_REVIEW_ROUNDS
from services.render_review.review import (
    review_render,
    run_review_loop,
    schedule_render_review,
)

__all__ = [
    "MAX_REVIEW_ROUNDS",
    "RenderReviewError",
    "extract_review_frames",
    "probe_audio_profile",
    "review_render",
    "run_review_loop",
    "schedule_render_review",
]
