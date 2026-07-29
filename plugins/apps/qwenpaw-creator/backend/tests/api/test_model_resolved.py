# -*- coding: utf-8 -*-
"""``GET /models/resolved`` must expose the same model identity execution uses.

The R2V workbench displays this value as the "模型" of an Element.  It has to
match what ``get_video_model_name()`` returns at submission time, otherwise the
UI drifts from the provider actually receiving the task (see the recipe.model
mismatch that motivated this endpoint).
"""
from __future__ import annotations

import asyncio

from api.model_routes import get_resolved_models
from models import config as model_config


def test_resolved_models_match_execution_identity() -> None:
    result = asyncio.run(get_resolved_models())

    assert result["video"]["model"] == model_config.get_video_model_name()
    assert result["video"]["provider"] == model_config.get_video_backend()
