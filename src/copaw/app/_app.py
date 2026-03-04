# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from agentscope_runtime.engine.app import AgentApp

from .runner import AgentRunner
from ..config import (  # pylint: disable=no-name-in-module
    load_config,
    update_last_dispatch,
    ConfigWatcher,
)
from ..config.utils import get_jobs_path, get_chats_path, get_config_path
from ..constant import DOCS_ENABLED, LOG_LEVEL_ENV, CORS_ORIGINS, WORKING_DIR
from ..__version__ import __version__
from ..utils.logging import setup_logger, add_copaw_file_handler
from .channels import ChannelManager  # pylint: disable=no-name-in-module
from .channels.utils import make_process_from_runner
from .mcp import MCPClientManager, MCPConfigWatcher  # MCP hot-reload support
from .runner.repo.json_repo import JsonChatRepository
from .crons.repo.json_repo import JsonJobRepository
from .crons.manager import CronManager
from .runner.manager import ChatManager
from .routers import router as api_router
from ..envs import load_envs_into_environ

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

runner = AgentRunner()

agent_app = AgentApp(
    app_name="Friday",
    app_description="A helpful assistant",
    runner=runner,
)


@asynccontextmanager
async def lifespan(app: FastAPI):  # pylint: disable=too-many-statements
    add_copaw_file_handler(WORKING_DIR / "copaw.log")
    await runner.start()

    # --- MCP client manager init (independent module, hot-reloadable) ---
    config = load_config()
    mcp_manager = MCPClientManager()
    if hasattr(config, "mcp"):
        try:
            await mcp_manager.init_from_config(config.mcp)
            runner.set_mcp_manager(mcp_manager)
            logger.debug("MCP client manager initialized")
        except Exception:
            logger.exception("Failed to initialize MCP manager")

    # --- channel connector init/start (from config.json) ---
    channel_manager = ChannelManager.from_config(
        process=make_process_from_runner(runner),
        config=config,
        on_last_dispatch=update_last_dispatch,
    )
    await channel_manager.start_all()

    # --- cron init/start ---
    repo = JsonJobRepository(get_jobs_path())
    cron_manager = CronManager(
        repo=repo,
        runner=runner,
        channel_manager=channel_manager,
        timezone="UTC",
    )
    await cron_manager.start()

    # --- chat manager init and connect to runner.session ---
    chat_repo = JsonChatRepository(get_chats_path())
    chat_manager = ChatManager(
        repo=chat_repo,
    )

    runner.set_chat_manager(chat_manager)

    # --- config file watcher (channels + heartbeat hot-reload on change) ---
    config_watcher = ConfigWatcher(
        channel_manager=channel_manager,
        cron_manager=cron_manager,
    )
    await config_watcher.start()

    # --- MCP config watcher (auto-reload MCP clients on change) ---
    mcp_watcher = None
    if hasattr(config, "mcp"):
        try:
            mcp_watcher = MCPConfigWatcher(
                mcp_manager=mcp_manager,
                config_loader=load_config,
                config_path=get_config_path(),
            )
            await mcp_watcher.start()
            logger.debug("MCP config watcher started")
        except Exception:
            logger.exception("Failed to start MCP watcher")

    # expose to endpoints
    app.state.runner = runner
    app.state.channel_manager = channel_manager
    app.state.cron_manager = cron_manager
    app.state.chat_manager = chat_manager
    app.state.config_watcher = config_watcher
    app.state.mcp_manager = mcp_manager
    app.state.mcp_watcher = mcp_watcher

    async def _restart_services() -> None:
        """Stop all managers, then rebuild from config (no exit)."""
        # pylint: disable=too-many-statements
        # Use current refs from app.state so repeated restarts work
        cfg_watcher = app.state.config_watcher
        mcp_w = getattr(app.state, "mcp_watcher", None)
        cron_mgr = app.state.cron_manager
        ch_mgr = app.state.channel_manager
        mcp_mgr = app.state.mcp_manager

        # Stop in same order as lifespan shutdown
        try:
            await cfg_watcher.stop()
        except Exception:
            logger.exception("restart_services: config_watcher.stop failed")
        if mcp_w is not None:
            try:
                await mcp_w.stop()
            except Exception:
                logger.exception("restart_services: mcp_watcher.stop failed")
        try:
            await cron_mgr.stop()
        except Exception:
            logger.exception("restart_services: cron_manager.stop failed")
        try:
            await ch_mgr.stop_all()
        except Exception:
            logger.exception(
                "restart_services: channel_manager.stop_all failed",
            )
        if mcp_mgr is not None:
            try:
                await mcp_mgr.close_all()
            except Exception:
                logger.exception(
                    "restart_services: mcp_manager.close_all failed",
                )

        # Reload config from disk and rebuild managers
        try:
            config = load_config(get_config_path())
        except Exception:
            logger.exception("restart_services: load_config failed")
            return

        # New MCP manager
        new_mcp_manager = MCPClientManager()
        if hasattr(config, "mcp"):
            try:
                await new_mcp_manager.init_from_config(config.mcp)
                runner.set_mcp_manager(new_mcp_manager)
            except Exception:
                logger.exception(
                    "restart_services: mcp init_from_config failed",
                )

        # New channel manager (full rebuild)
        new_channel_manager = ChannelManager.from_config(
            process=make_process_from_runner(runner),
            config=config,
            on_last_dispatch=update_last_dispatch,
        )
        await new_channel_manager.start_all()

        # New cron manager (same repo, new instance)
        job_repo = JsonJobRepository(get_jobs_path())
        new_cron_manager = CronManager(
            repo=job_repo,
            runner=runner,
            channel_manager=new_channel_manager,
            timezone="UTC",
        )
        await new_cron_manager.start()

        # New config watcher
        new_config_watcher = ConfigWatcher(
            channel_manager=new_channel_manager,
            cron_manager=new_cron_manager,
        )
        await new_config_watcher.start()

        # New MCP watcher if config has mcp
        new_mcp_watcher = None
        if hasattr(config, "mcp"):
            try:
                new_mcp_watcher = MCPConfigWatcher(
                    mcp_manager=new_mcp_manager,
                    config_loader=load_config,
                    config_path=get_config_path(),
                )
                await new_mcp_watcher.start()
            except Exception:
                logger.exception("restart_services: mcp_watcher.start failed")

        # Replace app.state so next request and next restart use new refs
        app.state.channel_manager = new_channel_manager
        app.state.cron_manager = new_cron_manager
        app.state.config_watcher = new_config_watcher
        app.state.mcp_manager = new_mcp_manager
        app.state.mcp_watcher = new_mcp_watcher
        logger.info("Daemon restart (in-process) completed: managers rebuilt")

    setattr(runner, "_restart_callback", _restart_services)

    try:
        yield
    finally:
        # stop order: watchers -> cron -> channels -> mcp -> runner
        try:
            await config_watcher.stop()
        except Exception:
            pass
        if mcp_watcher:
            try:
                await mcp_watcher.stop()
            except Exception:
                pass
        try:
            await cron_manager.stop()
        finally:
            await channel_manager.stop_all()
            if mcp_manager:
                try:
                    await mcp_manager.close_all()
                except Exception:
                    pass
            await runner.stop()


app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)

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
    return {"message": "Hello World"}


@app.get("/api/version")
def get_version():
    """Return the current CoPaw version."""
    return {"version": __version__}


app.include_router(api_router, prefix="/api")

app.include_router(
    agent_app.router,
    prefix="/api/agent",
    tags=["agent"],
)

# Mount console: root static files (logo.png etc.) then assets, then SPA
# fallback.
if os.path.isdir(_CONSOLE_STATIC_DIR):
    _console_path = Path(_CONSOLE_STATIC_DIR)

    @app.get("/logo.png")
    def _console_logo():
        f = _console_path / "logo.png"
        if f.is_file():
            return FileResponse(f, media_type="image/png")

        raise HTTPException(status_code=404, detail="Not Found")

    @app.get("/copaw-symbol.svg")
    def _console_icon():
        f = _console_path / "copaw-symbol.svg"
        if f.is_file():
            return FileResponse(f, media_type="image/svg+xml")

        raise HTTPException(status_code=404, detail="Not Found")

    _assets_dir = _console_path / "assets"
    if _assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(_assets_dir)),
            name="assets",
        )

    @app.get("/{full_path:path}")
    def _console_spa(full_path: str):
        if _CONSOLE_INDEX and _CONSOLE_INDEX.exists():
            return FileResponse(_CONSOLE_INDEX)

        raise HTTPException(status_code=404, detail="Not Found")
