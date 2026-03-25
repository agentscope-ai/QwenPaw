# -*- coding: utf-8 -*-

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from copaw.app.routers.agents_pipeline_core import (
    PipelineTemplateInfo,
    PipelineTemplateStep,
    _get_pipeline_draft,
    _pipeline_flow_memory_path,
    _pipeline_md_path,
    _save_agent_pipeline_template_with_md,
)


def _build_template(template_id: str = "demo-pipeline") -> PipelineTemplateInfo:
    return PipelineTemplateInfo(
        id=template_id,
        name="Demo Pipeline",
        version="0.1.0",
        description="Demo flow",
        steps=[
            PipelineTemplateStep(
                id="step-1",
                name="Collect",
                kind="ingest",
                description="collect source",
            ),
            PipelineTemplateStep(
                id="step-2",
                name="Validate",
                kind="validation",
                description="check schema",
            ),
        ],
    )


def _read_template_json(workspace_dir: Path, template_id: str) -> dict:
    json_path = workspace_dir / "pipelines" / "templates" / f"{template_id}.json"
    return json.loads(json_path.read_text(encoding="utf-8"))


def test_save_template_bootstraps_markdown_and_flow_memory(tmp_path: Path):
    saved = _save_agent_pipeline_template_with_md(tmp_path, _build_template())

    md_path = _pipeline_md_path(tmp_path, saved.id)
    flow_memory_path = _pipeline_flow_memory_path(tmp_path, saved.id)

    assert md_path.exists()
    assert flow_memory_path.exists()
    assert saved.revision == 1
    assert saved.content_hash

    draft = _get_pipeline_draft(tmp_path, saved.id)
    assert draft is not None
    assert draft.flow_memory_relative_path.endswith("flow-memory.md")
    assert len(draft.steps) == 2


def test_save_template_is_idempotent_for_same_markdown(tmp_path: Path):
    first = _save_agent_pipeline_template_with_md(tmp_path, _build_template())
    second = _save_agent_pipeline_template_with_md(
        tmp_path,
        _build_template(),
        expected_revision=first.revision,
    )

    assert second.revision == first.revision
    assert second.content_hash == first.content_hash


def test_save_template_detects_revision_conflict(tmp_path: Path):
    first = _save_agent_pipeline_template_with_md(tmp_path, _build_template())

    with pytest.raises(HTTPException) as exc_info:
        _save_agent_pipeline_template_with_md(
            tmp_path,
            _build_template(),
            expected_revision=first.revision + 1,
        )

    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "pipeline_revision_conflict"


def test_save_template_validation_failure_keeps_previous_json(tmp_path: Path):
    initial = _save_agent_pipeline_template_with_md(tmp_path, _build_template())
    before_doc = _read_template_json(tmp_path, initial.id)

    md_path = _pipeline_md_path(tmp_path, initial.id)
    md_path.write_text(
        "---\n"
        f"pipeline_id: {initial.id}\n"
        "name: Broken\n"
        "version: 0.1.0\n"
        "---\n\n"
        "# Broken\n\n"
        "No step headings here.\n",
        encoding="utf-8",
    )

    with pytest.raises(HTTPException) as exc_info:
        _save_agent_pipeline_template_with_md(
            tmp_path,
            _build_template(),
            expected_revision=initial.revision,
        )

    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "pipeline_md_validation_failed"
    errors = detail.get("errors") or []
    assert isinstance(errors, list)
    assert errors

    after_doc = _read_template_json(tmp_path, initial.id)
    assert after_doc == before_doc
