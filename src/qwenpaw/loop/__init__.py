# -*- coding: utf-8 -*-
"""Loop engineering infrastructure package.

Core architecture:
    StopHandler + StopGate (in gates/ sub-package)
    ├── DoomLoopGate  — multi-stage repetition detection
    ├── RubricGate    — rubric-based evaluation (GoalMode)
    ├── IterationGate — iteration limit (GoalMode)
    └── BudgetGate    — token budget (GoalMode)

Hooks:
    LoopIterBypassHook  — lifts ReAct max_iters during loop
    LoopIterRestoreHook — restores original max_iters
"""

from .gates import (
    DoomLoopGate,
    GoalStatusRubric,
    RubricStrategy,
    RubricVerdict,
    StopAction,
    StopGate,
    StopHandler,
    StopHandlerRegistration,
    StopHandlerResult,
)
from .iter_bypass_hook import (
    LoopIterBypassHook,
    LoopIterRestoreHook,
)

__all__ = [
    "DoomLoopGate",
    "GoalStatusRubric",
    "LoopIterBypassHook",
    "LoopIterRestoreHook",
    "RubricStrategy",
    "RubricVerdict",
    "StopAction",
    "StopGate",
    "StopHandler",
    "StopHandlerRegistration",
    "StopHandlerResult",
]
