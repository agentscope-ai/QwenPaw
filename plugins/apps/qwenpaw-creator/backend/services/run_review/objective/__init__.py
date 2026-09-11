# -*- coding: utf-8 -*-
"""Objective fact operators (tier-0 of the bypass review).

CPU-only measurements ported from APE-benchmark's objective grader
(cut/scene/freeze detection, speech/music presence, AV sync, machine
params, sharpness/stability/color, cross-shot consistency, camera
motion, OCR gray-zone text verification). Every operator degrades to a
recorded skip when a dependency (ASR model, opencv, easyocr) is absent,
and every output is an advisory FACT for the reviewing model — never a
pass/fail verdict on its own.
"""

from services.run_review.objective.facts import (
    collect_image_facts,
    collect_video_facts,
    render_facts_block,
)

__all__ = [
    "collect_image_facts",
    "collect_video_facts",
    "render_facts_block",
]
