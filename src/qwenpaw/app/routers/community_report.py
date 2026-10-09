# -*- coding: utf-8 -*-
"""Local drafting and explicitly requested read-only diagnostics."""

import asyncio
import time

from fastapi import APIRouter, HTTPException, Request

from ..community_diagnostics import DiagnosticsRequest

from ..community_report import (
    CommunityReportRequest,
    ReportGenerationError,
    generate_community_report,
)

router = APIRouter(prefix="/community/report", tags=["community"])


async def _wait_for_disconnect(request: Request) -> None:
    while not await request.is_disconnected():
        await asyncio.sleep(0.25)


@router.post("/generate")
async def generate_report(body: CommunityReportRequest, request: Request):
    if not body.agent_id:
        body = body.model_copy(
            update={
                "agent_id": getattr(request, "headers", {}).get("X-Agent-Id"),
            },
        )
    generation = asyncio.create_task(generate_community_report(body))
    disconnect = asyncio.create_task(_wait_for_disconnect(request))
    try:
        done, _ = await asyncio.wait(
            {generation, disconnect},
            timeout=120,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if disconnect in done:
            raise HTTPException(status_code=499, detail="report_cancelled")
        if generation not in done:
            raise HTTPException(status_code=504, detail="report_timeout")
        return {"report": generation.result()}
    except ReportGenerationError as exc:
        status = (
            422
            if exc.code in {"materials_not_reviewed", "writing_input_required"}
            else 503
        )
        raise HTTPException(status_code=status, detail=exc.code) from None
    finally:
        for task in (generation, disconnect):
            if not task.done():
                task.cancel()
        await asyncio.gather(generation, disconnect, return_exceptions=True)


async def _resource_catalog(
    request: Request,
    include_resources: bool = True,
) -> tuple[list[dict], str, list[str]]:
    from pathlib import Path

    from .plugins import list_plugins, _list_plugins_from_disk
    from ..community_diagnostics import skill_resources
    from ..community_plugin_lookup import community_plugin_resources
    from ...config.utils import load_config
    from ...utils.io_utils import run_sync_io

    config = await run_sync_io(load_config)
    agent_id = request.headers.get("X-Agent-Id") or config.agents.active_agent
    ref = config.agents.profiles.get(agent_id or "default")
    if not ref:
        raise HTTPException(status_code=404, detail="agent_not_found")
    if not include_resources:
        return [], ref.id, []
    if getattr(request.app.state, "plugin_loader", None) is None:
        plugins = await run_sync_io(_list_plugins_from_disk)
    else:
        plugins = await list_plugins(request)
    resources, failed_ids = await community_plugin_resources(plugins)
    resources.extend(
        await run_sync_io(skill_resources, Path(ref.workspace_dir)),
    )
    return resources, ref.id, failed_ids


@router.get("/resources")
async def report_resources(request: Request):
    resources, _, failed_ids = await _resource_catalog(request)
    return {"resources": resources, "lookup_failed_ids": failed_ids}


@router.post("/diagnostics")
async def collect_diagnostics(body: DiagnosticsRequest, request: Request):
    from ..community_diagnostics import (
        environment_evidence,
        matching_logs,
        resource_key,
    )
    from ..community_report import redact_report_text
    from ..inbox_store import query_events
    from ...utils.io_utils import run_sync_io

    catalog, agent_id, _ = await _resource_catalog(
        request,
        include_resources=bool(body.origins),
    )
    wanted = {resource_key(origin.model_dump()) for origin in body.origins}
    resources = [
        item for item in catalog if resource_key(item["origin"]) in wanted
    ]
    environment, (logs, truncated) = await asyncio.gather(
        run_sync_io(environment_evidence, resources),
        run_sync_io(matching_logs, resources, body.minutes),
    )
    evidence = [{"id": "environment", "content": environment}]
    warnings = []
    if logs:
        evidence.append({"id": "logs", "content": logs})
    elif resources:
        warnings.append("no_matching_logs")
    if truncated:
        warnings.append("logs_truncated")
    if len({resource_key(item["origin"]) for item in resources}) < len(wanted):
        warnings.append("resource_not_installed")
    if body.session_id:
        events, _, _ = await query_events(limit=5000, agent_id=agent_id)
        errors = [
            redact_report_text(str(event.get("body", "")))[:1000]
            for event in events
            if (
                event.get("severity") == "error"
                or event.get("status") in {"error", "failed"}
            )
            and event.get("created_at", 0) >= time.time() - body.minutes * 60
            and event.get("payload", {}).get("session_id") == body.session_id
        ][:2]
        if errors:
            evidence.append({"id": "session", "content": "\n\n".join(errors)})
        else:
            warnings.append("no_session_errors")
    return {"evidence": evidence, "warnings": warnings}
