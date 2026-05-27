# -*- coding: utf-8 -*-
"""DataPaw orchestration layer: TaskGraph data model + runtime state manager.

Exports:
- ``TaskNode`` / ``TaskGraph`` / ``NodeOutput`` / ``FileRef``: DAG types
- ``ArtifactItem``: session-level file-artifact index entry
- ``TaskEvent`` / ``TaskEventType``: SSE event model
- ``DefaultGraphToHint``: hint generator
- ``RuntimeStateManager``: runtime state manager
"""

from .artifact import ArtifactItem
from .dag_store import DAGBroadcaster, DAGStore
from .events import TaskEvent, TaskEventType
from .hint import DefaultGraphToHint
from .state import RuntimeStateManager
from .task_graph import (
    FileRef,
    NodeOutput,
    TaskGraph,
    TaskNode,
)

__all__ = [
    "ArtifactItem",
    "DAGBroadcaster",
    "DAGStore",
    "DefaultGraphToHint",
    "FileRef",
    "NodeOutput",
    "RuntimeStateManager",
    "TaskEvent",
    "TaskEventType",
    "TaskGraph",
    "TaskNode",
]
