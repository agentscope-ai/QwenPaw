# -*- coding: utf-8 -*-
"""Custom plan-to-hint generator for QwenPaw.

Key differences from the AgentScope default:

1. **Confirmation step** -- after creating a plan the agent must
   present it and wait for user approval before execution.
2. **Seamless transitions** -- after finishing one subtask the agent
   moves to the next immediately without pausing.
3. **Compact plan text** -- completed-subtask outcomes and timestamps
   are dropped from the hint so the per-iteration context cost stays
   constant regardless of how many subtasks have finished.  This
   prevents the "overflow -> truncate -> retry -> overflow" loop that
   occurs when the plan hint grows unboundedly.
4. **Scoped ``no_plan`` hint** -- when there is no active plan yet, a
   short hint tells the model to call ``create_plan`` without
   browser/web tools first *only if* the user asked for a plan; heavy
   tooling is deferred to named subtasks after confirmation.
5. **Stall guard** -- if the same subtask stays ``in_progress`` across
   many consecutive hint generations, the hint escalates to force
   ``finish_subtask`` so the ReAct loop does not repeat the same tool
   calls until ``max_iters`` is hit.
6. **Console visibility** -- during execution, hints require short
   user-visible prose each turn (not tool-only replies) so the web
   console shows what is happening, not only tool invocations.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentscope.plan import Plan

logger = logging.getLogger(__name__)

try:
    from agentscope.plan._plan_notebook import DefaultPlanToHint

    _HAS_DEFAULT_HINT = True
except ImportError:
    _HAS_DEFAULT_HINT = False

_DESC_LIMIT = 80
_PLAN_DESC_LIMIT = 200

# After this many consecutive hint generations for the same
# in_progress subtask, replace the normal hint with a forced-finish
# directive.  Keep this low — the agent should finish a subtask in
# a handful of tool calls, not dozens.
_STALL_THRESHOLD = 6


def set_plan_gate(plan_notebook, enabled: bool = True) -> None:
    """Activate or deactivate the plan tool gate on *plan_notebook*.

    The gate ensures that only ``create_plan`` is allowed until an
    active plan exists.  Called by the runner when a ``/plan <desc>``
    command is detected.
    """
    if plan_notebook is not None:
        # pylint: disable-next=protected-access
        plan_notebook._qwenpaw_plan_gate = enabled


def check_plan_tool_gate(plan_notebook, tool_name: str):
    """Return an error string if *tool_name* must be blocked, else
    ``None``.

    Enforces that when a ``/plan`` request is pending (plan mode is
    on, no plan exists yet, gate flag is set by the runner), only
    ``create_plan`` may run.  All other tools are rejected with a
    message instructing the model to call ``create_plan`` first.

    The gate flag is set via :func:`set_plan_gate` and is
    automatically bypassed once a plan exists
    (``current_plan is not None``).
    """
    if plan_notebook is None:
        return None
    if plan_notebook.current_plan is not None:
        return None
    if not getattr(plan_notebook, "_qwenpaw_plan_gate", False):
        return None
    if tool_name == "create_plan":
        return None
    return (
        f"Tool '{tool_name}' is not available right now. "
        "You MUST call 'create_plan' first to define the "
        "plan and its subtasks. Do NOT call browser_use, "
        "web_search, or any other tool before 'create_plan'. "
        "Include any research or investigation steps as "
        "subtasks in the plan."
    )


def _compact_plan_text(plan: "Plan") -> str:
    """Build a compact markdown representation of *plan*.

    * **Done / abandoned** subtasks -> one-line status + name only.
    * **In-progress** subtask -> name + description + expected outcome.
    * **Todo** subtasks -> name + first ``_DESC_LIMIT`` chars of
      description.

    This keeps the hint O(n) in subtask *count* but with a tiny
    constant per completed subtask, instead of O(sum of outcomes).
    """
    desc = plan.description
    if len(desc) > _PLAN_DESC_LIMIT:
        desc = desc[: _PLAN_DESC_LIMIT - 3] + "..."

    lines = [
        f"# {plan.name}",
        f"Description: {desc}",
        f"State: {plan.state}",
        "## Subtasks",
    ]
    for i, st in enumerate(plan.subtasks):
        if st.state == "done":
            lines.append(f"  {i}. [done] {st.name}")
        elif st.state == "abandoned":
            lines.append(f"  {i}. [abandoned] {st.name}")
        elif st.state == "in_progress":
            lines.append(f"  {i}. [in_progress] {st.name}")
            lines.append(f"     Desc: {st.description}")
            lines.append(
                f"     Expected: {st.expected_outcome}",
            )
        else:
            d = st.description
            if len(d) > _DESC_LIMIT:
                d = d[: _DESC_LIMIT - 3] + "..."
            lines.append(f"  {i}. [todo] {st.name}")
            lines.append(f"     Desc: {d}")
    return "\n".join(lines)


def _subtask_text(subtask) -> str:
    """Concise view for the ``{subtask}`` format variable."""
    return (
        f"Name: {subtask.name}\n"
        f"Description: {subtask.description}\n"
        f"Expected Outcome: {subtask.expected_outcome}"
    )


def _count_states(plan: "Plan"):
    """Return (n_todo, n_ip, n_done, n_abn, ip_idx)."""
    n_todo = n_ip = n_done = n_abn = 0
    ip_idx = None
    for idx, st in enumerate(plan.subtasks):
        if st.state == "todo":
            n_todo += 1
        elif st.state == "in_progress":
            n_ip += 1
            ip_idx = idx
        elif st.state == "done":
            n_done += 1
        elif st.state == "abandoned":
            n_abn += 1
    return n_todo, n_ip, n_done, n_abn, ip_idx


if _HAS_DEFAULT_HINT:

    class QwenPawPlanToHint(DefaultPlanToHint):
        """Plan-to-hint generator with bounded context cost.

        Overrides ``__call__`` so that ``{plan}`` is replaced with
        a **compact** representation once execution starts.
        At the very beginning (all subtasks *todo*, no outcomes yet)
        the full ``plan.to_markdown()`` is used because it is small
        and the agent needs full details to present the plan.
        """

        def __init__(self) -> None:
            self._ip_call_count: int = 0
            self._last_ip_name: str | None = None

        _stalled_subtask: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            "IMPORTANT: Subtask {subtask_idx} ('{subtask_name}') has been "
            "in_progress for {call_count} iterations without completion.\n"
            "Briefly tell the user you are wrapping up this subtask "
            "(one sentence), then call 'finish_subtask' NOW with "
            "subtask_idx={subtask_idx} "
            "and a summary of what you have accomplished so far (even if "
            "incomplete). Do NOT invoke any other tool before that. If you "
            "have not accomplished anything meaningful, state that clearly "
            "in the outcome and move on.\n"
        )

        at_the_beginning: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            "Present this plan to the user and ask them to "
            "confirm, edit, or cancel before you start.\n"
            "- If the user confirms (e.g. 'go ahead', 'start', "
            "'confirm', 'yes', 'ok'), call "
            "'update_subtask_state' with subtask_idx=0 and "
            "state='in_progress', then begin executing it.\n"
            "- If the user asks to modify the plan, use "
            "'revise_current_plan' to make changes. Then "
            "present the updated plan and ask again.\n"
            "- If the user cancels, call 'finish_plan' with "
            "state='abandoned'.\n"
            "- Do NOT execute any subtask until the user "
            "explicitly confirms.\n"
            "- Until the user confirms, do NOT use browser, "
            "web search, or other tools to research the task. "
            "Summarize the plan in your reply from the user's "
            "request and reasonable assumptions. Any browsing, "
            "repo inspection, or heavy investigation must appear "
            "as explicit todo subtasks and run only after "
            "confirmation when that subtask is in_progress.\n"
        )

        when_a_subtask_in_progress: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            "Subtask {subtask_idx} ('{subtask_name}') is "
            "in_progress. Details:\n"
            "```\n"
            "{subtask}\n"
            "```\n"
            "Execute this subtask efficiently:\n"
            "1. **User-visible progress (required):** In every "
            "assistant turn, include plain text the user can read "
            "before any tool calls. Start with one short paragraph: "
            "name this subtask (index and title), state what you are "
            "about to do, and why. Do **not** reply with only tool "
            "calls and no readable prose in the same turn — the web "
            "UI must show your reasoning, not just tools.\n"
            "2. After important tool results, add 1–2 sentences "
            "interpreting what changed and what you will do next "
            "before more tools.\n"
            "3. Use tools to accomplish the objective. Do "
            "NOT call the same tool with the same or "
            "similar arguments twice — each call must "
            "produce genuinely new information.\n"
            "4. As soon as the objective is achieved OR "
            "you have gathered enough information, call "
            "'finish_subtask' immediately with a concrete "
            "outcome summary.\n"
            "5. If you cannot make further progress after "
            "a few tool calls, call 'finish_subtask' with "
            "what you have and move to the next subtask.\n"
            "6. After 'finish_subtask', continue directly "
            "to the next subtask without pausing.\n"
            "IMPORTANT: Prefer calling 'finish_subtask' "
            "sooner rather than later. A concise partial "
            "outcome is better than repeating the same "
            "action.\n"
        )

        when_no_subtask_in_progress: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            "The first {index} subtask(s) are done and no "
            "subtask is currently in_progress.\n"
            "First, send one short user-visible sentence: what "
            "was finished and which subtask you are starting next "
            "(name and goal). Then call 'update_subtask_state' to "
            "mark the next todo subtask as 'in_progress' and begin "
            "executing it right away. Do not pause for user input.\n"
        )

        at_the_end: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            "All subtasks are complete. Call 'finish_plan' "
            "with state='done' and a concise outcome "
            "summary, then present the full results to "
            "the user.\n"
        )

        # Shown only when plan mode is on and there is no current plan.
        # Wording avoids autonomous plans: applies when the user is
        # asking for a breakdown (/plan, etc.), not on every chat turn.
        no_plan: str | None = (
            "There is no active plan yet.\n"
            "If and only if the user is asking for a structured plan "
            "or step-by-step breakdown (e.g. a /plan-style request), "
            "call 'create_plan' next with clear subtasks. Do NOT call "
            "browser_use, web_search, or similar tools before "
            "'create_plan'; put browsing, repo research, or other "
            "tool-heavy work into explicit todo subtasks so they run "
            "after the user confirms the plan and that subtask is "
            "in_progress.\n"
            "If the user is not requesting a plan, ignore this block.\n"
        )

        # ---- override __call__ for compact context ----

        def _ip_hint(self, plan, ip_idx):
            """Hint for the in-progress subtask, with stall guard."""
            st = plan.subtasks[ip_idx]
            ip_key = st.name
            if ip_key == self._last_ip_name:
                self._ip_call_count += 1
            else:
                self._last_ip_name = ip_key
                self._ip_call_count = 1
            compact = _compact_plan_text(plan)
            if self._ip_call_count > _STALL_THRESHOLD:
                return self._stalled_subtask.format(
                    plan=compact,
                    subtask_idx=ip_idx,
                    subtask_name=st.name,
                    call_count=self._ip_call_count,
                )
            return self.when_a_subtask_in_progress.format(
                plan=compact,
                subtask_idx=ip_idx,
                subtask_name=st.name,
                subtask=_subtask_text(st),
            )

        def __call__(
            self,
            plan: "Plan | None",
        ) -> str | None:
            """Generate a compact hint.

            At the beginning (all subtasks *todo*) the full
            ``plan.to_markdown()`` is used.  Once execution
            starts, ``_compact_plan_text`` keeps the hint small.
            """
            if plan is None:
                self._last_ip_name = None
                self._ip_call_count = 0
                hint = self.no_plan
            else:
                _, n_ip, n_done, n_abn, ip_idx = _count_states(plan)
                if n_ip == 0:
                    self._last_ip_name = None
                    self._ip_call_count = 0

                hint = self._pick_hint(
                    plan,
                    n_ip,
                    n_done,
                    n_abn,
                    ip_idx,
                )

            if hint:
                return f"{self.hint_prefix}" f"{hint}" f"{self.hint_suffix}"
            return hint

        def _pick_hint(self, plan, n_ip, n_done, n_abn, ip_idx):
            """Select the right hint template for the plan state."""
            if n_ip == 0 and n_done == 0:
                return self.at_the_beginning.format(
                    plan=plan.to_markdown(),
                )
            if n_ip > 0 and ip_idx is not None:
                return self._ip_hint(plan, ip_idx)
            if n_done + n_abn == len(plan.subtasks):
                return self.at_the_end.format(
                    plan=_compact_plan_text(plan),
                )
            if n_ip == 0 and n_done > 0:
                return self.when_no_subtask_in_progress.format(
                    plan=_compact_plan_text(plan),
                    index=n_done,
                )
            return None

else:
    QwenPawPlanToHint = None  # type: ignore[misc,assignment]
