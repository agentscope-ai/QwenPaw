# -*- coding: utf-8 -*-
"""RuntimeStateManager: TaskGraph state store + agent tool adapter + hooks.

Extends AgentScope's ``PlanNotebook`` with:
- ``TaskGraph`` / ``TaskNode`` replacing ``Plan`` / ``SubTask``
- A session-level append-only ``artifacts`` index
- ``_pending_edits`` so the agent can observe frontend edits / SOP loads
- ``_trigger_msg_id``, set on ``create_plan`` to populate
  ``TaskGraph.anchor_message_id``
- Hook surface: ``_on_graph_change`` (save trigger) and
  ``_sse_event_queue`` (UI fan-out) fired by ``_notify_graph_change``
- Unified archive path (``_archive_current_plan``) shared by the three
  active-graph switch paths
- 8 overridden PlanNotebook tools adapted to ``node_id``, plus a new
  ``reset_downstream``

This module never executes work — execution is driven by DataPawAgent's
reasoning loop. State transitions only.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Coroutine,
    Dict,
    List,
    Literal,
    Optional,
    TYPE_CHECKING,
)

from collections import OrderedDict

from agentscope.message import Msg, TextBlock
from agentscope.plan import (
    InMemoryPlanStorage,
    PlanNotebook,
    PlanStorageBase,
)
from agentscope.tool import ToolResponse
from pydantic import ValidationError

from .artifact import ArtifactItem
from .events import TaskEvent, TaskEventType
from .hint import DefaultGraphToHint
from .task_graph import FileRef, TaskGraph, TaskNode

FilesInput = Optional[
    List[FileRef] | List[Dict[str, str]] | Dict[str, str] | str
]


class InMemoryTaskGraphStorage(InMemoryPlanStorage):
    """DataPaw flavor of ``InMemoryPlanStorage``.

    The base class registers ``plans`` to deserialize via
    ``Plan.model_validate``, which drops TaskGraph's extended fields and
    fails on missing ``subtasks``. We re-register the state with
    ``TaskGraph.model_validate`` instead.
    """

    def __init__(self) -> None:
        super().__init__()
        self.register_state(
            "plans",
            custom_to_json=lambda plans: {
                k: v.model_dump(mode="json") for k, v in plans.items()
            },
            custom_from_json=lambda json_data: OrderedDict(
                (k, TaskGraph.model_validate(v))
                for k, v in (json_data or {}).items()
            ),
        )

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

try:
    # Prefer agentscope_runtime's RunStatus; fall back to a local mirror
    # (kept aligned with agent_schemas.RunStatus) in dev/test environments
    # where the runtime package isn't importable.
    from agentscope_runtime.engine.schemas.agent_schemas import RunStatus
except Exception:  # pragma: no cover - defensive

    class RunStatus:  # type: ignore[no-redef]
        Created = "created"
        InProgress = "in_progress"
        Completed = "completed"
        Canceled = "canceled"
        Failed = "failed"
        Rejected = "rejected"
        Unknown = "unknown"
        Queued = "queued"
        Incomplete = "incomplete"


def _text(msg: str) -> ToolResponse:
    """Build a plain-text ``ToolResponse``."""
    return ToolResponse(content=[TextBlock(type="text", text=msg)])


class RuntimeStateManager(PlanNotebook):
    """DataPaw runtime state: one active graph + history + artifact index."""

    description: str = (
        "DataPaw task graph management tools. Use these to create a DAG "
        "of analysis tasks (create_plan), track node execution "
        "(update_subtask_state, finish_subtask), revise nodes and "
        "propagate STALE downstream (revise_current_plan), reset "
        "downstream subtrees (reset_downstream), and archive the current graph "
        "(finish_plan). Ready-to-execute node hints are injected "
        "automatically each reasoning round — follow them."
    )

    def __init__(
        self,
        storage: Optional[PlanStorageBase] = None,
        graph_to_hint: Optional[Callable] = None,
    ) -> None:
        """Args:
            storage: Backing store for historical TaskGraphs. Defaults to in-memory.
            graph_to_hint: Hint generator; defaults to :class:`DefaultGraphToHint`.
        """
        super().__init__(
            plan_to_hint=graph_to_hint or DefaultGraphToHint(),
            storage=storage or InMemoryTaskGraphStorage(),
        )

        # Extension fields.
        self.artifacts: List[ArtifactItem] = []
        self._pending_edits: list[dict] = []
        self._trigger_msg_id: str = ""
        self.path_resolver: Callable[[str], Path] | None = None

        # Hook slots; set at runtime by AgentRunner / DataPawAgent.
        self._on_graph_change: Callable[[], Awaitable[None]] | None = None
        self._sse_event_queue: asyncio.Queue | None = None

        # Re-register ``current_plan`` so deserialization goes through
        # ``TaskGraph.model_validate``. ``register_state`` overwrites the
        # entry in ``_attribute_dict``, so we can safely re-register here.
        self.register_state(
            "current_plan",
            custom_to_json=lambda g: g.model_dump(mode="json") if g else None,
            custom_from_json=lambda d: (
                TaskGraph.model_validate(d) if d else None
            ),
        )
        self.register_state(
            "artifacts",
            custom_to_json=lambda items: [
                item.model_dump(mode="json") for item in (items or [])
            ],
            custom_from_json=lambda data: [
                ArtifactItem.model_validate(item) for item in (data or [])
            ],
        )
        self.register_state("_pending_edits")

    # --- trigger_msg_id ----------------------------------------------------

    def set_trigger_msg_id(self, msg_id: str) -> None:
        """Set the triggering message ID, used to populate ``anchor_message_id``."""
        self._trigger_msg_id = msg_id

    # --- Hook plumbing -----------------------------------------------------

    async def _notify_graph_change(self, event_type: str) -> None:
        """Fan-out a graph-change event.

        Two things happen here:
        1. Call ``_on_graph_change()`` → host triggers a mid-flight save.
        2. Construct a ``TaskEvent`` and push it on ``_sse_event_queue`` →
           reaches the SSE stream consumed by the frontend.
        """
        if self._on_graph_change is not None:
            try:
                await self._on_graph_change()
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "RuntimeStateManager: _on_graph_change hook raised; "
                    "continuing",
                    exc_info=True,
                )

        if self._sse_event_queue is not None:
            graph_snapshot: Optional[dict] = None
            if self.current_plan is not None:
                graph_snapshot = self.current_plan.model_dump(mode="json")
            try:
                event = TaskEvent(
                    event_type=event_type,
                    status=self._resolve_graph_run_status(),
                    graph_snapshot=graph_snapshot,
                )
                self._sse_event_queue.put_nowait(event)
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "RuntimeStateManager: SSE queue put failed; "
                    "dropping event",
                    exc_info=True,
                )

    def _resolve_graph_run_status(self) -> str:
        """Map ``TaskGraph.state`` to a RunStatus string."""
        if self.current_plan is None:
            return RunStatus.Unknown
        state = self.current_plan.state
        return {
            "todo": RunStatus.Created,
            "in_progress": RunStatus.InProgress,
            "done": RunStatus.Completed,
            "abandoned": RunStatus.Canceled,
        }.get(state, RunStatus.InProgress)

    # --- Frontend-edit support ---------------------------------------------

    def pop_pending_edits(self) -> list[dict]:
        """Take and clear the queued frontend edit records.

        ``DataPawAgent.reply()`` calls this before entering the ReAct
        loop and renders the edits into a memory-visible change summary.
        """
        edits = self._pending_edits[:]
        self._pending_edits = []
        return edits

    # --- Active-graph lifecycle --------------------------------------------

    async def _archive_current_plan(self, reason: str = "") -> None:
        """Archive the current active graph to storage (single archive path).

        - Mark the graph abandoned (with ``reason``) if it isn't already
          done / abandoned.
        - Set ``current_plan = None`` afterwards.
        - ``artifacts`` are session-level (append-only) and NOT cleared.
        - Fires ``_notify_graph_change(GRAPH_ARCHIVED)``.

        Called from all three active-graph switch paths: ``create_plan``
        (agent creates a new graph), ``load_graph`` (REST SOP upload),
        and ``recover_historical_plan`` (resume an archived graph).
        """
        plan = self.current_plan
        if plan is None:
            return

        if plan.state not in ("done", "abandoned"):
            plan.finish(
                "abandoned",
                reason or "Replaced by a new task graph.",
            )

        await self.storage.add_plan(plan)

        # Emit GRAPH_ARCHIVED before clearing current_plan so the snapshot
        # carries the now-archived graph rather than nothing.
        await self._notify_graph_change(TaskEventType.GRAPH_ARCHIVED)

        self.current_plan = None

    async def load_graph(self, graph: TaskGraph) -> None:
        """Install a TaskGraph as the active graph.

        Archives any existing active graph first. ``artifacts`` are
        preserved across the swap. Main use case: REST SOP upload, which
        parses an SOP into a TaskGraph and hands it off here so it
        reaches the session file.
        """
        await self._archive_current_plan(
            reason=f"Replaced by loaded graph '{graph.name}'.",
        )
        self.current_plan = graph
        await self._notify_graph_change(TaskEventType.GRAPH_CREATED)

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore full state (TaskGraph + artifacts) from a ``state_dict``.

        Delegates to ``StateModule.load_state_dict`` to avoid maintaining
        a separate serialization path; ``strict=False`` tolerates schema
        drift across versions.
        """
        self.load_state_dict(state, strict=False)

    # --- Artifact bookkeeping ----------------------------------------------

    def _stat_size_bytes(self, rel_path: str) -> int:
        """Resolve ``rel_path`` and read its size; returns 0 + warning on failure."""
        if self.path_resolver is None:
            logger.warning(
                "RuntimeStateManager: no path resolver for artifact path %r",
                rel_path,
            )
            return 0
        try:
            path = self.path_resolver(rel_path)
            return path.stat().st_size
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "RuntimeStateManager: failed to stat artifact path %r",
                rel_path,
                exc_info=True,
            )
            return 0

    def _record_files(
        self,
        *,
        graph_id: str,
        node_id: str,
        files: Optional[List[FileRef]],
    ) -> int:
        """Append the node's FileRefs to the session-level artifact list."""
        if not files:
            return 0
        count = 0
        for file_ref in files:
            self.artifacts.append(
                ArtifactItem(
                    graph_id=graph_id,
                    node_id=node_id,
                    name=file_ref.name,
                    path=file_ref.path,
                    mime_type=file_ref.mime_type,
                    size_bytes=self._stat_size_bytes(file_ref.path),
                ),
            )
            count += 1
        return count

    def _normalize_files(
        self,
        files: FilesInput,
    ) -> List[FileRef]:
        """Normalize ``files`` tool argument into a ``List[FileRef]``.

        AgentScope tool calls may pass nested Pydantic args as plain dicts;
        some LLMs also serialize the list as a JSON string. We funnel
        everything through ``FileRef`` so downstream code can always
        access ``file_ref.name`` without surprises.
        """
        if not files:
            return []
        if isinstance(files, str):
            try:
                files = json.loads(files)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "files must be a JSON array/object when provided as a "
                    "string.",
                ) from exc
        if isinstance(files, dict):
            files = [files]
        if not isinstance(files, list):
            raise ValueError(
                "files must be a list of FileRef objects, a single FileRef "
                "object, or a JSON string containing either shape.",
            )
        return [
            file_ref
            if isinstance(file_ref, FileRef)
            else FileRef.model_validate(file_ref)
            for file_ref in files
        ]

    # --- Agent tools (DAG-adapted overrides) -------------------------------

    async def create_plan(  # type: ignore[override]
        self,
        name: str,
        description: str,
        expected_outcome: str,
        nodes: List[TaskNode],
    ) -> ToolResponse:
        """Create a new analysis task graph (DAG).

        Call this when the user's request requires multiple analytical
        steps (data fetching, transformation, analysis, report). If an
        active task graph already exists, it will be archived as
        'abandoned' before the new graph replaces it.

        Args:
            name: Short, descriptive graph name (<= 10 words).
            description: Constraints, target, and measurable outcome.
            expected_outcome: Specific, concrete final deliverable.
            nodes: List of TaskNode objects. Each node must have a
                unique node_id and list its deps (other node_ids it
                depends on). Leaf nodes have deps=[].
        """
        replaced_msg = ""
        if self.current_plan is not None:
            old_name = self.current_plan.name
            await self._archive_current_plan(
                reason=(
                    f"Replaced by a new task graph '{name}'."
                ),
            )
            replaced_msg = (
                f"The previous graph '{old_name}' was archived. "
            )

        graph = TaskGraph(
            name=name,
            description=description,
            expected_outcome=expected_outcome,
            anchor_message_id=self._trigger_msg_id,
        )
        for n in nodes:
            if not isinstance(n, TaskNode):
                n = TaskNode.model_validate(n)
            # node_id may be omitted; TaskNode supplies a default_factory.
            graph.add_node(n)

        self.current_plan = graph
        await self._notify_graph_change(TaskEventType.GRAPH_CREATED)

        return _text(
            f"{replaced_msg}Task graph '{name}' created with "
            f"{len(graph.nodes)} node(s). "
            f"Graph ID: {graph.id}",
        )

    async def view_subtasks(  # type: ignore[override]
        self,
        node_ids: List[str],
    ) -> ToolResponse:
        """View detailed information about one or more nodes.

        Args:
            node_ids: List of node_id strings to inspect.
        """
        if self.current_plan is None:
            return _text("No active task graph.")

        parts: List[str] = []
        unknown: List[str] = []
        for nid in node_ids:
            node = self.current_plan.nodes.get(nid)
            if node is None:
                unknown.append(nid)
                continue
            parts.append(
                f"Node `{nid}`:\n```\n{node.to_markdown(detailed=True)}\n```",
            )
        if unknown:
            parts.append(f"Unknown node_ids: {unknown}")
        return _text("\n\n".join(parts) if parts else "Nothing to show.")

    async def update_subtask_state(  # type: ignore[override]
        self,
        node_id: str,
        state: Literal[
            "todo",
            "in_progress",
            "failed",
            "abandoned",
        ],
        error: Optional[str] = None,
    ) -> ToolResponse:
        """Update the status of a DAG node.

        Use this when transitioning a node to 'in_progress' before
        executing its work, or marking it 'failed' / 'abandoned'. To
        mark a node as done, use finish_subtask instead so the
        structured output is recorded.

        Args:
            node_id: ID of the node to update.
            state: Target state. Note 'done' is NOT allowed here —
                use finish_subtask instead.
            error: Required when state='failed'; describes why.
        """
        if self.current_plan is None:
            return _text(
                "No active task graph. Call create_plan first.",
            )

        node = self.current_plan.nodes.get(node_id)
        if node is None:
            return _text(f"Node '{node_id}' not found.")

        if state not in ("todo", "in_progress", "failed", "abandoned"):
            return _text(
                f"Invalid state '{state}'. Must be one of "
                "todo/in_progress/failed/abandoned.",
            )

        # Enforce single-in-progress: marking two nodes in_progress in
        # one reasoning round would bind their traces to the wrong nodes.
        if state == "in_progress" and node.state != "in_progress":
            existing_in_progress = [
                n.node_id for n in self.current_plan.nodes.values()
                if n.state == "in_progress" and n.node_id != node_id
            ]
            if existing_in_progress:
                return _text(
                    f"已有节点 {existing_in_progress} 正在执行。"
                    f"请先完成当前节点（调用 finish_subtask 或 update_subtask_state 设置为 done/failed），"
                    f"再开始执行节点 '{node_id}'。"
                )

        if state == "failed":
            node.fail(error or "(no error message provided)")
        else:
            if state == "in_progress":
                node.clear_trace()
            # Reverting from done/abandoned back to todo is allowed.
            node.state = state
            if state == "in_progress":
                from agentscope._utils._common import _get_timestamp
                node.started_at = _get_timestamp()
            if state == "todo":
                node.error = None
                node.started_at = None

        suffix = self.current_plan.refresh_state()
        await self._notify_graph_change(TaskEventType.GRAPH_UPDATED)
        return _text(
            f"Node '{node_id}' marked as '{state}'. " + suffix,
        )

    async def finish_subtask(  # type: ignore[override]
        self,
        node_id: str,
        reasoning: str,
        summary: str,
        files: FilesInput = None,
    ) -> ToolResponse:
        """Mark a node as done and record its structured output.

        Args:
            node_id: ID of the node to finish.
            reasoning: How the work was done (method, rationale).
            summary: What the result is (conclusion, data highlights).
            files: Optional list of FileRef objects (charts, excel, pdf,
                etc.). Provide name / path / mime_type only; file size is
                measured by the backend automatically. Prefer a structured
                array, not a string; JSON strings are accepted only for
                recovery from malformed model output.
        """
        if self.current_plan is None:
            return _text(
                "No active task graph. Call create_plan first.",
            )
        node = self.current_plan.nodes.get(node_id)
        if node is None:
            return _text(f"Node '{node_id}' not found.")

        try:
            file_refs = self._normalize_files(files)
        except (ValueError, ValidationError) as exc:
            return _text(
                "Invalid files argument for finish_subtask. Use files as a "
                "structured array, not a plain string: "
                '[{"name": "result.csv", "path": "...", '
                '"mime_type": "text/csv"}]. '
                f"Details: {exc}",
            )

        node.finish_with_output(
            reasoning=reasoning,
            summary=summary,
            files=file_refs,
        )
        file_count = self._record_files(
            graph_id=self.current_plan.id,
            node_id=node_id,
            files=file_refs,
        )

        suffix = self.current_plan.refresh_state()
        await self._notify_graph_change(TaskEventType.GRAPH_UPDATED)
        return _text(
            f"Node '{node_id}' marked as done. "
            f"Recorded {file_count} file(s). {suffix}",
        )

    async def revise_current_plan(  # type: ignore[override]
        self,
        node_id: str,
        action: Literal["add", "revise", "delete"],
        node: Optional[TaskNode] = None,
    ) -> ToolResponse:
        """Add / revise / delete a node in the active graph.

        For 'revise', the node will be overwritten, marked STALE, and
        STALE will propagate to all downstream nodes.
        For 'add', a new node is inserted (no STALE impact).
        For 'delete', the node is removed and also pruned from other
        nodes' deps lists.

        Args:
            node_id: Target node_id (for 'add': the new node's id
                will override this if mismatched).
            action: 'add' / 'revise' / 'delete'.
            node: Required for 'add' and 'revise'; the new TaskNode.
        """
        if self.current_plan is None:
            return _text("No active task graph.")

        if action in ("add", "revise") and node is None:
            return _text(
                f"action='{action}' requires a 'node' argument.",
            )

        if node is not None and not isinstance(node, TaskNode):
            node = TaskNode.model_validate(node)

        if action == "delete":
            removed = self.current_plan.remove_node(node_id)
            if removed is None:
                return _text(f"Node '{node_id}' not found.")
            await self._notify_graph_change(TaskEventType.GRAPH_UPDATED)
            return _text(f"Node '{node_id}' deleted.")

        if action == "add":
            if node is None:  # defensive (already validated above)
                return _text("Missing 'node' for action 'add'.")
            node.node_id = node.node_id or node_id
            if node.node_id in self.current_plan.nodes:
                return _text(
                    f"Cannot add: node '{node.node_id}' already exists.",
                )
            self.current_plan.add_node(node)
            await self._notify_graph_change(TaskEventType.GRAPH_UPDATED)
            return _text(f"Node '{node.node_id}' added.")

        # revise: keep the original node_id and force STALE so downstream
        # cascade triggers regardless of what the LLM passed in.
        if node_id not in self.current_plan.nodes:
            return _text(f"Node '{node_id}' not found.")
        assert node is not None
        node.node_id = node_id
        if node.state not in ("todo", "stale", "abandoned"):
            node.state = "stale"
        elif node.state == "todo":
            node.state = "stale"
        self.current_plan.replace_node(node_id, node)
        stale_ids = self.current_plan.mark_downstream_stale(node_id)

        await self._notify_graph_change(TaskEventType.GRAPH_UPDATED)
        return _text(
            f"Node '{node_id}' revised and marked STALE. "
            f"Downstream nodes also marked STALE: {stale_ids}",
        )

    async def finish_plan(  # type: ignore[override]
        self,
        state: Literal["done", "abandoned"],
        outcome: str,
    ) -> ToolResponse:
        """Finish the active graph with an outcome (or abandon it).

        The graph is archived to storage. ``artifacts`` are NOT cleared
        because they are a session-level file index.

        Args:
            state: 'done' for successful completion, 'abandoned' for
                user-cancelled or no-longer-needed.
            outcome: Final report summary (if 'done') or abandonment
                reason (if 'abandoned').
        """
        if self.current_plan is None:
            return _text("No active task graph to finish.")

        self.current_plan.finish(state, outcome)
        await self.storage.add_plan(self.current_plan)
        await self._notify_graph_change(TaskEventType.GRAPH_FINISHED)
        self.current_plan = None
        return _text(f"Task graph finished as '{state}'.")

    async def recover_historical_plan(  # type: ignore[override]
        self,
        plan_id: str,
    ) -> ToolResponse:
        """Recover a previously finished/abandoned task graph.

        Archives the current active graph first (if any), then brings
        the historical graph back as the active one.

        Args:
            plan_id: ID of the historical graph to recover.
        """
        historical = await self.storage.get_plan(plan_id)
        if historical is None:
            return _text(f"Historical plan '{plan_id}' not found.")

        await self._archive_current_plan(
            reason=f"Replaced by recovered plan '{historical.name}'.",
        )

        # Some storage backends drop the subclass on round-trip, so
        # re-validate to guarantee we hand back a TaskGraph.
        if not isinstance(historical, TaskGraph):
            historical = TaskGraph.model_validate(historical.model_dump())

        # If the recovered graph still has unfinished nodes, flip it
        # back to ``in_progress`` and wipe the previously-set ``finished``
        # fields so the LLM sees it as resumable.
        self.current_plan = historical
        if any(
            n.state not in ("done", "abandoned")
            for n in historical.nodes.values()
        ):
            historical.state = "in_progress"
            historical.finished_at = None
            historical.outcome = None

        await self._notify_graph_change(TaskEventType.GRAPH_CREATED)
        return _text(
            f"Historical graph '{historical.name}' (id={plan_id}) "
            "recovered as the active graph.",
        )

    # --- DAG-specific tool -------------------------------------------------

    async def reset_downstream(self, node_id: str) -> ToolResponse:
        """Reset a node and all its downstream to 'todo'.

        Useful when you want to re-run a subtree after changing a
        parameter. The target node itself is also reset.

        Args:
            node_id: The root of the subtree to reset.
        """
        if self.current_plan is None:
            return _text("No active task graph.")
        if node_id not in self.current_plan.nodes:
            return _text(f"Node '{node_id}' not found.")

        targets = [node_id] + self.current_plan._find_downstream_nodes(
            node_id,
        )
        reset: List[str] = []
        for nid in targets:
            node = self.current_plan.nodes[nid]
            if node.state in ("done", "in_progress", "failed", "stale"):
                node.state = "todo"
                node.error = None
                node.started_at = None
                node.output = None
                reset.append(nid)

        await self._notify_graph_change(TaskEventType.GRAPH_UPDATED)
        return _text(f"Reset nodes: {reset}")

    # --- Tool listing ------------------------------------------------------

    def list_tools(
        self,
    ) -> List[Callable[..., Coroutine[Any, Any, ToolResponse]]]:
        """Return all 9 agent tools (8 inherited overrides + 1 new).

        Note on the type-hint resolution dance below: this module uses
        ``from __future__ import annotations``, so method signatures
        carry ``List`` / ``Optional`` / ``Literal`` as strings at runtime.
        agentscope's ``_parse_tool_function`` does not pass the module's
        ``__globals__`` to pydantic, so pydantic raises
        ``PydanticUserError: ... is not fully defined`` when building
        ``_StructuredOutputDynamicClass``. That error is swallowed by
        ``DataPawAgent`` and the tool silently disappears. We pre-resolve
        each tool function's annotations via ``typing.get_type_hints``
        before returning the list to sidestep the issue.
        """
        import typing

        tools = [
            self.create_plan,
            self.finish_plan,
            self.revise_current_plan,
            self.view_subtasks,
            self.update_subtask_state,
            self.finish_subtask,
            self.view_historical_plans,
            self.recover_historical_plan,
            self.reset_downstream,
        ]
        for bound_method in tools:
            fn = getattr(bound_method, "__func__", bound_method)
            if getattr(fn, "_datapaw_annotations_resolved", False):
                continue
            try:
                fn.__annotations__ = typing.get_type_hints(fn)
                fn._datapaw_annotations_resolved = True
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "Failed to resolve type hints for tool '%s'; "
                    "agentscope may fail to register it.",
                    getattr(fn, "__name__", repr(fn)),
                    exc_info=True,
                )
        return tools

    # --- Hint generation ---------------------------------------------------
    # plan_to_hint is set to DefaultGraphToHint in __init__; parent's
    # plan_to_hint accepts a Plan, and DefaultGraphToHint accepts our
    # TaskGraph (a Plan subclass) without further adaptation.

    async def get_current_hint(self) -> Msg | None:  # type: ignore[override]
        """Produce the DAG-state hint, called before each ``_reasoning`` turn."""
        hint_content = self.plan_to_hint(self.current_plan)
        if hint_content:
            return Msg("user", hint_content, "user")
        return None

    # --- Trace collection (called by DataPawAgent) -------------------------

    def append_to_trace(self, msg: Msg) -> None:
        """Append a message to the currently in-progress node's trace."""
        if not self.current_plan:
            return

        for node in self.current_plan.nodes.values():
            if node.state == "in_progress":
                node.append_to_trace(msg)
                return
