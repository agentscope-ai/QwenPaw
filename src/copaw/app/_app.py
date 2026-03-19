# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
import mimetypes
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from agentscope_runtime.engine.app import AgentApp

from ..config import load_config  # pylint: disable=no-name-in-module
from ..config.utils import get_config_path
from ..constant import DOCS_ENABLED, LOG_LEVEL_ENV, CORS_ORIGINS, WORKING_DIR
from ..__version__ import __version__
from ..utils.logging import setup_logger, add_copaw_file_handler
from .auth import AuthMiddleware
from .routers import router as api_router, create_agent_scoped_router
from .routers.agent_scoped import AgentContextMiddleware
from .routers.voice import voice_router
from ..envs import load_envs_into_environ
from ..providers.provider_manager import ProviderManager
from .multi_agent_manager import MultiAgentManager
from .migration import (
    migrate_legacy_workspace_to_default_agent,
    ensure_default_agent_exists,
)

# Apply log level on load so reload child process gets same level as CLI.
logger = setup_logger(os.environ.get(LOG_LEVEL_ENV, "info"))

# Ensure static assets are served with browser-compatible MIME types across
# platforms (notably Windows may miss .js/.mjs mappings).
mimetypes.init()
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/wasm", ".wasm")

# Load persisted env vars into os.environ at module import time
# so they are available before the lifespan starts.
load_envs_into_environ()


# Dynamic runner that selects the correct workspace runner based on request
class DynamicMultiAgentRunner:
    """Runner wrapper that dynamically routes to the correct workspace runner.

    This allows AgentApp to work with multiple agents by inspecting
    the X-Agent-Id header on each request.
    """

    def __init__(self):
        self.framework_type = "agentscope"
        self._multi_agent_manager = None

    def set_multi_agent_manager(self, manager):
        """Set the MultiAgentManager instance after initialization."""
        self._multi_agent_manager = manager

    async def _get_workspace_runner(self, request):
        """Get the correct workspace runner based on request."""
        from .agent_context import get_current_agent_id

        # Get agent_id from context (set by middleware or header)
        agent_id = get_current_agent_id()

        logger.debug(f"_get_workspace_runner: agent_id={agent_id}")

        # Get the correct workspace runner
        if not self._multi_agent_manager:
            raise RuntimeError("MultiAgentManager not initialized")

        try:
            workspace = await self._multi_agent_manager.get_agent(agent_id)
            logger.debug(
                f"Got workspace: {workspace.agent_id}, "
                f"runner: {workspace.runner}",
            )
            return workspace.runner
        except ValueError as e:
            logger.error(f"Agent not found: {e}")
            raise
        except Exception as e:
            logger.error(
                f"Error getting workspace runner: {e}",
                exc_info=True,
            )
            raise

    async def stream_query(self, request, *args, **kwargs):
        """Dynamically route to the correct workspace runner."""
        logger.debug("DynamicMultiAgentRunner.stream_query called")
        try:
            runner = await self._get_workspace_runner(request)
            logger.debug(f"Got runner: {runner}, type: {type(runner)}")
            # Delegate to the actual runner's stream_query generator
            count = 0
            async for item in runner.stream_query(request, *args, **kwargs):
                count += 1
                logger.debug(f"Yielding item #{count}: {type(item)}")
                yield item
            logger.debug(f"stream_query completed, yielded {count} items")
        except Exception as e:
            logger.error(
                f"Error in stream_query: {e}",
                exc_info=True,
            )
            # Yield error message to client
            yield {
                "error": str(e),
                "type": "error",
            }

    async def query_handler(self, request, *args, **kwargs):
        """Dynamically route to the correct workspace runner."""
        runner = await self._get_workspace_runner(request)
        # Delegate to the actual runner's query_handler generator
        async for item in runner.query_handler(request, *args, **kwargs):
            yield item

    # Async context manager support for AgentApp lifecycle
    async def __aenter__(self):
        """
        No-op context manager entry (workspaces manage their own runners).
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """No-op context manager exit (workspaces manage their own runners)."""
        return None


# Use dynamic runner for AgentApp
runner = DynamicMultiAgentRunner()

agent_app = AgentApp(
    app_name="Friday",
    app_description="A helpful assistant",
    runner=runner,
)


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):  # pylint: disable=too-many-statements,too-many-branches
    startup_start_time = time.time()
    add_copaw_file_handler(WORKING_DIR / "copaw.log")

    # Auto-register admin from env vars (for automated deployments)
    from .auth import auto_register_from_env

    auto_register_from_env()

    try:
        from ..utils.telemetry import (
            collect_and_upload_telemetry,
            has_telemetry_been_collected,
            is_telemetry_opted_out,
        )

        if not is_telemetry_opted_out(
            WORKING_DIR,
        ) and not has_telemetry_been_collected(WORKING_DIR):
            collect_and_upload_telemetry(WORKING_DIR)
    except Exception:
        logger.debug(
            "Telemetry collection skipped due to error",
            exc_info=True,
        )

    # --- Multi-agent migration and initialization ---
    logger.info("Checking for legacy config migration...")
    migrate_legacy_workspace_to_default_agent()
    ensure_default_agent_exists()

    # --- Multi-agent manager initialization ---
    logger.info("Initializing MultiAgentManager...")
    multi_agent_manager = MultiAgentManager()

    # Start all configured agents (handled by manager)
    await multi_agent_manager.start_all_configured_agents()

    # --- Model provider manager (non-reloadable, in-memory) ---
    provider_manager = ProviderManager.get_instance()

    # Expose to endpoints - multi-agent manager
    app.state.multi_agent_manager = multi_agent_manager

    # Connect DynamicMultiAgentRunner to MultiAgentManager
    if isinstance(runner, DynamicMultiAgentRunner):
        runner.set_multi_agent_manager(multi_agent_manager)

    # Helper function to get agent instance by ID (async)
    async def _get_agent_by_id(agent_id: str = None):
        """Get agent instance by ID, or active agent if not specified."""
        if agent_id is None:
            config = load_config(get_config_path())
            agent_id = config.agents.active_agent or "default"
        return await multi_agent_manager.get_agent(agent_id)

    app.state.get_agent_by_id = _get_agent_by_id

    # Global managers (shared across all agents)
    app.state.provider_manager = provider_manager

    # Setup approval service with default agent's channel_manager
    default_agent = await multi_agent_manager.get_agent("default")
    if default_agent.channel_manager:
        from .approvals import get_approval_service

        get_approval_service().set_channel_manager(
            default_agent.channel_manager,
        )

    startup_elapsed = time.time() - startup_start_time
    logger.debug(
        f"Application startup completed in {startup_elapsed:.3f} seconds",
    )

    try:
        yield
    finally:
        # Stop multi-agent manager (stops all agents and their components)
        multi_agent_mgr = getattr(app.state, "multi_agent_manager", None)
        if multi_agent_mgr is not None:
            logger.info("Stopping MultiAgentManager...")
            try:
                await multi_agent_mgr.stop_all()
            except Exception as e:
                logger.error(f"Error stopping MultiAgentManager: {e}")

        logger.info("Application shutdown complete")


app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)

# Add agent context middleware for agent-scoped routes
app.add_middleware(AgentContextMiddleware)

app.add_middleware(AuthMiddleware)

# Apply CORS middleware if CORS_ORIGINS is set
if CORS_ORIGINS:
    origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Console static dir: env, or copaw package data (console), or cwd.
_CONSOLE_STATIC_ENV = "COPAW_CONSOLE_STATIC_DIR"


def _resolve_console_static_dir() -> str:
    if os.environ.get(_CONSOLE_STATIC_ENV):
        return os.environ[_CONSOLE_STATIC_ENV]
    # Shipped dist lives in copaw package as static data (not a Python pkg).
    pkg_dir = Path(__file__).resolve().parent.parent
    candidate = pkg_dir / "console"
    if candidate.is_dir() and (candidate / "index.html").exists():
        return str(candidate)
    # the following code can be removed after next release,
    # because the console will be output to copaw's
    # `src/copaw/console/` directory directly by vite.
    cwd = Path(os.getcwd())
    for subdir in ("console/dist", "console_dist"):
        candidate = cwd / subdir
        if candidate.is_dir() and (candidate / "index.html").exists():
            return str(candidate)
    return str(cwd / "console" / "dist")


_CONSOLE_STATIC_DIR = _resolve_console_static_dir()
_CONSOLE_INDEX = (
    Path(_CONSOLE_STATIC_DIR) / "index.html" if _CONSOLE_STATIC_DIR else None
)
logger.info(f"STATIC_DIR: {_CONSOLE_STATIC_DIR}")


@app.get("/")
def read_root():
    if _CONSOLE_INDEX and _CONSOLE_INDEX.exists():
        return FileResponse(_CONSOLE_INDEX)
    return {
        "message": (
            "CoPaw Web Console is not available. "
            "If you installed CoPaw from source code, please run "
            "`npm ci && npm run build` in CoPaw's `console/` "
            "directory, and restart CoPaw to enable the "
            "web console."
        ),
    }


@app.get("/api/version")
def get_version():
    """Return the current CoPaw version."""
    return {"version": __version__}


app.include_router(api_router, prefix="/api")

# Agent-scoped router: /api/agents/{agentId}/chats, etc.
agent_scoped_router = create_agent_scoped_router()
app.include_router(agent_scoped_router, prefix="/api")


app.include_router(
    agent_app.router,
    prefix="/api/agent",
    tags=["agent"],
)

# Voice channel: Twilio-facing endpoints at root level (not under /api/).
# POST /voice/incoming, WS /voice/ws, POST /voice/status-callback
app.include_router(voice_router, tags=["voice"])

# Mount console: root static files (logo.png etc.) then assets, then SPA
# fallback.
if os.path.isdir(_CONSOLE_STATIC_DIR):
    _console_path = Path(_CONSOLE_STATIC_DIR)

    def _serve_console_index():
        if _CONSOLE_INDEX and _CONSOLE_INDEX.exists():
            return FileResponse(_CONSOLE_INDEX)

        raise HTTPException(status_code=404, detail="Not Found")

    @app.get("/logo.png")
    def _console_logo():
        f = _console_path / "logo.png"
        if f.is_file():
            return FileResponse(f, media_type="image/png")
        raise HTTPException(status_code=404, detail="Not Found")

    @app.get("/dark-logo.png")
    def _console_dark_logo():
        f = _console_path / "dark-logo.png"
        if f.is_file():
            return FileResponse(f, media_type="image/png")
        raise HTTPException(status_code=404, detail="Not Found")

    @app.get("/copaw-symbol.svg")
    def _console_icon():
        f = _console_path / "copaw-symbol.svg"
        if f.is_file():
            return FileResponse(f, media_type="image/svg+xml")
        raise HTTPException(status_code=404, detail="Not Found")

    @app.get("/copaw-dark.png")
    def _console_dark_icon():
        f = _console_path / "copaw-dark.png"
        if f.is_file():
            return FileResponse(f, media_type="image/png")
        raise HTTPException(status_code=404, detail="Not Found")

    _assets_dir = _console_path / "assets"
    if _assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(_assets_dir)),
            name="assets",
        )

    @app.get("/console")
    @app.get("/console/")
    @app.get("/console/{full_path:path}")
    def _console_spa_alias(full_path: str = ""):
        _ = full_path
        return _serve_console_index()

    @app.get("/{full_path:path}")
    def _console_spa(full_path: str):
        _ = full_path
        return _serve_console_index()
