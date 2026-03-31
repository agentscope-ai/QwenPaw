# -*- coding: utf-8 -*-
"""Custom plan-to-hint generator for CoPaw.

Two key differences from the AgentScope default:

1. **Confirmation step** – after creating a plan the agent must
   present it and wait for user approval.
2. **Seamless transitions** – after finishing one subtask the agent
   must move on to the next subtask immediately, without pausing
   to ask the user or report intermediate status.
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


if _HAS_DEFAULT_HINT:

    class CoPawPlanToHint(DefaultPlanToHint):
        """Balanced hint generator for CoPaw.

        * ``at_the_beginning`` – ask user to review / edit / confirm.
        * ``when_a_subtask_in_progress`` – work on the subtask,
          call ``finish_subtask`` once it is done, then proceed.
        * ``when_no_subtask_in_progress`` – activate the next
          subtask immediately.
        * ``at_the_end`` – finish the plan and summarize.
        """

        at_the_beginning: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            "Present this plan to the user and ask them to "
            "confirm, edit, or cancel before you start.\n"
            "- If the user confirms (e.g. 'go ahead', 'start', "
            "'confirm', 'yes', 'ok', '确认', '开始'), call "
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
            "Work on this subtask using the appropriate tools. "
            "As soon as the subtask objective is achieved, call "
            "'finish_subtask' with a concrete outcome summary "
            "and move on.\n"
            "After calling 'finish_subtask', continue directly "
            "to the next subtask without pausing for user input "
            "or reporting intermediate status.\n"
            "If you are unable to make further progress on this "
            "subtask, call 'finish_subtask' with what you have "
            "accomplished so far and proceed to the next one.\n"
        )

        when_no_subtask_in_progress: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            "The first {index} subtask(s) are done and no "
            "subtask is currently in_progress.\n"
            "Call 'update_subtask_state' to mark the next todo "
            "subtask as 'in_progress' and begin executing it "
            "right away. Do not pause for user input.\n"
        )

        at_the_end: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            "All subtasks are complete. Call 'finish_plan' "
            "with state='done' and a concise outcome summary, "
            "then present the full results to the user.\n"
        )

else:
    CoPawPlanToHint = None  # type: ignore[misc,assignment]
