# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib

from services.project_files.agent_tools import (
    AgentProjectToolContext,
    AgentProjectTools,
)
from services.project_files.models import Project
from services.project_files.schema_prompt import build_project_schema_prompt
from services.project_files.store import ProjectStore


def test_schema_prompt_is_static_deterministic_and_cached_across_turns(
    tmp_path,
) -> None:
    build_project_schema_prompt.cache_clear()
    first = build_project_schema_prompt()
    repeated = [build_project_schema_prompt() for _ in range(100)]
    build_project_schema_prompt.cache_clear()
    regenerated = build_project_schema_prompt()

    assert all(item is first for item in repeated)
    assert regenerated.text == first.text
    assert regenerated.sha256 == first.sha256
    assert regenerated.sha256 == (
        "sha256:"
        + hashlib.sha256(regenerated.text.encode("utf-8")).hexdigest()
    )
    assert '"project_id"' in regenerated.text
    assert '"elements_by_id"' in regenerated.text
    assert '"source_in_tick"' in regenerated.text
    assert "./project.json" in regenerated.text
    assert "./assets/source-intelligence/*" in regenerated.text
    assert "Pydantic 权威 JSON Schema" in regenerated.text
    assert "./runtime" not in regenerated.text

    store = ProjectStore(tmp_path.resolve())
    store.create(Project.new(project_id="project-1", name="One"))
    first_runtime = AgentProjectTools(
        store,
        context=AgentProjectToolContext(origin="initial_creation"),
    )
    second_runtime = AgentProjectTools(
        store,
        context=AgentProjectToolContext(origin="runtime_task"),
    )
    assert first_runtime.schema_prompt is second_runtime.schema_prompt
