# -*- coding: utf-8 -*-
"""Builds the per-turn ``<system-hint>`` string from the current TaskGraph.

Replaces AgentScope's ``DefaultPlanToHint`` with DAG-aware variants for
ready / in-progress / stale / failed nodes. Called by
``RuntimeStateManager.get_current_hint()`` before each ``_reasoning`` turn.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .task_graph import TaskGraph


class DefaultGraphToHint:
    """Render a TaskGraph snapshot into a hint string (``None`` = no hint)."""

    hint_prefix: str = "<system-hint>"
    hint_suffix: str = "</system-hint>"

    no_graph: str = (
        "The user has not initiated any analysis task graph yet. "
        "If the user's request is complex or requires multiple analytical "
        "steps (data fetching, volatility analysis, attribution, report), "
        "you SHOULD call `create_plan` to lay out a DAG first. "
        "For simple questions you can answer directly without creating a "
        "graph."
    )

    at_beginning: str = (
        "The current task graph:\n"
        "```\n{graph}\n```\n"
        "All nodes are in `todo` state. Your options:\n"
        "- Execute the graph serially: start only one ready node, complete "
        "it, then choose the next node in a later step.\n"
        "- Pick one ready node (no unfinished dependencies) and call "
        "`update_subtask_state(node_id, 'in_progress')` to start executing.\n"
        "- If the graph no longer fits the user's intent, call "
        "`revise_current_plan` to adjust.\n"
        "- If the user has abandoned the task, call `finish_plan("
        "'abandoned', ...)`."
    )

    ready_nodes_hint: str = (
        "The current task graph:\n"
        "```\n{graph}\n```\n"
        "Ready nodes (deps satisfied, status todo/stale): "
        "{ready_ids}\n"
        "- Even if multiple ready nodes are listed, execute exactly ONE "
        "node at a time.\n"
        "- Pick one ready node and call `update_subtask_state(node_id, "
        "'in_progress')` before doing actual work.\n"
        "- Do NOT start another ready node until the current node has been "
        "finished, failed, or abandoned.\n"
        "- After the work, call `finish_subtask(node_id, reasoning, summary, "
        "files=...)`. Include any generated files with name / path / "
        "mime_type; the backend will fill file sizes automatically.\n"
        "- If a node fails, call `update_subtask_state(node_id, 'failed', "
        "error=...)`."
    )

    in_progress_hint: str = (
        "The current task graph:\n"
        "```\n{graph}\n```\n"
        "Node `{node_id}` (name: '{node_name}') is currently `in_progress`. "
        "This MAY be the result of a prior interruption.\n"
        "- **Check the conversation history carefully**: if the tool call "
        "for this node has already produced a complete result, call "
        "`finish_subtask({node_id}, ...)` immediately to record it.\n"
        "- If the tool result is incomplete or absent, re-execute the node.\n"
        "- If the user has asked for a change to this node's parameters, "
        "call `revise_current_plan({node_id}, 'revise', ...)` which will "
        "mark it STALE and propagate STALE to all downstream nodes."
    )

    in_progress_continuing_hint: str = (
        "The current task graph:\n"
        "```\n{graph}\n```\n"
        "Node `{node_id}` (name: '{node_name}') is in progress.\n"
        "- If you've achieved the node's goal, call "
        "`finish_subtask({node_id}, reasoning, summary, files=...)` now.\n"
        "- Otherwise continue executing tools toward that goal."
    )

    stale_hint: str = (
        "The current task graph:\n"
        "```\n{graph}\n```\n"
        "Node(s) {stale_ids} are in STALE state — their description or "
        "upstream data has changed since last execution. Re-run them:\n"
        "- Call `update_subtask_state(node_id, 'todo')` to reset and then "
        "treat it like a fresh ready node.\n"
        "- For bulk reset of a node + all its downstream, use "
        "`reset_downstream(node_id)`."
    )

    failed_hint: str = (
        "The current task graph:\n"
        "```\n{graph}\n```\n"
        "Node(s) {failed_ids} are in FAILED state. Examine the error "
        "message and decide:\n"
        "- Retry by resetting to todo: `update_subtask_state(node_id, "
        "'todo')`.\n"
        "- Revise the node (e.g. different SQL, different threshold): "
        "`revise_current_plan(node_id, 'revise', ...)`.\n"
        "- Abandon the node if it can't be salvaged: `update_subtask_state("
        "node_id, 'abandoned')`."
    )

    all_done: str = (
        "The current task graph:\n"
        "```\n{graph}\n```\n"
        "All nodes are done/abandoned. Summarize the analysis to the user, "
        "then call `finish_plan('done', outcome=<final report summary>)` "
        "to archive the graph."
    )

    node_in_progress_after_interrupt_key: str = "in_progress_after_interrupt"

    def __call__(self, graph: "TaskGraph | None") -> Optional[str]:
        """Dispatch by graph state, in priority order:
        empty → in_progress → failed → stale → all_done → at_beginning → ready.
        """
        if graph is None:
            return self._wrap(self.no_graph)

        nodes = list(graph.nodes.values())
        if not nodes:
            return self._wrap(self.no_graph)

        graph_md = graph.to_markdown()

        # An empty/short trace means the node was just marked in_progress
        # (or we're resuming from an interrupt) — use the full hint so the
        # model is reminded to check history for any pre-interrupt result.
        # ``TaskNode.trace`` is only synthesized at model_dump() time; the
        # runtime list lives on the ``_raw_trace`` private attribute.
        in_progress = [n for n in nodes if n.state == "in_progress"]
        if in_progress:
            node = in_progress[0]
            trace_len = len(getattr(node, "_raw_trace", []) or [])
            template = (
                self.in_progress_hint
                if trace_len <= 1
                else self.in_progress_continuing_hint
            )
            return self._wrap(
                template.format(
                    graph=graph_md,
                    node_id=node.node_id,
                    node_name=node.name,
                ),
            )

        failed = [n for n in nodes if n.state == "failed"]
        if failed:
            return self._wrap(
                self.failed_hint.format(
                    graph=graph_md,
                    failed_ids=[n.node_id for n in failed],
                ),
            )

        stale = [n for n in nodes if n.state == "stale"]
        if stale:
            return self._wrap(
                self.stale_hint.format(
                    graph=graph_md,
                    stale_ids=[n.node_id for n in stale],
                ),
            )

        if graph.is_complete():
            return self._wrap(self.all_done.format(graph=graph_md))

        done_count = sum(1 for n in nodes if n.state == "done")
        if done_count == 0:
            return self._wrap(self.at_beginning.format(graph=graph_md))

        ready = graph.get_ready_nodes()
        ready_ids = [n.node_id for n in ready] or ["(none)"]
        return self._wrap(
            self.ready_nodes_hint.format(
                graph=graph_md,
                ready_ids=ready_ids,
            ),
        )

    def _wrap(self, body: str) -> str:
        return f"{self.hint_prefix}{body}{self.hint_suffix}"
