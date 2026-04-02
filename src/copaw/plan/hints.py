# -*- coding: utf-8 -*-
"""Custom plan-to-hint generator for CoPaw.

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
4. **No automatic plans** -- ``no_plan`` is empty so the model is not
   nudged to create a plan on every turn.  Users start planning with
   the ``/plan`` command or the console Plan panel instead.
5. **Stall guard** -- if the same subtask stays ``in_progress`` across
   many consecutive hint generations, the hint escalates to force
   ``finish_subtask`` so the ReAct loop does not repeat the same tool
   calls until ``max_iters`` is hit.
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

# After this many consecutive system-hint generations for the same
# in_progress subtask, replace the normal hint with a forced-finish hint.
_STALL_THRESHOLD = 12


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


if _HAS_DEFAULT_HINT:

    class CoPawPlanToHint(DefaultPlanToHint):
        """Plan-to-hint generator with bounded context cost.

        Overrides ``__call__`` so that ``{plan}`` is replaced with
        a **compact** representation once execution starts.
        At the very beginning (all subtasks *todo*, no outcomes yet)
        the full ``plan.to_markdown()`` is used because it is small
        and the agent needs full details to present the plan.
        """

        def __init__(self) -> None:
            self._ip_call_count: int = 0
            self._last_ip_idx: int | None = None

        _stalled_subtask: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            "IMPORTANT: Subtask {subtask_idx} ('{subtask_name}') has been "
            "in_progress for {call_count} iterations without completion.\n"
            "You MUST call 'finish_subtask' NOW with subtask_idx={subtask_idx} "
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
            "Work on this subtask using the appropriate "
            "tools. As soon as the subtask objective is "
            "achieved, call 'finish_subtask' with a concrete "
            "outcome summary and move on.\n"
            "After calling 'finish_subtask', continue directly "
            "to the next subtask without pausing for user "
            "input or reporting intermediate status.\n"
            "If you are unable to make further progress, call "
            "'finish_subtask' with what you have accomplished "
            "so far and proceed to the next one.\n"
        )

        when_no_subtask_in_progress: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            "The first {index} subtask(s) are done and no "
            "subtask is currently in_progress.\n"
            "Call 'update_subtask_state' to mark the next "
            "todo subtask as 'in_progress' and begin "
            "executing it right away. Do not pause for "
            "user input.\n"
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

        # Empty: do not prompt the model to create plans unless the user
        # explicitly uses /plan <task> or equivalent (see runner pre-process).
        no_plan: str | None = None

        # ---- override __call__ for compact context ----

        def __call__(  # noqa: C901
            self, plan: "Plan | None",
        ) -> str | None:
            """Generate a hint whose plan section is compact.

            At the beginning (all subtasks *todo*) the full
            ``plan.to_markdown()`` is used because there are no
            outcomes yet and the text is small.  Once execution
            starts, ``_compact_plan_text`` replaces it so that
            completed-subtask outcomes never inflate the hint.
            """
            if plan is None:
                self._last_ip_idx = None
                self._ip_call_count = 0
                hint = self.no_plan
            else:
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

                if n_ip == 0:
                    self._last_ip_idx = None
                    self._ip_call_count = 0

                hint = None
                if n_ip == 0 and n_done == 0:
                    hint = self.at_the_beginning.format(
                        plan=plan.to_markdown(),
                    )
                elif n_ip > 0 and ip_idx is not None:
                    if ip_idx == self._last_ip_idx:
                        self._ip_call_count += 1
                    else:
                        self._last_ip_idx = ip_idx
                        self._ip_call_count = 1
                    st = plan.subtasks[ip_idx]
                    compact = _compact_plan_text(plan)
                    if self._ip_call_count > _STALL_THRESHOLD:
                        hint = self._stalled_subtask.format(
                            plan=compact,
                            subtask_idx=ip_idx,
                            subtask_name=st.name,
                            call_count=self._ip_call_count,
                        )
                    else:
                        hint = (
                            self.when_a_subtask_in_progress.format(
                                plan=compact,
                                subtask_idx=ip_idx,
                                subtask_name=st.name,
                                subtask=_subtask_text(st),
                            )
                        )
                elif n_done + n_abn == len(plan.subtasks):
                    compact = _compact_plan_text(plan)
                    hint = self.at_the_end.format(
                        plan=compact,
                    )
                elif n_ip == 0 and n_done > 0:
                    compact = _compact_plan_text(plan)
                    hint = (
                        self.when_no_subtask_in_progress.format(
                            plan=compact,
                            index=n_done,
                        )
                    )

            if hint:
                return (
                    f"{self.hint_prefix}"
                    f"{hint}"
                    f"{self.hint_suffix}"
                )
            return hint

else:
    CoPawPlanToHint = None  # type: ignore[misc,assignment]
