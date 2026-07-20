# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
import asyncio
import inspect
import mimetypes
import os
import sys
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..__version__ import __version__
from ..backup._utils.safe_swap import cleanup_startup_restore_artifacts
from ..config import load_config  # pylint: disable=no-name-in-module
from ..config.utils import get_config_path, read_last_api
from ..constant import (
    CORS_ORIGINS,
    DOCS_ENABLED,
    LOG_LEVEL_ENV,
    PROJECT_NAME,
    WORKING_DIR,
)
from ..envs import load_envs_into_environ
from ..local_models.manager import LocalModelManager
from ..providers.provider_manager import ProviderManager
from ..utils.logging import (
    LOG_FILE_PATH,
    add_project_file_handler,
    setup_logger,
)
from ..utils.startup_display import AgentStartupDisplay
from ..utils.system_info import summarize_python_environment
from .auth import (
    AuthMiddleware,
    auto_register_from_env,
    check_proxy_config_sanity,
)
from .migration import (
    ensure_default_agent_exists,
    ensure_qa_agent_exists,
    migrate_legacy_skills_to_skill_pool,
    migrate_legacy_workspace_to_default_agent,
)
from .routers import create_agent_scoped_router
from .routers import router as api_router
from .routers.agent_scoped import AgentContextMiddleware
from .routers.approval import router as approval_router
from .routers.coding_mode import router as coding_mode_router
from .routers.healthz import router as healthz_router
from .routers.loops import router as loops_router
from .routers.tool_calls import router as tool_calls_router
from .routers.voice import voice_router

# Apply log level on load so reload child process gets same level as CLI.
logger = setup_logger(os.environ.get(LOG_LEVEL_ENV, "info"))

# Ensure static assets are served with browser-compatible MIME types across
# platforms (notably Windows may miss .js/.mjs mappings).
mimetypes.init()
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("image/svg+xml", ".svg")

# Load persisted env vars into os.environ at module import time
# so they are available before the lifespan starts.
load_envs_into_environ()


@asynccontextmanager
async def lifespan(  # pylint: disable=too-many-statements,too-many-branches
    app: FastAPI,
):
    startup_start_time = time.time()
    add_project_file_handler(LOG_FILE_PATH)

    # ================================================================
    # Fast synchronous setup (target < 100ms)
    # Everything here must be lightweight so the server starts quickly.
    # ================================================================

    try:
        cleanup_startup_restore_artifacts()
    except Exception as exc:
        message = (
            "QwenPaw startup failed because restore artifact cleanup did not "
            "complete. Another restore or cleanup may still be running, or "
            "a previous restore may need recovery before startup can safely "
            "read restored files."
        )
        logger.error(message, exc_info=True)
        raise RuntimeError(f"{message} Original error: {exc}") from exc

    auto_register_from_env()
    check_proxy_config_sanity()

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

    logger.debug("Checking for legacy config migration...")
    migrate_legacy_workspace_to_default_agent()
    ensure_default_agent_exists()
    migrate_legacy_skills_to_skill_pool()
    ensure_qa_agent_exists()

    # Migrate old conversations from sessions/*.json into each scroll agent's
    # history.db, so chats from before scroll existed stay recallable. This is
    # a one-off backfill, not core startup work: if it fails, we log and keep
    # booting — that agent just won't have its old chats imported (scroll still
    # records new turns normally). The import sits inside the try for the same
    # reason — even a failed import must not block init.
    #
    # Note: being pure backfill, this could later run asynchronously (off the
    # boot path) to speed up startup.
    try:
        from ..agents.context.scroll.sync import sync_all_scroll_agents

        sync_all_scroll_agents()
    except Exception:  # noqa: BLE001 - session sync must never block startup
        logger.warning("session-sync: import/launch failed", exc_info=True)

    # Create core managers (instant — no I/O)
    provider_manager = ProviderManager.get_instance()
    local_model_manager = LocalModelManager.get_instance()

    # --- AppServiceManager + WorkspaceRegistry ---
    app_services = None
    workspace_registry = None
    try:
        from .app_services import AppServiceManager
        from .workspace_registry import WorkspaceRegistry

        app_services = AppServiceManager()
        await app_services.start()
        app.state.app_services = app_services

        workspace_registry = WorkspaceRegistry(
            app_services=app_services,
        )
        app.state.workspace_registry = workspace_registry
        logger.debug("Runtime infrastructure initialized")

        # --- @api_action auto-registration ---
        _api_action_command_specs: list[Any] = []
        try:
            from ..api_action import ManagerRegistry
            from ._api_action_routes import (
                collect_slash_specs_from_api_actions,
                register_http_routes,
            )
            from .crons.manager import CronManager

            manager_registry = ManagerRegistry()

            def _get_default_cron_mgr(app_inst: Any) -> Any:
                mam = getattr(app_inst.state, "multi_agent_manager", None)
                if mam is None:
                    return None
                # pylint: disable-next=protected-access
                ws = mam._workspaces.get("default")
                return getattr(ws, "cron_manager", None) if ws else None

            manager_registry.register(CronManager, _get_default_cron_mgr)
            app.state.manager_registry = manager_registry

            n_routes = register_http_routes(app, manager_registry)
            logger.debug("Auto-registered %d HTTP routes", n_routes)

            _api_action_command_specs.extend(
                collect_slash_specs_from_api_actions(manager_registry),
            )
            logger.debug(
                "Collected %d slash specs from @api_action",
                len(_api_action_command_specs),
            )
        except Exception:
            logger.debug(
                "@api_action auto-registration skipped",
                exc_info=True,
            )

        # --- HITL slash commands ---
        try:
            from .app_services._builtin_tool_commands import (
                build_tool_command_specs,
            )

            _api_action_command_specs.extend(
                build_tool_command_specs(app_services.tool_coordinator),
            )
            logger.debug("HITL tool commands registered")
        except Exception:
            logger.debug(
                "HITL tool command registration skipped",
                exc_info=True,
            )

        # --- Built-in tools ---
        try:
            from ..agents.tools import discover_builtin_tool_funcs

            # pylint: disable-next=protected-access
            workspace_registry._bootstrap_kwargs[
                "builtin_tool_funcs"
            ] = discover_builtin_tool_funcs()
            logger.debug("Built-in tool funcs collected")
        except Exception:
            logger.debug(
                "Built-in tool func collection skipped",
                exc_info=True,
            )

        # --- Built-in slash commands (daemon, control, conversation) ---
        try:
            from ..runtime.builtin_commands import (
                collect_builtin_command_specs,
                get_skill_fallback_handler,
            )

            _api_action_command_specs.extend(collect_builtin_command_specs())
            # pylint: disable-next=protected-access
            workspace_registry._bootstrap_kwargs[
                "builtin_fallback_handler"
            ] = get_skill_fallback_handler()
            logger.debug("Built-in slash commands collected")
        except Exception:
            logger.debug(
                "Built-in slash command collection skipped",
                exc_info=True,
            )

        # --- Built-in lifecycle hooks ---
        try:
            from ..hooks.bootstrap.bootstrap_hook import BootstrapHook
            from ..hooks.cron.cron_hook import (
                CronContextHook,
                CronMemoryIsolateHook,
                CronMemoryRestoreHook,
            )
            from ..hooks.error.error_hook import (
                CancelCleanupHook,
                ErrorNormalizeHook,
            )
            from ..hooks.request_setup.contextvars_hook import (
                ContextVarsSetupHook,
            )
            from ..hooks.request_setup.media_hook import MediaProcessHook
            from ..hooks.session.session_hook import (
                SessionLoadHook,
                SessionSaveHook,
            )
            from ..hooks.skill_env.skill_env_hook import (
                SkillEnvCleanupHook,
                SkillEnvHook,
            )

            # pylint: disable-next=protected-access
            workspace_registry._bootstrap_kwargs["builtin_hook_clses"] = [
                CronContextHook,
                CronMemoryIsolateHook,
                CronMemoryRestoreHook,
                SessionLoadHook,
                SessionSaveHook,
                BootstrapHook,
                SkillEnvHook,
                SkillEnvCleanupHook,
                ContextVarsSetupHook,
                MediaProcessHook,
                ErrorNormalizeHook,
                CancelCleanupHook,
            ]

            try:
                from ..hooks.observability.langfuse_hook import (
                    LangfuseTraceCleanupHook,
                    LangfuseTraceHook,
                )

                # pylint: disable=protected-access
                workspace_registry._bootstrap_kwargs.setdefault(
                    "builtin_hook_clses",
                    [],
                ).extend([LangfuseTraceHook, LangfuseTraceCleanupHook])
            except Exception:
                logger.debug(
                    "Langfuse hooks not available",
                    exc_info=True,
                )

            logger.debug("Built-in lifecycle hooks collected")
        except Exception:
            logger.debug(
                "Built-in lifecycle hook collection skipped",
                exc_info=True,
            )

        # --- Built-in prompt contributors ---
        try:
            from ..runtime.prompt_contributors import _ALL_CONTRIBUTORS

            # pylint: disable-next=protected-access
            workspace_registry._bootstrap_kwargs[
                "builtin_contributor_clses"
            ] = _ALL_CONTRIBUTORS
            logger.debug("Built-in prompt contributors collected")
        except Exception:
            logger.debug(
                "Built-in prompt contributor collection skipped",
                exc_info=True,
            )

        # --- Built-in modes (CodingMode, MissionMode) ---
        try:
            from ..modes.coding import CodingMode
            from ..modes.default import DefaultMode
            from ..modes.goal import GoalMode
            from ..modes.mission import MissionMode

            # pylint: disable-next=protected-access
            workspace_registry._bootstrap_kwargs["builtin_mode_clses"] = [
                DefaultMode,
                CodingMode,
                MissionMode,
                GoalMode,
            ]
            logger.debug("Built-in modes collected")
        except Exception:
            logger.debug(
                "Built-in mode collection skipped",
                exc_info=True,
            )

        if _api_action_command_specs:
            # pylint: disable-next=protected-access
            workspace_registry._bootstrap_kwargs[
                "builtin_command_specs"
            ] = _api_action_command_specs

    except Exception:
        logger.debug(
            "Runtime infrastructure init skipped",
            exc_info=True,
        )

    # Start token usage manager background tasks
    logger.debug("Starting TokenUsageManager background tasks...")
    from ..token_usage import get_token_usage_manager

    token_usage_manager = get_token_usage_manager()
    token_usage_manager.start(flush_interval=10)

    # Expose to endpoints (must be set before first request arrives).
    # WorkspaceRegistry IS-A MultiAgentManager — backward compat for
    # routers / agent_context that read app.state.multi_agent_manager.
    app.state.multi_agent_manager = workspace_registry
    app.state.provider_manager = provider_manager
    app.state.local_model_manager = local_model_manager
    app.state.plugin_loader = None
    app.state.plugin_registry = None

    async def _get_agent_by_id(agent_id: str = None):
        """Get agent instance by ID, or active agent if not specified."""
        if agent_id is None:
            config = load_config(get_config_path())
            agent_id = config.agents.active_agent or "default"
        return await workspace_registry.get_agent(agent_id)

    app.state.get_agent_by_id = _get_agent_by_id

    app.state.startup_ready = asyncio.Event()
    app.state.startup_time = startup_start_time

    fast_elapsed = time.time() - startup_start_time
    logger.info(
        f"Server ready in {fast_elapsed:.3f}s (agents loading in background)",
    )

    # ================================================================
    # Background heavy initialization
    # Agents, plugins, and services start in a background task so the
    # server can begin accepting HTTP requests immediately.
    # First API requests that need an agent will await its readiness
    # via MultiAgentManager.get_agent() lazy-loading / event wait.
    # ================================================================

    startup_display = AgentStartupDisplay(read_last_api()).start()

    async def _background_startup():  # pylint: disable=too-many-statements
        try:
            # ---- Plugin System (phase 1: channel plugins) ----
            # Load channel-type plugins *before* agents start so that
            # ChannelManager discovers them via get_channel_registry()
            # on first creation — no reload needed afterwards.
            logger.debug("Initializing plugin system...")

            from ..config.utils import get_plugins_dir
            from ..plugins.loader import PluginLoader
            from ..plugins.runtime import RuntimeHelpers

            plugin_dirs = [
                get_plugins_dir(),
            ]

            plugin_loader = PluginLoader(plugin_dirs)

            plugin_loader.registry.set_plugin_http_app(app)

            config = load_config(get_config_path())
            plugin_configs = (
                config.plugins if hasattr(config, "plugins") else {}
            )
            logger.debug(
                f"Loading plugins with {len(plugin_configs)} config(s)",
            )

            # Phase 1: load channel plugins before agents start
            await plugin_loader.load_all_plugins(
                configs=plugin_configs,
                types=["channel"],
            )
            logger.debug("Phase 1: channel plugins loaded")

            def _mark_core_agents_ready(_results: dict[str, bool]) -> None:
                """Publish readiness after the core agent phase."""
                core_elapsed = time.time() - startup_start_time
                startup_display.mark_core_ready(core_elapsed)
                app.state.startup_ready.set()

            await workspace_registry.start_all_configured_agents(
                on_core_ready=_mark_core_agents_ready,
                startup_display=startup_display,
            )
            if app.state.startup_ready.is_set():
                startup_display.mark_finalizing()

            provider_manager.start_local_model_resume(local_model_manager)

            # Phase 2: load remaining plugins (channel plugins already
            # loaded — load_plugin skips them automatically)
            loaded_plugins = await plugin_loader.load_all_plugins(
                configs=plugin_configs,
            )
            logger.debug(f"Loaded {len(loaded_plugins)} plugin(s)")

            runtime_helpers = RuntimeHelpers(
                provider_manager=provider_manager,
            )
            plugin_loader.registry.set_runtime_helpers(runtime_helpers)
            plugin_loader.registry.set_workspace_manager(
                workspace_registry,
            )

            for (
                provider_id,
                provider_reg,
            ) in plugin_loader.registry.get_all_providers().items():
                provider_manager.register_plugin_provider(
                    provider_id=provider_id,
                    provider_class=provider_reg.provider_class,
                    label=provider_reg.label,
                    base_url=provider_reg.base_url,
                    metadata=provider_reg.metadata,
                )
                logger.debug(
                    f"Registered plugin provider: {provider_id}",
                )

            app.state.plugin_loader = plugin_loader
            app.state.plugin_registry = plugin_loader.registry

            # ---- Plugin Control Commands ----
            logger.debug("Registering plugin control commands...")
            from qwenpaw.runtime.commands.control import register_command

            from ..app.channels.command_registry import CommandRegistry

            command_registry = CommandRegistry()

            control_commands = plugin_loader.registry.get_control_commands()
            for cmd_reg in control_commands:
                try:
                    register_command(cmd_reg.handler)

                    command_registry.register_command(
                        f"/{cmd_reg.handler.command_name}",
                        priority_level=cmd_reg.priority_level,
                    )

                    logger.debug(
                        f"Registered plugin control command: "
                        f"/{cmd_reg.handler.command_name} "
                        f"from plugin '{cmd_reg.plugin_id}' (priority"
                        f"={cmd_reg.priority_level})",
                    )
                except Exception as e:
                    logger.error(
                        f"✗ Failed to register control command "
                        f"'{cmd_reg.handler.command_name}' "
                        f"from plugin '{cmd_reg.plugin_id}': {e}",
                        exc_info=True,
                    )

            # ---- Startup Hooks ----
            logger.debug("Executing plugin startup hooks...")
            startup_hooks = plugin_loader.registry.get_startup_hooks()
            for hook in startup_hooks:
                try:
                    logger.debug(
                        f"Executing startup hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}' "
                        f"(priority={hook.priority})",
                    )

                    result = hook.callback()
                    if inspect.iscoroutine(
                        result,
                    ) or inspect.isawaitable(result):
                        await result

                    logger.debug(
                        f"Completed startup hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}'",
                    )
                except Exception as e:
                    logger.error(
                        f"✗ Failed to execute startup hook "
                        f"'{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}': {e}",
                        exc_info=True,
                    )

            # ---- Approval Service ----
            try:
                default_agent = await workspace_registry.get_agent(
                    "default",
                )
                if default_agent.channel_manager:
                    from .approvals import get_approval_service

                    get_approval_service().set_channel_manager(
                        default_agent.channel_manager,
                    )
            except Exception as e:
                logger.warning(f"Approval service setup skipped: {e}")

            # ---- Skill pool auto-update sync ----
            try:
                from ..agents.skill_system import run_pool_auto_update_sync
                from .routers.skills import post_auto_update_inbox

                au_result = await asyncio.to_thread(run_pool_auto_update_sync)
                await post_auto_update_inbox(au_result)
            except Exception:
                logger.warning(
                    "Skill pool auto-update sync skipped on startup",
                    exc_info=True,
                )

            startup_elapsed = time.time() - startup_start_time
            logger.info(
                "Background startup completed in "
                f"{startup_elapsed:.3f} seconds",
            )
            if app.state.startup_ready.is_set():
                startup_display.complete(startup_elapsed)

        except Exception:
            logger.error(
                "Background startup encountered an error",
                exc_info=True,
            )

    _bg_task = asyncio.create_task(_background_startup())

    try:
        yield
    finally:
        # Cancel background startup if still in progress
        if not _bg_task.done():
            _bg_task.cancel()
            with suppress(asyncio.CancelledError):
                await _bg_task

        # ==================== Execute Shutdown Hooks ====================
        plugin_registry = getattr(app.state, "plugin_registry", None)
        if plugin_registry is not None:
            logger.info("Executing plugin shutdown hooks...")
            shutdown_hooks = plugin_registry.get_shutdown_hooks()
            for hook in shutdown_hooks:
                try:
                    logger.info(
                        f"Executing shutdown hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}' (priority"
                        f"={hook.priority})",
                    )

                    result = hook.callback()
                    if inspect.iscoroutine(result) or inspect.isawaitable(
                        result,
                    ):
                        await result

                    logger.info(
                        f"✓ Completed shutdown hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}'",
                    )
                except Exception as e:
                    logger.error(
                        f"✗ Failed to execute shutdown hook "
                        f"'{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}': {e}",
                        exc_info=True,
                    )

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
                    local_model_mgr.shutdown_server_sync()

        # Stop AppServiceManager (ToolCoordinator shutdown, etc.)
        _app_svc = getattr(app.state, "app_services", None)
        if _app_svc is not None:
            try:
                await _app_svc.stop()
            except Exception as e:
                logger.error(f"Error stopping AppServiceManager: {e}")

        # Stop multi-agent manager (stops all agents and their components)
        multi_agent_mgr = getattr(app.state, "multi_agent_manager", None)
        if multi_agent_mgr is not None:
            logger.info("Stopping MultiAgentManager...")
            try:
                await multi_agent_mgr.stop_all()
            except Exception as e:
                logger.error(f"Error stopping MultiAgentManager: {e}")

        # These three cleanup tasks are independent; run in parallel.
        from ..agents.skill_system.hub import aclose_hub_client
        from ..agents.tools.browser_control import stop_all_browsers

        async def _stop_token_usage():
            logger.info("Stopping TokenUsageManager...")
            try:
                await token_usage_manager.stop()
            except Exception as e:
                logger.error(
                    f"Error stopping TokenUsageManager: {e}",
                )

        async def _stop_browsers():
            try:
                await stop_all_browsers()
            except Exception as e:
                logger.error(
                    f"Error stopping browsers: {e}",
                )

        async def _close_hub():
            try:
                await aclose_hub_client()
            except Exception as e:
                logger.error(
                    f"Error closing skills hub HTTP client: {e}",
                )

        await asyncio.gather(
            _stop_token_usage(),
            _stop_browsers(),
            _close_hub(),
        )

        # Destroy Windows sandbox artifacts (user accounts, profiles, ACLs,
        # firewall rules). Runs in a thread because it invokes subprocess
        # calls (takeown, icacls, net user, powershell) that may block.
        if sys.platform == "win32":
            try:
                from ..sandbox import shutdown_all_sandboxes

                logger.info("Cleaning up Windows sandbox artifacts...")
                await asyncio.to_thread(shutdown_all_sandboxes)
                logger.info("Windows sandbox cleanup complete.")
            except Exception as e:
                logger.error(f"Error during sandbox cleanup: {e}")

        logger.info("Application shutdown complete")
        startup_display.stop()


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


_CONSOLE_STATIC_ENV = "QWENPAW_CONSOLE_STATIC_DIR"


def _resolve_console_static_dir() -> str:
    from ..constant import EnvVarLoader

    static_dir = EnvVarLoader.get_str(_CONSOLE_STATIC_ENV)
    if static_dir:
        return static_dir
    # Shipped dist lives in the package as static data
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

# The SPA entry (index.html) must never be cached: it references content-hashed
# JS/CSS bundles, so a stale cached index.html would keep pointing the WebView
# at old asset hashes after a rebuild (see desktop dev cache issue). The hashed
# assets under /assets remain safely cacheable because their name changes with
# their content.
_INDEX_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    # Pragma/Expires cover legacy proxies and older WebView caches that do not
    # honor Cache-Control on their own.
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/")
def read_root():
    if _CONSOLE_INDEX and _CONSOLE_INDEX.exists():
        return FileResponse(_CONSOLE_INDEX, headers=_INDEX_NO_CACHE_HEADERS)
    return {
        "message": (
            f"{PROJECT_NAME} web console is not available. "
            "If you installed the project from source code, please run "
            "`npm ci && npm run build` in the `console/` "
            f"directory, and restart {PROJECT_NAME} to enable the "
            "web console."
        ),
    }


@app.get("/api/version")
def get_version():
    """Return the current application version (public-safe payload)."""
    return {
        "version": __version__,
    }


@app.get("/api/doctor/runtime")
def get_doctor_runtime():
    """Return server runtime diagnostics for authenticated troubleshooting."""
    return {
        "python_executable": sys.executable,
        "python_environment": summarize_python_environment(),
    }


app.include_router(api_router, prefix="/api")

app.include_router(healthz_router, prefix="/api")

app.include_router(tool_calls_router, prefix="/api")

# Approval router: /api/approval/approve, /api/approval/deny, etc.
app.include_router(approval_router, prefix="/api")

# Coding Mode router: /api/coding-mode
app.include_router(coding_mode_router, prefix="/api")

# Loops router: /api/loops
app.include_router(loops_router, prefix="/api")

# Agent-scoped router: /api/agents/{agentId}/chats, etc.
agent_scoped_router = create_agent_scoped_router()
app.include_router(agent_scoped_router, prefix="/api")

# Voice channel: Twilio-facing endpoints at root level (not under /api/).
# POST /voice/incoming, WS /voice/ws, POST /voice/status-callback
app.include_router(voice_router, tags=["voice"])


# Console static files and SPA fallback
# Register these AFTER API routes to ensure proper routing priority
if os.path.isdir(_CONSOLE_STATIC_DIR):
    _console_path = Path(_CONSOLE_STATIC_DIR)

    def _serve_console_index():
        if _CONSOLE_INDEX and _CONSOLE_INDEX.exists():
            return FileResponse(
                _CONSOLE_INDEX,
                headers=_INDEX_NO_CACHE_HEADERS,
            )

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

    # SPA fallback: catch-all route for frontend routing
    # Must be registered AFTER all API routes to avoid conflicts
    @app.get(
        "/{full_path:path}",
        name="qwenpaw_console_spa_catchall",
    )
    def _console_spa(full_path: str):
        # Prevent catching common system/special paths
        if full_path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not Found")
        # Skip API routes (should already be matched due to registration order)
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="Not Found")

        # Serve static files from the console build directory (e.g. logo SVGs,
        # favicons, images placed in public/).  Only serve regular files whose
        # path does not escape the console directory.
        if full_path and ".." not in full_path:
            # Security: Reject absolute paths to prevent path traversal bypass
            if not Path(full_path).is_absolute():
                static_file = _console_path / full_path
                if static_file.is_file():
                    return FileResponse(static_file)

        return _serve_console_index()
