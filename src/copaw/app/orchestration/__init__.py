# -*- coding: utf-8 -*-
"""Workflow orchestration module.

This module provides workflow-based multi-agent orchestration capabilities,
allowing users to define and execute workflows that coordinate multiple
agents to accomplish complex tasks.

Key components:
- WorkflowEngine: Executes workflows by invoking agents
- WorkflowDefinition: Schema for workflow YAML files
- WorkflowExecutionResult: Results of workflow execution
"""

from .engine import WorkflowEngine
from .schema import (
    StepResult,
    StepStatus,
    WorkflowDefinition,
    WorkflowExecutionRequest,
    WorkflowExecutionResult,
    WorkflowExecutionStatus,
    WorkflowStep,
)

__all__ = [
    "WorkflowEngine",
    "WorkflowDefinition",
    "WorkflowExecutionRequest",
    "WorkflowExecutionResult",
    "WorkflowExecutionStatus",
    "WorkflowStep",
    "StepResult",
    "StepStatus",
]
