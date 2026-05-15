# -*- coding: utf-8 -*-
"""Agent registration and workspace initialization for CloudPaw plugin."""

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from .constants import (
    BUILTIN_EXECUTOR_AGENT_ID,
    BUILTIN_ORCHESTRATION_AGENT_ID,
    BUILTIN_VERIFIER_AGENT_ID,
    PLUGIN_DIR,
    _AGENT_SPECS,
)

logger = logging.getLogger(__name__)


def register_extra_tools(agent_id: str, extra_tools: dict[str, dict]) -> None:
    """Register plugin tools into agent's builtin_tools config."""
    if not extra_tools:
        return
    try:
        from qwenpaw.config.config import (
            BuiltinToolConfig,
            ToolsConfig,
            load_agent_config,
            save_agent_config,
        )
    except ImportError:
        return

    try:
        agent_cfg = load_agent_config(agent_id)
    except Exception:
        return

    if not agent_cfg.tools:
        agent_cfg.tools = ToolsConfig()

    changed = False
    _SYNC_FIELDS = (
        "enabled",
        "async_execution",
        "description",
        "icon",
        "display_to_user",
    )
    for tool_name, tool_spec in extra_tools.items():
        if tool_name not in agent_cfg.tools.builtin_tools:
            agent_cfg.tools.builtin_tools[tool_name] = BuiltinToolConfig(
                **tool_spec,
            )
            changed = True
            logger.info(
                "Registered tool '%s' for agent %s",
                tool_name,
                agent_id,
            )
            continue

        # Tool already exists in config (e.g. as a default builtin) — sync
        # spec fields onto the existing entry so plugin-driven overrides
        # (enabled / async_execution / icon / etc.) take effect on subsequent
        # startups too.
        existing = agent_cfg.tools.builtin_tools[tool_name]
        for field in _SYNC_FIELDS:
            if field not in tool_spec:
                continue
            new_value = tool_spec[field]
            if getattr(existing, field, None) != new_value:
                setattr(existing, field, new_value)
                changed = True
                logger.info(
                    "Updated tool '%s' field %s=%r for agent %s",
                    tool_name,
                    field,
                    new_value,
                    agent_id,
                )

    if changed:
        try:
            save_agent_config(agent_id, agent_cfg)
        except Exception as exc:
            logger.warning(
                "Failed to save tools for agent %s: %s",
                agent_id,
                exc,
            )


def _build_acp_config(spec: dict[str, Any]) -> Any:
    """Build an ACPConfig from the spec's acp_agent definition.

    ACP child processes inherit the parent's full os.environ automatically
    (see ACPService._open_conversation:
    env={**os.environ, **agent_config.env}),
    so Alibaba Cloud credentials (AK/SK) are passed implicitly.  We only need
    to inject LLM provider config that iac-code reads from IAC_CODE_* vars.
    """
    try:
        from qwenpaw.config.config import ACPAgentConfig, ACPConfig
    except ImportError:
        logger.warning("Cannot import ACPConfig; ACP configuration skipped")
        return None

    acp_spec = spec["acp_agent"]
    env = {**acp_spec.get("env", {})}

    _inject_llm_env(env)

    agent_config = ACPAgentConfig(
        enabled=True,
        command=acp_spec["command"],
        args=acp_spec.get("args", []),
        env=env,
        trusted=acp_spec.get("trusted", True),
        tool_parse_mode=acp_spec.get("tool_parse_mode", "call_detail"),
    )

    return ACPConfig(agents={acp_spec["name"]: agent_config})


def _inject_llm_env(env: dict[str, str]) -> None:
    """Inject the current QwenPaw LLM provider configuration into env.

    If the user has not explicitly set IAC_CODE_PROVIDER / IAC_CODE_API_KEY,
    we read the active LLM configuration from the QwenPaw provider manager
    and pass it through so iac-code uses the same model backend.
    """
    import os

    if os.environ.get("IAC_CODE_PROVIDER") or env.get("IAC_CODE_PROVIDER"):
        return

    try:
        from qwenpaw.providers.provider_manager import ProviderManager

        pm = ProviderManager()
        active_slot = pm.get_active_model()
        if active_slot is None:
            return

        provider_id = active_slot.provider_id or ""
        model = active_slot.model or ""
        if not provider_id:
            return

        provider = pm.get_provider(provider_id)
        api_key = getattr(provider, "api_key", "") or "" if provider else ""
        base_url = getattr(provider, "base_url", "") or "" if provider else ""

        _PROVIDER_MAP = {
            "dashscope": "DashScope",
            "aliyun-codingplan": "DashScopeTokenPlan",
            "aliyun-codingplan-intl": "DashScopeTokenPlan",
            "openai": "OpenAI",
            "anthropic": "Anthropic",
            "deepseek": "DeepSeek",
        }
        iac_provider = _PROVIDER_MAP.get(
            provider_id.lower(),
            "OpenAPICompatible",
        )

        if iac_provider:
            env.setdefault("IAC_CODE_PROVIDER", iac_provider)
        if api_key:
            env.setdefault("IAC_CODE_API_KEY", api_key)
        if model:
            env.setdefault("IAC_CODE_MODEL", model)
        if base_url and iac_provider == "OpenAPICompatible":
            env.setdefault("IAC_CODE_BASE_URL", base_url)

        logger.info(
            "Injected LLM config for iac-code: provider=%s, model=%s",
            iac_provider,
            model,
        )
    except Exception as exc:
        logger.debug("Failed to inject LLM config for iac-code: %s", exc)


def ensure_builtin_agents() -> None:
    """Register built-in Aliyun agents."""
    try:
        from qwenpaw.config.config import (
            AgentProfileConfig,
            AgentProfileRef,
            AgentsRunningConfig,
            ChannelConfig,
            HeartbeatConfig,
            MCPConfig,
            save_agent_config,
        )
        from qwenpaw.config.utils import load_config, save_config
        from qwenpaw.constant import WORKING_DIR
    except ImportError:
        logger.error(
            "Cannot import config modules; agent registration skipped",
        )
        return

    config = load_config()

    if config.agents.active_agent in ("default", ""):
        config.agents.active_agent = BUILTIN_ORCHESTRATION_AGENT_ID
        save_config(config)
        logger.info(
            "Set active_agent to orchestration agent: %s",
            BUILTIN_ORCHESTRATION_AGENT_ID,
        )

    for spec in _AGENT_SPECS:
        agent_id = spec["agent_id"]
        expected_ws = (
            (Path(WORKING_DIR) / "workspaces" / agent_id)
            .expanduser()
            .resolve()
        )

        if agent_id in config.agents.profiles:
            ref = config.agents.profiles[agent_id]
            actual = Path(ref.workspace_dir).expanduser().resolve()
            if actual != expected_ws:
                logger.warning(
                    "Agent %s workspace mismatch (%s vs %s); skipping",
                    agent_id,
                    actual,
                    expected_ws,
                )
                continue
        else:
            expected_ws.mkdir(parents=True, exist_ok=True)
            config.agents.profiles[agent_id] = AgentProfileRef(
                id=agent_id,
                workspace_dir=str(expected_ws),
            )
            save_config(config)
            logger.info("Registered agent %s at %s", agent_id, expected_ws)

        running_overrides = spec.get("running_overrides", {})
        running_cfg = (
            AgentsRunningConfig(**running_overrides)
            if running_overrides
            else AgentsRunningConfig()
        )

        acp_config = _build_acp_config(spec) if "acp_agent" in spec else None

        agent_cfg = AgentProfileConfig(
            id=agent_id,
            name=spec["name"],
            description=spec["description"],
            workspace_dir=str(expected_ws),
            language=config.agents.language or "zh",
            channels=ChannelConfig(),
            mcp=MCPConfig(),
            heartbeat=HeartbeatConfig(),
            running=running_cfg,
            acp=acp_config,
        )

        _initialize_agent_workspace(
            expected_ws,
            skill_names=spec["skill_names"],
            persona_pack=spec["persona_pack"],
            language=config.agents.language or "zh",
        )

        try:
            save_agent_config(agent_id, agent_cfg)
        except ValueError:
            logger.exception("Failed to save agent.json for %s", agent_id)

        register_extra_tools(agent_id, spec.get("extra_tools", {}))


def _initialize_agent_workspace(
    workspace_dir: Path,
    skill_names: list[str],
    persona_pack: str,
    language: str = "zh",
) -> None:
    """Initialize agent workspace with persona md files and skills."""
    from qwenpaw.agents.skill_system import get_workspace_skills_dir

    (workspace_dir / "sessions").mkdir(exist_ok=True)
    (workspace_dir / "memory").mkdir(exist_ok=True)
    skills_dir = get_workspace_skills_dir(workspace_dir)
    skills_dir.mkdir(exist_ok=True)

    _seed_persona_md_files(workspace_dir, language, persona_pack)
    _install_workspace_skills(workspace_dir, skill_names)

    for fname, default in [
        ("chats.json", {"version": 1, "chats": []}),
        ("jobs.json", {"version": 1, "jobs": []}),
    ]:
        fpath = workspace_dir / fname
        if not fpath.exists():
            fpath.write_text(
                json.dumps(default, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )


def _seed_persona_md_files(
    workspace_dir: Path,
    language: str,
    persona_pack: str,
) -> None:
    """Copy persona markdown files from the plugin's agents directory."""
    agents_dir = PLUGIN_DIR / "agents"
    role_md_dir = agents_dir / persona_pack / language
    if not role_md_dir.exists():
        role_md_dir = agents_dir / persona_pack / "en"
    if not role_md_dir.exists():
        logger.warning("Persona pack dir not found: %s", persona_pack)
        return

    for md_file in role_md_dir.glob("*.md"):
        target = workspace_dir / md_file.name
        if not target.exists():
            try:
                shutil.copy2(md_file, target)
            except Exception as e:
                logger.warning("Failed to copy %s: %s", md_file.name, e)

    try:
        from qwenpaw.agents.prompt import _get_agent_md_dir

        generic_md = _get_agent_md_dir(language)
        if generic_md and generic_md.exists():
            for name in ("MEMORY.md",):
                src = generic_md / name
                dst = workspace_dir / name
                if src.exists() and not dst.exists():
                    shutil.copy2(src, dst)
    except (ImportError, Exception) as e:
        logger.debug("Generic MD copy skipped: %s", e)


def uninstall_agents() -> None:
    """Uninstall all CloudPaw agents and related resources.

    Removes agent profiles, workspaces, plugin skills from the pool,
    and environment variables that were provisioned by CloudPaw.
    """
    _uninstall_agent_profiles()
    _uninstall_plugin_skills()
    _uninstall_cloudpaw_env_vars()


def _uninstall_agent_profiles() -> None:
    """Remove CloudPaw agent profiles and their workspaces."""
    agent_ids = [
        BUILTIN_ORCHESTRATION_AGENT_ID,
        BUILTIN_EXECUTOR_AGENT_ID,
        BUILTIN_VERIFIER_AGENT_ID,
    ]

    try:
        from qwenpaw.config.utils import load_config, save_config
    except ImportError:
        logger.warning("Cannot import config modules; agent uninstall skipped")
        return

    config = load_config()
    changed = False

    for agent_id in agent_ids:
        if agent_id in config.agents.profiles:
            ref = config.agents.profiles[agent_id]
            ws_dir = Path(ref.workspace_dir).expanduser().resolve()
            del config.agents.profiles[agent_id]
            changed = True
            logger.info("Removed agent profile: %s", agent_id)

            if ws_dir.exists():
                try:
                    shutil.rmtree(ws_dir)
                    logger.info("Deleted workspace: %s", ws_dir)
                except Exception as exc:
                    logger.warning(
                        "Failed to delete workspace %s: %s",
                        ws_dir,
                        exc,
                    )
        else:
            logger.debug("Agent %s not in profiles, skipping", agent_id)

    if config.agents.active_agent in agent_ids:
        config.agents.active_agent = "default"
        changed = True
        logger.info("Reset active_agent to 'default'")

    if changed:
        try:
            save_config(config)
            logger.info("Saved updated agent config")
        except Exception as exc:
            logger.warning("Failed to save config after uninstall: %s", exc)


def _uninstall_plugin_skills() -> None:
    """Remove CloudPaw skills from the shared skill pool."""
    from .constants import _PLUGIN_SKILLS

    try:
        from qwenpaw.agents.skill_system import (
            get_skill_pool_dir,
            ensure_skill_pool_initialized,
        )
    except ImportError:
        logger.warning("Cannot import skill_system; skill uninstall skipped")
        return

    try:
        ensure_skill_pool_initialized()
    except Exception as exc:
        logger.warning("Skill pool init failed: %s", exc)

    pool_dir = get_skill_pool_dir()
    manifest_path = pool_dir / "skill.json"

    for skill_name in _PLUGIN_SKILLS:
        skill_dir = pool_dir / skill_name
        if skill_dir.exists():
            try:
                shutil.rmtree(skill_dir)
                logger.info("Deleted skill from pool: %s", skill_name)
            except Exception as exc:
                logger.warning(
                    "Failed to delete skill %s: %s",
                    skill_name,
                    exc,
                )

    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            skills = manifest.get("skills", {})
            changed = False
            for skill_name in _PLUGIN_SKILLS:
                if skill_name in skills:
                    if skills[skill_name].get("source") == "plugin:cloudpaw":
                        del skills[skill_name]
                        changed = True

            if changed:
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                logger.info("Updated skill pool manifest")
        except Exception as exc:
            logger.warning("Failed to update skill pool manifest: %s", exc)


def _uninstall_cloudpaw_env_vars() -> None:
    """Remove CloudPaw-provisioned environment variables from envs.json."""
    from .plugin import _DEFAULT_ENV_KEYS

    try:
        from qwenpaw.envs import load_envs, save_envs
    except ImportError:
        logger.warning("Cannot import qwenpaw.envs; env uninstall skipped")
        return

    envs = load_envs()
    changed = False

    for key in _DEFAULT_ENV_KEYS:
        if key in envs:
            del envs[key]
            changed = True
            logger.info("Removed env var: %s", key)

    if changed:
        try:
            save_envs(envs)
            logger.info("Saved updated envs.json")
        except Exception as exc:
            logger.warning("Failed to save envs.json after uninstall: %s", exc)


def _install_workspace_skills(
    workspace_dir: Path,
    skill_names: list[str],
) -> None:
    """Install skills from pool into agent workspace and enable them."""
    try:
        from qwenpaw.agents.skill_system import (
            get_skill_pool_dir,
            get_workspace_skills_dir,
            reconcile_workspace_manifest,
        )
        from qwenpaw.agents.skill_system.store import (
            get_workspace_skill_manifest_path,
        )
    except ImportError:
        return

    pool_dir = get_skill_pool_dir()
    ws_skills = get_workspace_skills_dir(workspace_dir)

    for skill_name in skill_names:
        src = pool_dir / skill_name
        dst = ws_skills / skill_name
        if not src.exists():
            logger.warning(
                "Skill %s not in pool, cannot install to workspace",
                skill_name,
            )
            continue
        if dst.exists():
            continue
        try:
            shutil.copytree(src, dst)
        except Exception as e:
            logger.warning(
                "Failed to install skill %s to workspace: %s",
                skill_name,
                e,
            )

    reconcile_workspace_manifest(workspace_dir)

    manifest_path = get_workspace_skill_manifest_path(workspace_dir)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        skills = manifest.get("skills", {})
        for skill_name in skill_names:
            if skill_name in skills:
                skills[skill_name]["enabled"] = True
                skills[skill_name].setdefault("channels", ["all"])
                skills[skill_name].setdefault("source", "plugin:cloudpaw")
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning(
            "Failed to enable skills in workspace manifest: %s",
            exc,
        )
