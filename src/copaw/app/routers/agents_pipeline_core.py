# -*- coding: utf-8 -*-
"""Core models and helpers for project pipeline APIs."""

from __future__ import annotations

import json
import logging
import re
import hashlib
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, cast

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ...config.config import generate_short_agent_id

logger = logging.getLogger(__name__)

_PROJECT_PIPELINES_DIRNAME = "pipelines"
_PROJECT_PIPELINE_TEMPLATES_DIRNAME = "templates"
_PROJECT_PIPELINE_RUNS_DIRNAME = "runs"
_AGENT_PIPELINES_DIRNAME = "pipelines"
_AGENT_PIPELINE_TEMPLATES_DIRNAME = "templates"
_AGENT_PIPELINE_PLATFORM_DIRNAME = "platform-templates"
_AGENT_PIPELINE_WORKSPACES_DIRNAME = "workspaces"
_PIPELINE_MD_FILENAME = "pipeline.md"
_PIPELINE_MEMORY_FILENAME = "pipeline-workspaces.md"
_PIPELINE_FLOW_MEMORY_FILENAME = "flow-memory.md"


class PipelineTemplateStep(BaseModel):
    """Pipeline template step definition."""

    id: str
    name: str
    kind: str
    description: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    prompt: str = ""
    script: str = ""
    outputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    input_bindings: dict[str, str] = Field(default_factory=dict)
    retry_policy: dict[str, Any] = Field(default_factory=dict)


class PipelineTemplateInfo(BaseModel):
    """Project pipeline template metadata."""

    id: str
    name: str
    version: str = ""
    description: str = ""
    steps: list[PipelineTemplateStep] = Field(default_factory=list)
    revision: int = 0
    content_hash: str = ""
    md_mtime: float = 0.0
    validation_errors: list["PipelineValidationError"] = Field(default_factory=list)
    compilation_status: str = "ready"


class PipelineValidationError(BaseModel):
    """Structured validation error for pipeline markdown parsing/validation."""

    error_code: str
    message: str
    field_path: str
    step_id: str = ""
    expected: str = ""
    actual: str = ""
    suggestion: str = ""


class PipelineRunSummary(BaseModel):
    """Pipeline run summary."""

    id: str
    template_id: str
    status: str
    created_at: str
    updated_at: str
    focus_chat_id: str | None = None
    focus_type: str | None = None
    focus_path: str | None = None


class PipelineRunStep(BaseModel):
    """Pipeline run step state."""

    id: str
    name: str
    kind: str
    status: str
    started_at: str | None = None
    ended_at: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)


class PipelineArtifactRecord(BaseModel):
    """Structured artifact record with provenance."""

    artifact_id: str
    path: str
    name: str
    kind: str
    format: str = "bin"
    human_readable: bool = False
    run_id: str = ""
    producer_step_id: str | None = None
    producer_step_name: str | None = None
    consumer_step_ids: list[str] = Field(default_factory=list)
    consumer_step_names: list[str] = Field(default_factory=list)
    created_at: str = ""


class PipelineCollaborationEvent(BaseModel):
    """Structured collaboration event for one run."""

    ts: str
    event: str
    step_id: str = ""
    role: str = ""
    actor: str = ""
    status: str = ""
    message: str = ""
    evidence: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class PipelineRunDetail(PipelineRunSummary):
    """Pipeline run detail."""

    project_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    steps: list[PipelineRunStep] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    artifact_records: list[PipelineArtifactRecord] = Field(default_factory=list)
    flow_version: str = ""
    source_platform_template_id: str | None = None
    source_platform_template_version: str | None = None
    collaboration_events: list[PipelineCollaborationEvent] = Field(
        default_factory=list,
    )


class CreatePipelineRunRequest(BaseModel):
    """Create pipeline run request."""

    template_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class PipelineDraftInfo(BaseModel):
    """Pipeline draft info read from the workspace markdown file."""

    md_path: str
    md_relative_path: str
    flow_memory_path: str = ""
    flow_memory_relative_path: str = ""
    md_mtime: float
    steps: list[PipelineTemplateStep] = Field(default_factory=list)
    revision: int = 0
    content_hash: str = ""
    validation_errors: list[PipelineValidationError] = Field(default_factory=list)
    compilation_status: str = "ready"


class PlatformFlowTemplateInfo(PipelineTemplateInfo):
    """Project-agnostic platform flow template."""

    tags: list[str] = Field(default_factory=list)
    source_project_id: str | None = None
    source_project_template_id: str | None = None
    source_project_template_version: str | None = None


class ProjectFlowInstanceInfo(PipelineTemplateInfo):
    """Project-bound flow instance with optional upstream lineage."""

    project_id: str
    source_platform_template_id: str | None = None
    source_platform_template_version: str | None = None


class ImportPlatformTemplateRequest(BaseModel):
    """Import one platform template into a project as an instance."""

    platform_template_id: str
    target_template_id: str | None = None


class PublishProjectTemplateRequest(BaseModel):
    """Publish one project template back to platform library."""

    platform_template_id: str | None = None
    bump: str = "patch"
    tags: list[str] = Field(default_factory=list)


class PlatformTemplateVersionRecord(BaseModel):
    """Version history entry of one platform template."""

    template_id: str
    version: str
    published_at: str
    source_project_id: str | None = None
    source_project_template_id: str | None = None
    source_project_template_version: str | None = None
    bump: str = "patch"


def _pipeline_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _parse_pipeline_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_run_status(status: str) -> str:
    value = (status or "").strip().lower()
    if value == "completed":
        return "succeeded"
    if value in {"pending", "running", "blocked", "failed", "succeeded", "cancelled"}:
        return value
    return "pending"


def _normalize_step_status(status: str) -> str:
    value = (status or "").strip().lower()
    if value == "completed":
        return "succeeded"
    if value in {"pending", "running", "blocked", "failed", "succeeded", "skipped"}:
        return value
    return "pending"


def _is_safe_relative_path(rel_path: str) -> bool:
    if not rel_path:
        return False
    candidate = Path(rel_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    return True


def _project_pipeline_dirs(project_dir: Path) -> tuple[Path, Path, Path]:
    pipelines_dir = project_dir / _PROJECT_PIPELINES_DIRNAME
    templates_dir = pipelines_dir / _PROJECT_PIPELINE_TEMPLATES_DIRNAME
    runs_dir = pipelines_dir / _PROJECT_PIPELINE_RUNS_DIRNAME
    templates_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    return pipelines_dir, templates_dir, runs_dir


def _default_pipeline_template_doc() -> dict[str, Any]:
    return {
        "id": "books-alignment-v1",
        "name": "Multi-Book Processing v1",
        "version": "0.2.0",
        "description": "Full pipeline for multi-book ingestion, alignment, concept extraction, and report generation.",
        "steps": [
            {
                "id": "ingest",
                "name": "Ingest Books",
                "kind": "ingest",
                "description": "Discover and load all source markdown books into the processing corpus.",
            },
            {
                "id": "normalize",
                "name": "Normalize Structure",
                "kind": "transform",
                "description": "Apply heading and structure normalization across all books.",
            },
            {
                "id": "extract",
                "name": "Extract Entities",
                "kind": "transform",
                "description": "Extract named entities, terms, and citations from each book.",
            },
            {
                "id": "align",
                "name": "Cross-Book Alignment",
                "kind": "alignment",
                "description": "Perform sentence/chapter alignment across the entire book corpus.",
            },
            {
                "id": "build_concept_tree",
                "name": "Build Concept Tree",
                "kind": "analysis",
                "description": "Construct a hierarchical concept tree from the aligned and extracted content.",
            },
            {
                "id": "build_relation_matrix",
                "name": "Build Relation Matrix",
                "kind": "analysis",
                "description": "Compute cross-book relation and co-occurrence matrix.",
            },
            {
                "id": "review_pack",
                "name": "Review Pack",
                "kind": "validation",
                "description": "Generate review package: diffs, conflicts, and quality metrics.",
            },
            {
                "id": "report",
                "name": "Generate Report",
                "kind": "publish",
                "description": "Emit final manifests, reports, and artifacts for downstream use.",
            },
        ],
    }


def _ensure_default_pipeline_template(templates_dir: Path) -> None:
    default_path = templates_dir / "books-alignment-v1.json"
    if default_path.exists():
        return
    default_path.write_text(
        json.dumps(_default_pipeline_template_doc(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_pipeline_template_doc(raw: dict[str, Any], fallback_id: str) -> PipelineTemplateInfo | None:
    template_id = str(raw.get("id") or fallback_id).strip()
    name = str(raw.get("name") or template_id).strip()
    if not template_id or not name:
        return None

    steps: list[PipelineTemplateStep] = []
    for node in raw.get("steps") or []:
        if not isinstance(node, dict):
            continue
        step_id = str(node.get("id") or "").strip()
        step_name = str(node.get("name") or step_id).strip()
        step_kind = str(node.get("kind") or "task").strip() or "task"
        if not step_id or not step_name:
            continue
        raw_inputs = node.get("inputs")
        raw_outputs = node.get("outputs")
        raw_depends_on = node.get("depends_on")
        raw_input_bindings = node.get("input_bindings")
        raw_retry_policy = node.get("retry_policy")
        steps.append(
            PipelineTemplateStep(
                id=step_id,
                name=step_name,
                kind=step_kind,
                description=str(node.get("description") or "").strip(),
                inputs=raw_inputs if isinstance(raw_inputs, dict) else {},
                prompt=str(node.get("prompt") or "").strip(),
                script=str(node.get("script") or "").strip(),
                outputs=raw_outputs if isinstance(raw_outputs, dict) else {},
                depends_on=(
                    [str(item).strip() for item in raw_depends_on if str(item).strip()]
                    if isinstance(raw_depends_on, list)
                    else []
                ),
                input_bindings=(
                    {str(key): str(value) for key, value in raw_input_bindings.items()}
                    if isinstance(raw_input_bindings, dict)
                    else {}
                ),
                retry_policy=raw_retry_policy if isinstance(raw_retry_policy, dict) else {},
            ),
        )

    return PipelineTemplateInfo(
        id=template_id,
        name=name,
        version=str(raw.get("version") or "").strip(),
        description=str(raw.get("description") or "").strip(),
        steps=steps,
        revision=max(0, int(raw.get("revision") or 0)),
        content_hash=str(raw.get("content_hash") or "").strip(),
        md_mtime=float(raw.get("md_mtime") or 0.0),
        validation_errors=[
            PipelineValidationError.model_validate(item)
            for item in (raw.get("validation_errors") or [])
            if isinstance(item, dict)
        ],
        compilation_status=str(raw.get("compilation_status") or "ready").strip() or "ready",
    )


def _list_project_pipeline_templates(project_dir: Path) -> list[PipelineTemplateInfo]:
    _, templates_dir, _ = _project_pipeline_dirs(project_dir)
    _ensure_default_pipeline_template(templates_dir)

    templates: list[PipelineTemplateInfo] = []
    for path in sorted(templates_dir.glob("*.json"), key=lambda item: item.name.lower()):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            parsed = _parse_pipeline_template_doc(raw, fallback_id=path.stem)
            if parsed is not None:
                templates.append(parsed)
        except Exception as exc:
            logger.warning("Skip invalid pipeline template %s: %s", path, exc)
    return templates


def _agent_pipeline_templates_dir(workspace_dir: Path) -> Path:
    templates_dir = (
        workspace_dir / _AGENT_PIPELINES_DIRNAME / _AGENT_PIPELINE_TEMPLATES_DIRNAME
    )
    templates_dir.mkdir(parents=True, exist_ok=True)
    return templates_dir


def _agent_platform_templates_dir(workspace_dir: Path) -> Path:
    templates_dir = (
        workspace_dir
        / _AGENT_PIPELINES_DIRNAME
        / _AGENT_PIPELINE_PLATFORM_DIRNAME
    )
    templates_dir.mkdir(parents=True, exist_ok=True)
    return templates_dir


def _platform_template_history_path(
    workspace_dir: Path,
    template_id: str,
) -> Path:
    history_dir = _agent_platform_templates_dir(workspace_dir) / ".history"
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir / f"{template_id}.versions.json"


def _list_platform_template_versions(
    workspace_dir: Path,
    template_id: str,
) -> list[PlatformTemplateVersionRecord]:
    path = _platform_template_history_path(workspace_dir, template_id)
    if not path.exists() or not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [
        PlatformTemplateVersionRecord.model_validate(item)
        for item in raw
        if isinstance(item, dict)
    ]


def _append_platform_template_version(
    workspace_dir: Path,
    record: PlatformTemplateVersionRecord,
) -> None:
    history = _list_platform_template_versions(
        workspace_dir,
        record.template_id,
    )
    history.append(record)
    path = _platform_template_history_path(workspace_dir, record.template_id)
    path.write_text(
        json.dumps(
            [item.model_dump() for item in history],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _pipeline_workspace_dir(workspace_dir: Path, pipeline_id: str) -> Path:
    ws_dir = (
        workspace_dir
        / _AGENT_PIPELINES_DIRNAME
        / _AGENT_PIPELINE_WORKSPACES_DIRNAME
        / pipeline_id
    )
    ws_dir.mkdir(parents=True, exist_ok=True)
    return ws_dir


def _pipeline_md_path(workspace_dir: Path, pipeline_id: str) -> Path:
    return _pipeline_workspace_dir(workspace_dir, pipeline_id) / _PIPELINE_MD_FILENAME


def _pipeline_md_relative_path(pipeline_id: str) -> str:
    """Return the relative path (from workspace root) for the pipeline markdown."""
    return f"{_AGENT_PIPELINES_DIRNAME}/{_AGENT_PIPELINE_WORKSPACES_DIRNAME}/{pipeline_id}/{_PIPELINE_MD_FILENAME}"


def _pipeline_flow_memory_path(workspace_dir: Path, pipeline_id: str) -> Path:
    return _pipeline_workspace_dir(workspace_dir, pipeline_id) / _PIPELINE_FLOW_MEMORY_FILENAME


def _pipeline_flow_memory_relative_path(pipeline_id: str) -> str:
    return f"{_AGENT_PIPELINES_DIRNAME}/{_AGENT_PIPELINE_WORKSPACES_DIRNAME}/{pipeline_id}/{_PIPELINE_FLOW_MEMORY_FILENAME}"


def _ensure_pipeline_flow_memory(
    workspace_dir: Path,
    pipeline_id: str,
    pipeline_name: str,
) -> Path:
    """Ensure flow-scoped memory exists for this pipeline editing scope."""
    memory_path = _pipeline_flow_memory_path(workspace_dir, pipeline_id)
    if memory_path.exists():
        return memory_path

    memory_path.write_text(
        "\n".join(
            [
                "# Flow Scoped Memory",
                "",
                f"pipeline_id: {pipeline_id}",
                f"pipeline_name: {pipeline_name}",
                "",
                "仅在当前流程编辑会话中生效。",
                "可记录：目标、约束、临时决策、未完成事项。",
                "",
                "## Current Focus",
                "- ",
                "",
                "## Constraints",
                "- ",
                "",
                "## Pending",
                "- ",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return memory_path


def _pipeline_steps_to_md(template: PipelineTemplateInfo) -> str:
    """Generate a markdown representation of a pipeline template for agent editing.

    Format per step heading:
      ## <step-name> [<step-id>] (<kind>)
      <description>
    """
    lines: list[str] = [
        "---",
        f"pipeline_id: {template.id}",
        f"name: {template.name}",
        f"version: {template.version or '0.1.0'}",
        "---",
        "",
        f"# {template.name}",
        "",
        (template.description or "").strip(),
        "",
    ]
    for step in template.steps:
        lines.append(f"## {step.name} [{step.id}] ({step.kind})")
        lines.append("")
        if step.description:
            lines.append(step.description.strip())
            lines.append("")
        lines.append(f"- contract_inputs: {json.dumps(step.inputs or {}, ensure_ascii=False)}")
        lines.append(f"- contract_prompt: {json.dumps((step.prompt or '').strip(), ensure_ascii=False)}")
        lines.append(f"- contract_script: {json.dumps((step.script or '').strip(), ensure_ascii=False)}")
        lines.append(f"- contract_outputs: {json.dumps(step.outputs or {}, ensure_ascii=False)}")
        lines.append(f"- contract_depends_on: {json.dumps(step.depends_on or [], ensure_ascii=False)}")
        lines.append(f"- contract_input_bindings: {json.dumps(step.input_bindings or {}, ensure_ascii=False)}")
        lines.append(f"- contract_retry_policy: {json.dumps(step.retry_policy or {}, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


_STEP_HEADING_RE = re.compile(
    r"^##\s+(.+?)\s+\[([^\]]+)\]\s+\(([^)]+)\)\s*$"
)


def _parse_pipeline_md(content: str) -> list[PipelineTemplateStep]:
    """Parse markdown produced by _pipeline_steps_to_md back to step list.

    Each step heading:  ## <name> [<id>] (<kind>)
    followed by a description paragraph.
    Returns an empty list if no valid steps are found.
    """
    steps: list[PipelineTemplateStep] = []
    current: dict[str, str] | None = None
    desc_lines: list[str] = []
    contract_inputs: dict[str, Any] = {}
    contract_outputs: dict[str, Any] = {}
    contract_prompt = ""
    contract_script = ""
    contract_depends_on: list[str] = []
    contract_input_bindings: dict[str, str] = {}
    contract_retry_policy: dict[str, Any] = {}

    def _decode_contract_json(raw_value: str, fallback: Any) -> Any:
        try:
            return json.loads(raw_value)
        except Exception:
            return fallback

    def _flush() -> None:
        nonlocal contract_inputs, contract_outputs, contract_prompt, contract_script
        nonlocal contract_depends_on, contract_input_bindings, contract_retry_policy
        if current is not None:
            desc = " ".join(desc_lines).strip()
            steps.append(
                PipelineTemplateStep(
                    id=current["id"],
                    name=current["name"],
                    kind=current["kind"],
                    description=desc,
                    inputs=contract_inputs,
                    prompt=contract_prompt,
                    script=contract_script,
                    outputs=contract_outputs,
                    depends_on=contract_depends_on,
                    input_bindings=contract_input_bindings,
                    retry_policy=contract_retry_policy,
                )
            )
        contract_inputs = {}
        contract_outputs = {}
        contract_prompt = ""
        contract_script = ""
        contract_depends_on = []
        contract_input_bindings = {}
        contract_retry_policy = {}

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        m = _STEP_HEADING_RE.match(line)
        if m:
            _flush()
            current = {"name": m.group(1).strip(), "id": m.group(2).strip(), "kind": m.group(3).strip()}
            desc_lines = []
        elif current is not None:
            # Ignore top-level #/--- headers inside step sections
            if line.startswith("# ") or line.startswith("---"):
                continue
            contract_match = re.match(
                r"^\s*-\s*contract_(inputs|prompt|script|outputs|depends_on|input_bindings|retry_policy):\s*(.+?)\s*$",
                line,
            )
            if contract_match:
                contract_key = contract_match.group(1)
                contract_value = contract_match.group(2)
                if contract_key == "inputs":
                    parsed_inputs = _decode_contract_json(contract_value, {})
                    contract_inputs = parsed_inputs if isinstance(parsed_inputs, dict) else {}
                    continue
                if contract_key == "outputs":
                    parsed_outputs = _decode_contract_json(contract_value, {})
                    contract_outputs = parsed_outputs if isinstance(parsed_outputs, dict) else {}
                    continue
                if contract_key == "prompt":
                    parsed_prompt = _decode_contract_json(contract_value, "")
                    contract_prompt = str(parsed_prompt or "").strip()
                    continue
                if contract_key == "script":
                    parsed_script = _decode_contract_json(contract_value, "")
                    contract_script = str(parsed_script or "").strip()
                    continue
                if contract_key == "depends_on":
                    parsed_depends = _decode_contract_json(contract_value, [])
                    if isinstance(parsed_depends, list):
                        contract_depends_on = [
                            str(item).strip() for item in parsed_depends if str(item).strip()
                        ]
                    else:
                        contract_depends_on = []
                    continue
                if contract_key == "input_bindings":
                    parsed_bindings = _decode_contract_json(contract_value, {})
                    if isinstance(parsed_bindings, dict):
                        contract_input_bindings = {
                            str(key): str(value)
                            for key, value in parsed_bindings.items()
                            if str(key).strip() and str(value).strip()
                        }
                    else:
                        contract_input_bindings = {}
                    continue
                if contract_key == "retry_policy":
                    parsed_retry_policy = _decode_contract_json(contract_value, {})
                    contract_retry_policy = (
                        parsed_retry_policy
                        if isinstance(parsed_retry_policy, dict)
                        else {}
                    )
                    continue
            desc_lines.append(line)

    _flush()
    return steps


def _parse_md_frontmatter(content: str) -> tuple[dict[str, str], str]:
    lines = content.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}, content

    frontmatter: dict[str, str] = {}
    end_idx = -1
    for idx in range(1, len(lines)):
        line = lines[idx].rstrip()
        if line.strip() == "---":
            end_idx = idx
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip().lower()] = value.strip()

    if end_idx < 0:
        return {}, content
    body = "\n".join(lines[end_idx + 1 :])
    return frontmatter, body


_MD_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


def _parse_pipeline_md_strict(
    template_id: str,
    content: str,
    fallback_name: str,
    fallback_version: str,
    fallback_description: str,
) -> tuple[PipelineTemplateInfo, list[PipelineValidationError]]:
    """Parse markdown into template info and return structured validation errors."""
    frontmatter, body = _parse_md_frontmatter(content)
    errors: list[PipelineValidationError] = []

    parsed_id = (frontmatter.get("pipeline_id") or template_id).strip()
    if parsed_id and parsed_id != template_id:
        errors.append(
            PipelineValidationError(
                error_code="pipeline_id_mismatch",
                message="Frontmatter pipeline_id does not match template id.",
                field_path="frontmatter.pipeline_id",
                expected=template_id,
                actual=parsed_id,
                suggestion="Keep frontmatter pipeline_id equal to the template id.",
            )
        )

    name = (frontmatter.get("name") or fallback_name or template_id).strip() or template_id
    version = (frontmatter.get("version") or fallback_version or "0.1.0").strip() or "0.1.0"

    # Description is parsed from body content after first level-1 title and before first step heading.
    description_lines: list[str] = []
    found_title = False
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            break
        if line.startswith("# "):
            found_title = True
            continue
        if found_title:
            description_lines.append(line)
    description = " ".join(part.strip() for part in description_lines if part.strip())
    if not description:
        description = (fallback_description or "").strip()

    steps = _parse_pipeline_md(content)

    if not steps:
        errors.append(
            PipelineValidationError(
                error_code="steps_empty",
                message="No valid pipeline steps found in markdown.",
                field_path="steps",
                expected="At least one step heading in format: ## <name> [<id>] (<kind>)",
                actual="0 step",
                suggestion="Add at least one step heading and a description paragraph.",
            )
        )

    seen_step_ids: set[str] = set()
    for idx, step in enumerate(steps):
        step_path = f"steps[{idx}]"
        if not step.id.strip():
            errors.append(
                PipelineValidationError(
                    error_code="step_id_missing",
                    message="Step id is required.",
                    field_path=f"{step_path}.id",
                    suggestion="Use a stable id in heading brackets: [step-id].",
                )
            )
        if not step.name.strip():
            errors.append(
                PipelineValidationError(
                    error_code="step_name_missing",
                    message="Step name is required.",
                    field_path=f"{step_path}.name",
                    step_id=step.id,
                    suggestion="Use a non-empty step title before [id].",
                )
            )
        if not _MD_KIND_RE.match(step.kind.strip()):
            errors.append(
                PipelineValidationError(
                    error_code="step_kind_invalid",
                    message="Step kind format is invalid.",
                    field_path=f"{step_path}.kind",
                    step_id=step.id,
                    expected="lowercase kebab/snake style token, e.g. ingest/transform/validation",
                    actual=step.kind,
                    suggestion="Change kind to lowercase letters, digits, '_' or '-'.",
                )
            )
        if step.id in seen_step_ids:
            errors.append(
                PipelineValidationError(
                    error_code="step_id_duplicate",
                    message="Duplicate step id found.",
                    field_path=f"{step_path}.id",
                    step_id=step.id,
                    actual=step.id,
                    suggestion="Use unique step ids across the whole pipeline.",
                )
            )
        seen_step_ids.add(step.id)

        step_errors = _validate_pipeline_step(step)
        for item in step_errors:
            item.field_path = f"{step_path}.{item.field_path}"
            errors.append(item)

    errors.extend(_validate_pipeline_dependency_graph(steps))

    template = PipelineTemplateInfo(
        id=template_id,
        name=name,
        version=version,
        description=description,
        steps=steps,
        compilation_status="invalid" if errors else "ready",
        validation_errors=errors,
    )
    return template, errors


def _template_content_hash(template: PipelineTemplateInfo) -> str:
    canonical_doc = {
        "id": template.id,
        "name": template.name,
        "version": template.version,
        "description": template.description,
        "steps": [
            {
                "id": step.id,
                "name": step.name,
                "kind": step.kind,
                "description": step.description,
                "inputs": step.inputs,
                "prompt": step.prompt,
                "script": step.script,
                "outputs": step.outputs,
                "depends_on": step.depends_on,
                "input_bindings": step.input_bindings,
                "retry_policy": step.retry_policy,
            }
            for step in template.steps
        ],
    }
    raw = json.dumps(canonical_doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_pipeline_validation_exception(
    errors: list[PipelineValidationError],
    md_relative_path: str,
) -> HTTPException:
    detail = {
        "code": "pipeline_md_validation_failed",
        "message": "Pipeline markdown validation failed.",
        "md_relative_path": md_relative_path,
        "errors": [item.model_dump() for item in errors],
    }
    return HTTPException(status_code=422, detail=detail)


def _build_pipeline_revision_conflict_exception(
    expected_revision: int,
    current: PipelineTemplateInfo,
) -> HTTPException:
    detail = {
        "code": "pipeline_revision_conflict",
        "message": "Pipeline revision conflict.",
        "expected_revision": expected_revision,
        "current_revision": current.revision,
        "current_content_hash": current.content_hash,
    }
    return HTTPException(status_code=409, detail=detail)


def _load_agent_pipeline_template(workspace_dir: Path, template_id: str) -> PipelineTemplateInfo | None:
    target = _agent_pipeline_templates_dir(workspace_dir) / f"{template_id}.json"
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read pipeline template %s: %s", template_id, exc)
        return None
    if not isinstance(raw, dict):
        return None
    return _parse_pipeline_template_doc(raw, fallback_id=template_id)


def _sync_pipeline_md(workspace_dir: Path, template: PipelineTemplateInfo) -> Path:
    """Write (create or overwrite) the pipeline markdown file and return its path."""
    md_path = _pipeline_md_path(workspace_dir, template.id)
    md_content = _pipeline_steps_to_md(template)
    md_path.write_text(md_content, encoding="utf-8")
    return md_path


def _ensure_pipeline_draft_workspace(
    workspace_dir: Path,
    template: PipelineTemplateInfo,
) -> PipelineDraftInfo:
    """Ensure pipeline markdown workspace + flow memory exist, then return draft info."""
    template_id = (template.id or "").strip().lower()
    template_id = re.sub(r"[^a-z0-9_-]+", "-", template_id).strip("-")
    if not template_id:
        raise HTTPException(status_code=400, detail="Invalid pipeline template id")

    current = _load_agent_pipeline_template(workspace_dir, template_id)
    effective_template = PipelineTemplateInfo(
        id=template_id,
        name=((current.name if current else "") or template.name or template_id).strip() or template_id,
        version=((current.version if current else "") or template.version or "0.1.0").strip() or "0.1.0",
        description=((current.description if current else "") or template.description or "").strip(),
        steps=current.steps if current and current.steps else template.steps,
        revision=current.revision if current else 0,
        content_hash=current.content_hash if current else "",
        md_mtime=current.md_mtime if current else 0.0,
    )

    md_path = _pipeline_md_path(workspace_dir, template_id)
    if not md_path.exists():
        _sync_pipeline_md(workspace_dir, effective_template)

    _upsert_pipeline_workspace_memory(
        workspace_dir,
        effective_template.id,
        effective_template.name,
        _pipeline_md_relative_path(effective_template.id),
        _pipeline_flow_memory_relative_path(effective_template.id),
    )
    _ensure_pipeline_flow_memory(
        workspace_dir,
        effective_template.id,
        effective_template.name,
    )

    draft = _get_pipeline_draft(workspace_dir, effective_template.id)
    if draft is None:
        raise HTTPException(status_code=500, detail="Failed to initialize pipeline draft workspace")
    return draft


def _upsert_pipeline_workspace_memory(
    workspace_dir: Path,
    pipeline_id: str,
    pipeline_name: str,
    md_relative_path: str,
    flow_memory_relative_path: str,
) -> None:
    """Update the pipeline-workspaces memory file so the agent knows where to find the MD."""
    memory_dir = workspace_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    memory_path = memory_dir / _PIPELINE_MEMORY_FILENAME

    entry_marker = f"<!-- pipeline:{pipeline_id} -->"
    entry_text = (
        f"{entry_marker}\n"
        f"- **{pipeline_name}** (`{pipeline_id}`): `{md_relative_path}`\n"
        f"  - flow_memory: `{flow_memory_relative_path}`\n"
    )

    if memory_path.exists():
        existing = memory_path.read_text(encoding="utf-8")
        # Replace existing entry if present
        pattern = re.compile(
            rf"{re.escape(entry_marker)}\n.*?(?=\n<!-- pipeline:|\Z)",
            re.DOTALL,
        )
        if entry_marker in existing:
            updated = pattern.sub(entry_text, existing, count=1)
        else:
            updated = existing.rstrip() + "\n\n" + entry_text
        memory_path.write_text(updated, encoding="utf-8")
    else:
        header = (
            "# Pipeline Workspaces\n\n"
            "此文件由 CoPaw 自动维护，记录各流程的 Markdown 工作文件路径。\n"
            "编辑流程时请直接修改对应的 Markdown 文件。\n\n"
        )
        memory_path.write_text(header + entry_text, encoding="utf-8")


def _get_pipeline_draft(workspace_dir: Path, pipeline_id: str) -> PipelineDraftInfo | None:
    """Read the pipeline markdown and return parsed steps + metadata, or None if not exists."""
    md_path = _pipeline_md_path(workspace_dir, pipeline_id)
    if not md_path.exists():
        return None
    content = md_path.read_text(encoding="utf-8")
    current = _load_agent_pipeline_template(workspace_dir, pipeline_id)
    fallback_name = current.name if current else pipeline_id
    fallback_version = current.version if current else "0.1.0"
    fallback_description = current.description if current else ""
    parsed_template, errors = _parse_pipeline_md_strict(
        template_id=pipeline_id,
        content=content,
        fallback_name=fallback_name,
        fallback_version=fallback_version,
        fallback_description=fallback_description,
    )
    stat = md_path.stat()
    rel_path = _pipeline_md_relative_path(pipeline_id)
    content_hash = _template_content_hash(parsed_template) if not errors else ""
    return PipelineDraftInfo(
        md_path=str(md_path),
        md_relative_path=rel_path,
        flow_memory_path=str(_pipeline_flow_memory_path(workspace_dir, pipeline_id)),
        flow_memory_relative_path=_pipeline_flow_memory_relative_path(pipeline_id),
        md_mtime=stat.st_mtime,
        steps=parsed_template.steps,
        revision=current.revision if current else 0,
        content_hash=content_hash,
        validation_errors=errors,
        compilation_status="invalid" if errors else "ready",
    )


def _list_agent_pipeline_templates(workspace_dir: Path) -> list[PipelineTemplateInfo]:
    templates_dir = _agent_pipeline_templates_dir(workspace_dir)
    _ensure_default_pipeline_template(templates_dir)
    templates: list[PipelineTemplateInfo] = []

    for path in sorted(templates_dir.glob("*.json"), key=lambda item: item.name.lower()):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            parsed = _parse_pipeline_template_doc(raw, fallback_id=path.stem)
            if parsed is not None:
                templates.append(parsed)
        except Exception as exc:
            logger.warning("Skip invalid agent pipeline template %s: %s", path, exc)

    return templates


def _parse_platform_template_doc(
    raw: dict[str, Any],
    fallback_id: str,
) -> PlatformFlowTemplateInfo | None:
    parsed = _parse_pipeline_template_doc(raw, fallback_id)
    if parsed is None:
        return None
    return PlatformFlowTemplateInfo(
        **parsed.model_dump(),
        tags=[
            str(item).strip()
            for item in (raw.get("tags") or [])
            if str(item).strip()
        ],
        source_project_id=(str(raw.get("source_project_id") or "").strip() or None),
        source_project_template_id=(
            str(raw.get("source_project_template_id") or "").strip() or None
        ),
        source_project_template_version=(
            str(raw.get("source_project_template_version") or "").strip() or None
        ),
    )


def _list_platform_flow_templates(
    workspace_dir: Path,
) -> list[PlatformFlowTemplateInfo]:
    templates_dir = _agent_platform_templates_dir(workspace_dir)
    templates: list[PlatformFlowTemplateInfo] = []
    for path in sorted(
        templates_dir.glob("*.json"),
        key=lambda item: item.name.lower(),
    ):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            parsed = _parse_platform_template_doc(raw, fallback_id=path.stem)
            if parsed is not None:
                templates.append(parsed)
        except Exception as exc:
            logger.warning(
                "Skip invalid platform template %s: %s",
                path,
                exc,
            )
    return templates


def _bump_semver(version: str, mode: str) -> str:
    raw = (version or "0.1.0").strip()
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", raw)
    if m is None:
        return "0.1.0"
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if mode == "major":
        return f"{major + 1}.0.0"
    if mode == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _import_platform_template_to_project(
    project_id: str,
    project_dir: Path,
    platform_template: PlatformFlowTemplateInfo,
    target_template_id: str | None = None,
) -> ProjectFlowInstanceInfo:
    _, templates_dir, _ = _project_pipeline_dirs(project_dir)

    instance_id = (
        (target_template_id or platform_template.id).strip().lower()
    )
    instance_id = re.sub(r"[^a-z0-9_-]+", "-", instance_id).strip("-")
    if not instance_id:
        raise HTTPException(status_code=400, detail="Invalid target template id")

    template_doc = {
        "id": instance_id,
        "name": platform_template.name,
        "version": platform_template.version or "0.1.0",
        "description": platform_template.description,
        "steps": [
            {
                "id": step.id,
                "name": step.name,
                "kind": step.kind,
                "description": step.description,
                "inputs": step.inputs,
                "prompt": step.prompt,
                "script": step.script,
                "outputs": step.outputs,
                "depends_on": step.depends_on,
                "input_bindings": step.input_bindings,
                "retry_policy": step.retry_policy,
            }
            for step in platform_template.steps
        ],
        "source_platform_template_id": platform_template.id,
        "source_platform_template_version": platform_template.version,
        "imported_at": _pipeline_now_iso(),
    }

    target = templates_dir / f"{instance_id}.json"
    target.write_text(
        json.dumps(template_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return ProjectFlowInstanceInfo(
        id=instance_id,
        name=platform_template.name,
        version=platform_template.version or "0.1.0",
        description=platform_template.description,
        steps=platform_template.steps,
        project_id=project_id,
        source_platform_template_id=platform_template.id,
        source_platform_template_version=platform_template.version,
    )


def _publish_project_template_to_platform(
    project_id: str,
    project_dir: Path,
    workspace_dir: Path,
    template_id: str,
    platform_template_id: str | None = None,
    bump: str = "patch",
    tags: list[str] | None = None,
) -> PlatformFlowTemplateInfo:
    source_template = _resolve_pipeline_template(project_dir, template_id)
    target_id = (
        (platform_template_id or source_template.id).strip().lower()
    )
    target_id = re.sub(r"[^a-z0-9_-]+", "-", target_id).strip("-")
    if not target_id:
        raise HTTPException(status_code=400, detail="Invalid platform template id")

    current_templates = {
        item.id: item for item in _list_platform_flow_templates(workspace_dir)
    }
    current = current_templates.get(target_id)
    next_version = _bump_semver(
        current.version if current else source_template.version,
        bump,
    )

    merged_tags = tags or ([] if current is None else current.tags)
    merged_tags = [item for item in merged_tags if item]

    doc = {
        "id": target_id,
        "name": source_template.name,
        "version": next_version,
        "description": source_template.description,
        "steps": [
            {
                "id": step.id,
                "name": step.name,
                "kind": step.kind,
                "description": step.description,
                "inputs": step.inputs,
                "prompt": step.prompt,
                "script": step.script,
                "outputs": step.outputs,
                "depends_on": step.depends_on,
                "input_bindings": step.input_bindings,
                "retry_policy": step.retry_policy,
            }
            for step in source_template.steps
        ],
        "tags": merged_tags,
        "source_project_id": project_id,
        "source_project_template_id": source_template.id,
        "source_project_template_version": source_template.version,
        "published_at": _pipeline_now_iso(),
    }

    target = _agent_platform_templates_dir(workspace_dir) / f"{target_id}.json"
    target.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    _append_platform_template_version(
        workspace_dir,
        PlatformTemplateVersionRecord(
            template_id=target_id,
            version=next_version,
            published_at=str(doc.get("published_at") or _pipeline_now_iso()),
            source_project_id=project_id,
            source_project_template_id=source_template.id,
            source_project_template_version=source_template.version,
            bump=bump,
        ),
    )

    return PlatformFlowTemplateInfo(
        id=target_id,
        name=source_template.name,
        version=next_version,
        description=source_template.description,
        steps=source_template.steps,
        tags=merged_tags,
        source_project_id=project_id,
        source_project_template_id=source_template.id,
        source_project_template_version=source_template.version,
    )


def _save_agent_pipeline_template(
    workspace_dir: Path,
    template: PipelineTemplateInfo,
) -> PipelineTemplateInfo:
    template_id = (template.id or "").strip().lower()
    template_id = re.sub(r"[^a-z0-9_-]+", "-", template_id).strip("-")
    if not template_id:
        raise HTTPException(status_code=400, detail="Invalid pipeline template id")

    normalized = PipelineTemplateInfo(
        id=template_id,
        name=(template.name or template_id).strip() or template_id,
        version=(template.version or "0.1.0").strip() or "0.1.0",
        description=(template.description or "").strip(),
        steps=template.steps,
    )

    template_doc = {
        "id": normalized.id,
        "name": normalized.name,
        "version": normalized.version,
        "description": normalized.description,
        "steps": [
            {
                "id": step.id,
                "name": step.name,
                "kind": step.kind,
                "description": step.description,
                "inputs": step.inputs,
                "prompt": step.prompt,
                "script": step.script,
                "outputs": step.outputs,
                "depends_on": step.depends_on,
                "input_bindings": step.input_bindings,
                "retry_policy": step.retry_policy,
            }
            for step in normalized.steps
        ],
    }

    target = _agent_pipeline_templates_dir(workspace_dir) / f"{normalized.id}.json"
    target.write_text(
        json.dumps(template_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return normalized


def _save_agent_pipeline_template_with_md(
    workspace_dir: Path,
    template: PipelineTemplateInfo,
    expected_revision: int | None = None,
) -> PipelineTemplateInfo:
    """Markdown is the source of truth; derive JSON with strict validation and idempotent revision/hash."""
    template_id = (template.id or "").strip().lower()
    template_id = re.sub(r"[^a-z0-9_-]+", "-", template_id).strip("-")
    if not template_id:
        raise HTTPException(status_code=400, detail="Invalid pipeline template id")

    current = _load_agent_pipeline_template(workspace_dir, template_id)
    if (
        expected_revision is not None
        and expected_revision >= 0
        and current is not None
        and current.revision != expected_revision
    ):
        raise _build_pipeline_revision_conflict_exception(expected_revision, current)

    base_template = PipelineTemplateInfo(
        id=template_id,
        name=(template.name or template_id).strip() or template_id,
        version=(template.version or "0.1.0").strip() or "0.1.0",
        description=(template.description or "").strip(),
        steps=template.steps,
        revision=current.revision if current else 0,
        content_hash=current.content_hash if current else "",
        md_mtime=current.md_mtime if current else 0.0,
    )

    md_path = _pipeline_md_path(workspace_dir, template_id)
    if not md_path.exists():
        # Bootstrap markdown workspace from payload only once when markdown does not exist.
        md_path.write_text(_pipeline_steps_to_md(base_template), encoding="utf-8")

    md_content = md_path.read_text(encoding="utf-8")
    parsed_template, errors = _parse_pipeline_md_strict(
        template_id=template_id,
        content=md_content,
        fallback_name=base_template.name,
        fallback_version=base_template.version,
        fallback_description=base_template.description,
    )
    if errors:
        raise _build_pipeline_validation_exception(errors, _pipeline_md_relative_path(template_id))

    parsed_template.md_mtime = md_path.stat().st_mtime
    parsed_template.content_hash = _template_content_hash(parsed_template)
    if current and current.content_hash == parsed_template.content_hash:
        parsed_template.revision = current.revision
    else:
        parsed_template.revision = (current.revision if current else 0) + 1
    parsed_template.compilation_status = "ready"
    parsed_template.validation_errors = []

    template_doc = {
        "id": parsed_template.id,
        "name": parsed_template.name,
        "version": parsed_template.version,
        "description": parsed_template.description,
        "steps": [
            {
                "id": step.id,
                "name": step.name,
                "kind": step.kind,
                "description": step.description,
                "inputs": step.inputs,
                "prompt": step.prompt,
                "script": step.script,
                "outputs": step.outputs,
                "depends_on": step.depends_on,
                "input_bindings": step.input_bindings,
                "retry_policy": step.retry_policy,
            }
            for step in parsed_template.steps
        ],
        "revision": parsed_template.revision,
        "content_hash": parsed_template.content_hash,
        "md_mtime": parsed_template.md_mtime,
        "validation_errors": [],
        "compilation_status": parsed_template.compilation_status,
    }

    target = _agent_pipeline_templates_dir(workspace_dir) / f"{parsed_template.id}.json"
    target.write_text(
        json.dumps(template_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _upsert_pipeline_workspace_memory(
        workspace_dir,
        parsed_template.id,
        parsed_template.name,
        _pipeline_md_relative_path(parsed_template.id),
        _pipeline_flow_memory_relative_path(parsed_template.id),
    )
    _ensure_pipeline_flow_memory(
        workspace_dir,
        parsed_template.id,
        parsed_template.name,
    )
    return parsed_template


def _validate_pipeline_step(step: PipelineTemplateStep) -> list[PipelineValidationError]:
    """Validate a single pipeline step. Return list of errors if any."""
    # Valid step kinds
    VALID_STEP_KINDS = {
        "input", "analysis", "transform", "review",
        "validation", "publish", "task", "output", "ingest", "alignment"
    }
    
    errors: list[PipelineValidationError] = []
    
    # Validate step id
    step_id = (step.id or "").strip()
    if not step_id:
        errors.append(
            PipelineValidationError(
                error_code="missing_step_id",
                message="Step id is required",
                field_path="id",
                step_id="",
                expected="non-empty string",
                actual="",
                suggestion="Provide a unique identifier for the step",
            )
        )
    elif not re.match(r"^[a-z][a-z0-9_-]{0,63}$", step_id):
        errors.append(
            PipelineValidationError(
                error_code="invalid_step_id_format",
                message="Step id must be lowercase alphanumeric with hyphens/underscores, start with letter",
                field_path="id",
                step_id=step_id,
                expected="^[a-z][a-z0-9_-]{0,63}$",
                actual=step_id,
                suggestion="Use lowercase letters, numbers, hyphens, underscores",
            )
        )
    
    # Validate step name
    step_name = (step.name or "").strip()
    if not step_name:
        errors.append(
            PipelineValidationError(
                error_code="missing_step_name",
                message="Step name is required",
                field_path="name",
                step_id=step_id,
                expected="non-empty string",
                actual="",
                suggestion="Provide a human-readable display name",
            )
        )
    
    # Validate step kind
    step_kind = (step.kind or "").strip()
    if not step_kind:
        errors.append(
            PipelineValidationError(
                error_code="missing_step_kind",
                message="Step kind is required",
                field_path="kind",
                step_id=step_id,
                expected="one of: input, analysis, transform, review, validation, publish, task, output",
                actual="",
                suggestion="Choose a valid step kind",
            )
        )
    elif step_kind not in VALID_STEP_KINDS:
        errors.append(
            PipelineValidationError(
                error_code="invalid_step_kind",
                message=f"Step kind '{step_kind}' is not valid",
                field_path="kind",
                step_id=step_id,
                expected=", ".join(sorted(VALID_STEP_KINDS)),
                actual=step_kind,
                suggestion=f"Use one of: {', '.join(sorted(VALID_STEP_KINDS))}",
            )
        )

    # Validate explicit step contract fields
    if not isinstance(step.inputs, dict):
        errors.append(
            PipelineValidationError(
                error_code="invalid_step_inputs",
                message="Step inputs must be an object.",
                field_path="inputs",
                step_id=step_id,
                expected="object/dict",
                actual=type(step.inputs).__name__,
                suggestion="Set inputs as a JSON object with declared input contract.",
            )
        )

    if not isinstance(step.outputs, dict):
        errors.append(
            PipelineValidationError(
                error_code="invalid_step_outputs",
                message="Step outputs must be an object.",
                field_path="outputs",
                step_id=step_id,
                expected="object/dict",
                actual=type(step.outputs).__name__,
                suggestion="Set outputs as a JSON object with declared output contract.",
            )
        )

    if not isinstance(step.depends_on, list):
        errors.append(
            PipelineValidationError(
                error_code="invalid_step_depends_on",
                message="Step depends_on must be a list.",
                field_path="depends_on",
                step_id=step_id,
                expected="array/list of step ids",
                actual=type(step.depends_on).__name__,
                suggestion="Set depends_on as an array of upstream step ids.",
            )
        )

    if not isinstance(step.input_bindings, dict):
        errors.append(
            PipelineValidationError(
                error_code="invalid_step_input_bindings",
                message="Step input_bindings must be an object.",
                field_path="input_bindings",
                step_id=step_id,
                expected="object/dict",
                actual=type(step.input_bindings).__name__,
                suggestion="Set input_bindings as a JSON object like {'input': 'upstream.output'}.",
            )
        )

    if not isinstance(step.retry_policy, dict):
        errors.append(
            PipelineValidationError(
                error_code="invalid_step_retry_policy",
                message="Step retry_policy must be an object.",
                field_path="retry_policy",
                step_id=step_id,
                expected="object/dict",
                actual=type(step.retry_policy).__name__,
                suggestion="Set retry_policy as an object like {'max_attempts': 2}.",
            )
        )

    if isinstance(step.retry_policy, dict) and "max_attempts" in step.retry_policy:
        max_attempts = step.retry_policy.get("max_attempts")
        if not isinstance(max_attempts, int) or max_attempts < 0 or max_attempts > 10:
            errors.append(
                PipelineValidationError(
                    error_code="invalid_step_retry_max_attempts",
                    message="retry_policy.max_attempts must be an integer between 0 and 10.",
                    field_path="retry_policy.max_attempts",
                    step_id=step_id,
                    expected="integer in [0, 10]",
                    actual=str(max_attempts),
                    suggestion="Set retry_policy.max_attempts to a small integer such as 1 or 2.",
                )
            )

    step_prompt = (step.prompt or "").strip()
    step_script = (step.script or "").strip()
    executable_kinds = {
        "analysis",
        "transform",
        "review",
        "validation",
        "publish",
        "task",
        "alignment",
        "ingest",
    }
    if step_kind in executable_kinds and not step_prompt and not step_script:
        errors.append(
            PipelineValidationError(
                error_code="missing_step_execution_contract",
                message="Step requires prompt or script to define execution contract.",
                field_path="prompt|script",
                step_id=step_id,
                expected="non-empty prompt or script",
                actual="",
                suggestion="Provide prompt, script, or both for executable step kinds.",
            )
        )
    
    return errors


def _validate_pipeline_dependency_graph(
    steps: list[PipelineTemplateStep],
) -> list[PipelineValidationError]:
    """Validate dependency existence and cycle in a pipeline."""
    errors: list[PipelineValidationError] = []
    step_ids = {step.id for step in steps}

    for idx, step in enumerate(steps):
        step_path = f"steps[{idx}].depends_on"
        for dep in step.depends_on:
            dep_id = (dep or "").strip()
            if not dep_id:
                continue
            if dep_id == step.id:
                errors.append(
                    PipelineValidationError(
                        error_code="step_dependency_self_reference",
                        message="Step cannot depend on itself.",
                        field_path=step_path,
                        step_id=step.id,
                        expected="upstream step id different from self",
                        actual=dep_id,
                        suggestion="Remove self reference from depends_on.",
                    )
                )
                continue
            if dep_id not in step_ids:
                errors.append(
                    PipelineValidationError(
                        error_code="step_dependency_not_found",
                        message="Dependency step id not found in this pipeline.",
                        field_path=step_path,
                        step_id=step.id,
                        expected="existing step id",
                        actual=dep_id,
                        suggestion="Add the missing upstream step or fix the dependency id.",
                    )
                )

    graph: dict[str, list[str]] = {
        step.id: [dep for dep in step.depends_on if dep in step_ids and dep != step.id]
        for step in steps
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def _dfs(node: str, path: list[str]) -> None:
        if node in visiting:
            cycle = " -> ".join([*path, node])
            errors.append(
                PipelineValidationError(
                    error_code="step_dependency_cycle",
                    message="Dependency cycle detected.",
                    field_path="steps",
                    step_id=node,
                    expected="acyclic dependency graph",
                    actual=cycle,
                    suggestion="Break the cycle by removing at least one dependency edge.",
                )
            )
            return
        if node in visited:
            return

        visiting.add(node)
        for upstream in graph.get(node, []):
            _dfs(upstream, [*path, node])
        visiting.remove(node)
        visited.add(node)

    for step in steps:
        _dfs(step.id, [])

    return errors


def _update_step_in_markdown(
    md_content: str,
    step_id: str,
    step: PipelineTemplateStep | None = None,
    operation: str = "update",
) -> tuple[str, bool]:
    """Add, update, or delete a step in markdown content.
    
    Args:
        md_content: Current markdown content
        step_id: ID of the step to target
        step: New step data (for add/update operations)
        operation: 'add', 'update', or 'delete'
    
    Returns:
        (new_markdown_content, step_was_present)
    """
    lines = md_content.splitlines(keepends=True)
    step_found = False
    new_lines: list[str] = []
    step_start_idx = -1
    step_end_idx = -1
    
    # Find step location
    for idx, line in enumerate(lines):
        match = _STEP_HEADING_RE.match(line.rstrip())
        if match and match.group(2).strip() == step_id:
            step_found = True
            step_start_idx = idx
            # Find end of step (next heading or end of file)
            for end_idx in range(idx + 1, len(lines)):
                if _STEP_HEADING_RE.match(lines[end_idx].rstrip()):
                    step_end_idx = end_idx
                    break
            if step_end_idx < 0:
                step_end_idx = len(lines)
            break
    
    if operation == "delete":
        if step_found:
            # Remove step section
            new_lines = lines[:step_start_idx] + lines[step_end_idx:]
        else:
            new_lines = lines
        return "".join(new_lines), step_found
    
    if operation == "add":
        if step is None:
            raise ValueError("step is required for add operation")
        if step_found:
            raise HTTPException(
                status_code=400,
                detail=f"Step '{step_id}' already exists"
            )
        # Add at end of file
        new_content = "".join(lines).rstrip() + "\n\n"
        new_content += f"## {step.name} [{step.id}] ({step.kind})\n\n"
        if step.description:
            new_content += step.description.strip() + "\n\n"
        return new_content, False
    
    if operation == "update":
        if step is None:
            raise ValueError("step is required for update operation")
        if not step_found:
            raise HTTPException(
                status_code=404,
                detail=f"Step '{step_id}' not found"
            )
        # Replace step section
        heading = f"## {step.name} [{step.id}] ({step.kind})\n\n"
        description = ""
        if step.description:
            description = step.description.strip() + "\n\n"
        
        new_lines = (
            lines[:step_start_idx]
            + [heading, description]
            + (lines[step_end_idx:] if step_end_idx < len(lines) else [])
        )
        return "".join(new_lines), True
    
    return md_content, step_found


def _apply_step_operation(
    workspace_dir: Path,
    template_id: str,
    step: PipelineTemplateStep | None = None,
    step_id: str | None = None,
    operation: str = "update",
    expected_revision: int | None = None,
) -> PipelineTemplateInfo:
    """Apply a single step operation in pipeline markdown.
    
    Args:
        workspace_dir: Agent workspace directory
        template_id: Pipeline template ID
        step: Step payload for add/update
        step_id: Step id for delete or explicit targeting
        operation: 'add', 'update', or 'delete'
        expected_revision: Optional concurrency check
    
    Returns:
        Updated PipelineTemplateInfo
    """
    target_step_id = (step_id or (step.id if step else "")).strip()
    if not target_step_id:
        raise HTTPException(status_code=400, detail="step_id is required")

    if operation in ("add", "update"):
        if step is None:
            raise HTTPException(status_code=400, detail="step payload is required")
        validation_errors = _validate_pipeline_step(step)
        if validation_errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "validation_errors": [e.model_dump() for e in validation_errors],
                    "code": "step_validation_failed",
                }
            )
    elif operation != "delete":
        raise HTTPException(status_code=400, detail="operation must be add, update, or delete")
    
    # Load current template and markdown
    current = _load_agent_pipeline_template(workspace_dir, template_id)
    if (
        expected_revision is not None
        and expected_revision >= 0
        and current is not None
        and current.revision != expected_revision
    ):
        raise _build_pipeline_revision_conflict_exception(expected_revision, current)
    
    md_path = _pipeline_md_path(workspace_dir, template_id)
    if not md_path.exists():
        raise HTTPException(status_code=404, detail=f"Pipeline '{template_id}' not found")
    
    md_content = md_path.read_text(encoding="utf-8")
    
    # Modify markdown
    new_md_content, step_found = _update_step_in_markdown(md_content, target_step_id, step, operation)

    if operation == "delete" and not step_found:
        raise HTTPException(status_code=404, detail=f"Step '{target_step_id}' not found")
    
    # Parse and validate full pipeline
    frontmatter, body = _parse_md_frontmatter(new_md_content)
    parsed_template, errors = _parse_pipeline_md_strict(
        template_id=template_id,
        content=new_md_content,
        fallback_name=current.name if current else template_id,
        fallback_version=current.version if current else "0.1.0",
        fallback_description=current.description if current else "",
    )
    
    if errors:
        raise _build_pipeline_validation_exception(errors, _pipeline_md_relative_path(template_id))
    
    # Update markdown file
    md_path.write_text(new_md_content, encoding="utf-8")
    
    # Update JSON and revision
    parsed_template.md_mtime = md_path.stat().st_mtime
    parsed_template.content_hash = _template_content_hash(parsed_template)
    if current and current.content_hash == parsed_template.content_hash:
        parsed_template.revision = current.revision
    else:
        parsed_template.revision = (current.revision if current else 0) + 1
    parsed_template.compilation_status = "ready"
    parsed_template.validation_errors = []
    
    # Save JSON template
    template_doc = {
        "id": parsed_template.id,
        "name": parsed_template.name,
        "version": parsed_template.version,
        "description": parsed_template.description,
        "steps": [
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind,
                "description": s.description,
            }
            for s in parsed_template.steps
        ],
        "revision": parsed_template.revision,
        "content_hash": parsed_template.content_hash,
        "md_mtime": parsed_template.md_mtime,
        "validation_errors": [],
        "compilation_status": parsed_template.compilation_status,
    }
    
    target = _agent_pipeline_templates_dir(workspace_dir) / f"{parsed_template.id}.json"
    target.write_text(
        json.dumps(template_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    
    return parsed_template


def _add_or_update_step(
    workspace_dir: Path,
    template_id: str,
    step: PipelineTemplateStep,
    operation: str = "update",
    expected_revision: int | None = None,
) -> PipelineTemplateInfo:
    """Backward-compatible wrapper for add/update operations."""
    return _apply_step_operation(
        workspace_dir,
        template_id,
        step=step,
        step_id=step.id,
        operation=operation,
        expected_revision=expected_revision,
    )


def _delete_step(
    workspace_dir: Path,
    template_id: str,
    step_id: str,
    expected_revision: int | None = None,
) -> PipelineTemplateInfo:
    """Delete a single step from pipeline markdown."""
    return _apply_step_operation(
        workspace_dir,
        template_id,
        step=None,
        step_id=step_id,
        operation="delete",
        expected_revision=expected_revision,
    )


def _resolve_pipeline_template(project_dir: Path, template_id: str) -> PipelineTemplateInfo:
    templates = _list_project_pipeline_templates(project_dir)
    for template in templates:
        if template.id == template_id:
            return template
    raise HTTPException(status_code=404, detail=f"Pipeline template '{template_id}' not found")


def _load_project_template_doc(
    project_dir: Path,
    template_id: str,
) -> dict[str, Any]:
    """Load raw template doc to read lineage fields not in core model."""
    _, templates_dir, _ = _project_pipeline_dirs(project_dir)
    target = templates_dir / f"{template_id}.json"
    if not target.exists() or not target.is_file():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _infer_collab_role(step_kind: str) -> str:
    mapping = {
        "ingest": "collector",
        "transform": "processor",
        "alignment": "aligner",
        "analysis": "analyst",
        "validation": "reviewer",
        "publish": "publisher",
    }
    return mapping.get(step_kind, "executor")


def _append_collab_event(
    run: PipelineRunDetail,
    event: str,
    *,
    step_id: str = "",
    role: str = "",
    actor: str = "multi-agent",
    status: str = "",
    message: str = "",
    evidence: list[str] | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    run.collaboration_events.append(
        PipelineCollaborationEvent(
            ts=_pipeline_now_iso(),
            event=event,
            step_id=step_id,
            role=role,
            actor=actor,
            status=status,
            message=message,
            evidence=evidence or [],
            metrics=metrics or {},
        )
    )


def _step_storage_name(step_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", step_id.strip())
    return safe or "step"


def _run_dir_paths(runs_dir: Path, run_id: str) -> tuple[Path, Path, Path]:
    if not run_id or "/" in run_id or "\\" in run_id:
        raise HTTPException(status_code=400, detail="Invalid run id")
    run_dir = (runs_dir / run_id).resolve()
    if not str(run_dir).startswith(str(runs_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid run id")
    manifest_path = run_dir / "run_manifest.json"
    steps_dir = run_dir / "steps"
    return run_dir, manifest_path, steps_dir


def _infer_output_format(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in {".md", ".markdown"}:
        return "md"
    if suffix == ".csv":
        return "csv"
    if suffix in {".htm", ".html"}:
        return "html"
    if suffix in {".txt", ".log"}:
        return "txt"
    return "bin"


def _write_step_manifests(
    run_dir: Path,
    run_id: str,
    step: PipelineRunStep,
    generated_at: str,
    output_paths: list[str],
) -> tuple[str, str]:
    step_storage = _step_storage_name(step.id)
    step_dir = run_dir / "steps" / step_storage
    step_dir.mkdir(parents=True, exist_ok=True)

    artifact_manifest_rel = f"steps/{step_storage}/artifact_manifest.json"
    metric_pack_rel = f"steps/{step_storage}/metric_pack.json"

    artifact_manifest = {
        "artifact_id": f"{run_id}-{step.id}",
        "run_id": run_id,
        "step_id": step.id,
        "generated_at": generated_at,
        "producer": step.kind,
        "inputs": [],
        "outputs": [
            {
                "path": path,
                "role": "preview",
                "format": _infer_output_format(path),
                "human_readable": _infer_output_format(path) != "bin",
            }
            for path in output_paths
        ],
        "evidence": [
            {
                "kind": "rule-hit",
                "source": ref,
            }
            for ref in step.evidence
        ],
    }

    metric_pack = {
        "run_id": run_id,
        "step_id": step.id,
        "generated_at": generated_at,
        "metrics": [
            {
                "key": key,
                "value": float(value),
                "unit": "count",
            }
            for key, value in step.metrics.items()
            if isinstance(value, (int, float))
        ],
        "quality_gates": [],
    }

    (step_dir / "artifact_manifest.json").write_text(
        json.dumps(artifact_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (step_dir / "metric_pack.json").write_text(
        json.dumps(metric_pack, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return artifact_manifest_rel, metric_pack_rel


def _sample_project_artifacts(project_dir: Path, limit: int = 20) -> list[str]:
    project_root = project_dir.resolve()
    artifacts: list[str] = []
    for path in sorted(project_root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        rel = path.resolve().relative_to(project_root).as_posix()
        if rel.startswith(".git/") or "/.git/" in rel:
            continue
        if rel.startswith("pipelines/"):
            continue
        artifacts.append(rel)
        if len(artifacts) >= limit:
            break
    return artifacts


def _list_project_data_files(project_dir: Path) -> list[str]:
    data_dir = project_dir / "data"
    project_root = project_dir.resolve()
    if not data_dir.exists() or not data_dir.is_dir():
        return []

    files: list[str] = []
    for path in sorted(data_dir.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        files.append(path.resolve().relative_to(project_root).as_posix())
    return files


def _match_project_artifacts(paths: list[str], *patterns: str) -> list[str]:
    matched: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if any(fnmatch(path, pattern) for pattern in patterns):
            if path not in seen:
                matched.append(path)
                seen.add(path)
    return matched


def _compute_step_outputs(step_id: str, data_files: list[str]) -> tuple[list[str], dict[str, Any]]:
    markdown_inputs = _match_project_artifacts(data_files, "data/*.md")
    workbench_dirs = sorted(
        {
            path.rsplit("/", 1)[0]
            for path in data_files
            if path.startswith("data/term-workbench-") and "/" in path
        },
    )

    if step_id == "ingest":
        outputs = markdown_inputs
        return outputs, {
            "input_files": len(markdown_inputs),
            "markdown_files": len(markdown_inputs),
        }

    if step_id == "normalize":
        outputs = markdown_inputs
        return outputs, {
            "normalized_files": len(markdown_inputs),
        }

    if step_id == "extract":
        outputs = _match_project_artifacts(
            data_files,
            "data/term-workbench-*/manifest.json",
            "data/term-workbench-*/terms.normalized.json",
            "data/term-workbench-*/terms.reviewed.json",
            "data/term-workbench-*/terms.baseline*.json",
            "data/term-workbench-*/code-map*.json",
        )
        return outputs, {
            "workbench_count": len(workbench_dirs),
            "output_files": len(outputs),
        }

    if step_id == "align":
        outputs = _match_project_artifacts(
            data_files,
            "data/contrast-*.json",
            "data/contrast-*.md",
            "data/concept-trees/*/concept-alignment*.json",
            "data/concept-trees/*/concept-alignment*.md",
        )
        return outputs, {
            "alignment_outputs": len(outputs),
        }

    if step_id == "build_concept_tree":
        outputs = _match_project_artifacts(
            data_files,
            "data/concept-trees/*/concept-tree*.json",
            "data/concept-trees/*/concept-tree*.md",
            "data/concept-trees/*/concept-tree.index.*",
        )
        return outputs, {
            "concept_tree_outputs": len(outputs),
        }

    if step_id == "build_relation_matrix":
        outputs = _match_project_artifacts(
            data_files,
            "data/book-relation-matrix*.json",
            "data/book-relation-matrix*.md",
            "data/concept-trees/*/concept-alignment.incremental-matrix.*",
        )
        return outputs, {
            "relation_outputs": len(outputs),
        }

    if step_id == "review_pack":
        outputs = _match_project_artifacts(
            data_files,
            "data/review.dashboard*.json",
            "data/review.ui-payload*.json",
            "data/term-eval-detailed-report*.md",
        )
        return outputs, {
            "review_outputs": len(outputs),
        }

    if step_id == "report":
        outputs = _match_project_artifacts(
            data_files,
            "data/*summary-report.md",
            "data/repo-archive.manifest.json",
            "data/concept-trees/*.zip",
            "data/concept-trees/*/*.zip",
            "data/concept-trees/*/*.sha256",
        )
        return outputs, {
            "report_outputs": len(outputs),
        }

    return [], {}


def _apply_real_step_results(project_dir: Path, step: PipelineRunStep) -> list[str]:
    data_files = _list_project_data_files(project_dir)
    outputs, metrics = _compute_step_outputs(step.id, data_files)

    warning_count = 0
    if not data_files:
        raise ValueError("Project data directory is missing or contains no files")
    if not outputs:
        warning_count = 1

    step.metrics = {
        **step.metrics,
        **metrics,
        "warning_count": warning_count,
    }
    step.evidence = outputs[:20] or ["PROJECT.md"]
    return outputs


def _persist_project_pipeline_run(project_dir: Path, run: PipelineRunDetail, template: PipelineTemplateInfo) -> None:
    _, _, runs_dir = _project_pipeline_dirs(project_dir)
    run_dir, manifest_path, _ = _run_dir_paths(runs_dir, run.id)
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest_steps: list[dict[str, Any]] = []
    shared_artifacts = run.artifacts[:8]
    for idx, step in enumerate(run.steps):
        output_paths = shared_artifacts if idx == len(run.steps) - 1 else []
        artifact_manifest_rel, metric_pack_rel = _write_step_manifests(
            run_dir,
            run.id,
            step,
            run.updated_at,
            output_paths,
        )

        manifest_steps.append(
            {
                "step_id": step.id,
                "status": _normalize_step_status(step.status),
                "attempts": 1,
                "started_at": step.started_at,
                "ended_at": step.ended_at,
                "artifact_manifest": artifact_manifest_rel,
                "metric_pack": metric_pack_rel,
                "logs": [],
            },
        )

    manifest = {
        "run_id": run.id,
        "project_id": run.project_id,
        "dataset_id": "",
        "pipeline_id": run.template_id,
        "pipeline_version": template.version,
        "flow_version": run.flow_version or template.version,
        "source_platform_template_id": run.source_platform_template_id,
        "source_platform_template_version": run.source_platform_template_version,
        "spec_version": "0.1.0",
        "status": _normalize_run_status(run.status),
        "started_at": run.created_at,
        "ended_at": (
            run.updated_at
            if _normalize_run_status(run.status) in {"succeeded", "failed", "cancelled"}
            else None
        ),
        "params": run.parameters,
        "steps": manifest_steps,
        "collaboration_events": [
            item.model_dump()
            for item in run.collaboration_events
        ],
    }

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_pipeline_artifact_records(
    project_dir: Path,
    run_id: str,
    template: PipelineTemplateInfo,
    generated_at: str,
    raw_steps: list[dict[str, Any]],
    run_dir: Path,
) -> list[PipelineArtifactRecord]:
    records: list[PipelineArtifactRecord] = []
    produced_paths: set[str] = set()
    step_name_by_id = {step.id: step.name for step in template.steps}
    step_dep_names_by_id = {
        step.id: [dep for dep in step.depends_on if dep]
        for step in template.steps
    }
    terminal_step_id = template.steps[-1].id if template.steps else ""

    for node in raw_steps:
        if not isinstance(node, dict):
            continue
        step_id = str(node.get("step_id") or "").strip()
        artifact_path = node.get("artifact_manifest")
        if not step_id or not isinstance(artifact_path, str) or not _is_safe_relative_path(artifact_path):
            continue

        artifact_file = (run_dir / artifact_path).resolve()
        if not artifact_file.exists() or not artifact_file.is_file() or not str(artifact_file).startswith(str(run_dir)):
            continue

        artifact_doc = json.loads(artifact_file.read_text(encoding="utf-8"))
        outputs = artifact_doc.get("outputs") or []
        consumer_step_ids = [
            step.id for step in template.steps if step_id in (step.depends_on or [])
        ]
        consumer_step_names = [step_name_by_id.get(dep, dep) for dep in consumer_step_ids]

        for output in outputs:
            if not isinstance(output, dict):
                continue
            output_path = str(output.get("path") or "").strip()
            if not output_path:
                continue
            produced_paths.add(output_path)
            records.append(
                PipelineArtifactRecord(
                    artifact_id=f"{run_id}:{step_id}:{output_path}",
                    path=output_path,
                    name=Path(output_path).name,
                    kind="final" if step_id == terminal_step_id else "intermediate",
                    format=str(output.get("format") or _infer_output_format(output_path)),
                    human_readable=bool(output.get("human_readable", False)),
                    run_id=run_id,
                    producer_step_id=step_id,
                    producer_step_name=step_name_by_id.get(step_id, step_id),
                    consumer_step_ids=consumer_step_ids,
                    consumer_step_names=consumer_step_names,
                    created_at=str(artifact_doc.get("generated_at") or generated_at),
                )
            )

    root_step_ids = [step.id for step in template.steps if not step.depends_on]
    root_step_names = [step_name_by_id.get(step_id, step_id) for step_id in root_step_ids]
    for source_path in _sample_project_artifacts(project_dir, limit=200):
        if source_path in produced_paths:
            continue
        records.append(
            PipelineArtifactRecord(
                artifact_id=f"source:{source_path}",
                path=source_path,
                name=Path(source_path).name,
                kind="source",
                format=_infer_output_format(source_path),
                human_readable=_infer_output_format(source_path) != "bin",
                run_id=run_id,
                producer_step_id=None,
                producer_step_name=None,
                consumer_step_ids=root_step_ids,
                consumer_step_names=root_step_names,
                created_at=generated_at,
            )
        )

    return sorted(records, key=lambda item: (item.kind, item.path.lower()))


def _execute_project_pipeline_run(
    project_dir: Path,
    run: PipelineRunDetail,
    template: PipelineTemplateInfo,
) -> PipelineRunDetail:
    if not run.collaboration_events:
        _append_collab_event(
            run,
            "run.started",
            status="running",
            message="Project flow run started",
        )

    if not run.steps:
        run.status = "succeeded"
        run.updated_at = _pipeline_now_iso()
        _append_collab_event(
            run,
            "run.completed",
            status="succeeded",
            message="No steps to execute",
        )
        _persist_project_pipeline_run(project_dir, run, template)
        return run

    for step in run.steps:
        started_at = _pipeline_now_iso()
        step_role = _infer_collab_role(step.kind)
        step.status = "running"
        step.started_at = started_at
        step.ended_at = None
        run.status = "running"
        run.updated_at = started_at
        _append_collab_event(
            run,
            "step.started",
            step_id=step.id,
            role=step_role,
            status="running",
            message=f"Step {step.id} started",
        )
        _persist_project_pipeline_run(project_dir, run, template)

        try:
            step_started_dt = _parse_pipeline_iso(started_at) or datetime.now(timezone.utc)
            step_outputs = _apply_real_step_results(project_dir, step)
            ended_at = _pipeline_now_iso()
            step_ended_dt = _parse_pipeline_iso(ended_at) or datetime.now(timezone.utc)
            duration_sec = max((step_ended_dt - step_started_dt).total_seconds(), 0.0)

            step.status = "succeeded"
            step.ended_at = ended_at
            step.metrics = {
                **step.metrics,
                "duration_sec": round(duration_sec, 3),
            }
            step.evidence = step.evidence or ["PROJECT.md"]
            if step_outputs:
                merged_artifacts = list(dict.fromkeys([*run.artifacts, *step_outputs]))
                run.artifacts = merged_artifacts[:200]

            _append_collab_event(
                run,
                "step.completed",
                step_id=step.id,
                role=step_role,
                status="succeeded",
                message=f"Step {step.id} completed",
                evidence=step.evidence[:5],
                metrics={
                    "duration_sec": step.metrics.get("duration_sec", 0),
                    "output_count": len(step_outputs),
                },
            )

            run.updated_at = ended_at
        except Exception as exc:
            ended_at = _pipeline_now_iso()
            step.status = "failed"
            step.ended_at = ended_at
            step.metrics = {
                **step.metrics,
                "error_count": 1,
            }
            step.evidence = [*step.evidence[:19], f"error:{type(exc).__name__}: {exc}"]
            run.status = "failed"
            run.updated_at = ended_at
            _append_collab_event(
                run,
                "step.failed",
                step_id=step.id,
                role=step_role,
                status="failed",
                message=f"Step {step.id} failed: {type(exc).__name__}",
                evidence=step.evidence[:5],
                metrics={"error_count": 1},
            )
            _append_collab_event(
                run,
                "run.failed",
                status="failed",
                message="Project flow run failed",
            )
            _persist_project_pipeline_run(project_dir, run, template)
            return run

    run.status = "succeeded"
    run.updated_at = _pipeline_now_iso()
    _append_collab_event(
        run,
        "run.completed",
        status="succeeded",
        message="Project flow run completed",
    )
    _persist_project_pipeline_run(project_dir, run, template)
    return run


def _load_pipeline_run_from_manifest(project_dir: Path, run_id: str) -> PipelineRunDetail:
    _, _, runs_dir = _project_pipeline_dirs(project_dir)
    run_dir, manifest_path, _ = _run_dir_paths(runs_dir, run_id)
    if not manifest_path.exists() or not manifest_path.is_file():
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found")

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail=f"Pipeline run '{run_id}' is invalid")

    template = _resolve_pipeline_template(project_dir, str(raw.get("pipeline_id") or ""))

    raw_steps = [item for item in (raw.get("steps") or []) if isinstance(item, dict)]
    all_artifacts: list[str] = []
    steps: list[PipelineRunStep] = []
    for node in raw_steps:
        if not isinstance(node, dict):
            continue

        step_id = str(node.get("step_id") or "").strip()
        if not step_id:
            continue

        metric_path = node.get("metric_pack")
        artifact_path = node.get("artifact_manifest")
        metrics: dict[str, Any] = {}
        evidence: list[str] = []

        if isinstance(metric_path, str) and _is_safe_relative_path(metric_path):
            metric_file = (run_dir / metric_path).resolve()
            if metric_file.exists() and metric_file.is_file() and str(metric_file).startswith(str(run_dir)):
                metric_doc = json.loads(metric_file.read_text(encoding="utf-8"))
                for metric in metric_doc.get("metrics") or []:
                    if not isinstance(metric, dict):
                        continue
                    key = str(metric.get("key") or "").strip()
                    value = metric.get("value")
                    if key:
                        metrics[key] = value

        if isinstance(artifact_path, str) and _is_safe_relative_path(artifact_path):
            artifact_file = (run_dir / artifact_path).resolve()
            if artifact_file.exists() and artifact_file.is_file() and str(artifact_file).startswith(str(run_dir)):
                artifact_doc = json.loads(artifact_file.read_text(encoding="utf-8"))
                for output in artifact_doc.get("outputs") or []:
                    if not isinstance(output, dict):
                        continue
                    output_path = str(output.get("path") or "").strip()
                    if output_path:
                        all_artifacts.append(output_path)
                for item in artifact_doc.get("evidence") or []:
                    if not isinstance(item, dict):
                        continue
                    source = str(item.get("source") or "").strip()
                    if source:
                        evidence.append(source)

        step_name = next((item.name for item in template.steps if item.id == step_id), step_id)
        step_kind = next((item.kind for item in template.steps if item.id == step_id), "task")

        steps.append(
            PipelineRunStep(
                id=step_id,
                name=step_name,
                kind=step_kind,
                status=_normalize_step_status(str(node.get("status") or "pending")),
                started_at=node.get("started_at"),
                ended_at=node.get("ended_at"),
                metrics=metrics,
                evidence=evidence,
            ),
        )

    created_at = str(raw.get("started_at") or "").strip()
    updated_at = str(raw.get("ended_at") or created_at).strip()
    if not updated_at:
        updated_at = created_at

    run_detail = PipelineRunDetail(
        id=str(raw.get("run_id") or run_id),
        project_id=str(raw.get("project_id") or ""),
        template_id=str(raw.get("pipeline_id") or ""),
        status=_normalize_run_status(str(raw.get("status") or "running")),
        created_at=created_at,
        updated_at=updated_at,
        parameters=cast(dict[str, Any], raw.get("params") or {}),
        steps=steps,
        artifacts=sorted(set(all_artifacts)),
        artifact_records=_build_pipeline_artifact_records(
            project_dir,
            str(raw.get("run_id") or run_id),
            template,
            updated_at or created_at,
            raw_steps,
            run_dir,
        ),
        flow_version=str(raw.get("flow_version") or raw.get("pipeline_version") or ""),
        source_platform_template_id=(
            str(raw.get("source_platform_template_id") or "").strip() or None
        ),
        source_platform_template_version=(
            str(raw.get("source_platform_template_version") or "").strip() or None
        ),
        collaboration_events=[
            PipelineCollaborationEvent.model_validate(item)
            for item in (raw.get("collaboration_events") or [])
            if isinstance(item, dict)
        ],
    )
    return run_detail


def _load_legacy_pipeline_run(project_dir: Path, run_id: str) -> PipelineRunDetail:
    _, _, runs_dir = _project_pipeline_dirs(project_dir)
    if not _is_safe_relative_path(f"{run_id}.json"):
        raise HTTPException(status_code=400, detail="Invalid run id")

    path = (runs_dir / f"{run_id}.json").resolve()
    if not str(path).startswith(str(runs_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid run id")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found")

    raw = json.loads(path.read_text(encoding="utf-8"))
    run = PipelineRunDetail.model_validate(raw)
    run.status = _normalize_run_status(run.status)
    run.steps = [
        PipelineRunStep(
            id=step.id,
            name=step.name,
            kind=step.kind,
            status=_normalize_step_status(step.status),
            started_at=step.started_at,
            ended_at=step.ended_at,
            metrics=step.metrics,
            evidence=step.evidence,
        )
        for step in run.steps
    ]
    if not hasattr(run, "artifact_records") or run.artifact_records is None:
        run.artifact_records = []
    return run


def _list_project_pipeline_runs(project_dir: Path) -> list[PipelineRunSummary]:
    _, _, runs_dir = _project_pipeline_dirs(project_dir)
    runs: list[PipelineRunSummary] = []

    for run_dir in sorted(runs_dir.iterdir(), key=lambda item: item.name.lower()):
        if not run_dir.is_dir():
            continue
        manifest_path = run_dir / "run_manifest.json"
        if not manifest_path.exists() or not manifest_path.is_file():
            continue
        try:
            run_detail = _load_pipeline_run_from_manifest(project_dir, run_dir.name)
            runs.append(
                PipelineRunSummary(
                    id=run_detail.id,
                    template_id=run_detail.template_id,
                    status=run_detail.status,
                    created_at=run_detail.created_at,
                    updated_at=run_detail.updated_at,
                    focus_chat_id=run_detail.focus_chat_id,
                    focus_type=run_detail.focus_type,
                    focus_path=run_detail.focus_path,
                ),
            )
        except Exception as exc:
            logger.warning("Skip invalid pipeline run manifest %s: %s", manifest_path, exc)

    for path in sorted(runs_dir.glob("*.json"), key=lambda item: item.name.lower()):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            run_id = str(raw.get("id") or path.stem).strip()
            if any(item.id == run_id for item in runs):
                continue
            template_id = str(raw.get("template_id") or "").strip()
            status = _normalize_run_status(str(raw.get("status") or "pending"))
            created_at = str(raw.get("created_at") or "").strip()
            updated_at = str(raw.get("updated_at") or created_at).strip()
            if not run_id or not template_id or not created_at:
                continue
            runs.append(
                PipelineRunSummary(
                    id=run_id,
                    template_id=template_id,
                    status=status,
                    created_at=created_at,
                    updated_at=updated_at,
                ),
            )
        except Exception as exc:
            logger.warning("Skip invalid legacy pipeline run %s: %s", path, exc)

    runs.sort(key=lambda item: item.updated_at, reverse=True)
    return runs


def _load_project_pipeline_run(project_dir: Path, run_id: str) -> PipelineRunDetail:
    try:
        return _load_pipeline_run_from_manifest(project_dir, run_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return _load_legacy_pipeline_run(project_dir, run_id)


def _create_project_pipeline_run(
    project_id: str,
    project_dir: Path,
    body: CreatePipelineRunRequest,
) -> PipelineRunDetail:
    template = _resolve_pipeline_template(project_dir, body.template_id)
    template_doc = _load_project_template_doc(project_dir, template.id)
    now = _pipeline_now_iso()
    run_id = f"run-{generate_short_agent_id()}"

    artifacts = _sample_project_artifacts(project_dir)

    steps: list[PipelineRunStep] = []
    for idx, step in enumerate(template.steps):
        is_first = idx == 0
        steps.append(
            PipelineRunStep(
                id=step.id,
                name=step.name,
                kind=step.kind,
                status="running" if is_first else "pending",
                started_at=now if is_first else None,
                ended_at=None,
                metrics={},
                evidence=["PROJECT.md"] if is_first else [],
            ),
        )

    run = PipelineRunDetail(
        id=run_id,
        project_id=project_id,
        template_id=template.id,
        status="running",
        created_at=now,
        updated_at=now,
        parameters=body.parameters,
        steps=steps,
        artifacts=artifacts,
        flow_version=(template.version or "0.1.0"),
        source_platform_template_id=(
            str(template_doc.get("source_platform_template_id") or "").strip() or None
        ),
        source_platform_template_version=(
            str(template_doc.get("source_platform_template_version") or "").strip()
            or None
        ),
        collaboration_events=[],
        focus_chat_id=None,
        focus_type="project_run",
        focus_path=f"projects/{project_id}",
    )
    return _execute_project_pipeline_run(project_dir, run, template)
