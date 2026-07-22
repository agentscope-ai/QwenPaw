# -*- coding: utf-8 -*-
"""Gates sub-package for the loop stop handler system.

Public API:
    StopAction, StopGate, LoopGate, FileLoopGate,
    IterationGate, BudgetGate, DoomLoopGate,
    StopHandler, StopHandlerResult, StopHandlerRegistration,
    RubricStrategy, GoalStatusRubric, RubricVerdict,
    RubricEvaluation, DefaultRubric, SubAgentRubric.
"""
from .base import (
    StopAction,
    StopGate,
    StopHandlerRegistration,
    StopHandlerResult,
)
from .budget import BudgetGate
from .completion import CompletionRubricGate
from .configured import ConfiguredGate
from .doom_loop import DoomLoopGate
from .file_loop_gate import FileLoopGate
from .handler import StopHandler
from .iteration import IterationGate
from .limits import TimeoutGate, TokenBudgetGate, ToolCallBudgetGate
from .runner import run_stop_handlers
from .loop_gate import LoopGate
from .rubric import (
    QualitativeRubricGate,
    DefaultRubric,
    GoalStatusRubric,
    RubricEvaluation,
    RubricStrategy,
    RubricVerdict,
    SubAgentRubric,
)

__all__ = [
    "BudgetGate",
    "CompletionRubricGate",
    "ConfiguredGate",
    "QualitativeRubricGate",
    "DefaultRubric",
    "DoomLoopGate",
    "FileLoopGate",
    "GoalStatusRubric",
    "IterationGate",
    "LoopGate",
    "RubricEvaluation",
    "RubricStrategy",
    "RubricVerdict",
    "StopAction",
    "StopGate",
    "StopHandler",
    "StopHandlerRegistration",
    "StopHandlerResult",
    "SubAgentRubric",
    "TimeoutGate",
    "TokenBudgetGate",
    "ToolCallBudgetGate",
    "run_stop_handlers",
]
