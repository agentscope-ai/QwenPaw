# -*- coding: utf-8 -*-
"""Builds the per-turn ``<system-hint>`` string from the current TaskGraph.

Replaces AgentScope's ``DefaultPlanToHint`` with DAG-aware variants for
ready / in-progress / stale / failed nodes. Called by
``RuntimeStateManager.get_current_hint()`` before each ``_reasoning`` turn.

``DataPawPlanToHint`` extends ``DefaultGraphToHint`` with awareness of
host's plan-lifecycle flags (``_plan_tool_gate``, ``_plan_just_mutated``,
``_plan_recently_finished``) so DataPaw plays nicely with host plan mode:
``/plan`` command, post-mutation confirmation flow, recently-finished
guard. See datapaw-docs/qwenpaw-plan-mode-overview.md §9 for design
context.
"""
from __future__ import annotations

import weakref
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
        "- If a registered Agent Skill matches this node's task, "
        "`read_file` its SKILL.md first.\n"
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
        "call `revise_current_plan(changes=[{{node_id: '{node_id}', "
        "action: 'revise', node: ...}}])` which marks it STALE and "
        "propagates STALE to all downstream nodes."
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
        "- Pick one stale node, call `update_subtask_state(node_id, "
        "'in_progress')` and execute it.\n"
        "- STALE nodes are scheduled identically to TODO nodes; treat "
        "them as fresh ready nodes."
    )

    failed_hint: str = (
        "The current task graph:\n"
        "```\n{graph}\n```\n"
        "Node(s) {failed_ids} are in FAILED state. Examine the error "
        "message and decide:\n"
        "- Retry by resetting to todo: `update_subtask_state(node_id, "
        "'todo')`.\n"
        "- Revise the node (e.g. different SQL, different threshold): "
        "`revise_current_plan(changes=[{{node_id, action: 'revise', "
        "node: ...}}])`.\n"
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

    def __call__(  # pylint: disable=too-many-return-statements
        self,
        graph: "TaskGraph | None",
    ) -> Optional[str]:
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


class DataPawPlanToHint(DefaultGraphToHint):
    """Flag-aware hint generator that integrates with host plan mode.

    Adds three branches in front of the standard DAG state machine:

    1. ``_plan_just_mutated`` (set by DataPaw plan tools after create /
       revise): force the model to present the plan to the user and wait
       for confirmation, regardless of the underlying graph state. Mirrors
       host's ``at_the_beginning_after_mutation`` behavior.
    2. ``_plan_tool_gate`` with ``current_plan is None`` (set by host's
       ``/plan`` command): force ``create_plan`` to be the next call.
       Mirrors host's ``no_plan`` template.
    3. ``_plan_recently_finished`` with ``current_plan is None`` (set by
       DataPaw's ``finish_plan``): warn the model not to revive the
       previous plan; only create a new one if user explicitly asks.

    All three flags are read off the bound notebook (``RuntimeStateManager``
    instance). Use :meth:`bind_notebook` after construction.
    """

    just_mutated_hint: str = (
        "The current task graph:\n```\n{graph}\n```\n"
        "This task graph was JUST created or revised. **Do NOT execute "
        "any node yet.**\n"
        "- Present the graph to the user as a Markdown summary: list each "
        "node, its dependencies, and the expected outcome.\n"
        "- End your reply by asking the user to confirm, edit, or cancel "
        '(e.g. "是否开始执行？").\n'
        "- Do NOT call any tool except `finish_plan('abandoned', ...)` "
        "if the user explicitly cancels.\n"
        "The backend has hard-locked all execution tools until the user's "
        "next message — calling them will only return errors."
    )

    no_plan_with_gate: str = (
        "There is no active task graph yet, and the user invoked /plan. "
        "**You MUST call `create_plan` first** to lay out a DAG of "
        "analytical steps:\n"
        "- Each node needs: node_id, name, description, expected_outcome, "
        "deps (list of upstream node_ids).\n"
        "- Order by data dependency: leaf nodes (no deps) first.\n"
        "- After `create_plan` succeeds, present the graph to the user "
        "and wait for confirmation. Do NOT execute any node in the same "
        "turn."
    )

    recently_finished_guard: str = (
        "There is no active task graph now. The previous graph was "
        "finished or abandoned.\n"
        "- Do NOT continue old subtasks.\n"
        "- If the user asks to redo / modify the analysis, call "
        "`create_plan` to build a fresh graph.\n"
        "- Otherwise answer the user's latest message directly without "
        "creating a graph."
    )

    def bind_notebook(self, plan_notebook) -> None:
        """Store a weakref to the notebook so each call can read its flags."""
        if plan_notebook is None:
            self._bound_notebook = None
        else:
            self._bound_notebook = weakref.ref(plan_notebook)

    def _get_notebook(self):
        nb = getattr(self, "_bound_notebook", None)
        if nb is None:
            return None
        return nb() if callable(nb) else nb  # pylint: disable=not-callable

    def __call__(self, graph: "TaskGraph | None") -> Optional[str]:
        nb = self._get_notebook()

        # Priority 1: just-mutated lock — present plan + wait, regardless.
        if (
            nb is not None
            and getattr(nb, "_plan_just_mutated", False)
            and graph is not None
        ):
            return self._wrap(
                self.just_mutated_hint.format(graph=graph.to_markdown()),
            )

        # Priority 2: no graph yet, but /plan command active.
        if graph is None and nb is not None:
            if getattr(nb, "_plan_tool_gate", False):
                return self._wrap(self.no_plan_with_gate)
            if getattr(nb, "_plan_recently_finished", False):
                return self._wrap(self.recently_finished_guard)

        # Fall through to standard DAG state branches.
        return super().__call__(graph)
