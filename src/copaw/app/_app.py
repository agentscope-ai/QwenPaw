# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
import mimetypes
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
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
from ..local_models.manager import LocalModelManager
from .multi_agent_manager import MultiAgentManager
from .migration import (
    migrate_legacy_workspace_to_default_agent,
    migrate_legacy_skills_to_skill_pool,
    ensure_default_agent_exists,
    ensure_qa_agent_exists,
)
from .channels.registry import register_custom_channel_routes

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
                "Got workspace: %s, runner: %s",
                workspace.agent_id,
                workspace.runner,
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
    app_description="A helpful assistant with background task support",
    runner=runner,
    enable_stream_task=True,
    stream_task_queue="stream_query",
    stream_task_timeout=300,
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
    migrate_legacy_skills_to_skill_pool()
    ensure_qa_agent_exists()

    provider_manager = ProviderManager.get_instance()
    try:
        base_url = os.environ.get("COPAW_DEFAULT_LLM_BASE_URL", "").strip()
        model_id = os.environ.get("COPAW_DEFAULT_LLM_MODEL", "").strip()
        if base_url and model_id:
            from ..config.config import load_agent_config, save_agent_config
            from ..providers.models import ModelSlotConfig

            config = load_config(get_config_path())
            target_agent_id = config.agents.active_agent or "default"
            agent_config = load_agent_config(target_agent_id)
            provider_id = (
                os.environ.get(
                    "COPAW_DEFAULT_LLM_PROVIDER_ID",
                    "copaw-env",
                ).strip()
                or "copaw-env"
            )
            if provider_id in provider_manager.builtin_providers:
                provider_id = f"{provider_id}-env"
            agent_config.active_model = ModelSlotConfig(
                provider_id=provider_id,
                model=model_id,
            )
            save_agent_config(target_agent_id, agent_config)
            logger.info(
                "Applied agent LLM from env: %s (%s / %s)",
                target_agent_id,
                provider_id,
                model_id,
            )
    except Exception as e:
        logger.warning(
            "Failed to apply env LLM to active agent: %s",
            e,
        )

    # --- Multi-agent manager initialization ---
    logger.info("Initializing MultiAgentManager...")
    multi_agent_manager = MultiAgentManager()

    # Start all configured agents (handled by manager)
    await multi_agent_manager.start_all_configured_agents()

    # --- Local model manager initialization ---
    local_model_manager = LocalModelManager.get_instance()

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
    app.state.local_model_manager = local_model_manager

    provider_manager.start_local_model_resume(local_model_manager)

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
        local_model_mgr = getattr(app.state, "local_model_manager", None)
        if local_model_mgr is not None:
            logger.info("Stopping local model server...")
            try:
                await local_model_mgr.shutdown_server()
            except Exception as exc:
                logger.error(
                    "Error shutting down local model server gracefully: %s",
                    exc,
                )
                with suppress(OSError, RuntimeError, ValueError):
                    local_model_mgr.force_shutdown_server()

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
        expose_headers=["Content-Disposition"],
    )


# Console static dir: env, or copaw package data (console), or cwd.
_CONSOLE_STATIC_ENV = "COPAW_CONSOLE_STATIC_DIR"


def _resolve_console_static_dir() -> str:
    if os.environ.get(_CONSOLE_STATIC_ENV):
        return os.environ[_CONSOLE_STATIC_ENV]
    # Shipped dist lives in copaw package as static data
    pkg_dir = Path(__file__).resolve().parent.parent
    candidate = pkg_dir / "console"
    if candidate.is_dir() and (candidate / "index.html").exists():
        return str(candidate)

    # Fallback to repo data
    repo_dir = pkg_dir.parent.parent
    candidate = repo_dir / "console" / "dist"
    if candidate.is_dir() and (candidate / "index.html").exists():
        return str(candidate)

    # Fallback to cwd data
    cwd = Path(os.getcwd())
    for subdir in ("console/dist", "console_dist"):
        candidate = cwd / subdir
        if candidate.is_dir() and (candidate / "index.html").exists():
            return str(candidate)

    fallback = cwd / "console" / "dist"
    logger.warning(
        f"Console static directory not found. Falling back to '{fallback}'.",
    )
    return str(fallback)


_CONSOLE_STATIC_DIR = _resolve_console_static_dir()
_CONSOLE_INDEX = (
    Path(_CONSOLE_STATIC_DIR) / "index.html" if _CONSOLE_STATIC_DIR else None
)
logger.info(f"STATIC_DIR: {_CONSOLE_STATIC_DIR}")

_BASE_PATH_ENV = "COPAW_BASE_PATH"


def _normalize_base_path(raw: str) -> str:
    base_path = (raw or "").strip()
    if not base_path:
        return ""
    if not base_path.startswith("/"):
        base_path = f"/{base_path}"
    base_path = base_path.rstrip("/")
    if base_path == "/":
        return ""
    return base_path


COPAW_BASE_PATH = _normalize_base_path(os.environ.get(_BASE_PATH_ENV, ""))


def _prefixed(path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    if not COPAW_BASE_PATH:
        return path
    return f"{COPAW_BASE_PATH}{path}"


API_PREFIX = _prefixed("/api")


def _rewrite_console_index(html: str, base_path: str) -> str:
    if not base_path:
        return html

    injected = (
        "<script>" f"window.__COPAW_BASE_PATH__ = {base_path!r};" "</script>"
    )
    if "</head>" in html:
        html = html.replace("</head>", f"{injected}</head>", 1)
    else:
        html = f"{injected}{html}"

    html = html.replace('href="/assets/', f'href="{base_path}/assets/')
    html = html.replace('src="/assets/', f'src="{base_path}/assets/')
    html = html.replace(
        'href="/copaw-symbol.svg',
        f'href="{base_path}/copaw-symbol.svg',
    )
    html = html.replace(
        'src="/copaw-symbol.svg',
        f'src="{base_path}/copaw-symbol.svg',
    )
    html = html.replace('href="/logo.png', f'href="{base_path}/logo.png')
    html = html.replace('src="/logo.png', f'src="{base_path}/logo.png')
    html = html.replace(
        'href="/dark-logo.png',
        f'href="{base_path}/dark-logo.png',
    )
    html = html.replace(
        'src="/dark-logo.png',
        f'src="{base_path}/dark-logo.png',
    )
    html = html.replace(
        'href="/copaw-dark.png',
        f'href="{base_path}/copaw-dark.png',
    )
    html = html.replace(
        'src="/copaw-dark.png',
        f'src="{base_path}/copaw-dark.png',
    )
    return html


def _serve_console_index():
    if not (_CONSOLE_INDEX and _CONSOLE_INDEX.exists()):
        raise HTTPException(status_code=404, detail="Not Found")
    if not COPAW_BASE_PATH:
        return FileResponse(_CONSOLE_INDEX)
    html = _CONSOLE_INDEX.read_text(encoding="utf-8")
    return HTMLResponse(_rewrite_console_index(html, COPAW_BASE_PATH))


@app.get("/")
def read_root():
    if COPAW_BASE_PATH:
        return RedirectResponse(url=f"{COPAW_BASE_PATH}/")
    if _CONSOLE_INDEX and _CONSOLE_INDEX.exists():
        return _serve_console_index()
    return {
        "message": (
            "CoPaw Web Console is not available. "
            "If you installed CoPaw from source code, please run "
            "`npm ci && npm run build` in CoPaw's `console/` "
            "directory, and restart CoPaw to enable the "
            "web console."
        ),
    }


@app.get(f"{API_PREFIX}/version")
def get_version():
    """Return the current CoPaw version."""
    return {"version": __version__}


app.include_router(api_router, prefix=API_PREFIX)

# Agent-scoped router: /api/agents/{agentId}/chats, etc.
agent_scoped_router = create_agent_scoped_router()
app.include_router(agent_scoped_router, prefix=API_PREFIX)


app.include_router(
    agent_app.router,
    prefix=f"{API_PREFIX}/agent",
    tags=["agent"],
)

# Voice channel: Twilio-facing endpoints at root level (not under /api/).
# POST /voice/incoming, WS /voice/ws, POST /voice/status-callback
app.include_router(voice_router, tags=["voice"])

# Custom channel routes (before SPA catch-all to ensure route priority)
register_custom_channel_routes(app)

# Console static files and SPA fallback
# Register these AFTER API routes to ensure proper routing priority
if os.path.isdir(_CONSOLE_STATIC_DIR):
    _console_path = Path(_CONSOLE_STATIC_DIR)

    @app.get(_prefixed("/logo.png"))
    def _console_logo():
        f = _console_path / "logo.png"
        if f.is_file():
            return FileResponse(f, media_type="image/png")
        raise HTTPException(status_code=404, detail="Not Found")

    @app.get(_prefixed("/dark-logo.png"))
    def _console_dark_logo():
        f = _console_path / "dark-logo.png"
        if f.is_file():
            return FileResponse(f, media_type="image/png")
        raise HTTPException(status_code=404, detail="Not Found")

    @app.get(_prefixed("/copaw-symbol.svg"))
    def _console_icon():
        f = _console_path / "copaw-symbol.svg"
        if f.is_file():
            return FileResponse(f, media_type="image/svg+xml")
        raise HTTPException(status_code=404, detail="Not Found")

    @app.get(_prefixed("/copaw-dark.png"))
    def _console_dark_icon():
        f = _console_path / "copaw-dark.png"
        if f.is_file():
            return FileResponse(f, media_type="image/png")
        raise HTTPException(status_code=404, detail="Not Found")

    _assets_dir = _console_path / "assets"
    if _assets_dir.is_dir():
        app.mount(
            _prefixed("/assets"),
            StaticFiles(directory=str(_assets_dir)),
            name="assets",
        )

    @app.get(_prefixed("/console"))
    @app.get(_prefixed("/console/"))
    @app.get(_prefixed("/console/{full_path:path}"))
    def _console_spa_alias(full_path: str = ""):
        _ = full_path
        return _serve_console_index()

    # SPA fallback: catch-all route for frontend routing
    # Must be registered AFTER all API routes to avoid conflicts
    @app.get("/{full_path:path}")
    def _console_spa(full_path: str):
        # Prevent catching common system/special paths
        if full_path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not Found")
        # Skip API routes (should already be matched due to registration order)
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="Not Found")
        if COPAW_BASE_PATH:
            base = COPAW_BASE_PATH.lstrip("/")
            if full_path == base or full_path.startswith(f"{base}/api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            if full_path.startswith(f"{base}/assets/"):
                raise HTTPException(status_code=404, detail="Not Found")
        return _serve_console_index()


if COPAW_BASE_PATH:

    @app.api_route(COPAW_BASE_PATH, methods=["GET", "HEAD"])
    def _base_prefix_redirect():
        return RedirectResponse(url=f"{COPAW_BASE_PATH}/")
