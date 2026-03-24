# -*- coding: utf-8 -*-
"""Core models and helpers for project pipeline APIs."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
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


class PipelineTemplateStep(BaseModel):
    """Pipeline template step definition."""

    id: str
    name: str
    kind: str
    description: str = ""


class PipelineTemplateInfo(BaseModel):
    """Project pipeline template metadata."""

    id: str
    name: str
    version: str = ""
    description: str = ""
    steps: list[PipelineTemplateStep] = Field(default_factory=list)


class PipelineRunSummary(BaseModel):
    """Pipeline run summary."""

    id: str
    template_id: str
    status: str
    created_at: str
    updated_at: str


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


class PipelineRunDetail(PipelineRunSummary):
    """Pipeline run detail."""

    project_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    steps: list[PipelineRunStep] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)


class CreatePipelineRunRequest(BaseModel):
    """Create pipeline run request."""

    template_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


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
        "name": "Books Alignment v1",
        "version": "0.1.0",
        "description": "Baseline pipeline for large-markdown alignment and quality checks.",
        "steps": [
            {
                "id": "collect-input",
                "name": "Collect Inputs",
                "kind": "ingest",
                "description": "Discover source markdown and supporting reference files.",
            },
            {
                "id": "normalize-structure",
                "name": "Normalize Structure",
                "kind": "transform",
                "description": "Apply heading and structure normalization before alignment.",
            },
            {
                "id": "run-alignment",
                "name": "Run Alignment",
                "kind": "alignment",
                "description": "Execute sentence/chapter alignment with deterministic settings.",
            },
            {
                "id": "quality-gate",
                "name": "Quality Gate",
                "kind": "validation",
                "description": "Evaluate coverage, consistency, and citation quality metrics.",
            },
            {
                "id": "package-artifacts",
                "name": "Package Artifacts",
                "kind": "publish",
                "description": "Emit manifests and reports for downstream review workflows.",
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
        steps.append(
            PipelineTemplateStep(
                id=step_id,
                name=step_name,
                kind=step_kind,
                description=str(node.get("description") or "").strip(),
            ),
        )

    return PipelineTemplateInfo(
        id=template_id,
        name=name,
        version=str(raw.get("version") or "").strip(),
        description=str(raw.get("description") or "").strip(),
        steps=steps,
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


def _list_agent_pipeline_templates(workspace_dir: Path) -> list[PipelineTemplateInfo]:
    templates_dir = _agent_pipeline_templates_dir(workspace_dir)
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


def _resolve_pipeline_template(project_dir: Path, template_id: str) -> PipelineTemplateInfo:
    templates = _list_project_pipeline_templates(project_dir)
    for template in templates:
        if template.id == template_id:
            return template
    raise HTTPException(status_code=404, detail=f"Pipeline template '{template_id}' not found")


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
    }

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _advance_pipeline_run_if_due(
    project_dir: Path,
    run: PipelineRunDetail,
    template: PipelineTemplateInfo,
) -> PipelineRunDetail:
    if run.status not in {"running", "pending"}:
        return run
    if not run.steps:
        return run

    now = datetime.utcnow().astimezone()
    now_iso = _pipeline_now_iso()
    changed = False
    step_duration_sec = 6

    running_index = next(
        (idx for idx, step in enumerate(run.steps) if step.status == "running"),
        -1,
    )

    if running_index < 0:
        next_index = next(
            (idx for idx, step in enumerate(run.steps) if step.status in {"pending", "blocked"}),
            -1,
        )
        if next_index >= 0:
            run.steps[next_index].status = "running"
            run.steps[next_index].started_at = now_iso
            running_index = next_index
            changed = True

    if running_index >= 0:
        current_step = run.steps[running_index]
        started_at = _parse_pipeline_iso(current_step.started_at) or now
        elapsed = (now - started_at).total_seconds()
        if elapsed >= step_duration_sec:
            current_step.status = "succeeded"
            current_step.ended_at = now_iso
            current_step.metrics = {
                **current_step.metrics,
                "duration_sec": round(elapsed, 2),
            }
            current_step.evidence = current_step.evidence or ["PROJECT.md"]
            changed = True

            next_index = next(
                (
                    idx
                    for idx in range(running_index + 1, len(run.steps))
                    if run.steps[idx].status in {"pending", "blocked"}
                ),
                -1,
            )
            if next_index >= 0:
                run.steps[next_index].status = "running"
                run.steps[next_index].started_at = now_iso
            else:
                run.status = "succeeded"

    if run.status == "succeeded":
        run.updated_at = now_iso
    elif changed:
        run.status = "running"
        run.updated_at = now_iso

    if changed:
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

    all_artifacts: list[str] = []
    steps: list[PipelineRunStep] = []
    for node in raw.get("steps") or []:
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
    )
    return _advance_pipeline_run_if_due(project_dir, run_detail, template)


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
                metrics=(
                    {
                        "input_files": len(_sample_project_artifacts(project_dir, limit=200)),
                    }
                    if is_first
                    else {}
                ),
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
    )
    _persist_project_pipeline_run(project_dir, run, template)
    return run
