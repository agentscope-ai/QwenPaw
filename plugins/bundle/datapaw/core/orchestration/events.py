# -*- coding: utf-8 -*-
"""TaskEvent — SSE event model for DataPaw TaskGraph state changes.

Reuses QwenPaw / AgentScope Runtime's ``Event`` base so it sits beside
Message (``object="message"``), Content (``object="content"``) and
BaseResponse (``object="response"``). The frontend routes by
``object == "task_status"`` and uses ``graph_snapshot`` to fully replace
the DAG view — no client-side merge logic.

Event types:
- ``graph_created``: new graph from ``create_plan`` / ``load_graph`` /
  ``recover_historical_plan``
- ``graph_updated``: node-level change from ``update_subtask_state`` /
  ``finish_subtask`` / ``revise_current_plan`` / ``reset_downstream``
- ``graph_finished``: graph closed via ``finish_plan``
- ``graph_archived``: active graph replaced by a new graph
"""
from typing import Optional

from agentscope_runtime.engine.schemas.agent_schemas import Event


class TaskEventType:
    """Event-type constants for TaskGraph state changes."""

    GRAPH_CREATED = "graph_created"
    GRAPH_UPDATED = "graph_updated"
    GRAPH_FINISHED = "graph_finished"
    GRAPH_ARCHIVED = "graph_archived"


class TaskEvent(Event):
    """SSE event carrying a DataPaw TaskGraph state change.

    Wire format: ``data: {task_event.model_dump_json()}\\n\\n``.

    Inherited fields (serialized automatically):
    - ``sequence_number``: SSE-stream sequence number
    - ``status``: reused ``RunStatus``, describing the graph-level state
      (``in_progress`` / ``completed`` / ``canceled``)
    - ``error``: reused ``Error`` model for graph-level errors
    """

    object: str = "task_status"

    event_type: str
    """Change type; see :class:`TaskEventType`. Used for logging / debug."""

    graph_snapshot: Optional[dict] = None
    """Post-change TaskGraph snapshot; the frontend replaces the DAG view with it."""
