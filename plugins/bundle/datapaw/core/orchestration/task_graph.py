# -*- coding: utf-8 -*-
"""DAG data model: TaskGraph / TaskNode / NodeOutput / FileRef.

Extends AgentScope's ``SubTask`` / ``Plan`` with:
- DAG dependencies (``TaskNode.deps``)
- Two extra states (``failed``, ``stale``)
- File outputs (``NodeOutput.files``)
- STALE cascade propagation (``TaskGraph.mark_downstream_stale``)
- YAML round-trip (``TaskGraph.to_yaml`` / ``from_yaml``)
- Trigger-message tracking (``TaskGraph.anchor_message_id``)

``TaskGraph.nodes`` is the authoritative store; ``subtasks`` is derived
from it for parent-class compatibility and excluded from serialization
to avoid duplicate data.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import shortuuid
import yaml
from agentscope._utils._common import _get_timestamp
from agentscope.message import Msg
from agentscope.plan import Plan, SubTask
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# NodeOutput / FileRef
# ---------------------------------------------------------------------------


class FileRef(BaseModel):
    """A file emitted by a node (chart / Excel / PDF / ...)."""

    name: str = Field(description="File name, e.g. ``dau_trend.png``.")
    path: str = Field(
        description=(
            "Sandbox-relative path (relative to the sandbox mount"
            " root, e.g. ``/workspace``)."
        ),
    )
    mime_type: str = Field(description="MIME type, e.g. ``image/png``.")


class NodeOutput(BaseModel):
    """Structured output of a node.

    ``reasoning`` and ``summary`` are inlined for hint rendering and quick
    display; ``files`` lists artifacts produced by the node.
    """

    reasoning: str = Field(
        description="How it was done: method, basis, key judgments.",
    )
    summary: str = Field(
        description="What was found: conclusions, data characteristics.",
    )
    files: List[FileRef] = Field(
        default_factory=list,
        description="Files emitted by the node (chart / Excel / PDF / ...).",
    )


# ---------------------------------------------------------------------------
# TaskNode
# ---------------------------------------------------------------------------

# TaskNode states: parent ``SubTask`` 4-state set plus ``failed`` / ``stale``.
NodeStatus = Literal[
    "todo",
    "in_progress",
    "done",
    "failed",
    "stale",
    "abandoned",
]

PlanChangeAction = Literal["add", "revise", "delete"]


class TaskNode(SubTask):
    """DAG execution unit; extends ``SubTask``."""

    state: NodeStatus = Field(
        default="todo",
        description=(
            "Node state (todo/in_progress/done/failed/stale/abandoned)."
        ),
    )

    node_id: str = Field(
        default_factory=lambda: "node_" + shortuuid.uuid()[:8],
        description="Node ID (DAG dependency key).",
    )
    deps: List[str] = Field(
        default_factory=list,
        description="Upstream node IDs this node depends on.",
    )
    started_at: Optional[str] = Field(
        default=None,
        description="Execution start timestamp.",
    )
    output: Optional[NodeOutput] = Field(
        default=None,
        description="Structured output (populated after the node completes).",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message (only when state == 'failed').",
    )

    def __init__(self, **data) -> None:
        trace_data = data.pop("trace", None)
        super().__init__(**data)
        # Non-Pydantic field: holds raw ``Msg`` objects (or already-serialized
        # dicts when loaded from JSON). Converted to dicts at dump time.
        self._raw_trace: List[Any] = list(trace_data or [])

    def clear_trace(self) -> None:
        self._raw_trace = []

    def append_to_trace(self, msg: Msg) -> None:
        self._raw_trace.append(msg)

    def model_dump(self, **kwargs) -> dict:
        """Include ``trace`` in serialized output."""
        data = super().model_dump(**kwargs)
        if self._raw_trace:
            data["trace"] = [
                m.to_dict() if hasattr(m, "to_dict") else m
                for m in self._raw_trace
            ]
        return data

    def finish_with_output(
        self,
        reasoning: str,
        summary: str,
        files: Optional[List[FileRef]] = None,
    ) -> None:
        """Mark the node ``done`` and record its structured output.

        The ``_with_output`` suffix avoids clashing with the parent
        ``finish(outcome: str)`` signature, which is used by the
        PlanNotebook built-in tool. DataPaw drives finish through
        RuntimeStateManager and calls this method directly.
        """
        self.state = "done"
        self.error = None
        self.output = NodeOutput(
            reasoning=reasoning,
            summary=summary,
            files=files or [],
        )
        self.outcome = summary  # keep parent ``outcome`` field in sync
        self.finished_at = _get_timestamp()

    def fail(self, error: str) -> None:
        self.state = "failed"
        self.error = error
        self.finished_at = _get_timestamp()

    def mark_stale(self) -> None:
        # Terminal states (done / abandoned) never become stale.
        if self.state in ("todo", "in_progress", "failed"):
            self.state = "stale"

    def to_markdown(self, detailed: bool = False) -> str:
        status_map = {
            "todo": "- [ ] ",
            "in_progress": "- [ ] [WIP]",
            "done": "- [x] ",
            "failed": "- [!] [FAILED]",
            "stale": "- [ ] [STALE]",
            "abandoned": "- [ ] [Abandoned]",
        }
        prefix = status_map.get(self.state, "- [ ] ")
        header = f"{prefix}{self.name} (`{self.node_id}`)"

        if not detailed:
            return header

        lines = [
            header,
            f"\t- State: {self.state}",
            f"\t- Deps: {self.deps or '[]'}",
            f"\t- Description: {self.description}",
            f"\t- Expected Outcome: {self.expected_outcome}",
        ]
        if self.started_at:
            lines.append(f"\t- Started At: {self.started_at}")
        if self.state == "done" and self.output is not None:
            lines.extend(
                [
                    f"\t- Reasoning: {self.output.reasoning}",
                    f"\t- Summary: {self.output.summary}",
                ],
            )
            if self.output.files:
                files_desc = ", ".join(f.name for f in self.output.files)
                lines.append(f"\t- Files: {files_desc}")
        if self.state == "failed" and self.error:
            lines.append(f"\t- Error: {self.error}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# SOP / DAG schema constants
# ---------------------------------------------------------------------------

_SOP_GRAPH_FIELDS: tuple = ("name", "description", "expected_outcome")
_SOP_NODE_FIELDS: tuple = (
    "node_id",
    "name",
    "description",
    "expected_outcome",
    "deps",
)
_SOP_GRAPH_ALLOWED: frozenset = frozenset(set(_SOP_GRAPH_FIELDS) | {"nodes"})
_SOP_GRAPH_FORBIDDEN: frozenset = frozenset(
    {
        "id",
        "anchor_message_id",
        "created_at",
        "finished_at",
        "outcome",
        "state",
    },
)
_SOP_NODE_ALLOWED: frozenset = frozenset(_SOP_NODE_FIELDS)
_SOP_NODE_FORBIDDEN: frozenset = frozenset(
    {
        "state",
        "output",
        "error",
        "started_at",
        "finished_at",
        "outcome",
        "trace",
    },
)

_DAG_TOP_RUNTIME_IGNORED: frozenset = frozenset(
    {
        "id",
        "anchor_message_id",
        "created_at",
        "finished_at",
        "outcome",
        "state",
    },
)
_DAG_NODE_RUNTIME_IGNORED: frozenset = frozenset(
    {
        "created_at",
        "output",
        "error",
        "started_at",
        "finished_at",
        "outcome",
        "trace",
    },
)
_DAG_NODE_ALLOWED: frozenset = frozenset(set(_SOP_NODE_FIELDS) | {"state"})
_DAG_USER_STATES: frozenset = frozenset({"todo", "stale", "abandoned"})
_DAG_BACKEND_STATES: frozenset = frozenset({"done", "in_progress", "failed"})


def _check_deps_and_topology(
    processed_nodes: List[Dict[str, Any]],
    cycle_label: str = "Graph",
) -> None:
    """Reject dangling deps and cycles for an already-validated node list.

    Shared by :func:`_validate_sop_dict` and :func:`_validate_dag_dict`
    after each has done its own per-node field validation. ``cycle_label``
    prefixes the cycle error so the message keeps the SOP / DAG distinction
    the originals had — pass ``"SOP DAG"`` or ``"DAG"`` to match the
    pre-refactor wording.
    """
    node_ids = {n["node_id"] for n in processed_nodes}
    for n in processed_nodes:
        unknown_deps = set(n["deps"]) - node_ids
        if unknown_deps:
            raise ValueError(
                f"Node '{n['node_id']}'"
                f" has unknown deps: {sorted(unknown_deps)}.",
            )

    in_degree: Dict[str, int] = {n["node_id"]: 0 for n in processed_nodes}
    adjacency: Dict[str, List[str]] = {
        n["node_id"]: [] for n in processed_nodes
    }
    for n in processed_nodes:
        for dep in n["deps"]:
            adjacency[dep].append(n["node_id"])
            in_degree[n["node_id"]] += 1

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    visited_count = 0
    while queue:
        cur = queue.pop(0)
        visited_count += 1
        for downstream in adjacency.get(cur, []):
            in_degree[downstream] -= 1
            if in_degree[downstream] == 0:
                queue.append(downstream)

    if visited_count != len(processed_nodes):
        raise ValueError(
            f"{cycle_label} contains a cycle."
            " Check 'deps' for circular references.",
        )


def _validate_sop_dict(  # pylint: disable=too-many-branches
    data: dict,
) -> List[Dict[str, Any]]:
    """Shared SOP validator used by ``Sop.from_dict`` + ``TaskGraph.from_sop``.

    Rejects forbidden runtime fields, unknown fields, dangling deps, and
    cyclic graphs (Kahn). Returns the processed node list with defaults
    filled in (``node_id`` auto-generated, ``deps`` defaulted to ``[]``).
    """
    if not isinstance(data, dict):
        raise ValueError("SOP must be a mapping.")

    forbidden_top = set(data.keys()) & _SOP_GRAPH_FORBIDDEN
    if forbidden_top:
        raise ValueError(
            f"SOP contains forbidden runtime field(s) at graph level: "
            f"{sorted(forbidden_top)}. "
            f"Remove them — these are auto-generated by the system.",
        )

    unknown_top = set(data.keys()) - _SOP_GRAPH_ALLOWED
    if unknown_top:
        raise ValueError(
            f"SOP contains unknown field(s) at graph level: "
            f"{sorted(unknown_top)}. "
            f"Allowed: {sorted(_SOP_GRAPH_ALLOWED)}.",
        )

    nodes_raw = data.get("nodes", [])
    if not isinstance(nodes_raw, list):
        raise ValueError("SOP 'nodes' must be a list.")

    processed_nodes: List[Dict[str, Any]] = []
    for idx, node in enumerate(nodes_raw):
        if not isinstance(node, dict):
            raise ValueError(f"Node at index {idx} is not a mapping: {node!r}")

        forbidden_node = set(node.keys()) & _SOP_NODE_FORBIDDEN
        if forbidden_node:
            raise ValueError(
                f"Node at index {idx} contains forbidden runtime field(s): "
                f"{sorted(forbidden_node)}. Remove them.",
            )

        unknown_node = set(node.keys()) - _SOP_NODE_ALLOWED
        if unknown_node:
            raise ValueError(
                f"Node at index {idx} contains unknown field(s): "
                f"{sorted(unknown_node)}. "
                f"Allowed: {sorted(_SOP_NODE_ALLOWED)}.",
            )

        nid = node.get("node_id") or f"node_{idx:03d}"
        if any(existing["node_id"] == nid for existing in processed_nodes):
            raise ValueError(f"Duplicate node_id in SOP: {nid!r}.")
        n = dict(node)
        n["node_id"] = nid
        n.setdefault("deps", [])
        processed_nodes.append(n)

    _check_deps_and_topology(processed_nodes, cycle_label="SOP DAG")
    return processed_nodes


def _validate_dag_dict(  # pylint: disable=too-many-branches
    data: dict,
) -> List[Dict[str, Any]]:
    """Validate a DAG patch dict; returns processed node list.

    Same shape as SOP, plus an optional per-node ``state`` restricted to
    user-owned values (todo / stale / abandoned). Runtime fields that come
    back via ``GET /dag`` round-trip are silently dropped; unknown fields
    still fail.
    """
    if not isinstance(data, dict):
        raise ValueError("DAG must be a mapping.")

    clean_data = {
        k: v for k, v in data.items() if k not in _DAG_TOP_RUNTIME_IGNORED
    }
    unknown_top = set(clean_data.keys()) - _SOP_GRAPH_ALLOWED
    if unknown_top:
        raise ValueError(
            f"DAG contains unknown field(s) at graph level: "
            f"{sorted(unknown_top)}. Allowed: {sorted(_SOP_GRAPH_ALLOWED)}.",
        )

    nodes_raw = clean_data.get("nodes", [])
    if not isinstance(nodes_raw, list):
        raise ValueError("DAG 'nodes' must be a list.")

    processed_nodes: List[Dict[str, Any]] = []
    for idx, node in enumerate(nodes_raw):
        if not isinstance(node, dict):
            raise ValueError(f"Node at index {idx} is not a mapping: {node!r}")

        clean_node = {
            k: v for k, v in node.items() if k not in _DAG_NODE_RUNTIME_IGNORED
        }
        if (
            "state" in clean_node
            and clean_node["state"] not in _DAG_USER_STATES
        ):
            # ``GET /dag`` round-trip carries backend-owned states (done /
            # in_progress / failed). Treat them as read-only and drop only
            # when the node also carries other runtime fields. A hand-
            # written patch that names a backend state alone still fails.
            if set(node.keys()) & _DAG_NODE_RUNTIME_IGNORED:
                clean_node.pop("state", None)
            else:
                raise ValueError(
                    f"Node at index {idx} has invalid state "
                    f"{clean_node['state']!r};"
                    f" allowed: {sorted(_DAG_USER_STATES)}.",
                )

        unknown_node = set(clean_node.keys()) - _DAG_NODE_ALLOWED
        if unknown_node:
            raise ValueError(
                f"Node at index {idx} contains unknown field(s): "
                f"{sorted(unknown_node)}. "
                f"Allowed: {sorted(_DAG_NODE_ALLOWED)}.",
            )

        nid = clean_node.get("node_id") or f"node_{idx:03d}"
        if any(existing["node_id"] == nid for existing in processed_nodes):
            raise ValueError(f"Duplicate node_id in DAG: {nid!r}.")
        n = dict(clean_node)
        n["node_id"] = nid
        n.setdefault("deps", [])
        processed_nodes.append(n)

    _check_deps_and_topology(processed_nodes, cycle_label="DAG")
    return processed_nodes


def _reject_backend_owned_state_changes(
    data: dict,
    current_states: Dict[str, str],
) -> None:
    """Reject explicit user changes to backend-owned states.

    ``GET /dag`` then ``PUT /dag`` round-trip carries done / in_progress /
    failed; those are tolerated only when they match the current backend
    state for that node.
    """
    nodes_raw = data.get("nodes", []) if isinstance(data, dict) else []
    if not isinstance(nodes_raw, list):
        return

    for idx, node in enumerate(nodes_raw):
        if not isinstance(node, dict) or "state" not in node:
            continue
        state = node["state"]
        if state not in _DAG_BACKEND_STATES:
            continue
        nid = node.get("node_id") or f"node_{idx:03d}"
        if current_states.get(nid) == state:
            continue
        raise ValueError(
            f"Node at index {idx} has invalid state {state!r}; "
            f"allowed: {sorted(_DAG_USER_STATES)}.",
        )


# ---------------------------------------------------------------------------
# Sop / SopNode — pure structural Pydantic types (no runtime fields)
# ---------------------------------------------------------------------------


class SopNode(BaseModel):
    """SOP node: structure only, no runtime state."""

    node_id: Optional[str] = None
    name: str
    description: str
    expected_outcome: str
    deps: List[str] = Field(default_factory=list)


class Sop(BaseModel):
    """SOP: task structure with no runtime fields."""

    name: str
    description: str
    expected_outcome: str
    nodes: List[SopNode] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Sop":
        """Strict validation: reject runtime/unknown/dangling-dep/cyclic."""
        _validate_sop_dict(data)
        nodes_raw = data.get("nodes", [])
        sop_nodes: List[SopNode] = []
        for idx, n in enumerate(nodes_raw):
            nid = n.get("node_id") or f"node_{idx:03d}"
            sop_nodes.append(
                SopNode(
                    node_id=nid,
                    name=n["name"],
                    description=n["description"],
                    expected_outcome=n["expected_outcome"],
                    deps=n.get("deps", []),
                ),
            )
        return cls(
            name=data["name"],
            description=data["description"],
            expected_outcome=data["expected_outcome"],
            nodes=sop_nodes,
        )

    @classmethod
    def from_yaml(cls, yaml_text: str) -> "Sop":
        raw: Any = yaml.safe_load(yaml_text)
        if not isinstance(raw, dict):
            raise ValueError("SOP YAML root must be a mapping.")
        return cls.from_dict(raw)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "expected_outcome": self.expected_outcome,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "name": n.name,
                    "description": n.description,
                    "expected_outcome": n.expected_outcome,
                    "deps": list(n.deps),
                }
                for n in self.nodes
            ],
        }

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            self.to_dict(),
            allow_unicode=True,
            sort_keys=False,
        )


# ---------------------------------------------------------------------------
# Dag / DagNode — user-supplied DAG patch schema
# ---------------------------------------------------------------------------


class DagNode(SopNode):
    """DAG patch node: SOP fields plus a user-overridable ``state``."""

    state: Optional[Literal["todo", "stale", "abandoned"]] = None


class Dag(BaseModel):
    """DAG patch: structure plus user-owned state; ignores backend fields."""

    name: str
    description: str
    expected_outcome: str
    nodes: List[DagNode] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Dag":
        """Parse a DAG patch dict; tolerates ``GET /dag`` round-trip input."""
        processed_nodes = _validate_dag_dict(data)
        clean_data = {
            k: v for k, v in data.items() if k not in _DAG_TOP_RUNTIME_IGNORED
        }
        dag_nodes: List[DagNode] = []
        for n in processed_nodes:
            kwargs = {
                "node_id": n["node_id"],
                "name": n["name"],
                "description": n["description"],
                "expected_outcome": n["expected_outcome"],
                "deps": n.get("deps", []),
            }
            if "state" in n:
                kwargs["state"] = n["state"]
            dag_nodes.append(DagNode(**kwargs))
        return cls(
            name=clean_data["name"],
            description=clean_data["description"],
            expected_outcome=clean_data["expected_outcome"],
            nodes=dag_nodes,
        )

    @classmethod
    def from_yaml(cls, yaml_text: str) -> "Dag":
        raw: Any = yaml.safe_load(yaml_text)
        if not isinstance(raw, dict):
            raise ValueError("DAG YAML root must be a mapping.")
        return cls.from_dict(raw)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "expected_outcome": self.expected_outcome,
            "nodes": [
                {
                    **{
                        "node_id": n.node_id,
                        "name": n.name,
                        "description": n.description,
                        "expected_outcome": n.expected_outcome,
                        "deps": list(n.deps),
                    },
                    **(
                        {"state": n.state}
                        if "state" in n.model_fields_set
                        else {}
                    ),
                }
                for n in self.nodes
            ],
        }


class PlanNodeChange(BaseModel):
    """Single node mutation for ``revise_current_plan``."""

    node_id: str = Field(description="Target node_id.")
    action: PlanChangeAction = Field(
        description="'add' / 'revise' / 'delete'.",
    )
    node: Optional[TaskNode] = Field(
        default=None,
        description="Required for 'add' and 'revise'.",
    )


class ApplyPlanChangesResult(BaseModel):
    """Result returned by ``TaskGraph.apply_plan_changes``."""

    added: List[str] = Field(default_factory=list)
    revised: List[str] = Field(default_factory=list)
    deleted: List[str] = Field(default_factory=list)
    stale_propagated: List[str] = Field(default_factory=list)


class DagDiff(BaseModel):
    """Merge diff returned by ``TaskGraph.apply_dag``."""

    added: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)
    modified: List[str] = Field(default_factory=list)
    state_overridden: List[str] = Field(default_factory=list)
    stale_propagated: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# TaskGraph
# ---------------------------------------------------------------------------


class TaskGraph(Plan):
    """DAG task graph (extends ``Plan``).

    ``nodes: Dict[str, TaskNode]`` is the authoritative store. The parent
    ``subtasks`` list is kept in sync via :meth:`_sync_subtasks_from_nodes`
    and marked ``exclude=True`` so the same data is not serialized twice.
    Execution order is computed from ``deps`` (see :meth:`get_ready_nodes`).
    """

    id: str = Field(
        default_factory=lambda: "graph_" + shortuuid.uuid()[:8],
        description="Graph ID.",
    )
    anchor_message_id: Optional[str] = Field(
        default=None,
        description=(
            "ID of the user message that triggered this graph"
            " (used to trace message↔graph linkage)."
        ),
    )
    nodes: Dict[str, TaskNode] = Field(
        default_factory=dict,
        description="Nodes indexed by node_id.",
    )
    # Required by parent; kept in sync with ``nodes`` and excluded from dump.
    subtasks: List[TaskNode] = Field(
        default_factory=list,
        exclude=True,
        description=(
            "Derived from ``nodes``;"
            " kept only for parent-class compatibility."
        ),
    )

    @model_validator(mode="after")
    def _sync_subtasks_from_nodes(self) -> "TaskGraph":
        self.subtasks = list(self.nodes.values())
        return self

    def _rebuild_subtasks(self) -> None:
        self.subtasks = list(self.nodes.values())

    # --- Node management ----------------------------------------------------

    def add_node(self, node: TaskNode) -> None:
        if node.node_id in self.nodes:
            raise ValueError(
                f"Node with id '{node.node_id}' already exists in graph "
                f"'{self.id}'.",
            )
        self.nodes[node.node_id] = node
        self._rebuild_subtasks()

    def remove_node(self, node_id: str) -> Optional[TaskNode]:
        node = self.nodes.pop(node_id, None)
        if node is not None:
            self._rebuild_subtasks()
            # Strip the removed id from every other node's deps.
            for other in self.nodes.values():
                if node_id in other.deps:
                    other.deps = [d for d in other.deps if d != node_id]
        return node

    def replace_node(self, node_id: str, node: TaskNode) -> None:
        if node_id not in self.nodes:
            raise KeyError(f"Node '{node_id}' not found.")
        # Force node_id to match the slot if the caller passed a mismatch.
        node.node_id = node_id
        self.nodes[node_id] = node
        self._rebuild_subtasks()

    # --- DAG scheduling -----------------------------------------------------

    def get_ready_nodes(self) -> List[TaskNode]:
        """Nodes in state ``todo``/``stale`` whose deps are all ``done``."""
        ready: List[TaskNode] = []
        for node in self.nodes.values():
            if node.state not in ("todo", "stale"):
                continue
            if all(
                self.nodes.get(dep) is not None
                and self.nodes[dep].state == "done"
                for dep in node.deps
            ):
                ready.append(node)
        return ready

    def is_complete(self) -> bool:
        if not self.nodes:
            return False
        return all(
            node.state in ("done", "abandoned") for node in self.nodes.values()
        )

    def _find_downstream_nodes(self, node_id: str) -> List[str]:
        """All downstream node IDs (depth-first)."""
        downstream: List[str] = []
        visited: set = set()

        def visit(cur: str) -> None:
            for nid, node in self.nodes.items():
                if cur in node.deps and nid not in visited:
                    visited.add(nid)
                    downstream.append(nid)
                    visit(nid)

        visit(node_id)
        return downstream

    def mark_downstream_stale(self, node_id: str) -> List[str]:
        """Mark every downstream node STALE; returns the IDs newly marked."""
        downstream = self._find_downstream_nodes(node_id)
        stale_ids: List[str] = []
        for nid in downstream:
            node = self.nodes[nid]
            prev = node.state
            node.mark_stale()
            if node.state == "stale" and prev != "stale":
                stale_ids.append(nid)
        return stale_ids

    @staticmethod
    def _force_revise_stale(node: TaskNode) -> None:
        """Force STALE on a revised node (matches single-node tool logic)."""
        if node.state not in ("todo", "stale", "abandoned"):
            node.state = "stale"
        elif node.state == "todo":
            node.state = "stale"

    def apply_plan_changes(
        self,
        changes: List[PlanNodeChange],
    ) -> ApplyPlanChangesResult:
        """Atomically apply a batch of plan node mutations."""
        if not changes:
            raise ValueError("changes must not be empty.")

        seen_ids: set[str] = set()
        for change in changes:
            if change.node_id in seen_ids:
                raise ValueError(
                    f"Duplicate node_id in changes: {change.node_id!r}.",
                )
            seen_ids.add(change.node_id)

        deletes = [c for c in changes if c.action == "delete"]
        adds = [c for c in changes if c.action == "add"]
        revises = [c for c in changes if c.action == "revise"]

        for change in changes:
            if change.action in ("add", "revise") and change.node is None:
                raise ValueError(
                    f"action='{change.action}' requires a 'node' argument.",
                )

        simulated_ids = set(self.nodes.keys())
        for change in deletes:
            if change.node_id not in simulated_ids:
                raise ValueError(f"Node '{change.node_id}' not found.")
            simulated_ids.discard(change.node_id)

        for change in revises:
            if change.node_id not in simulated_ids:
                raise ValueError(f"Node '{change.node_id}' not found.")

        pending_adds = list(adds)
        while pending_adds:
            progress = False
            for change in list(pending_adds):
                node = change.node
                assert node is not None
                nid = node.node_id or change.node_id
                if nid in simulated_ids:
                    raise ValueError(
                        f"Cannot add: node '{nid}' already exists.",
                    )
                if all(dep in simulated_ids for dep in node.deps):
                    simulated_ids.add(nid)
                    pending_adds.remove(change)
                    progress = True
            if not progress:
                raise ValueError(
                    "Cannot resolve add dependencies; check deps reference "
                    "existing nodes or nodes added in the same batch.",
                )

        result = ApplyPlanChangesResult()

        for change in deletes:
            self.remove_node(change.node_id)
            result.deleted.append(change.node_id)

        for change in adds:
            node = change.node
            assert node is not None
            if not isinstance(node, TaskNode):
                node = TaskNode.model_validate(node)
            node.node_id = node.node_id or change.node_id
            self.add_node(node)
            result.added.append(node.node_id)

        revised_ids: List[str] = []
        for change in revises:
            node = change.node
            assert node is not None
            if not isinstance(node, TaskNode):
                node = TaskNode.model_validate(node)
            node_id = change.node_id
            node.node_id = node_id
            self._force_revise_stale(node)
            self.replace_node(node_id, node)
            result.revised.append(node_id)
            revised_ids.append(node_id)

        stale_seen: set[str] = set()
        for node_id in revised_ids:
            for stale_id in self.mark_downstream_stale(node_id):
                if stale_id not in stale_seen:
                    stale_seen.add(stale_id)
                    result.stale_propagated.append(stale_id)

        return result

    # --- State refresh ------------------------------------------------------

    def refresh_state(self) -> str:
        # pylint: disable=access-member-before-definition
        # ``state`` is a pydantic Field on Plan; pylint's flow analysis
        # doesn't see model-field assignments as definitions.
        """Recompute graph-level state from node states.

        Returns a human-readable description of the change, or empty string
        if nothing changed. Overrides parent ``refresh_plan_state`` to
        recognize the extended state enum.
        """
        if self.state in ("done", "abandoned"):  # type: ignore[has-type]
            return ""

        any_in_progress = any(
            n.state == "in_progress" for n in self.nodes.values()
        )
        if any_in_progress and self.state == "todo":  # type: ignore[has-type]
            self.state = "in_progress"
            return "The graph state has been updated to 'in_progress'."
        if not any_in_progress and self.state == "in_progress":
            self.state = "todo"
            return "The graph state has been updated to 'todo'."
        return ""

    def refresh_plan_state(self) -> str:
        """Parent-class shim; delegates to :meth:`refresh_state`."""
        return self.refresh_state()

    # --- Rendering / serialization -----------------------------------------

    def model_dump(self, **kwargs) -> dict:
        """Manually dump each node so overridden ``TaskNode.model_dump`` runs.

        Pydantic does not invoke overridden ``model_dump`` on nested models;
        without this we lose the ``trace`` field on every node.
        """
        data = super().model_dump(**kwargs)
        data["nodes"] = {
            nid: node.model_dump(**kwargs) for nid, node in self.nodes.items()
        }
        return data

    def to_markdown(self, detailed: bool = False) -> str:
        """Human-readable Markdown render (not round-trippable)."""
        node_lines = [
            node.to_markdown(detailed=detailed) for node in self.nodes.values()
        ]
        header = [
            f"# {self.name}",
            f"**ID**: `{self.id}`",
            f"**Anchor Message ID**: `{self.anchor_message_id or '(none)'}`",
            f"**Description**: {self.description}",
            f"**Expected Outcome**: {self.expected_outcome}",
            f"**State**: {self.state}",
            f"**Created At**: {self.created_at}",
            "## Nodes",
        ]
        return "\n".join(header + node_lines)

    def to_yaml(self) -> str:
        """Round-trippable YAML dump (used for SOP template save / import)."""
        data = self.model_dump(mode="json")
        # Emit nodes as a list for readability.
        data["nodes"] = list(data.get("nodes", {}).values())
        return yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
        )

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "TaskGraph":
        """Parse from YAML; accepts ``nodes`` as either a list or a dict."""
        data: Any = yaml.safe_load(yaml_str)
        if not isinstance(data, dict):
            raise ValueError("YAML root must be a mapping for TaskGraph.")

        nodes_raw = data.get("nodes", [])
        if isinstance(nodes_raw, list):
            nodes_dict: Dict[str, Any] = {}
            for idx, node in enumerate(nodes_raw):
                if not isinstance(node, dict):
                    raise ValueError(
                        f"Node at index {idx} is not a mapping: {node!r}",
                    )
                nid = node.get("node_id") or f"node_{idx:03d}"
                node["node_id"] = nid
                nodes_dict[nid] = node
            data["nodes"] = nodes_dict
        return cls.model_validate(data)

    # --- SOP projection (minimal schema, no runtime fields) ----------------

    def to_sop(self) -> "Sop":
        """Project to ``Sop``, stripping all runtime fields including state."""
        return Sop(
            name=self.name,
            description=self.description,
            expected_outcome=self.expected_outcome,
            nodes=[
                SopNode(
                    node_id=n.node_id,
                    name=n.name,
                    description=n.description,
                    expected_outcome=n.expected_outcome,
                    deps=list(n.deps),
                )
                for n in self.nodes.values()
            ],
        )

    def to_sop_dict(self) -> dict:
        return self.to_sop().to_dict()

    def to_sop_yaml(self) -> str:
        return self.to_sop().to_yaml()

    @classmethod
    def from_sop(cls, data: "Sop | Dict[str, Any] | str") -> "TaskGraph":
        """Build an all-``todo`` TaskGraph from an SOP (Sop / dict / YAML).

        ``graph.id`` and ``created_at`` are regenerated; ``anchor_message_id``,
        ``outcome`` and ``finished_at`` are left empty; state starts at
        ``"todo"``. Missing ``node_id`` values are filled in as
        ``node_{idx:03d}``.
        """
        if isinstance(data, Sop):
            raw_data: Dict[str, Any] = data.to_dict()
        elif isinstance(data, str):
            raw: Any = yaml.safe_load(data)
            if not isinstance(raw, dict):
                raise ValueError("SOP YAML root must be a mapping.")
            raw_data = raw
        else:
            raw_data = data

        processed_nodes = _validate_sop_dict(raw_data)

        graph_init: Dict[str, Any] = {
            f: raw_data[f] for f in _SOP_GRAPH_FIELDS if f in raw_data
        }
        nodes_dict: Dict[str, Any] = {n["node_id"]: n for n in processed_nodes}
        graph_init["nodes"] = nodes_dict

        return cls.model_validate(graph_init)

    # --- DAG patch merge / export ------------------------------------------

    def apply_dag(  # pylint: disable=too-many-branches,too-many-statements
        self,
        dag: "Dag | Dict[str, Any] | str",
    ) -> DagDiff:
        """Merge a ``Dag`` patch into this graph by ``node_id``.

        Structural fields are user-mutable; per-node ``state`` may only be
        set to one of ``todo`` / ``stale`` / ``abandoned``. The backend-owned
        states (done / in_progress / failed) remain under runtime control.
        """
        if isinstance(dag, Dag):
            patch = dag
        elif isinstance(dag, str):
            try:
                raw: Any = yaml.safe_load(dag)
            except yaml.YAMLError as exc:
                raise ValueError(f"Failed to parse DAG YAML: {exc}") from exc
            if not isinstance(raw, dict):
                raise ValueError("DAG YAML root must be a mapping.")
            _reject_backend_owned_state_changes(
                raw,
                {nid: node.state for nid, node in self.nodes.items()},
            )
            patch = Dag.from_dict(raw)
        else:
            _reject_backend_owned_state_changes(
                dag,
                {nid: node.state for nid, node in self.nodes.items()},
            )
            patch = Dag.from_dict(dag)

        existing_ids = set(self.nodes.keys())
        patch_ids = {n.node_id for n in patch.nodes if n.node_id is not None}

        diff = DagDiff()

        self.name = patch.name
        self.description = patch.description
        self.expected_outcome = patch.expected_outcome

        for removed_id in sorted(existing_ids - patch_ids):
            self.remove_node(removed_id)
            diff.removed.append(removed_id)

        source_ids: set[str] = set()
        force_downstream_ids: set[str] = set()
        structural_fields = ("description", "expected_outcome", "deps")
        for patch_node in patch.nodes:
            assert patch_node.node_id is not None
            nid = patch_node.node_id
            explicit_state = "state" in patch_node.model_fields_set

            if nid not in self.nodes:
                node = TaskNode(
                    node_id=nid,
                    name=patch_node.name,
                    description=patch_node.description,
                    expected_outcome=patch_node.expected_outcome,
                    deps=list(patch_node.deps),
                    state=patch_node.state if explicit_state else "todo",
                )
                self.nodes[nid] = node
                diff.added.append(nid)
                source_ids.add(nid)
                if explicit_state:
                    diff.state_overridden.append(nid)
                continue

            node = self.nodes[nid]
            original_state = node.state
            changed = False
            for field in structural_fields:
                old = getattr(node, field)
                new = (
                    list(patch_node.deps)
                    if field == "deps"
                    else getattr(patch_node, field)
                )
                if old != new:
                    setattr(node, field, new)
                    changed = True
            # ``name`` is display-only and does not trigger STALE.
            node.name = patch_node.name
            if changed:
                prev = node.state
                node.mark_stale()
                diff.modified.append(nid)
                if node.state != prev or prev in ("done", "abandoned"):
                    source_ids.add(nid)

            if explicit_state:
                if original_state != patch_node.state:
                    node.state = patch_node.state  # type: ignore[assignment]
                    diff.state_overridden.append(nid)
                    source_ids.add(nid)
                    force_downstream_ids.add(nid)

            self.nodes[nid] = node

        self._rebuild_subtasks()

        stale_seen: set[str] = set()
        for nid in sorted(source_ids):
            if nid in force_downstream_ids:
                stale_ids = []
                for stale_id in self._find_downstream_nodes(nid):
                    stale_node = self.nodes[stale_id]
                    if stale_node.state != "abandoned":
                        stale_node.state = "stale"
                        stale_ids.append(stale_id)
            else:
                stale_ids = self.mark_downstream_stale(nid)
            for stale_id in stale_ids:
                if stale_id not in stale_seen:
                    stale_seen.add(stale_id)
                    diff.stale_propagated.append(stale_id)

        self._rebuild_subtasks()
        return diff

    def to_dag_dict(self, include_trace: bool = True) -> dict:
        """Full DAG dump for ``GET /dag`` YAML serialization."""
        data = self.model_dump(mode="json")
        nodes = []
        for node_data in data.get("nodes", {}).values():
            if not include_trace:
                node_data = dict(node_data)
                node_data.pop("trace", None)
            nodes.append(node_data)
        data["nodes"] = nodes
        return data

    def to_dag_yaml(self, include_trace: bool = True) -> str:
        """Export full DAG YAML (structure + runtime fields)."""
        return yaml.safe_dump(
            self.to_dag_dict(include_trace=include_trace),
            allow_unicode=True,
            sort_keys=False,
        )
