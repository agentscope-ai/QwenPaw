# -*- coding: utf-8 -*-
"""DataPaw task-panel REST API.

Endpoints:

- ``GET  /api/tasks/{session_id}`` — current_plan + history summary + artifacts summary
- ``GET  /api/tasks/{session_id}/sop`` — download active graph SOP YAML (minimal contract, no runtime fields)
- ``GET  /api/tasks/{session_id}/dag`` — download active graph DAG YAML (structure + runtime)
- ``GET  /api/tasks/{session_id}/history/{plan_id}`` — fetch a specific historical graph
- ``GET  /api/tasks/{session_id}/history/{plan_id}/sop`` — historical graph SOP YAML
- ``PUT  /api/tasks/{session_id}/sop`` — upload an SOP YAML, archive the old graph, rebuild all-todo
- ``PUT  /api/tasks/{session_id}/dag`` — upload a DAG patch, merge into current graph by node_id
- ``GET  /api/tasks/{session_id}/files`` — list session-cumulative file artifacts (filter by graph_id / node_id)
- ``GET  /api/tasks/{session_id}/files/preview`` — inline preview of one file via ``?path=``
- ``GET  /api/tasks/{session_id}/files/download`` — download one file via ``?path=``

SOP minimal contract: only structural fields are allowed (graph:
name/description/expected_outcome; node: node_id/name/description/
expected_outcome/deps). Runtime fields are rejected.

Concurrency (MVP): ``PUT`` endpoints only run while no agent is active
for the session; otherwise 409.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, List, Literal, Optional
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..path_context import PathContext, shared_artifacts_root
from ..orchestration.artifact import ArtifactItem
from ..orchestration.task_graph import Sop, TaskGraph

logger = logging.getLogger(__name__)

# Prefix is applied at mount time by host's ``api.register_http_router``
# (host prepends ``/api`` automatically), so this router carries no prefix
# of its own. See plugin.py for the registration call.
router = APIRouter(tags=["datapaw-tasks"])


# ---------------------------------------------------------------------------
# Shared dependencies
# ---------------------------------------------------------------------------


def _get_multi_agent_manager(request: Request):
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    return manager


async def _get_session_for_agent(request: Request, agent_id: Optional[str]):
    """Return the ``SafeJSONSession`` for a specific agent."""
    manager = _get_multi_agent_manager(request)

    if not agent_id:
        agent_id = request.headers.get("X-Agent-Id") or "default"

    workspace = await manager.get_agent(agent_id)
    runner = getattr(workspace, "runner", None)
    if runner is None or getattr(runner, "session", None) is None:
        raise HTTPException(
            status_code=503,
            detail=(f"Agent '{agent_id}' runner/session not ready"),
        )
    return runner.session, agent_id


async def _get_workspace_for_agent(request: Request, agent_id: Optional[str]):
    """Return the workspace for a specific agent (used for the running-state check)."""
    manager = _get_multi_agent_manager(request)
    if not agent_id:
        agent_id = request.headers.get("X-Agent-Id") or "default"
    return await manager.get_agent(agent_id)


def _extract_plan_notebook(state: dict) -> dict:
    """Pull the plan_notebook dict out of session state (may be absent).

    ``DataPawAgent`` persists its ``RuntimeStateManager`` under the
    StateModule key ``plan_notebook`` (see ``agents/base.py`` comments
    around ``state_dict`` / ``load_state_dict``). The legacy ``runtime_state``
    key is still tolerated so PUT writes that haven't been consumed by
    the agent yet remain visible to GETs.
    """
    agent_state = state.get("agent") if isinstance(state, dict) else None
    if not isinstance(agent_state, dict):
        return {}
    pn = agent_state.get("plan_notebook")
    if not isinstance(pn, dict):
        pn = agent_state.get("runtime_state")
    return pn if isinstance(pn, dict) else {}


async def _check_not_running(
    workspace: Any,
    session_id: str,
) -> None:
    """Raise 409 if an agent is actively running for this session.

    Without this guard, PUT / PATCH writes race against the
    ``_on_graph_change`` hook and the runner's ``finally``-block
    persistence (read-modify-write of the session JSON).
    """
    chat_manager = getattr(workspace, "chat_manager", None)
    task_tracker = getattr(workspace, "task_tracker", None)
    if chat_manager is None or task_tracker is None:
        return

    chat_id = await chat_manager.get_chat_id_by_session(
        session_id,
        channel="console",
    )
    if chat_id is not None:
        status = await task_tracker.get_status(chat_id)
        if status == "running":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Agent is running for this session. "
                    "Stop it via POST /console/chat/stop before editing tasks."
                ),
            )


def _archive_current_plan_to_pn(pn: dict, reason: str) -> Optional[str]:
    """Archive ``pn["current_plan"]`` into ``pn["storage"]["plans"]``.

    Returns the archived graph id (or ``None``). This is the dict-level
    equivalent of ``RuntimeStateManager._archive_current_plan``: unfinished
    graphs are marked ``abandoned`` before archiving; ``current_plan`` is
    expected to be overwritten by the caller. ``artifacts`` are not cleared
    (session-level append-only file index).
    """
    existing = pn.get("current_plan")
    if not isinstance(existing, dict):
        return None
    try:
        old = TaskGraph.model_validate(existing)
    except Exception:  # pylint: disable=broad-except
        return None
    if old.state not in ("done", "abandoned"):
        old.finish(
            "abandoned",
            reason,
        )
    pn.setdefault("storage", {}).setdefault("plans", {})[
        old.id
    ] = old.model_dump(mode="json")
    return old.id


def _ensure_plan_notebook_keys(pn: dict) -> None:
    """Make sure plan_notebook has all keys ``load_state_dict`` expects.

    DataPawAgent persists via StateModule, and ``load_state_dict(strict=True)``
    requires every key in ``_module_dict`` (storage) and ``_attribute_dict``
    (current_plan / artifacts / _pending_edits) to be present. If any PUT
    endpoint writes JSON missing those keys, ``load_session_state`` raises
    KeyError, the runner swallows it and skips state loading, and the
    ``finally`` block then overwrites the session file with empty agent
    state — silently losing the SOP that was just uploaded.
    """
    pn.setdefault("storage", {"plans": {}})
    pn.setdefault("artifacts", [])
    pn.setdefault("_pending_edits", [])
    pn.setdefault("current_plan", None)


def _safe_filename(name: str) -> str:
    """Convert ``graph.name`` to an HTTP-header-safe filename (ASCII, ≤120 chars).

    HTTP ``Content-Disposition`` headers only allow latin-1; non-ASCII
    characters are replaced with ``"_"`` to avoid UnicodeEncodeError.
    """
    safe = re.sub(r"[^A-Za-z0-9\-_.]", "_", name)[:120]
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe or "sop"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class HistoricalPlanSummary(BaseModel):
    """Summary entry for an archived graph."""

    id: str
    name: str
    state: str = "done"
    finished_at: Optional[str] = None


class GetTasksResponse(BaseModel):
    """Body of ``GET /api/tasks/{session_id}``."""

    current_plan: Optional[dict] = None
    historical_plans: List[HistoricalPlanSummary] = Field(default_factory=list)
    artifacts_summary: dict = Field(default_factory=dict)


class SOPUploadBody(BaseModel):
    """Body of ``PUT /api/tasks/{session_id}/sop`` (YAML only).

    Only SOP minimal-contract YAML text is accepted (no dict). Runtime
    fields (id / state / output / trace / ...) are rejected by
    ``from_sop``.
    """

    yaml: str = Field(
        ...,
        min_length=1,
        description="SOP YAML text (minimal-contract format).",
    )


class DAGUploadBody(BaseModel):
    """Body of ``PUT /api/tasks/{session_id}/dag`` (YAML only)."""

    yaml: str = Field(..., min_length=1, description="DAG patch YAML text.")


class Ok(BaseModel):
    ok: bool = True
    detail: Optional[str] = None
    extra: Optional[dict] = None


class FileEntry(BaseModel):
    """One file-artifact entry in the ``GET /files`` listing."""

    graph_id: str
    node_id: str
    name: str
    path: str = Field(
        description="Sandbox-view relative path, identical to FileRef.path passed to finish_subtask.",
    )
    mime_type: str
    size_bytes: int
    created_at: str
    preview_url: str = Field(
        description="Pre-built relative URL; the frontend can GET it directly for inline preview.",
    )
    download_url: str = Field(
        description="Pre-built relative URL; the frontend can GET it directly to download.",
    )


class FilesResponse(BaseModel):
    """Body of ``GET /api/tasks/{session_id}/files``."""

    files: List[FileEntry] = Field(default_factory=list)


def _build_file_urls(
    session_id: str,
    path: str,
    *,
    user_id: str = "",
) -> tuple[str, str]:
    """Build preview / download URLs scoped to ``session_id`` + artifact path."""
    encoded_session = quote(session_id, safe="")
    encoded_path = quote(path, safe="")
    user_part = f"&user_id={quote(user_id, safe='')}" if user_id else ""
    return (
        f"/api/tasks/{encoded_session}/files/preview?path={encoded_path}{user_part}",
        f"/api/tasks/{encoded_session}/files/download?path={encoded_path}{user_part}",
    )


def _extract_artifacts(pn: dict) -> List[ArtifactItem]:
    """Parse the artifacts list from a plan_notebook dict; skip malformed entries."""
    raw = pn.get("artifacts") if isinstance(pn, dict) else None
    if not isinstance(raw, list):
        return []
    items: List[ArtifactItem] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            items.append(ArtifactItem.model_validate(entry))
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "tasks router: skip malformed artifact entry %r",
                entry,
                exc_info=True,
            )
    return items


def _get_workspace_dir(
    workspace: Any, agent_config: Any | None = None
) -> Path:
    """Infer the agent workspace directory from workspace / runner / agent_config."""
    runner = getattr(workspace, "runner", None)
    raw = (
        getattr(runner, "workspace_dir", None)
        or getattr(workspace, "workspace_dir", None)
        or getattr(agent_config, "workspace_dir", None)
    )
    return Path(raw).expanduser().resolve() if raw else Path.cwd().resolve()


def _build_artifact_path_context(
    workspace: Any,
    session_id: str,
    agent_id: str,
) -> PathContext:
    """Build an artifact path context for the current workspace / agent.

    ``session_id`` is currently unused (kept for a possible future split
    by session). Resolution is delegated to ``shared_artifacts_root``: with
    a sandbox config the ``mount_root`` is passed as override; otherwise
    falls through to ``default_artifacts_root``.
    """
    del session_id
    agent_config: Any | None = None

    try:
        from qwenpaw.config.config import load_agent_config

        agent_config = load_agent_config(agent_id)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "tasks router: failed to load agent config for %r; "
            "falling back to workspace_dir lookup on workspace object",
            agent_id,
            exc_info=True,
        )

    workspace_dir = _get_workspace_dir(workspace, agent_config)
    base_dir = shared_artifacts_root(
        agent_id=agent_id,
        workspace_dir=workspace_dir,
        mount_override=None,
    )
    return PathContext(mount_dir=base_dir)


def _resolve_artifact_host_path(
    workspace: Any,
    session_id: str,
    agent_id: str,
    path: str,
) -> Path:
    """Resolve a sandbox-relative path to a host absolute path.

    Caller is responsible for whitelisting against ``artifacts``. This
    function only rebuilds the context, resolves the path, and enforces
    the mount-dir boundary.
    """
    context = _build_artifact_path_context(workspace, session_id, agent_id)
    host_path = context.resolve_artifact_path(path)
    resolved = host_path.resolve()
    if not context.contains(resolved):
        raise HTTPException(
            status_code=400,
            detail="Resolved artifact path escapes the agent workspace.",
        )
    return resolved


# ---------------------------------------------------------------------------
# HTML artifact link-rewrite helpers
# ---------------------------------------------------------------------------

_HTML_REWRITE_ATTRS: tuple[tuple[str, str], ...] = (
    ("a", "href"),
    ("link", "href"),
    ("img", "src"),
    ("script", "src"),
    ("iframe", "src"),
    ("source", "src"),
    ("video", "src"),
    ("audio", "src"),
    ("embed", "src"),
    ("object", "data"),
)

_SKIP_SCHEMES: tuple[str, ...] = (
    "http://",
    "https://",
    "file://",
    "data:",
    "mailto:",
    "tel:",
    "javascript:",
    "blob:",
    "about:",
)


def _is_html_artifact(item: ArtifactItem) -> bool:
    """Return True iff the artifact looks like HTML (mime_type or extension)."""
    mt = (item.mime_type or "").lower()
    if mt.startswith("text/html"):
        return True
    return Path(item.path).suffix.lower() in {".html", ".htm"}


def _is_external_or_anchor(value: str) -> bool:
    """Return True for external URLs, anchors, or anything else we should skip."""
    v = value.strip()
    if not v or v.startswith("#"):
        return True
    low = v.lower()
    if any(low.startswith(s) for s in _SKIP_SCHEMES):
        return True
    return bool(urlsplit(v).scheme)


def _rewrite_html_artifact_links(
    html_bytes: bytes,
    *,
    context: PathContext,
) -> bytes:
    """Rewrite relative-path attributes in an HTML doc to host ``file://`` URIs.

    Rules:
    - Only the attributes listed in ``_HTML_REWRITE_ATTRS`` are touched.
    - Skip external URLs (any scheme in ``_SKIP_SCHEMES``) and anchors.
    - Resolved path must stay within ``context.mount_dir`` (out-of-bounds
      paths keep the original value).
    - Target file must exist; missing files keep the original value.
    - Any failure is swallowed and leaves the original value intact.
    """
    from bs4 import BeautifulSoup  # lazy import

    try:
        text = html_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = html_bytes.decode("utf-8", errors="replace")

    soup = BeautifulSoup(text, "html.parser")
    for tag_name, attr in _HTML_REWRITE_ATTRS:
        for tag in soup.find_all(tag_name):
            value = tag.get(attr)
            if not isinstance(value, str) or _is_external_or_anchor(value):
                continue
            try:
                resolved = context.resolve_artifact_path(value).resolve()
            except Exception:  # pylint: disable=broad-except
                continue
            if not context.contains(resolved):
                continue
            if not resolved.exists():
                continue
            tag[attr] = resolved.as_uri()

    return str(soup).encode("utf-8")


def _serve_artifact_file(
    workspace: Any,
    session_id: str,
    agent_id: str,
    artifacts: List[ArtifactItem],
    path: str,
    *,
    disposition: Literal["inline", "attachment"],
) -> Response:
    """Validate against the artifact whitelist + mount boundary, then serve the file."""
    matched: Optional[ArtifactItem] = next(
        (item for item in artifacts if item.path == path),
        None,
    )
    if matched is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Artifact path {path!r} is not registered in this session."
            ),
        )

    host_path = _resolve_artifact_host_path(
        workspace,
        session_id,
        agent_id,
        matched.path,
    )
    if not host_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(f"Artifact file is missing on disk: {matched.path}"),
        )

    if not _is_html_artifact(matched):
        return FileResponse(
            path=host_path,
            media_type=matched.mime_type or "application/octet-stream",
            filename=matched.name,
            content_disposition_type=disposition,
        )

    # HTML branch: rewrite relative paths to absolute file:// URIs.
    try:
        context = _build_artifact_path_context(workspace, session_id, agent_id)
        rewritten = _rewrite_html_artifact_links(
            host_path.read_bytes(),
            context=context,
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "tasks router: failed to rewrite html artifact links for %r",
            matched.path,
            exc_info=True,
        )
        return FileResponse(
            path=host_path,
            media_type=matched.mime_type or "text/html",
            filename=matched.name,
            content_disposition_type=disposition,
        )

    safe_name = _safe_filename(matched.name)
    encoded_name = quote(matched.name)
    content_disposition = (
        f'{disposition}; filename="{safe_name}"; '
        f"filename*=UTF-8''{encoded_name}"
    )
    return Response(
        content=rewritten,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": content_disposition},
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}
# ---------------------------------------------------------------------------


@router.get("/{session_id}", response_model=GetTasksResponse)
async def get_tasks(
    session_id: str,
    request: Request,
    user_id: str = Query(default="default"),
) -> GetTasksResponse:
    """Active-graph overview + historical-graph index + artifact summary."""
    session, _ = await _get_session_for_agent(
        request,
        request.state.agent_id if hasattr(request.state, "agent_id") else None,
    )
    state = await session.get_session_state_dict(
        session_id=session_id,
        user_id=user_id,
    )
    pn = _extract_plan_notebook(state)

    storage_plans = (
        pn.get("storage", {}).get("plans", {}) if isinstance(pn, dict) else {}
    )
    historical: List[HistoricalPlanSummary] = []
    for p in storage_plans.values() if isinstance(storage_plans, dict) else []:
        if not isinstance(p, dict):
            continue
        historical.append(
            HistoricalPlanSummary(
                id=p.get("id", ""),
                name=p.get("name", ""),
                state=p.get("state", "done"),
                finished_at=p.get("finished_at"),
            ),
        )

    artifacts = pn.get("artifacts", []) if isinstance(pn, dict) else []
    artifacts_summary = {
        "total": len(artifacts) if isinstance(artifacts, list) else 0,
    }

    return GetTasksResponse(
        current_plan=pn.get("current_plan") if isinstance(pn, dict) else None,
        historical_plans=historical,
        artifacts_summary=artifacts_summary,
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/sop — download active graph SOP YAML
# ---------------------------------------------------------------------------


@router.get("/{session_id}/sop")
async def get_sop(
    session_id: str,
    request: Request,
    user_id: str = Query(default="default"),
) -> Response:
    """Download the active graph's SOP YAML (minimal contract; no runtime fields).

    - No active graph → 409.
    - ``application/x-yaml`` with a Content-Disposition filename.
    """
    session, _ = await _get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    state = await session.get_session_state_dict(session_id, user_id=user_id)
    pn = _extract_plan_notebook(state)
    current = pn.get("current_plan") if isinstance(pn, dict) else None
    if not isinstance(current, dict):
        raise HTTPException(
            status_code=409,
            detail="No active task graph in session.",
        )
    try:
        graph = TaskGraph.model_validate(current)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse current_plan: {exc}",
        ) from exc

    yaml_content = graph.to_sop_yaml()
    filename = f"{_safe_filename(graph.name)}.sop.yaml"
    return Response(
        content=yaml_content,
        media_type="application/x-yaml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/dag — download active graph DAG YAML
# ---------------------------------------------------------------------------


@router.get("/{session_id}/dag")
async def get_dag(
    session_id: str,
    request: Request,
    user_id: str = Query(default="default"),
    include_trace: bool = Query(default=True),
) -> Response:
    """Download the active graph's DAG YAML (structure + runtime fields)."""
    session, _ = await _get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    state = await session.get_session_state_dict(session_id, user_id=user_id)
    pn = _extract_plan_notebook(state)
    current = pn.get("current_plan") if isinstance(pn, dict) else None
    if not isinstance(current, dict):
        raise HTTPException(
            status_code=409,
            detail="No active task graph in session.",
        )
    try:
        graph = TaskGraph.model_validate(current)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse current_plan: {exc}",
        ) from exc

    yaml_content = graph.to_dag_yaml(include_trace=include_trace)
    filename = f"{_safe_filename(graph.name)}.dag.yaml"
    return Response(
        content=yaml_content,
        media_type="application/x-yaml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/history/{plan_id}
# ---------------------------------------------------------------------------


@router.get("/{session_id}/history/{plan_id}")
async def get_historical_plan(
    session_id: str,
    plan_id: str,
    request: Request,
    user_id: str = Query(default="default"),
) -> dict:
    """Return the full TaskGraph (nodes / outcome) of a specific historical graph."""
    session, _ = await _get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    state = await session.get_session_state_dict(session_id, user_id=user_id)
    pn = _extract_plan_notebook(state)
    storage_plans = pn.get("storage", {}).get("plans", {})
    if not isinstance(storage_plans, dict) or plan_id not in storage_plans:
        raise HTTPException(
            status_code=404,
            detail=f"Historical plan '{plan_id}' not found.",
        )
    return {"plan": storage_plans[plan_id]}


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/history/{plan_id}/sop
# ---------------------------------------------------------------------------


@router.get("/{session_id}/history/{plan_id}/sop")
async def get_historical_sop(
    session_id: str,
    plan_id: str,
    request: Request,
    user_id: str = Query(default="default"),
) -> Response:
    """Download a historical graph's SOP YAML (minimal contract).

    - Plan not found → 404.
    - ``application/x-yaml`` with a Content-Disposition filename.
    """
    session, _ = await _get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    state = await session.get_session_state_dict(session_id, user_id=user_id)
    pn = _extract_plan_notebook(state)
    storage_plans = pn.get("storage", {}).get("plans", {})
    if not isinstance(storage_plans, dict) or plan_id not in storage_plans:
        raise HTTPException(
            status_code=404,
            detail=f"Historical plan '{plan_id}' not found.",
        )
    try:
        graph = TaskGraph.model_validate(storage_plans[plan_id])
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse historical plan: {exc}",
        ) from exc

    yaml_content = graph.to_sop_yaml()
    filename = f"{_safe_filename(graph.name)}.sop.yaml"
    return Response(
        content=yaml_content,
        media_type="application/x-yaml; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# PUT /api/tasks/{session_id}/sop — upload SOP (rebuild graph)
# ---------------------------------------------------------------------------


@router.put("/{session_id}/sop", response_model=Ok)
async def put_sop(
    session_id: str,
    request: Request,
    body: SOPUploadBody = Body(...),
    user_id: str = Query(default="default"),
) -> Ok:
    """Upload an SOP YAML and rebuild the graph (overwrite semantics).

    Steps:
    1. ``Sop.from_yaml(body.yaml)`` parses strictly (no runtime fields +
       DAG validation).
    2. If a ``current_plan`` exists, archive it (mark abandoned if unfinished).
    3. Install the new ``current_plan`` (all nodes start ``todo``).
    4. Append ``_pending_edits: [{type: "sop_replaced", ...}]`` with a
       per-node summary.
    5. Persist the entire block back to the session.

    Stop any running agent first — this endpoint returns 409 if one is active.
    """
    workspace = await _get_workspace_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    await _check_not_running(workspace, session_id)

    try:
        sop = Sop.from_yaml(body.yaml)
        graph = TaskGraph.from_sop(sop)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse SOP: {exc}",
        ) from exc

    session = getattr(getattr(workspace, "runner", None), "session", None)
    if session is None:
        raise HTTPException(status_code=503, detail="Session not ready")

    state = await session.get_session_state_dict(session_id, user_id=user_id)
    agent_block = state.setdefault("agent", {})
    pn = agent_block.get("plan_notebook")
    if not isinstance(pn, dict):
        pn = agent_block.get("runtime_state")
    if not isinstance(pn, dict):
        pn = {}
    _ensure_plan_notebook_keys(pn)

    replaced_id = _archive_current_plan_to_pn(
        pn,
        reason=f"Replaced by SOP '{graph.name}'.",
    )

    pn["current_plan"] = graph.model_dump(mode="json")

    edits = pn.setdefault("_pending_edits", [])
    edits.append(
        {
            "type": "sop_replaced",
            "name": graph.name,
            "graph_id": graph.id,
            "node_count": len(graph.nodes),
            "node_summary": [
                {
                    "id": n.node_id,
                    "name": n.name,
                    "deps": list(n.deps),
                }
                for n in graph.nodes.values()
            ],
            "replaced_graph_id": replaced_id,
        },
    )

    await session.update_session_state(
        session_id=session_id,
        key="agent.plan_notebook",
        value=pn,
        user_id=user_id,
    )

    return Ok(
        detail=f"SOP '{graph.name}' loaded as the active task graph.",
        extra={"graph_id": graph.id, "node_count": len(graph.nodes)},
    )


# ---------------------------------------------------------------------------
# PUT /api/tasks/{session_id}/dag — upload DAG patch (merge into current graph)
# ---------------------------------------------------------------------------


@router.put("/{session_id}/dag", response_model=Ok)
async def put_dag(
    session_id: str,
    request: Request,
    body: DAGUploadBody = Body(...),
    user_id: str = Query(default="default"),
) -> Ok:
    """Upload a DAG patch and merge into the current graph. Old graph is not archived."""
    workspace = await _get_workspace_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    await _check_not_running(workspace, session_id)

    session = getattr(getattr(workspace, "runner", None), "session", None)
    if session is None:
        raise HTTPException(status_code=503, detail="Session not ready")

    state = await session.get_session_state_dict(session_id, user_id=user_id)
    agent_block = state.setdefault("agent", {})
    pn = agent_block.get("plan_notebook")
    if not isinstance(pn, dict):
        pn = agent_block.get("runtime_state")
    if not isinstance(pn, dict):
        pn = {}
    _ensure_plan_notebook_keys(pn)

    current = pn.get("current_plan")
    if not isinstance(current, dict):
        raise HTTPException(
            status_code=409,
            detail="No active DAG to patch. Use PUT /sop to create one.",
        )

    try:
        existing = TaskGraph.model_validate(current)
        diff = existing.apply_dag(body.yaml)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=500,
            detail=f"Failed to apply DAG: {exc}",
        ) from exc

    pn["current_plan"] = existing.model_dump(mode="json")
    edits = pn.setdefault("_pending_edits", [])
    edits.append(
        {
            "type": "dag_merged",
            "name": existing.name,
            "graph_id": existing.id,
            "added": diff.added,
            "removed": diff.removed,
            "modified": diff.modified,
            "state_overridden": diff.state_overridden,
            "stale_propagated": diff.stale_propagated,
        },
    )

    await session.update_session_state(
        session_id=session_id,
        key="agent.plan_notebook",
        value=pn,
        user_id=user_id,
    )

    return Ok(
        detail=f"DAG '{existing.name}' merged into the active task graph.",
        extra=diff.model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/files — session file-artifact listing
# ---------------------------------------------------------------------------


@router.get("/{session_id}/files", response_model=FilesResponse)
async def list_files(
    session_id: str,
    request: Request,
    user_id: str = Query(default="default"),
    graph_id: Optional[str] = Query(
        default=None,
        description="Filter by graph_id; omitted returns all.",
    ),
    node_id: Optional[str] = Query(
        default=None,
        description="Filter by node_id; omitted returns all.",
    ),
) -> FilesResponse:
    """List every file-artifact registered via ``finish_subtask`` in this session.

    Backed by ``RuntimeStateManager.artifacts`` — an append-only list, so
    file records survive across graph archives.
    """
    session, _ = await _get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    state = await session.get_session_state_dict(
        session_id=session_id,
        user_id=user_id,
    )
    pn = _extract_plan_notebook(state)
    artifacts = _extract_artifacts(pn)

    entries: List[FileEntry] = []
    for item in artifacts:
        if graph_id and item.graph_id != graph_id:
            continue
        if node_id and item.node_id != node_id:
            continue
        preview_url, download_url = _build_file_urls(
            session_id,
            item.path,
            user_id=user_id,
        )
        entries.append(
            FileEntry(
                graph_id=item.graph_id,
                node_id=item.node_id,
                name=item.name,
                path=item.path,
                mime_type=item.mime_type,
                size_bytes=item.size_bytes,
                created_at=item.created_at,
                preview_url=preview_url,
                download_url=download_url,
            ),
        )

    return FilesResponse(files=entries)


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/files/preview?path=... — inline preview
# ---------------------------------------------------------------------------


@router.get("/{session_id}/files/preview")
async def preview_file(
    session_id: str,
    request: Request,
    path: str = Query(
        ...,
        min_length=1,
        description="``ArtifactItem.path``; must exist in this session's artifacts list.",
    ),
    user_id: str = Query(default="default"),
) -> FileResponse:
    """Inline-preview a file-artifact registered in this session."""
    session, agent_id = await _get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    state = await session.get_session_state_dict(
        session_id=session_id,
        user_id=user_id,
    )
    pn = _extract_plan_notebook(state)
    artifacts = _extract_artifacts(pn)

    workspace = await _get_workspace_for_agent(
        request,
        agent_id,
    )
    return _serve_artifact_file(
        workspace,
        session_id,
        agent_id,
        artifacts,
        path,
        disposition="inline",
    )


# ---------------------------------------------------------------------------
# GET /api/tasks/{session_id}/files/download?path=... — download
# ---------------------------------------------------------------------------


@router.get("/{session_id}/files/download")
async def download_file(
    session_id: str,
    request: Request,
    path: str = Query(
        ...,
        min_length=1,
        description="``ArtifactItem.path``; must exist in this session's artifacts list.",
    ),
    user_id: str = Query(default="default"),
) -> FileResponse:
    """Download a file-artifact registered in this session."""
    session, agent_id = await _get_session_for_agent(
        request,
        getattr(request.state, "agent_id", None),
    )
    state = await session.get_session_state_dict(
        session_id=session_id,
        user_id=user_id,
    )
    pn = _extract_plan_notebook(state)
    artifacts = _extract_artifacts(pn)

    workspace = await _get_workspace_for_agent(
        request,
        agent_id,
    )
    return _serve_artifact_file(
        workspace,
        session_id,
        agent_id,
        artifacts,
        path,
        disposition="attachment",
    )
