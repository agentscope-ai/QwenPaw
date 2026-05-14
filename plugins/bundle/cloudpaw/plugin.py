# -*- coding: utf-8 -*-
"""CloudPaw Plugin for QwenPaw.

Provides Alibaba Cloud deployment orchestration capabilities:
- Built-in agents (Orchestration + IaC Code + Executor + Verifier)
- Custom skills (alicloud_cli, terraform, etc.)
- Custom tools (proposal_choice, manage_prd)
- API router (interaction)
- IaC Code ACP integration (iac-code agent via ACP protocol)

Uses the plugin startup hook to inject all components into the main system.
See README.md for detailed implementation notes.
"""

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill installation
# ---------------------------------------------------------------------------

def _install_plugin_skills() -> None:
    """Copy plugin skills into the shared skill pool."""
    from .constants import PLUGIN_DIR, _PLUGIN_SKILLS

    try:
        from qwenpaw.agents.skill_system import (
            get_skill_pool_dir,
            ensure_skill_pool_initialized,
        )
    except ImportError:
        logger.error("Cannot import skill_system; skill installation skipped")
        return

    try:
        ensure_skill_pool_initialized()
    except Exception as exc:
        logger.warning("Skill pool init failed: %s", exc)

    pool_dir = get_skill_pool_dir()
    skills_src = PLUGIN_DIR / "skills"

    for skill_name in _PLUGIN_SKILLS:
        src = skills_src / skill_name
        dst = pool_dir / skill_name
        if not src.exists():
            logger.warning("Plugin skill source missing: %s", src)
            continue
        if dst.exists():
            logger.debug("Skill %s already in pool, updating...", skill_name)
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        logger.info("Installed plugin skill to pool: %s", skill_name)

    _update_pool_manifest(pool_dir)


def _update_pool_manifest(pool_dir: Path) -> None:
    """Update skill.json manifest to include newly installed skills."""
    from .constants import _PLUGIN_SKILLS

    manifest_path = pool_dir / "skill.json"
    try:
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            manifest = {"skills": {}, "builtin_skill_names": []}

        skills = manifest.setdefault("skills", {})
        for skill_name in _PLUGIN_SKILLS:
            skill_dir = pool_dir / skill_name
            if not skill_dir.exists():
                continue
            if skill_name not in skills:
                skills[skill_name] = {
                    "source": "plugin:cloudpaw",
                    "protected": False,
                }

        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to update pool manifest: %s", exc)


# ---------------------------------------------------------------------------
# Default environment variable provisioning
# ---------------------------------------------------------------------------

_DEFAULT_ENV_KEYS = (
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    "ALIBABA_CLOUD_REGION_ID",
)

_DEFAULT_ENV_VALUES: dict[str, str] = {
    "ALIBABA_CLOUD_REGION_ID": "cn-hangzhou",
}


def _ensure_default_env_vars() -> None:
    """Ensure required env var keys always appear in the QwenPaw console.

    For each key in ``_DEFAULT_ENV_KEYS``:
    - If already in envs.json → keep as-is (user may have edited it).
    - If absent from envs.json but present in ``os.environ`` → copy the
      system value into envs.json so it is visible in the console.
    - If absent from both → create a blank placeholder.
    """
    try:
        from qwenpaw.envs import load_envs, save_envs
    except ImportError:
        logger.warning("Cannot import qwenpaw.envs; env provisioning skipped")
        return

    envs = load_envs()
    changed = False
    for key in _DEFAULT_ENV_KEYS:
        if key not in envs:
            fallback = _DEFAULT_ENV_VALUES.get(key, "")
            envs[key] = os.environ.get(key, fallback)
            changed = True
    if changed:
        save_envs(envs)
        logger.info(
            "Provisioned default env keys into envs.json: %s",
            [k for k in _DEFAULT_ENV_KEYS if k in envs],
        )


# ---------------------------------------------------------------------------
# A2A client manager initialization
# ---------------------------------------------------------------------------

def _init_a2a_manager() -> None:
    """Initialize the A2A client manager singleton.

    This ensures the manager is ready when a2a_discover / a2a_call
    tools are invoked. The actual connections are created lazily.
    """
    try:
        from .modules.a2a.client_manager import get_a2a_manager
        get_a2a_manager()
        logger.info("A2A client manager initialized")
    except Exception as e:
        logger.warning("Failed to initialize A2A client manager: %s", e)


def _register_a2a_command() -> None:
    """Register /a2a as a control command."""
    try:
        from qwenpaw.app.runner.control_commands import register_command
        from .tools.a2a_command import A2AListCommandHandler
        register_command(A2AListCommandHandler())
        logger.info("Registered /a2a control command")
    except Exception as e:
        logger.warning("Failed to register /a2a command: %s", e)


# ---------------------------------------------------------------------------
# Alibaba Cloud CLI (aliyun) detection and auto-install
# ---------------------------------------------------------------------------

def _get_aliyun_cli_url() -> str | None:
    """Return the download URL for aliyun CLI based on OS and architecture."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Darwin":
        if machine in ("arm64", "aarch64"):
            return "https://aliyuncli.alicdn.com/aliyun-cli-darwin-arm64-latest-amd64.tgz"
        return "https://aliyuncli.alicdn.com/aliyun-cli-darwin-latest-amd64.tgz"
    elif system == "Linux":
        if machine in ("aarch64", "arm64"):
            return "https://aliyuncli.alicdn.com/aliyun-cli-linux-latest-arm64.tgz"
        return "https://aliyuncli.alicdn.com/aliyun-cli-linux-latest-amd64.tgz"
    return None


def _install_aliyun_cli_blocking() -> bool:
    """Download and install aliyun CLI. Returns True on success."""
    url = _get_aliyun_cli_url()
    if url is None:
        logger.warning(
            "Unsupported platform for auto-install: %s/%s",
            platform.system(), platform.machine(),
        )
        return False

    tmp_dir = tempfile.mkdtemp()
    try:
        tgz_path = os.path.join(tmp_dir, "aliyun-cli.tgz")
        logger.info("Downloading aliyun CLI from %s", url)
        subprocess.run(
            ["curl", "-fsSL", url, "-o", tgz_path],
            check=True, timeout=120,
        )
        subprocess.run(
            ["tar", "-xzf", tgz_path, "-C", tmp_dir],
            check=True, timeout=30,
        )

        aliyun_bin = os.path.join(tmp_dir, "aliyun")
        if not os.path.isfile(aliyun_bin):
            logger.error("aliyun binary not found after extraction")
            return False

        install_dir = "/usr/local/bin"
        dest = os.path.join(install_dir, "aliyun")
        try:
            shutil.move(aliyun_bin, dest)
        except PermissionError:
            subprocess.run(
                ["sudo", "mv", aliyun_bin, dest],
                check=True, timeout=10,
            )

        os.chmod(dest, 0o755)
        logger.info("aliyun CLI installed to %s", dest)
        return True
    except Exception as exc:
        logger.warning("Failed to install aliyun CLI: %s", exc)
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def _ensure_aliyun_cli() -> None:
    """Check if aliyun CLI is available; install if missing."""
    if shutil.which("aliyun") is not None:
        try:
            result = subprocess.run(
                ["aliyun", "version"],
                capture_output=True, text=True, timeout=10,
            )
            version = result.stdout.strip() or "unknown"
            logger.info("aliyun CLI already installed: %s", version)
        except Exception:
            logger.info("aliyun CLI found on PATH")
        return

    logger.info("aliyun CLI not found, attempting auto-install...")
    success = await asyncio.to_thread(_install_aliyun_cli_blocking)
    if success:
        logger.info("aliyun CLI auto-install completed")
    else:
        logger.warning(
            "aliyun CLI auto-install failed. Install manually: "
            "https://help.aliyun.com/zh/cli/"
        )


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------

class CloudPawPlugin:
    """CloudPaw plugin entry point."""

    def register(self, api):
        """Register all CloudPaw components via startup hook."""
        api.register_startup_hook(
            hook_name="cloudpaw_init",
            callback=self._on_startup,
            priority=50,
        )
        api.register_shutdown_hook(
            hook_name="cloudpaw_cleanup",
            callback=self._on_shutdown,
            priority=50,
        )
        logger.info("CloudPaw plugin registered hooks")

    async def _on_startup(self):
        """Initialize all CloudPaw components on application startup."""
        from .injectors import inject_interaction_module
        from .agents_setup import ensure_builtin_agents
        from .hooks import setup_tool_and_prompt_hooks, setup_mission_hooks, setup_acp_auto_approve
        from .routers_setup import mount_routers

        logger.info("CloudPaw plugin starting up...")

        logger.info("[CloudPaw] Ensuring default environment variables...")
        _ensure_default_env_vars()

        logger.info("[CloudPaw] Injecting synthetic modules...")
        inject_interaction_module()

        logger.info("[CloudPaw] Installing skills to pool...")
        _install_plugin_skills()

        logger.info("[CloudPaw] Registering built-in agents...")
        ensure_builtin_agents()

        logger.info("[CloudPaw] Setting up tool and prompt hooks...")
        setup_tool_and_prompt_hooks()

        logger.info("[CloudPaw] Setting up ACP permission auto-approve...")
        setup_acp_auto_approve()

        logger.info("[CloudPaw] Setting up mission mode hooks...")
        setup_mission_hooks()

        logger.info("[CloudPaw] Mounting API routers...")
        mount_routers()

        logger.info("[CloudPaw] Initializing A2A client manager...")
        _init_a2a_manager()

        logger.info("[CloudPaw] Registering /a2a control command...")
        _register_a2a_command()

        logger.info("[CloudPaw] Checking aliyun CLI availability...")
        await _ensure_aliyun_cli()

        logger.info("CloudPaw plugin startup complete")

    async def _on_shutdown(self):
        """Cleanup on application shutdown."""
        logger.info("CloudPaw plugin shutting down...")
        try:
            from .modules.a2a.client_manager import shutdown_a2a_manager
            await shutdown_a2a_manager()
            logger.info("[CloudPaw] A2A client manager shut down")
        except Exception as e:
            logger.warning("Failed to shut down A2A manager: %s", e)


plugin = CloudPawPlugin()
