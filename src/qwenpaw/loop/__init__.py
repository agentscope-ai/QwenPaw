# -*- coding: utf-8 -*-
"""Loop engineering infrastructure package.

Core architecture:
    StopHandler + StopGate (in gates/ sub-package)
    ├── LoopGate      — session-safe base for loop plugins
    ├── DoomLoopGate  — multi-stage repetition detection
    ├── RubricGate    — rubric-based evaluation (GoalMode)
    ├── IterationGate — iteration limit (universal)
    └── BudgetGate    — token budget (GoalMode)
"""

from .gates import (
    DoomLoopGate,
    GoalStatusRubric,
    LoopGate,
    RubricStrategy,
    RubricVerdict,
    StopAction,
    StopGate,
    StopHandler,
    StopHandlerRegistration,
    StopHandlerResult,
)

__all__ = [
    "DoomLoopGate",
    "GoalStatusRubric",
    "LoopGate",
    "RubricStrategy",
    "RubricVerdict",
    "StopAction",
    "StopGate",
    "StopHandler",
    "StopHandlerRegistration",
    "StopHandlerResult",
]
