# -*- coding: utf-8 -*-
"""QwenPaw-Data PawApp backend entry point."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from qwenpaw.pawapp import DependencyHealth, DependencyProbe, PawApp

PLUGIN_DIR = Path(__file__).resolve().parent.parent
if __package__ and __package__.startswith("plugin_"):
    from .backend.context_gateway import ContextGateway
    from .backend.runtime import (
        context_python,
        context_working_dir,
        skill_layers,
        skills_root,
    )
else:
    if str(PLUGIN_DIR) not in sys.path:
        sys.path.insert(0, str(PLUGIN_DIR))
    from backend.context_gateway import ContextGateway  # noqa: E402
    from backend.runtime import (  # noqa: E402
        context_python,
        context_working_dir,
        skill_layers,
        skills_root,
    )


app = PawApp("QwenPaw-Data", app_id="datapaw")
app.enable_standard_capabilities()
app.enable_dependency_agent_tools()
app.agent_profile(
    "datapaw",
    name="QwenPaw-Data",
    description="Graph-grounded data analysis with governed queries.",
    persona_dir=PLUGIN_DIR / "agents" / "datapaw",
    language="en",
    plan_enabled=True,
    pinned=True,
)

_context_token = secrets.token_urlsafe(32)
_context_service = app.managed_service(
    "context",
    command=(
        str(context_python()),
        "-m",
        "uvicorn",
        "context_manager.api.server:app",
        "--host",
        "{host}",
        "--port",
        "{port}",
    ),
    health_path="/api/health",
    cwd=context_working_dir(),
    env={
        "DATAPAW_API_TOKEN": _context_token,
        "DATAPAW_CLIENT_API_TOKEN": _context_token,
    },
    external_url_env="DATAPAW_CONTEXT_URL",
    mode_env="DATAPAW_CONTEXT_MODE",
    startup_timeout=45,
    display_name="Context API",
    capabilities=("context-search", "semantic-grounding", "governed-query"),
)
_gateway = ContextGateway(_context_service, _context_token)


async def _probe_graph() -> DependencyHealth:
    try:
        await _gateway.json("GET", "/api/v1/admin/explorer/schema")
    except HTTPException:
        return DependencyHealth(
            health="unavailable",
            lifecycle="unmanaged",
            error_code="GRAPH_UNAVAILABLE",
            message="Graph Store is not accepting application requests",
            remediation=(
                "Use datapaw-cli diagnostics or contact the configured "
                "Graph Store owner"
            ),
        )
    return DependencyHealth(
        health="healthy",
        lifecycle="unmanaged",
        message="Graph grounding is ready",
    )


app.dependency(
    "graph-store",
    display_name="Graph Store",
    ownership="external",
    capabilities=("context-graph", "context-search", "semantic-grounding"),
    required=False,
    probe=DependencyProbe(
        callback=_probe_graph,
        timeout_seconds=5,
        cache_seconds=8,
    ),
)


_skills = skills_root()
_skill_layers = skill_layers(_skills) if _skills is not None else []
_skill_count = sum(
    1
    for layer in _skill_layers
    for child in layer.iterdir()
    if child.is_dir() and (child / "SKILL.md").is_file()
)
if _skills is not None:
    for _layer in _skill_layers:
        app.skill_provider(_layer, enabled_by_default=True, channels=["all"])


app.prompt_section(
    "datapaw-analysis",
    """
You are operating inside the QwenPaw-Data application. For questions that
depend on organizational metrics, datasets, dimensions, prior analysis, or
graph context, call datapaw_search_context before drawing conclusions. Use
datapaw_execute_sql only for read-only SQL and preserve the selected data
source. Clearly distinguish retrieved facts, computed results, and inference.
Keep progress narration brief. In the final response, answer the user's
question directly and include the computed rows as a compact table when the
result is small enough to read. State the observed date coverage exactly;
do not speculate about why dates are absent unless retrieved evidence
supports the explanation.
""".strip(),
    after="workspace",
    priority=80,
    agent_id="datapaw",
)


@app.hook("startup", priority=90)
async def _start_gateway() -> None:
    await _gateway.start()


@app.hook("shutdown", priority=120)
async def _stop_gateway() -> None:
    await _gateway.stop()


_known_source_dependencies: set[str] = set()


@app.hook("startup", priority=100)
async def _register_data_source_dependencies() -> None:
    """Discover configured sources after the context service is ready."""
    try:
        response = await _gateway.json(
            "GET",
            "/api/v1/cm/datasources",
            params={"page": 1, "size": 500},
        )
    except HTTPException:
        return
    for source in response.get("records", []):
        source_id = str(source.get("datasource_id") or "").strip()
        if not source_id:
            continue
        dependency_id = f"source:{source_id}"
        if dependency_id in _known_source_dependencies:
            continue
        display_name = str(source.get("datasource_name") or source_id)

        async def probe_source(
            selected_source_id: str = source_id,
        ) -> DependencyHealth:
            try:
                await _gateway.json(
                    "POST",
                    "/api/v1/cm/execute_sql",
                    body={
                        "sql": "SELECT 1 AS qwenpaw_data_health_check",
                        "datasource_id": selected_source_id,
                        "max_rows": 1,
                    },
                )
            except HTTPException:
                return DependencyHealth(
                    health="unavailable",
                    lifecycle="unmanaged",
                    error_code="DATASOURCE_UNAVAILABLE",
                    message="Data source connection check failed",
                    remediation=(
                        "Verify the source service, credentials, and "
                        "network access"
                    ),
                )
            return DependencyHealth(
                health="healthy",
                lifecycle="unmanaged",
                message="Governed queries are ready",
            )

        app.dependency(
            dependency_id,
            display_name=display_name,
            ownership="external",
            capabilities=("governed-query",),
            required=False,
            probe=DependencyProbe(
                callback=probe_source,
                timeout_seconds=8,
                cache_seconds=15,
            ),
        )
        _known_source_dependencies.add(dependency_id)


router = APIRouter()


_llm_bootstrap_done = False


def _host_llm_payload() -> dict[str, Any] | None:
    """Read the host's active model as an OpenAI-compatible payload."""
    try:
        from qwenpaw.providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()
        slot = manager.get_active_model()
        provider = manager.get_provider(slot.provider_id) if slot else None
    except Exception:  # pragma: no cover - host internals unavailable
        return None
    if slot is None or provider is None:
        return None
    model = (slot.model or "").strip()
    base_url = (getattr(provider, "base_url", "") or "").strip()
    api_key = (getattr(provider, "api_key", "") or "").strip()
    if not model or not base_url or not api_key:
        return None
    return {"model": model, "base_url": base_url, "api_key": api_key}


async def _bootstrap_llm_from_host() -> None:
    """Bootstrap the Context service's LLM from the QwenPaw host model.

    The app owns its model configuration, matching standalone datapaw-cli
    and Data-Cloud deployments. The host's active model is used only as a
    first-run default when no LLM has been configured yet; an existing
    configuration is never overwritten.
    """
    global _llm_bootstrap_done
    if _llm_bootstrap_done or not _context_service.is_ready:
        return
    try:
        current = await _gateway.json("GET", "/api/system/model-config/")
    except HTTPException:
        return
    llm_config = (current or {}).get("llm") or {}
    if (llm_config.get("api_key") or "").strip():
        # App-specific configuration exists; leave it alone for good.
        _llm_bootstrap_done = True
        return
    body = _host_llm_payload()
    if body is None:
        return
    try:
        await _gateway.json("PUT", "/api/system/model-config/llm", body=body)
    except HTTPException:
        return
    _llm_bootstrap_done = True


@router.get("/status")
async def status() -> dict[str, Any]:
    health: dict[str, Any] | None = None
    if _context_service.is_ready:
        await _bootstrap_llm_from_host()
        health = await _gateway.json("GET", "/api/health")
    return {
        "app": "datapaw",
        "service": _context_service.status(),
        "health": health,
        "skills_available": _skills is not None,
        "skills": {
            "available": _skills is not None,
            "count": _skill_count,
            "providers": len(_skill_layers),
        },
        "dependencies": await app.dependencies.snapshot(),
    }


@router.get("/context/api/auth/status")
async def context_auth_status() -> dict[str, Any]:
    """Report that the embedded console needs no client-side login.

    The gateway injects the Context service token server-side, so from the
    embedded UI's point of view authentication is never required.  Serve
    both contract shapes: ``required`` (public datapaw-context 0.2.x
    AuthGate) and ``enabled`` (internal Data-Cloud auth store).
    """
    return {"required": False, "enabled": False}


@router.api_route(
    "/context/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def context_proxy(path: str, request: Request) -> Any:
    # First-run default: seed the LLM config from the host before the
    # console reads it; configured values are never overwritten.
    if request.method == "GET" and "system/model-config" in path:
        await _bootstrap_llm_from_host()
    return await _gateway.proxy(path, request)


app.include_router(router)


@app.tool(
    "datapaw_search_context",
    description=(
        "Retrieve QwenPaw-Data semantic, metric, dataset, and graph "
        "context for a question."
    ),
    icon="🔎",
    tool_type="network",
)
async def datapaw_search_context(
    query: str,
    datasource_id: str = "",
    domain: str = "",
) -> Any:
    body: dict[str, Any] = {"query": query, "stream": False}
    if datasource_id:
        body["datasource_id"] = datasource_id
    if domain:
        body["scope"] = {"domain": domain}
    return await _gateway.json("POST", "/api/v1/cm/search_context", body=body)


@app.tool(
    "datapaw_list_domains",
    description="List QwenPaw-Data business domains available for analysis.",
    icon="🗂️",
    tool_type="network",
)
async def datapaw_list_domains(datasource_id: str = "") -> Any:
    params = {"datasource_id": datasource_id} if datasource_id else None
    return await _gateway.json("GET", "/api/v1/cm/domains", params=params)


@app.tool(
    "datapaw_explore_entity",
    description=(
        "Explore a metric or business entity across QwenPaw-Data "
        "context graphs."
    ),
    icon="🕸️",
    tool_type="network",
)
async def datapaw_explore_entity(
    entity_name: str,
    datasource_id: str = "",
    domain: str = "",
) -> Any:
    body: dict[str, Any] = {"entity_name": entity_name}
    if datasource_id:
        body["datasource_id"] = datasource_id
    if domain:
        body["domain"] = domain
    return await _gateway.json("POST", "/api/v1/cm/explore_entity", body=body)


@app.tool(
    "datapaw_execute_sql",
    description=(
        "Execute a read-only SQL query through the selected "
        "QwenPaw-Data source."
    ),
    icon="🧮",
    tool_type="network",
)
async def datapaw_execute_sql(
    sql: str,
    datasource_id: str = "",
    max_rows: int = 2000,
) -> Any:
    body: dict[str, Any] = {"sql": sql, "max_rows": max_rows}
    if datasource_id:
        body["datasource_id"] = datasource_id
    return await _gateway.json("POST", "/api/v1/cm/execute_sql", body=body)


plugin = app
