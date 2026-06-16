# -*- coding: utf-8 -*-
"""API routers."""

import json
import os
import time

from fastapi import APIRouter

from .access_control import router as access_control_router
from .agent_stats import router as agent_stats_router
from .agents import router as agents_router
from .auth import router as auth_router
from .backup import router as backup_router
from .coding_project import router as coding_project_router
from .config import router as config_router
from .console import router as console_router
from .envs import router as envs_router
from .files import router as files_router
from .fork import router as fork_router
from .frontend_plugin import router as frontend_plugin_router
from .git import router as git_router
from .local_models import router as local_models_router
from .market import router as market_router
from .mcp import router as mcp_router
from .mcp_oauth import router as mcp_oauth_router
from .messages import router as messages_router
from .plan import router as plan_router
from .plugins import router as plugins_router
from .provider_oauth import router as provider_oauth_router
from .providers import router as providers_router
from .settings import router as settings_router
from .skills import router as skills_router
from .skills_stream import router as skills_stream_router
from .token_usage import router as token_usage_router
from .tools import router as tools_router
from .workspace import router as workspace_router
from ..crons.api import router as cron_router
from ..runner.api import router as runner_router

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


_emit_router_import_timing("all_routers_imported")

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
