# -*- coding: utf-8 -*-
"""QwenPaw-Data PawApp backend entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response

from qwenpaw.pawapp import DependencyHealth, DependencyProbe, PawApp

logger = logging.getLogger(__name__)

PLUGIN_DIR = Path(__file__).resolve().parent.parent
if __package__ and __package__.startswith("plugin_"):
    from .backend.config import (
        CONFIG_JSON_PATH,
        DataAppConfig,
        load_config,
        on_before_start,
        prepare_runtime_files,
        save_config,
        seed_from_env,
        set_context_env_vars,
    )
    from .backend.context_gateway import ContextGateway
    from .backend.runtime import (
        context_python,
        context_working_dir,
        runtime_packages_available,
        skill_layers,
        skills_root,
    )
else:
    if str(PLUGIN_DIR) not in sys.path:
        sys.path.insert(0, str(PLUGIN_DIR))
    from backend.config import (  # noqa: E402
        CONFIG_JSON_PATH,
        DataAppConfig,
        load_config,
        on_before_start,
        prepare_runtime_files,
        save_config,
        seed_from_env,
        set_context_env_vars,
    )
    from backend.context_gateway import ContextGateway  # noqa: E402
    from backend.runtime import (  # noqa: E402
        context_python,
        context_working_dir,
        runtime_packages_available,
        skill_layers,
        skills_root,
    )


app = PawApp("QwenPaw-Data", app_id="qwenpaw-data")
app.enable_standard_capabilities()
app.enable_dependency_agent_tools()
app.agent_profile(
    "qwenpaw-data",
    name="QwenPaw-Data",
    description="Graph-grounded data analysis with governed queries.",
    persona_dir=PLUGIN_DIR / "agents" / "qwenpaw-data",
    language="en",
    plan_enabled=True,
    pinned=True,
)

_context_token = secrets.token_urlsafe(32)

_active_restore_done = False


async def _on_before_start() -> None:
    """Wrap the config hook so per-service-start state gets reset.

    The context service keeps the active datasource in memory only, so the
    restore flag must be cleared before every (re)start to re-apply the
    persisted selection once the service is ready again. Host-model reuse
    is also refreshed here so switching the active model in QwenPaw and
    restarting this app is enough to follow the change.
    """
    global _active_restore_done
    _active_restore_done = False
    config = _sync_reuse_from_host(load_config())
    if config.llm.reuse_host or config.embedding.reuse_host:
        # Persist the refreshed snapshot so the Configure page and the
        # regenerated runtime files stay aligned with the host's model.
        save_config(config)
    await on_before_start()


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
    # Only pass plugin-owned overrides; the framework's
    # ManagedService.start() already inherits os.environ.copy() and merges
    # spec.env on top. Spreading **os.environ here would (a) freeze the
    # snapshot at import time, pinning later env changes to stale values on
    # restart, and (b) subject every inherited env var to
    # _replace_placeholders(), silently rewriting literal {host}/{port}.
    env={
        "QWENPAW_DATA_API_TOKEN": _context_token,
        "QWENPAW_DATA_CLIENT_API_TOKEN": _context_token,
    },
    external_url_env="QWENPAW_DATA_CONTEXT_URL",
    mode_env="QWENPAW_DATA_CONTEXT_MODE",
    on_before_start=_on_before_start,
    startup_timeout=45,
    display_name="Context API",
    capabilities=("context-search", "semantic-grounding", "governed-query"),
    runtime_remediation=(
        "Install the runtime from PyPI (scripts/setup-pypi.sh) or from the "
        "QwenPaw-Data workspace (scripts/setup-dev.sh); alternatively set "
        "QWENPAW_DATA_CONTEXT_MODE=external with QWENPAW_DATA_CONTEXT_URL and "
        "QWENPAW_DATA_CONTEXT_TOKEN"
    ),
)
_gateway = ContextGateway(_context_service, _context_token)


def _context_runtime_issue() -> dict[str, str] | None:
    """Detect a context-service misconfiguration at plugin load time.

    The plugin runs in one of two supported modes. External mode (the
    production mode for clean installs) proxies an operator-provided
    Context service and needs a URL and token; managed mode spawns the
    bundled sidecar and needs a provisioned Python runtime. Resolving the
    problem here lets installation surface one actionable error instead
    of registering a service that is doomed to fail its first start.
    """
    mode = os.getenv("QWENPAW_DATA_CONTEXT_MODE", "").strip().lower()
    external_url = os.getenv("QWENPAW_DATA_CONTEXT_URL", "").strip()
    if mode == "external" or external_url:
        missing = [
            name
            for name in (
                "QWENPAW_DATA_CONTEXT_URL",
                "QWENPAW_DATA_CONTEXT_TOKEN",
            )
            if not os.getenv(name, "").strip()
        ]
        if missing:
            return {
                "code": "EXTERNAL_MODE_INCOMPLETE",
                "message": (
                    "External context mode is selected but "
                    + " and ".join(missing)
                    + (" is" if len(missing) == 1 else " are")
                    + " not set"
                ),
                "remediation": (
                    "Set QWENPAW_DATA_CONTEXT_URL and "
                    "QWENPAW_DATA_CONTEXT_TOKEN to "
                    "the operated Context service, or unset "
                    "QWENPAW_DATA_CONTEXT_MODE to run the managed sidecar"
                ),
            }
        return None
    if not _context_service.runtime_available():
        if runtime_packages_available():
            remediation = (
                "The qwenpaw-data runtime packages are installed, but the "
                "chosen Python interpreter is not available. Set "
                "QWENPAW_DATA_CONTEXT_PYTHON to a valid interpreter, or set "
                "QWENPAW_DATA_CONTEXT_MODE=external with "
                "QWENPAW_DATA_CONTEXT_URL and QWENPAW_DATA_CONTEXT_TOKEN"
            )
        else:
            remediation = (
                "Install the runtime from PyPI: scripts/setup-pypi.sh; or "
                "from source: scripts/setup-dev.sh; or set "
                "QWENPAW_DATA_CONTEXT_MODE=external with "
                "QWENPAW_DATA_CONTEXT_URL and QWENPAW_DATA_CONTEXT_TOKEN"
            )
        return {
            "code": "RUNTIME_MISSING",
            "message": (
                "No managed context runtime is provisioned for this install"
            ),
            "remediation": remediation,
        }
    return None


_runtime_issue = _context_runtime_issue()
if _runtime_issue is not None:
    logger.error(
        "qwenpaw-data context service cannot launch: %s [%s]. %s",
        _runtime_issue["message"],
        _runtime_issue["code"],
        _runtime_issue["remediation"],
    )


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
                "Use qwenpaw-data-cli diagnostics or contact the configured "
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
    "qwenpaw-data-analysis",
    """
You are operating inside the QwenPaw-Data application. For questions that
depend on organizational metrics, datasets, dimensions, prior analysis, or
graph context, call qwenpaw_data_search_context before drawing conclusions. Use
qwenpaw_data_execute_sql only for read-only SQL and preserve the selected data
source. Clearly distinguish retrieved facts, computed results, and inference.
Keep progress narration brief. In the final response, answer the user's
question directly and include the computed rows as a compact table when the
result is small enough to read. Answer in the language of the user's
message, including generated table headers and run summaries; catalog
names such as metric or dataset identifiers stay as stored. State the
observed date coverage exactly; do not speculate about why dates are
absent unless retrieved evidence supports the explanation.
""".strip(),
    after="workspace",
    priority=80,
    agent_id="qwenpaw-data",
)


@app.hook("startup", priority=60)
async def _initialize_config() -> None:
    """Ensure config.json exists and runtime files are generated.

    This runs before managed services start (priority 70) so the context
    service's on_before_start hook can read a fully initialized config.json.
    """
    from qwenpaw.envs import load_envs_into_environ

    # Framework-level envs (``qwenpaw env set``) participate in first-run
    # seeding, mirroring what on_before_start reloads before every start.
    load_envs_into_environ()
    config = load_config()
    if not CONFIG_JSON_PATH.is_file():
        host_llm = _host_llm_payload()
        if host_llm:
            config.llm.provider = "openai"
            config.llm.base_url = host_llm["base_url"]
            config.llm.model = host_llm["model"]
            config.llm.api_key = host_llm["api_key"]
            # Default embedding to the same provider/credentials.
            config.embedding.base_url = host_llm["base_url"]
            config.embedding.api_key = host_llm["api_key"]
        # Fill anything the host model did not cover (Neo4j credentials,
        # embedding model) from the environment so the Configure page
        # reflects the values the service actually uses.
        seed_from_env(config)
        save_config(config)
    else:
        prepare_runtime_files(config)
        set_context_env_vars()


@app.hook("startup", priority=90)
async def _start_gateway() -> None:
    await _gateway.start()


@app.hook("shutdown", priority=120)
async def _stop_gateway() -> None:
    await _gateway.stop()


_known_source_dependencies: dict[str, str] = {}
_source_reconcile_lock: asyncio.Lock = asyncio.Lock()
_source_reconciled_at = 0.0
_SOURCE_RECONCILE_MIN_INTERVAL = 10.0
_background_tasks: set[asyncio.Task] = set()


def _spawn_source_reconcile() -> None:
    """Run a throttled reconcile without dropping the task to the GC."""
    task = asyncio.create_task(_reconcile_source_dependencies())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _spawn_active_restore() -> None:
    """Re-apply the persisted active datasource off the request path."""
    task = asyncio.create_task(_restore_active_datasource())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _source_probe(source_id: str):
    """Build a governed-query health probe for one data source."""

    async def probe_source() -> DependencyHealth:
        try:
            await _gateway.json(
                "POST",
                "/api/v1/cm/execute_sql",
                body={
                    "sql": "SELECT 1 AS qwenpaw_data_health_check",
                    "datasource_id": source_id,
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

    return probe_source


async def _reconcile_source_dependencies(*, force: bool = False) -> None:
    """Align ``source:{id}`` dependencies with the live source catalog.

    Sources can be added, renamed, or deleted from the embedded management
    console at any time, so registration is a reentrant reconciliation
    instead of a startup-only, grow-only set.
    """
    global _source_reconciled_at
    async with _source_reconcile_lock:
        now = time.monotonic()
        if (
            not force
            and now - _source_reconciled_at < _SOURCE_RECONCILE_MIN_INTERVAL
        ):
            return
        try:
            response = await _gateway.json(
                "GET",
                "/api/v1/cm/datasources",
                params={"page": 1, "size": 500},
            )
        except HTTPException:
            # Catalog unavailable: keep current registrations instead of
            # mass-dropping dependencies while the service is down.
            return
        desired: dict[str, str] = {}
        for source in response.get("records", []):
            source_id = str(source.get("datasource_id") or "").strip()
            if not source_id:
                continue
            desired[f"source:{source_id}"] = str(
                source.get("datasource_name") or source_id,
            )

        for dependency_id in app.dependencies.ids(prefix="source:"):
            if dependency_id not in desired:
                app.remove_dependency(dependency_id)
                _known_source_dependencies.pop(dependency_id, None)

        for dependency_id, display_name in desired.items():
            if _known_source_dependencies.get(dependency_id) == display_name:
                continue
            app.dependency(
                dependency_id,
                display_name=display_name,
                ownership="external",
                capabilities=("governed-query",),
                required=False,
                probe=DependencyProbe(
                    callback=_source_probe(
                        dependency_id.removeprefix("source:"),
                    ),
                    timeout_seconds=8,
                    cache_seconds=15,
                ),
                replace=dependency_id in _known_source_dependencies,
            )
            _known_source_dependencies[dependency_id] = display_name
        _source_reconciled_at = time.monotonic()


@app.hook("startup", priority=100)
async def _register_data_source_dependencies() -> None:
    """Discover configured sources after the context service is ready."""
    await _reconcile_source_dependencies(force=True)


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

    The app owns its model configuration, matching standalone qwenpaw-data-cli
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
        "app": "qwenpaw-data",
        "service": _context_service.status(),
        "runtime": {
            "ok": _runtime_issue is None,
            "issue": _runtime_issue,
        },
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
    both contract shapes: ``required`` (public qwenpaw-data-context 0.1.x
    AuthGate) and ``enabled`` (internal Data-Cloud auth store).
    """
    return {"required": False, "enabled": False}


_DATASOURCE_ITEM_RE = re.compile(
    r"(?:^|/)semantic-config/datasource/[^/]+/?$",
)


async def _proxy_set_active_datasource(
    path: str,
    request: Request,
) -> Response:
    """Forward an active-datasource switch and persist the selection.

    The context service keeps the active selection in memory only; the
    plugin mirrors successful switches into config.json so the choice
    survives restarts. Starlette caches the request body, so parsing it
    here leaves the forwarded request intact.
    """
    try:
        payload = json.loads(await request.body() or b"{}")
    except ValueError:
        payload = None
    response = await _gateway.proxy(path, request)
    if response.status_code < 400 and isinstance(payload, dict):
        config = load_config()
        config.datasources.active_id = str(
            payload.get("datasource_id") or "",
        ).strip()
        save_config(config)
    return response


async def _proxy_delete_datasource(
    path: str,
    request: Request,
) -> Response:
    """Forward a datasource deletion and drop a stale active selection."""
    response = await _gateway.proxy(path, request)
    if response.status_code < 400:
        deleted_id = path.rstrip("/").rsplit("/", 1)[-1]
        config = load_config()
        if config.datasources.active_id == deleted_id:
            config.datasources.active_id = ""
            save_config(config)
    return response


@router.api_route(
    "/context/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def context_proxy(path: str, request: Request) -> Any:
    # First-run default: seed the LLM config from the host before the
    # console reads it; configured values are never overwritten.
    if request.method == "GET" and "system/model-config" in path:
        await _bootstrap_llm_from_host()
    # The shell polls the source list; piggyback the persisted-active
    # restore and a throttled reconcile so the selection survives
    # restarts and console-side changes converge onto the dependency
    # catalog without a dedicated timer.
    if request.method == "GET" and path.rstrip("/").endswith(
        "cm/datasources",
    ):
        _spawn_active_restore()
        _spawn_source_reconcile()
    # Datasource lifecycle flows through this proxy, so mirror the
    # context service's in-memory state into config.json here.
    if request.method == "PUT" and path.rstrip("/").endswith(
        "datasources/active",
    ):
        return await _proxy_set_active_datasource(path, request)
    if request.method == "DELETE" and _DATASOURCE_ITEM_RE.search(path):
        return await _proxy_delete_datasource(path, request)
    return await _gateway.proxy(path, request)


@router.get("/config")
async def get_config() -> dict[str, Any]:
    """Return the current unified plugin configuration."""
    return load_config().to_dict()


async def _push_model_config(config: DataAppConfig) -> None:
    """Push model settings to the running context service, if any."""
    if not _context_service.is_ready:
        return
    try:
        await _gateway.json(
            "PUT",
            "/api/system/model-config/llm",
            body={
                "provider": config.llm.provider,
                "base_url": config.llm.base_url,
                "model": config.llm.model,
                "api_key": config.llm.api_key,
            },
        )
        await _gateway.json(
            "PUT",
            "/api/system/model-config/embedding",
            body={
                "base_url": config.embedding.base_url or config.llm.base_url,
                "model": config.embedding.model,
                "api_key": config.embedding.api_key or config.llm.api_key,
                "dim": config.embedding.dim,
            },
        )
    except HTTPException:
        logger.exception("Failed to push model config to context service")


async def _restore_active_datasource() -> None:
    """Re-apply the persisted active datasource after a service (re)start.

    The context service keeps the active selection in memory only; without
    this restore every restart would silently fall back to "no datasource".
    The done flag latches only on success so a restore racing the service's
    startup window retries on the next poll instead of giving up for good.
    """
    global _active_restore_done
    if _active_restore_done or not _context_service.is_ready:
        return
    active_id = (load_config().datasources.active_id or "").strip()
    if not active_id:
        _active_restore_done = True
        return
    try:
        await _gateway.json(
            "PUT",
            "/api/datasources/active",
            body={"datasource_id": active_id},
        )
    except HTTPException:
        logger.warning(
            "Failed to restore active datasource %r "
            "(it may have been deleted)",
            active_id,
        )
        return
    _active_restore_done = True


@router.post("/config")
async def set_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist configuration and regenerate runtime files."""
    config = DataAppConfig.from_dict(payload)
    # Saved payloads carry the reuse snapshot from page load; refresh it so
    # saving while reuse is enabled also follows host model switches.
    _sync_reuse_from_host(config)
    save_config(config)
    set_context_env_vars()
    # If the context service is already running, push the new model
    # configuration so it takes effect without a manual restart.
    await _push_model_config(config)
    return config.to_dict()


def _resolve_host_active():
    """Return the host's active provider instance and model, if usable.

    The context service only speaks the OpenAI chat-completions protocol,
    so native Anthropic/Gemini protocol providers and providers without an
    explicit base_url cannot serve it. DashScope's compatible-mode endpoint
    stays usable even though the host wraps it with its own chat model
    implementation.
    """
    try:
        from qwenpaw.providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()
        slot = manager.get_active_model()
        if slot is None:
            return None
        provider_id = (getattr(slot, "provider_id", "") or "").strip()
        model = (getattr(slot, "model", "") or "").strip()
        if not provider_id or not model:
            return None
        provider = manager.get_provider(provider_id)
        base_url = (getattr(provider, "base_url", "") or "").strip()
        chat_model = (getattr(provider, "chat_model", "") or "").strip()
    except Exception:  # pragma: no cover - host internals unavailable
        return None
    if not base_url or chat_model in {"AnthropicChatModel", "GeminiChatModel"}:
        return None
    return provider, model


def _sync_reuse_from_host(
    config: DataAppConfig,
    *,
    strict: bool = False,
) -> DataAppConfig:
    """Refresh reused model fields from the host's active model.

    Following the host when it switches models is the point of the reuse
    toggle, so every save/start refreshes the snapshot instead of keeping
    the credentials captured when the toggle was first checked. When the
    host has no usable active model the last snapshot is kept (non-strict
    callers) or rejected with an actionable error (the toggle endpoint).
    """
    if not (config.llm.reuse_host or config.embedding.reuse_host):
        return config
    resolved = _resolve_host_active()
    if resolved is None:
        if strict:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No usable active model in the QwenPaw host. Configure "
                    "an OpenAI-compatible model in QwenPaw settings first."
                ),
            )
        logger.warning(
            "Host model reuse is enabled but the QwenPaw host exposes no "
            "usable active model; keeping the stored snapshot",
        )
        return config
    provider, model = resolved
    base_url = (getattr(provider, "base_url", "") or "").strip()
    api_key = (getattr(provider, "api_key", "") or "").strip()
    provider_name = (getattr(provider, "name", "") or "").strip() or (
        getattr(provider, "id", "") or ""
    )
    if config.llm.reuse_host:
        config.llm.provider = "openai"
        config.llm.base_url = base_url
        config.llm.model = model
        config.llm.api_key = api_key
        config.llm.host_provider_name = provider_name
    if config.embedding.reuse_host:
        # The host has no "active embedding model" concept; reuse shares
        # the active provider's endpoint and key while the model stays
        # locally configured.
        config.embedding.base_url = base_url
        config.embedding.api_key = api_key
        config.embedding.host_provider_name = provider_name
    return config


@router.post("/config/reuse-host-model")
async def reuse_host_model(payload: dict[str, Any]) -> dict[str, Any]:
    """Toggle reusing the model configured in the QwenPaw host.

    Enabling copies the host's active model credentials into the plugin
    configuration; the Configure page collapses the manual fields while
    the toggle stays checked. Disabling keeps the last values so switching
    back to manual entry does not lose them.
    """
    target = (payload.get("target") or "").strip()
    reuse = bool(payload.get("reuse"))
    if target not in {"llm", "embedding"}:
        raise HTTPException(
            status_code=400,
            detail="target must be llm or embedding",
        )
    config = load_config()
    section = config.llm if target == "llm" else config.embedding
    section.reuse_host = reuse
    if reuse:
        _sync_reuse_from_host(config, strict=True)
    save_config(config)
    set_context_env_vars()
    await _push_model_config(config)
    return config.to_dict()


@router.post("/config/test/{target}")
async def test_config_target(
    target: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Test connectivity for one configured subsystem.

    LLM and embedding endpoints are probed by the context service itself
    (``/api/system/model-config/{llm,embedding}/test``): it owns the
    credentials and dials with the same client the app will use, so its
    verdict is authoritative. Neo4j is probed from this process because
    the context service exposes no graph-store test endpoint.
    """
    if target not in {"llm", "embedding", "neo4j"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported test target: {target}",
        )

    def _test_neo4j(cfg: dict[str, Any]) -> dict[str, Any]:
        uri = cfg.get("uri", "")
        if not uri:
            return {"ok": False, "error": "Neo4j URI is required"}
        parsed = urlsplit(uri)
        host = parsed.hostname
        port = parsed.port or 7687
        if not host:
            return {"ok": False, "error": "Could not parse Neo4j host"}
        try:
            with socket.create_connection((host, port), timeout=5.0):
                return {"ok": True}
        except OSError as exc:
            # Exception strings can embed resolved addresses; the error
            # class is enough to tell refused connections from timeouts.
            return {
                "ok": False,
                "error": f"Connection failed: {exc.__class__.__name__}",
            }

    if target == "neo4j":
        return _test_neo4j(payload.get("neo4j", {}))

    try:
        result = await _gateway.json(
            "POST",
            f"/api/system/model-config/{target}/test",
            body=payload.get(target, {}),
        )
    except HTTPException as exc:
        # Covers the sidecar startup window and transport failures; the
        # gateway's detail is already a clean user-facing string.
        return {"ok": False, "error": str(exc.detail)}
    return {
        "ok": bool(result.get("success")),
        "error": (
            None
            if result.get("success")
            else str(result.get("message") or "Test failed")
        ),
        "detected_dim": result.get("detected_dim"),
    }


app.include_router(router)


@app.tool(
    "qwenpaw_data_search_context",
    description=(
        "Retrieve QwenPaw-Data semantic, metric, dataset, and graph "
        "context for a question."
    ),
    icon="🔎",
    tool_type="network",
)
async def qwenpaw_data_search_context(
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
    "qwenpaw_data_list_domains",
    description="List QwenPaw-Data business domains available for analysis.",
    icon="🗂️",
    tool_type="network",
)
async def qwenpaw_data_list_domains(datasource_id: str = "") -> Any:
    params = {"datasource_id": datasource_id} if datasource_id else None
    return await _gateway.json("GET", "/api/v1/cm/domains", params=params)


@app.tool(
    "qwenpaw_data_explore_entity",
    description=(
        "Explore a metric or business entity across QwenPaw-Data "
        "context graphs."
    ),
    icon="🕸️",
    tool_type="network",
)
async def qwenpaw_data_explore_entity(
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
    "qwenpaw_data_execute_sql",
    description=(
        "Execute a read-only SQL query through the selected "
        "QwenPaw-Data source."
    ),
    icon="🧮",
    tool_type="network",
)
async def qwenpaw_data_execute_sql(
    sql: str,
    datasource_id: str = "",
    max_rows: int = 2000,
) -> Any:
    body: dict[str, Any] = {"sql": sql, "max_rows": max_rows}
    if datasource_id:
        body["datasource_id"] = datasource_id
    return await _gateway.json("POST", "/api/v1/cm/execute_sql", body=body)


plugin = app
