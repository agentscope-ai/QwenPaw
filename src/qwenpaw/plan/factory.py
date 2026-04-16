# -*- coding: utf-8 -*-
"""Factory function for PlanNotebook initialization."""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config.config import PlanConfig
    from agentscope.plan import PlanNotebook

logger = logging.getLogger(__name__)

_PLAN_AVAILABLE = importlib.util.find_spec("agentscope.plan") is not None


def create_plan_notebook(
    config: "PlanConfig",
    agent_id: str,
    working_dir: Path,
) -> PlanNotebook | None:
    """Instantiate PlanNotebook from PlanConfig.

    Returns None when plan is disabled or the agentscope plan module
    is not available (avoids import-time side effects).
    """
    if not config.enabled:
        return None

    if not _PLAN_AVAILABLE:
        logger.warning(
            "Plan mode is enabled but agentscope.plan is not available. "
            "Please upgrade AgentScope to a version that includes the "
            "plan module. Plan mode will be disabled.",
        )
        return None

    from .storage import FilePlanStorage

    storage = None
    if config.storage_type == "file":
        storage_path = config.storage_path
        if storage_path is None:
            storage_path = str(working_dir / "plans" / agent_id)
        storage = FilePlanStorage(storage_path=storage_path)

    from .hints import QwenPawPlanToHint
    from .notebook import QwenPawPlanNotebook

    plan_to_hint = None
    if QwenPawPlanToHint is not None:
        plan_to_hint = QwenPawPlanToHint()

    notebook = QwenPawPlanNotebook(
        max_subtasks=config.max_subtasks,
        storage=storage,
        plan_to_hint=plan_to_hint,
    )
    if plan_to_hint is not None:
        plan_to_hint.bind_notebook(notebook)
    return notebook
