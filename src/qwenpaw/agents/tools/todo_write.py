# -*- coding: utf-8 -*-
"""Tool for writing and updating a task todo list.

Shows real-time progress.
"""

import logging
from typing import List, Dict, Any

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse
from agentscope.plan import SubTask

logger = logging.getLogger(__name__)


async def todo_write(
    todos: List[Dict[str, Any]],
    plan_name: str = "Agent Task",
    plan_description: str = "Execution progress tracker",
) -> ToolResponse:
    """Update or create the agent's active task progress list.

    Displays to the user in the right-side panel.

    Use this tool whenever you start a multi-step task or want to report
    your execution plan and progress to the user. This updates a
    persistent Todo list panel.

    Args:
        todos: A list of dicts representing the tasks/steps. Each dict
            must contain:
            - 'title' (str): Short name/description of the step
              (e.g. "Clone repository", "Run tests").
            - 'status' (Literal['todo', 'in_progress', 'done',
              'abandoned']): Current status of this step.
            - 'result' (str, optional): The outcome or result of the step
              if finished.
        plan_name: The overall title of the multi-step task (e.g. "Fixing
            bug in repository").
        plan_description: A brief summary of what the overall task does.

    Returns:
        `ToolResponse`: A confirmation message.
    """
    from ...app.agent_context import get_current_plan_notebook

    nb = get_current_plan_notebook()
    if nb is None:
        logger.warning(
            "todo_write called but plan_notebook is not set in context",
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "Error: Progress panel / Plan notebook is not "
                        "initialized in the current context."
                    ),
                ),
            ],
        )

    subtasks = []
    for idx, t in enumerate(todos):
        title = t.get("title") or t.get("name") or f"Step {idx + 1}"
        desc = t.get("description") or ""

        # ponytail: simple state mapping for ease of agent use
        # Map statuses:
        # done/completed/finished -> done
        # in_progress/running -> in_progress
        # abandoned/failed/skipped -> abandoned
        # todo/pending -> todo
        status_val = (
            str(
                t.get("status") or t.get("state") or "todo",
            )
            .lower()
            .strip()
        )
        if status_val in ("completed", "done", "finished", "success"):
            state = "done"
        elif status_val in ("in_progress", "running", "active", "started"):
            state = "in_progress"
        elif status_val in ("abandoned", "failed", "skipped", "error"):
            state = "abandoned"
        else:
            state = "todo"

        result = t.get("result") or t.get("outcome") or ""
        expected = t.get("expected_outcome") or "Step completed"

        subtasks.append(
            SubTask(
                name=title,
                description=desc,
                expected_outcome=expected,
                state=state,
                outcome=result if state in ("done", "abandoned") else None,
            ),
        )

    # Await create_plan to write/overwrite it
    await nb.create_plan(
        name=plan_name,
        description=plan_description,
        expected_outcome="All tasks completed",
        subtasks=subtasks,
    )

    # Check if all subtasks are finished (done or abandoned)
    # to auto-finish the plan
    if len(subtasks) > 0 and all(
        st.state in ("done", "abandoned") for st in subtasks
    ):
        # Mark plan as finished/done
        await nb.finish_plan(
            state="done",
            outcome="All tasks completed successfully.",
        )

    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=(
                    "Successfully updated progress panel with "
                    f"{len(todos)} tasks."
                ),
            ),
        ],
    )


# Alias for compatibility with PascalCase issue naming
TodoWrite = todo_write
