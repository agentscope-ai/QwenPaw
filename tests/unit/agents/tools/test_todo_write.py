# -*- coding: utf-8 -*-
from unittest.mock import patch

import pytest
from agentscope.plan import PlanNotebook, InMemoryPlanStorage

from qwenpaw.agents.tools.todo_write import todo_write


@pytest.mark.asyncio
async def test_todo_write_basic():
    notebook = PlanNotebook(storage=InMemoryPlanStorage())

    with patch(
        "qwenpaw.app.agent_context.get_current_plan_notebook",
        return_value=notebook,
    ):
        todos = [
            {"title": "Step 1", "status": "done", "result": "Result 1"},
            {"title": "Step 2", "status": "in_progress"},
            {"title": "Step 3", "status": "todo"},
        ]

        response = await todo_write(
            todos=todos,
            plan_name="Test Task",
            plan_description="Testing todo_write",
        )

        assert response is not None
        assert (
            "Successfully updated progress panel"
            in response.content[0]["text"]
        )

        plan = notebook.current_plan
        assert plan is not None
        assert plan.name == "Test Task"
        assert plan.description == "Testing todo_write"
        assert len(plan.subtasks) == 3
        assert plan.subtasks[0].name == "Step 1"
        assert plan.subtasks[0].state == "done"
        assert plan.subtasks[0].outcome == "Result 1"
        assert plan.subtasks[1].state == "in_progress"
        assert plan.subtasks[2].state == "todo"
