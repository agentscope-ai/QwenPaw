# -*- coding: utf-8 -*-
"""API routers."""

import json
import os
import time

from fastapi import APIRouter

_ROUTER_IMPORT_STARTED_AT = time.perf_counter()
_ROUTER_IMPORT_LAST_AT = _ROUTER_IMPORT_STARTED_AT


def _emit_router_import_timing(phase: str) -> None:
    if os.environ.get("QWENPAW_DESKTOP_APP") != "1":
        return

    global _ROUTER_IMPORT_LAST_AT
    now = time.perf_counter()
    payload = {
        "component": "qwenpaw.app.routers",
        "phase": phase,
        "elapsed_ms": round((now - _ROUTER_IMPORT_STARTED_AT) * 1000.0, 1),
        "delta_ms": round((now - _ROUTER_IMPORT_LAST_AT) * 1000.0, 1),
    }
    _ROUTER_IMPORT_LAST_AT = now
    print(
        "QWENPAW_BACKEND_TIMING "
        + json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
        flush=True,
    )


from .agents import router as agents_router
_emit_router_import_timing("agents_router_imported")
from .config import router as config_router
_emit_router_import_timing("config_router_imported")
from .local_models import router as local_models_router
_emit_router_import_timing("local_models_router_imported")
from .providers import router as providers_router
_emit_router_import_timing("providers_router_imported")
from .market import router as market_router
_emit_router_import_timing("market_router_imported")
from .skills import router as skills_router
_emit_router_import_timing("skills_router_imported")
from .skills_stream import router as skills_stream_router
_emit_router_import_timing("skills_stream_router_imported")
from .workspace import router as workspace_router
_emit_router_import_timing("workspace_router_imported")
from .envs import router as envs_router
_emit_router_import_timing("envs_router_imported")
from .mcp import router as mcp_router
_emit_router_import_timing("mcp_router_imported")
from .mcp_oauth import router as mcp_oauth_router
_emit_router_import_timing("mcp_oauth_router_imported")
from .tools import router as tools_router
_emit_router_import_timing("tools_router_imported")
from ..crons.api import router as cron_router
_emit_router_import_timing("cron_router_imported")
from ..runner.api import router as runner_router
_emit_router_import_timing("runner_router_imported")
from .console import router as console_router
_emit_router_import_timing("console_router_imported")
from .token_usage import router as token_usage_router
_emit_router_import_timing("token_usage_router_imported")
from .agent_stats import router as agent_stats_router
_emit_router_import_timing("agent_stats_router_imported")
from .auth import router as auth_router
_emit_router_import_timing("auth_router_imported")
from .messages import router as messages_router
_emit_router_import_timing("messages_router_imported")
from .files import router as files_router
_emit_router_import_timing("files_router_imported")
from .settings import router as settings_router
_emit_router_import_timing("settings_router_imported")
from .plugins import router as plugins_router
_emit_router_import_timing("plugins_router_imported")
from .frontend_plugin import router as frontend_plugin_router
_emit_router_import_timing("frontend_plugin_router_imported")
from .backup import router as backup_router
_emit_router_import_timing("backup_router_imported")
from .plan import router as plan_router
_emit_router_import_timing("plan_router_imported")
from .fork import router as fork_router
_emit_router_import_timing("fork_router_imported")
from .git import router as git_router
_emit_router_import_timing("git_router_imported")
from .coding_project import router as coding_project_router
_emit_router_import_timing("coding_project_router_imported")
from .access_control import router as access_control_router
_emit_router_import_timing("access_control_router_imported")
from .provider_oauth import router as provider_oauth_router
_emit_router_import_timing("provider_oauth_router_imported")

router = APIRouter()
_emit_router_import_timing("router_created")

router.include_router(agents_router)
router.include_router(config_router)
router.include_router(console_router)
router.include_router(cron_router)
router.include_router(local_models_router)
router.include_router(mcp_oauth_router)
router.include_router(mcp_router)
router.include_router(messages_router)
router.include_router(providers_router)
router.include_router(runner_router)
router.include_router(market_router)
router.include_router(skills_router)
router.include_router(skills_stream_router)
router.include_router(tools_router)
router.include_router(workspace_router)
router.include_router(envs_router)
router.include_router(token_usage_router)
router.include_router(agent_stats_router)
router.include_router(auth_router)
router.include_router(files_router)
router.include_router(settings_router)
router.include_router(plugins_router)
router.include_router(frontend_plugin_router)
router.include_router(backup_router)
router.include_router(plan_router)
router.include_router(fork_router)
router.include_router(git_router)
router.include_router(coding_project_router)
router.include_router(access_control_router)
router.include_router(provider_oauth_router)
_emit_router_import_timing("routers_included")


def create_agent_scoped_router() -> APIRouter:
    """Create agent-scoped router that wraps existing routers.

    Returns:
        APIRouter with all routers mounted under /agents/{agentId}/
    """
    from .agent_scoped import create_agent_scoped_router as _create

    return _create()


__all__ = ["router", "create_agent_scoped_router"]
