# -*- coding: utf-8 -*-
"""Per-request agent assembly.

:class:`AgentBuilder` fully constructs a :class:`QwenPawAgent` for each
request.  It obtains tools from the per-workspace
:class:`QwenPawLocalWorkspace` (via ``list_tools``), the system prompt
from :class:`PromptManager`, and the model from the factory, then
injects all dependencies into the agent constructor.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from ..agents.acp.meta import ACP_PROJECT_DIR_META_KEY
from ..utils.io_utils import run_sync_io
from ..utils.logging import sanitize_log_value

if TYPE_CHECKING:
    from ..agents.context.visual_compression.runtime.recovery import (
        TurnRecoveryStore,
    )

_logger = logging.getLogger(__name__)


def _descriptor_for(tool: Any) -> Any | None:
    """Return the descriptor from a tool or its common wrapper attributes."""
    for candidate in (
        tool,
        getattr(tool, "func", None),
        getattr(tool, "_func", None),
    ):
        descriptor = getattr(candidate, "_tool_descriptor", None)
        if descriptor is not None:
            return descriptor
    return None


def _bound_skill_loader_dirs(tools: Iterable[Any]) -> list[str]:
    """Resolve descriptor-declared skill directories with language variants."""
    from ..agents.skill_system.registry import (
        get_builtin_skill_language_preference,
    )

    language = get_builtin_skill_language_preference()
    dirs: list[str] = []
    for tool in tools:
        metadata = getattr(_descriptor_for(tool), "metadata", None) or {}
        names = metadata.get("bound_skills") or ()
        root = metadata.get("bound_skills_root")
        if not names or not root:
            continue
        for name in names:
            preferred = Path(root) / f"{name}-{language}"
            fallback = Path(root) / f"{name}-en"
            chosen = preferred if preferred.is_dir() else fallback
            if (chosen / "SKILL.md").exists():
                dirs.append(str(chosen))
            else:
                _logger.warning(
                    "bound skill %r has no SKILL.md under %s; not injected",
                    name,
                    root,
                )
    return dirs


class AgentBuilder:
    """Compose an agent for each request.

    Tools are obtained from ``ctx.workspace.local_workspace.list_tools()``.
    ``app_services`` provides cross-workspace shared services.
    """

    def __init__(
        self,
        app_services: Any | None = None,
    ) -> None:
        self._app_services = app_services

    # ------------------------------------------------------------------ public
    async def build_toolkit(
        self,
        agent_config: Any,
        *,
        agent_id: str | None = None,
        request_context: dict[str, Any] | None = None,
        active_modes: Iterable[str] | None = None,
        effective_skills: Iterable[str] | None = None,
        enabled_features: Iterable[str] | None = None,
        extra_tools: Iterable[Any] | None = None,
        memory_tools: Iterable[Any] | None = None,
        governor: Any = None,
        ctx: Any = None,
        workspace_dir: str | None = None,
    ) -> Any:
        """Build a populated ``Toolkit`` for one agent invocation.

        Tools are obtained from the per-workspace
        :class:`QwenPawLocalWorkspace` via ``list_tools()``.
        ``extra_tools`` and ``memory_tools`` are appended after the
        workspace tools.

        """
        from agentscope.tool import Toolkit

        local_ws = self._get_local_workspace(ctx) if ctx else None
        if local_ws is not None:
            tools: list[Any] = await local_ws.list_tools(
                agent_config=agent_config,
                agent_id=agent_id,
                request_context=request_context,
                active_modes=active_modes or (),
                active_skills=effective_skills or (),
                enabled_features=enabled_features or (),
            )
        else:
            tools = []

        if extra_tools:
            tools.extend(
                self._filter_extra_tools_for_subagent(
                    extra_tools,
                    request_context,
                ),
            )

        if memory_tools:
            from ..governance import PolicyGuardedTool

            for fn in memory_tools:
                tools.append(
                    PolicyGuardedTool(
                        fn,
                        governor=governor,
                        request_context=request_context,
                    ),
                )

        # Final pass: cover workspace + extras + memory in one filter.
        tools = self.apply_subagent_tool_whitelist(tools, request_context)
        tools.sort(key=self._tool_name)

        skills = await run_sync_io(
            self._load_runtime_skills,
            effective_skills,
            workspace_dir,
            tools,
        )
        return Toolkit(tools=tools, skills_or_loaders=skills)

    @staticmethod
    def _tool_name(tool: Any) -> str:
        """Return the model-facing name used for sorting and filtering."""
        name = getattr(tool, "name", None)
        if isinstance(name, str) and name:
            return name
        fn = getattr(tool, "func", None) or getattr(tool, "_func", None)
        if callable(fn):
            return getattr(fn, "__name__", "") or ""
        return getattr(tool, "__name__", "") or ""

    @classmethod
    def apply_subagent_tool_whitelist(
        cls,
        tools: Iterable[Any],
        request_context: dict[str, Any] | None,
    ) -> list[Any]:
        """Filter *tools* by ``subagent_allowed_tools`` (final-pass API).

        - ``None`` / non-list → inherit (no filter)
        - ``[]`` → deny all tools
        - non-empty list → keep only matching python tool names
        """
        items = list(tools)
        whitelist = (request_context or {}).get("subagent_allowed_tools")
        if not isinstance(whitelist, list):
            return items
        if not whitelist:
            return []
        allow = set(whitelist)
        return [t for t in items if cls._tool_name(t) in allow]

    @classmethod
    def _filter_extra_tools_for_subagent(
        cls,
        extra_tools: Iterable[Any],
        request_context: dict[str, Any] | None,
    ) -> list[Any]:
        """Apply ``subagent_allowed_tools`` to post-list_tools extras."""
        return cls.apply_subagent_tool_whitelist(
            extra_tools,
            request_context,
        )

    @staticmethod
    def _resolve_skill_loader_dirs(
        effective_skills: Iterable[str] | None,
        workspace_dir: str | None,
    ) -> list[str]:
        """Map effective skill names to their SKILL.md-bearing directories."""
        names = list(effective_skills or ())
        if not names:
            return []

        from ..agents.skill_system import get_workspace_skills_dir
        from ..constant import WORKING_DIR

        base = get_workspace_skills_dir(Path(workspace_dir or WORKING_DIR))
        dirs: list[str] = []
        for name in names:
            skill_dir = base / name
            if (skill_dir / "SKILL.md").exists():
                dirs.append(str(skill_dir))
            else:
                _logger.debug(
                    "skill '%s' has no SKILL.md at %s; not injected",
                    name,
                    skill_dir,
                )
        return dirs

    @classmethod
    def _load_runtime_skills(
        cls,
        effective_skills: Iterable[str] | None,
        workspace_dir: str | None,
        tools: Iterable[Any],
    ) -> list[Any]:
        """Load runtime Skills, preferring workspace skills on conflicts."""
        from ..agents.skill_system.runtime_cache import load_runtime_skills

        workspace_skill_dirs = cls._resolve_skill_loader_dirs(
            effective_skills,
            workspace_dir,
        )
        workspace_skills = load_runtime_skills(workspace_skill_dirs)
        workspace_skill_names = {skill.name for skill in workspace_skills}

        bound_skill_dirs = list(
            dict.fromkeys(_bound_skill_loader_dirs(tools)),
        )
        bound_skills = load_runtime_skills(bound_skill_dirs)
        return workspace_skills + [
            skill
            for skill in bound_skills
            if skill.name not in workspace_skill_names
        ]

    # ----------------------------------------------------------------- build

    async def build(  # pylint: disable=too-many-statements,too-many-branches
        self,
        ctx: Any,
    ) -> Any:
        """Construct a fully-wired :class:`QwenPawAgent` for one request.

        Integrates all per-workspace registries: QwenPawLocalWorkspace
        (toolkit), PromptManager (system prompt), model factory, and
        middlewares.  The agent receives all dependencies externally —
        it does not build any of them internally.
        """
        from agentscope.agent import ReActConfig

        from ..agents.react_agent import QwenPawAgent
        from ..agents.skill_system import (
            ensure_skills_initialized,
            resolve_effective_skills,
        )
        from ..config.config import load_agent_config
        from ..constant import WORKING_DIR
        from ..providers.provider_manager import ProviderManager

        agent_id = getattr(ctx, "agent_id", None) or "default"
        agent_config = await run_sync_io(load_agent_config, agent_id)
        request_context = self._build_request_context(ctx)
        agent_config = self._apply_request_project(
            agent_config,
            request_context,
        )
        ctx.agent_config = agent_config

        # Validate model availability.
        active = agent_config.active_model
        if not (active and active.provider_id and active.model):
            active = ProviderManager.get_instance().get_active_model()
        if active is None or not active.provider_id or not active.model:
            from ..exceptions import ConfigurationException

            raise ConfigurationException(
                "No active model configured; pick one in the UI",
                config_key="active_model",
                error_code="MODEL_NOT_CONFIGURED",
            )

        workspace_dir = getattr(ctx, "workspace_dir", None)

        # Resolve skills.
        skills_workspace = workspace_dir or WORKING_DIR
        await run_sync_io(ensure_skills_initialized, skills_workspace)
        channel_name = request_context.get("channel", "console")
        try:
            effective_skills = await run_sync_io(
                resolve_effective_skills,
                skills_workspace,
                channel_name,
            )
        except Exception:
            effective_skills = []

        subagent_skills = request_context.get("subagent_skills")
        if isinstance(subagent_skills, list):
            parent_set = set(effective_skills)
            effective_skills = [s for s in subagent_skills if s in parent_set]

        # Compute active modes.
        active_modes: set[str] = set()
        workspace = getattr(ctx, "workspace", None)
        if workspace is not None:
            plugins = getattr(workspace, "plugins", None)
            if plugins is not None:
                active_modes = plugins.active_mode_names(ctx)

        # Governor (governance policy layer). Built per request against
        # the dirs the tools will actually use, so a session-level
        # project switch is reflected in the policy instead of the
        # agent's startup dirs. Every effective project dir is
        # registered: the primary via the CODING_PROJECT_DIR placeholder,
        # the rest as extra ALLOW rules.
        from ..config.context import get_current_project_dirs

        _resolved_dirs = get_current_project_dirs()
        if _resolved_dirs:
            _project_dir = str(_resolved_dirs[0].path)
            _extra_project_dirs = [
                str(entry.path) for entry in _resolved_dirs[1:]
            ]
        else:
            _project_dir = getattr(agent_config, "project_dir", None)
            _extra_project_dirs = []
        governor = await run_sync_io(
            self._init_governor,
            workspace_dir,
            _project_dir,
            _extra_project_dirs,
        )

        # Inject governor into local_workspace so list_tools() can
        # wrap tools with PolicyGuardedTool.
        local_ws = self._get_local_workspace(ctx) if ctx else None
        if local_ws is not None:
            local_ws.set_governor(governor)

        # Toolkit.
        from ..agents.context.visual_compression.runtime.recovery import (
            TurnRecoveryStore,
        )

        visual_recovery_store = TurnRecoveryStore()
        extra_tools = self._collect_coding_mode_tools(
            agent_config,
            workspace_dir,
            agent_id,
            request_context,
            governor,
        )
        extra_tools.extend(
            self._collect_visual_compression_tools(
                agent_config,
                agent_id,
                request_context,
                governor,
                visual_recovery_store,
            ),
        )
        (
            driver_tools,
            driver_prompt_hints,
        ) = await self._collect_driver_tools_and_prompts(
            ctx,
            request_context,
        )
        extra_tools.extend(driver_tools)
        if not hasattr(ctx, "extras") or ctx.extras is None:
            ctx.extras = {}
        ctx.extras["driver_prompt_hints"] = driver_prompt_hints

        # Model + formatter (built before the toolkit so the scroll context
        # strategy, which needs the model for token counting, can wire in).
        model_slot_override = getattr(ctx.request, "model_slot_override", None)
        if model_slot_override is None:
            model_slot_override = request_context.get("model_slot_override")
        model, _formatter = await run_sync_io(
            self.build_model,
            agent_config,
            model_slot_override=model_slot_override,
        )

        # Built once and shared: the agent's native offloader, and (when
        # ``offload_dialog`` is on) scroll's optional dialog archive.
        offloader = self._build_offloader(ctx, agent_config)

        # Optional scroll context strategy (None unless strategy="scroll").
        scroll = await self._build_scroll_components(
            ctx,
            agent_config,
            model,
            offloader=offloader,
        )
        # Eviction and recall must live or die together. The structured
        # recall_history tool reads history in-process (no sandbox needed),
        # but it is still guard-wrapped — with no governor the guard layer
        # itself is degraded. Keep the conservative gate: if the governor
        # never came up and the operator hasn't opted into unsandboxed
        # recall, degrade to native so the full history stays in-context.
        if scroll is not None and not self._scroll_recall_runnable(
            agent_config,
            governor,
        ):
            _logger.warning(
                "scroll: recall tools cannot run (governor unavailable and "
                "allow_unsandboxed is off) — falling back to native context "
                "management so evicted history stays accessible",
            )
            scroll = None
        if scroll is not None:
            self._append_scroll_recall_tools(
                extra_tools,
                scroll,
                agent_config,
                agent_id,
                request_context,
                governor,
            )

        memory_manager = self._get_memory_manager(ctx)
        toolkit = await self.build_toolkit(
            agent_config,
            agent_id=agent_id,
            request_context=request_context,
            active_modes=active_modes,
            effective_skills=effective_skills,
            extra_tools=extra_tools,
            memory_tools=(
                memory_manager.list_memory_tools()
                if memory_manager is not None
                else None
            ),
            governor=governor,
            ctx=ctx,
            workspace_dir=workspace_dir,
        )

        # System prompt.
        sys_prompt = await run_sync_io(
            self.build_prompt,
            ctx,
            agent_config,
        )

        middlewares = self._build_middlewares(
            ctx,
            agent_config,
            visual_recovery_store,
        )

        running_config = agent_config.running

        from ..modes.default import (
            resolve_max_iterations,
        )

        effective_max = resolve_max_iterations(running_config)

        agent = QwenPawAgent(
            name=agent_config.name or "QwenPaw",
            model=model,
            system_prompt=sys_prompt,
            toolkit=toolkit,
            react_config=ReActConfig(max_iters=effective_max),
            middlewares=middlewares,
            agent_config=agent_config,
            workspace_dir=workspace_dir,
            request_context=request_context,
            offloader=offloader,
            context_config=self._build_context_config(agent_config),
            context_manager=(
                scroll.context_manager if scroll is not None else None
            ),
            effective_skills=effective_skills,
            governor=governor,
        )

        # Load session state if SessionLoadHook populated it.
        if ctx.session_state:
            agent.load_state_dict(ctx.session_state)

        _logger.info(
            "builder: built agent for session=%s agent=%s"
            " model=%s/%s tools=%d",
            sanitize_log_value(getattr(ctx, "session_id", "")),
            agent_id,
            active.provider_id,
            active.model,
            len(agent.toolkit.tool_groups[0].tools),
        )
        return agent

    def build_prompt(self, ctx: Any, agent_config: Any = None) -> str:
        """Build the system prompt via the per-workspace
        :class:`PromptManager`.
        """
        from types import SimpleNamespace
        from ..constant import WORKING_DIR

        if agent_config is None:
            from ..config.config import load_agent_config

            agent_config = load_agent_config(
                getattr(ctx, "agent_id", "default"),
            )

        workspace_dir = getattr(ctx, "workspace_dir", None) or WORKING_DIR

        heartbeat_enabled = False
        hb = getattr(agent_config, "heartbeat", None)
        if hb is not None:
            heartbeat_enabled = getattr(hb, "enabled", False)

        prompt_ctx = SimpleNamespace(
            workspace_dir=workspace_dir,
            agent_id=getattr(ctx, "agent_id", None),
            extras={
                "language": agent_config.language,
                "heartbeat_enabled": heartbeat_enabled,
                "env_context": self._build_env_context(ctx, agent_config),
                "agent_config": agent_config,
                "driver_prompt_hints": self._get_driver_prompt_hints(ctx),
            },
        )

        workspace = getattr(ctx, "workspace", None)
        if workspace is not None:
            plugins = getattr(workspace, "plugins", None)
            pm = getattr(plugins, "prompt_manager", None) if plugins else None
            if pm is not None and len(pm) > 0:
                return pm.build_sync(prompt_ctx)

        from .prompt_contributors import build_default_prompt_manager

        return build_default_prompt_manager().build_sync(prompt_ctx)

    def build_model(
        self,
        agent_config: Any,
        model_slot_override: Any = None,
    ) -> tuple[Any, Any]:
        """Create model and formatter using the factory method."""
        from ..agents.model_factory import create_model_and_formatter

        model, formatter = create_model_and_formatter(
            agent_id=agent_config.id,
            model_slot_override=model_slot_override,
            agent_config=agent_config,
        )
        if formatter is not None:
            innermost = model
            # pylint: disable=protected-access
            while hasattr(innermost, "_inner"):
                innermost = innermost._inner
            while hasattr(innermost, "_model"):
                innermost = innermost._model
            # pylint: enable=protected-access
            if hasattr(innermost, "formatter"):
                innermost.formatter = formatter
        return model, formatter

    @staticmethod
    def _init_governor(
        workspace_dir: Any,
        coding_project_dir: Any = None,
        extra_project_dirs: Iterable[Any] = (),
    ) -> Any:
        """Initialize ResourceGovernor if governance is available.

        ``coding_project_dir`` is the PRIMARY project directory;
        ``extra_project_dirs`` are the remaining bound directories, all
        of which get ALLOW rules and sandbox mounts.

        Returns the started governor, or ``None`` when governance cannot
        be initialised (missing dependencies, unsupported platform, etc.).
        """
        if not workspace_dir:
            return None
        try:
            from ..governance import ResourceGovernor

            governor = ResourceGovernor(
                str(workspace_dir),
                coding_project_dir=(
                    str(coding_project_dir) if coding_project_dir else None
                ),
                extra_project_dirs=[str(path) for path in extra_project_dirs],
            )
            governor.start()
            _logger.info("Governance started: dir=%s", workspace_dir)
            return governor
        except Exception:
            _logger.error(
                "Failed to start governance; tool calls will be "
                "fail-closed (governance layer DISABLED)",
                exc_info=True,
            )
            return None

    @staticmethod
    def _get_local_workspace(ctx: Any) -> Any:
        workspace = getattr(ctx, "workspace", None)
        if workspace is not None:
            return getattr(workspace, "local_workspace", None)
        return None

    @staticmethod
    def _build_request_context(ctx: Any) -> dict[str, Any]:
        request = getattr(ctx, "request", None)
        rc: dict[str, Any] = {
            "session_id": getattr(ctx, "session_id", "") or "",
            "agent_id": getattr(ctx, "agent_id", "") or "",
            "channel": (
                (getattr(request, "channel", None) or "") if request else ""
            ),
            "user_id": (
                (getattr(request, "user_id", None) or "") if request else ""
            ),
            "root_session_id": getattr(ctx, "root_session_id", "") or "",
            "root_agent_id": getattr(ctx, "root_agent_id", "") or "",
        }
        _ws = getattr(ctx, "workspace_dir", None)
        if _ws is not None:
            rc.setdefault("workspace_dir", str(_ws))
        app_services = getattr(ctx, "app_services", None)
        if app_services is not None:
            rc["approval_coordinator"] = getattr(
                app_services,
                "approval_coordinator",
                None,
            )
            rc["tool_coordinator"] = getattr(
                app_services,
                "tool_coordinator",
                None,
            )
        _channel_meta = (
            getattr(request, "channel_meta", None) if request else None
        )
        if isinstance(_channel_meta, dict):
            user_name = _channel_meta.get("user_name")
            if user_name:
                rc["user_name"] = user_name
            rc["channel_meta"] = _channel_meta
        rc["_channel_instance"] = getattr(
            request,
            "channel_instance",
            None,
        )
        _payload_ctx = (
            getattr(request, "request_context", None) if request else None
        )
        if isinstance(_payload_ctx, dict):
            rc.update(_payload_ctx)
        mode_state = getattr(ctx, "mode_state", {}) or {}
        mission_state = mode_state.get("mission", {})
        if isinstance(mission_state, dict) and mission_state.get("active"):
            loop_dir = mission_state.get("loop_dir")
            if isinstance(loop_dir, str) and loop_dir:
                from ..modes.mission.state import read_loop_config

                mission_config = read_loop_config(Path(loop_dir))
                source_project = mission_config.get("source_project_dir")
                if isinstance(source_project, str) and source_project:
                    rc["active_mode_project_dir"] = source_project
        return rc

    @staticmethod
    def _stamp_resolved_project(agent_config: Any) -> Any:
        """Stamp the already-resolved primary dir, or ``None`` if unset.

        Returns ``None`` only when the resolver never ran, which tells
        the caller to fall back to validating the request keys itself.
        """
        from ..config.context import (
            get_current_project_dir,
            get_current_project_dir_source,
        )

        resolved = get_current_project_dir()
        if resolved is None:
            return None
        if get_current_project_dir_source() == "workspace_fallback":
            # Nothing configured: keep project_dir unset instead of
            # repointing it at the agent's internal workspace.
            return agent_config
        if not hasattr(agent_config, "model_copy"):
            _logger.warning(
                "Ignoring request project for unsupported config type: %s",
                type(agent_config).__name__,
            )
            return agent_config
        stamped = agent_config.model_copy(deep=True)
        stamped.project_dir = str(resolved)
        return stamped

    @staticmethod
    def _apply_request_project(
        agent_config: Any,
        request_context: dict[str, Any],
    ) -> Any:
        """Stamp the effective primary project dir onto the config copy.

        Resolution happens exactly once in ``ContextVarsSetupHook``
        (PRE_DISPATCH); this stamps the same result onto
        ``agent_config`` for consumers that still read the config field
        (env context, coding tools, fork registry binding). When the
        hook did not run (context vars unset — direct builder calls in
        tests), the trusted request keys are validated directly as
        before.
        """
        stamped = AgentBuilder._stamp_resolved_project(agent_config)
        if stamped is not None:
            return stamped

        from ..agents.fork_project import resolve_allowed_fork_project_dir

        raw_project_dir = request_context.get("active_mode_project_dir")
        if not isinstance(raw_project_dir, str) or not raw_project_dir.strip():
            raw_project_dir = request_context.get("project_dir")
        if not isinstance(raw_project_dir, str) or not raw_project_dir.strip():
            raw_project_dir = request_context.get(ACP_PROJECT_DIR_META_KEY)
        fork_raw = request_context.get("fork_project_dir")
        if not isinstance(raw_project_dir, str) or not raw_project_dir.strip():
            # spawn_subagent(fork=True) places the worktree here.
            raw_project_dir = fork_raw
        if not isinstance(raw_project_dir, str) or not raw_project_dir.strip():
            return agent_config

        # When fork_project_dir is present, the final project directory MUST be
        # the validated worktree — never fall through to an unchecked ACP path.
        if isinstance(fork_raw, str) and fork_raw.strip():
            existing_pd = getattr(agent_config, "project_dir", None)
            workspace_hint = request_context.get("workspace_dir") or getattr(
                agent_config,
                "workspace_dir",
                None,
            )
            validated = resolve_allowed_fork_project_dir(
                fork_raw,
                workspace_dir=workspace_hint,
                project_dirs=[existing_pd] if existing_pd else None,
            )
            if validated is None:
                _logger.warning(
                    "Rejecting fork_project_dir outside allowed worktree "
                    "subtree: %s",
                    sanitize_log_value(fork_raw),
                )
                return agent_config
            raw_project_dir = str(validated)

        project_dir = Path(raw_project_dir).expanduser().resolve()
        if not project_dir.is_dir():
            _logger.warning(
                "Ignoring non-directory request project: %s",
                sanitize_log_value(raw_project_dir),
            )
            return agent_config

        if not hasattr(agent_config, "model_copy"):
            _logger.warning(
                "Ignoring request project for unsupported config type: %s",
                type(agent_config).__name__,
            )
            return agent_config

        agent_config = agent_config.model_copy(deep=True)
        agent_config.project_dir = str(project_dir)
        return agent_config

    @staticmethod
    def _build_env_context(ctx: Any, agent_config: Any) -> str:
        import os
        import sys
        from ..app.chats.utils import build_env_context
        from ..constant import WORKING_DIR

        from ..config.context import get_current_project_dir

        workspace_dir = getattr(ctx, "workspace_dir", None)
        ws = str(workspace_dir) if workspace_dir else str(WORKING_DIR)

        # The effective project dir was resolved once in PRE_DISPATCH;
        # re-deriving it here would risk the prompt disagreeing with
        # where the tools actually operate. Fall back to the stamped
        # config only when the hook did not run (direct builder calls).
        _resolved_dir = get_current_project_dir()
        request = getattr(ctx, "request", None)
        if _resolved_dir is not None:
            _project_dir = str(_resolved_dir)
            if _project_dir == ws:
                # Nothing configured — do not print the workspace twice.
                _project_dir = None
        else:
            _project_dir = getattr(agent_config, "project_dir", None) or ws
            # Prefer validated fork worktree as the shell/file dir.
            _payload = (
                getattr(request, "request_context", None) if request else None
            )
            if isinstance(_payload, dict):
                from ..agents.fork_project import (
                    resolve_allowed_fork_project_dir,
                )

                _fork = resolve_allowed_fork_project_dir(
                    _payload.get("fork_project_dir"),
                    workspace_dir=workspace_dir,
                    project_dirs=[_project_dir] if _project_dir else None,
                )
                if _fork is not None:
                    ws = str(_fork)
                    _project_dir = str(_fork)
        _configured_shell = getattr(
            getattr(agent_config, "running", None),
            "shell_command_executable",
            None,
        )
        _default_shell = (
            _configured_shell
            or os.environ.get("SHELL")
            or ("cmd.exe" if sys.platform == "win32" else "/bin/sh")
        )
        _active = getattr(agent_config, "active_model", None)
        _model_name = (
            _active.model
            if _active and getattr(_active, "model", None)
            else None
        )
        return build_env_context(
            session_id=getattr(ctx, "session_id", ""),
            user_id=(getattr(request, "user_id", None) if request else None),
            user_name=None,
            channel=(getattr(request, "channel", None) if request else None),
            working_dir=ws,
            default_shell=_default_shell,
            project_dir=_project_dir,
            active_model_name=_model_name,
        )

    @staticmethod
    def _collect_coding_mode_tools(
        agent_config: Any,
        workspace_dir: Any,
        agent_id: str,
        request_context: dict[str, Any],
        governor: Any = None,
    ) -> list[Any]:
        from ..modes.coding import collect_coding_tools

        return collect_coding_tools(
            agent_config,
            workspace_dir,
            agent_id=agent_id,
            request_context=request_context,
            governor=governor,
        )

    @staticmethod
    def _collect_visual_compression_tools(
        agent_config: Any,
        agent_id: str,
        request_context: dict[str, Any],
        governor: Any = None,
        recovery_store: TurnRecoveryStore | None = None,
    ) -> list[Any]:
        """Collect the optional visual-context recovery tool."""
        config = (
            agent_config.running.light_context_config.visual_compact_config
        )
        if not config.enabled:
            return []

        from ..agents.context.visual_compression.runtime.recovery import (
            TurnRecoveryStore,
            make_recover_visual_context_tool,
        )

        store = (
            recovery_store
            if recovery_store is not None
            else TurnRecoveryStore()
        )
        recover_visual_context = make_recover_visual_context_tool(store)
        return [
            AgentBuilder._wrap_tool(
                recover_visual_context,
                agent_id,
                request_context,
                governor,
            ),
        ]

    @staticmethod
    def _get_driver_prompt_hints(ctx: Any) -> list[str]:
        extras = getattr(ctx, "extras", {}) or {}
        hints = extras.get("driver_prompt_hints") or []
        return [str(hint) for hint in hints if hint]

    @staticmethod
    async def _collect_driver_tools_and_prompts(
        ctx: Any,
        request_context: dict[str, Any],
    ) -> tuple[list[Any], list[str]]:
        """Build request-time Driver tools and prompt hints.

        MCP is exposed through Driver capabilities only, so a server cannot
        be exposed twice through separate runtime paths.
        """
        workspace = getattr(ctx, "workspace", None)
        driver_manager = (
            getattr(workspace, "driver_manager", None)
            if workspace is not None
            else None
        )
        from ..drivers.adapters.agentscope_tool import build_driver_agent_tools

        return await build_driver_agent_tools(
            driver_manager,
            request_context,
        )

    @staticmethod
    def _get_memory_manager(ctx: Any) -> Any:
        workspace = getattr(ctx, "workspace", None)
        if workspace is not None:
            return getattr(workspace, "memory_manager", None)
        return None

    @staticmethod
    def _build_context_config(agent_config: Any) -> Any:
        """Map QwenPaw's ``ContextCompactConfig`` to AS ``ContextConfig``."""
        from agentscope.agent import ContextConfig

        non_binding_limit = 2**63 - 1
        try:
            lcc = agent_config.running.light_context_config
            ccc = lcc.context_compact_config
            trc = lcc.tool_result_pruning_config
            # ToolResultPruningMiddleware already bounds fresh results by
            # bytes and persists the full artifact before replacing them.
            # AgentScope otherwise applies its own 50k-token split afterwards,
            # creates a replacement ToolResultBlock, and drops QwenPaw's
            # block-scoped truncation metadata.  Make that second cap
            # non-binding while unified pruning is enabled; when pruning is
            # disabled, retain AgentScope's default safety net.
            tool_result_limit = (
                non_binding_limit
                if trc.enabled
                else ContextConfig.model_fields["tool_result_limit"].default
            )
            trigger_ratio = ccc.compact_threshold_ratio
            reserve_ratio = min(
                ccc.reserve_threshold_ratio,
                trigger_ratio - 0.000001,
            )
            if reserve_ratio != ccc.reserve_threshold_ratio:
                _logger.warning(
                    f"Context reserve ratio "
                    f"{ccc.reserve_threshold_ratio} must be smaller than "
                    f"trigger ratio {trigger_ratio}; using "
                    f"{reserve_ratio}.",
                )
            return ContextConfig(
                trigger_ratio=trigger_ratio,
                reserve_ratio=reserve_ratio,
                tool_result_limit=tool_result_limit,
                # QwenPaw's visual compression owns the image budget and
                # preserves native media. AgentScope 2.0.7 otherwise removes
                # canonical images beyond its default limit of five.
                max_image_num=non_binding_limit,
            )
        except Exception:
            return ContextConfig(max_image_num=non_binding_limit)

    @staticmethod
    async def _build_scroll_components(
        ctx: Any,
        agent_config: Any,
        model: Any,
        offloader: Any = None,
    ) -> Any:
        """Build the scroll context strategy, or None when not selected.

        Returns ``None`` for the native strategy (the default) so nothing
        changes unless ``light_context_config.strategy == "scroll"``. The
        shared ``offloader`` is forwarded so scroll can archive evicted turns
        to ``dialog/*.jsonl`` (``offload_dialog``, on by default).
        """
        workspace = getattr(ctx, "workspace", None)
        workspace_dir = (
            str(getattr(workspace, "workspace_dir", ""))
            if workspace is not None
            else ""
        )
        session_id = getattr(ctx, "session_id", None) or "local"
        agent_id = (
            getattr(agent_config, "id", None)
            or getattr(ctx, "agent_id", None)
            or "default"
        )

        from ..agents.context import build_scroll_components

        # history.db is shared across sessions in this workspace; rows are
        # keyed by session_id (the conversation) and agent_id (which agent
        # wrote them).
        return await run_sync_io(
            build_scroll_components,
            agent_config=agent_config,
            workspace_dir=workspace_dir,
            model=model,
            session_id=session_id,
            agent_id=agent_id,
            offloader=offloader,
        )

    @staticmethod
    def _scroll_recall_runnable(agent_config: Any, governor: Any) -> bool:
        """Whether scroll's recall tools can actually execute in this build.

        Two recall paths exist: the structured ``recall_history`` tool
        (in-process bound queries — needs no sandbox, only a working guard
        layer) and the sandboxed ``recall_history_python`` REPL, which fails
        closed unless a ``sandbox_config`` is supplied. That config is
        injected only by the governor (via ``PolicyGuardedTool``); the
        ``GuardedFunctionTool`` fallback used when the governor is absent
        never supplies one. A missing governor means the guard layer itself is
        degraded, so we stay conservative: recall is runnable iff the governor
        is present, or the deployment has opted into unsandboxed recall —
        which requires BOTH the ``QWENPAW_ALLOW_UNSANDBOXED_RECALL`` env var
        and ``scroll_config.allow_unsandboxed`` (see
        ``scroll_unsandboxed_allowed`` — agent.json alone can never bypass the
        sandbox). When neither holds, wiring scroll would evict history that
        nothing can read back, so the caller degrades to native context
        management.
        """
        if governor is not None:
            return True
        try:
            from ..agents.context import scroll_unsandboxed_allowed

            sc = agent_config.running.light_context_config.scroll_config
            return scroll_unsandboxed_allowed(sc)
        except Exception:
            return False

    @staticmethod
    def _scroll_repl_runnable(agent_config: Any, governor: Any) -> bool:
        """Whether the sandboxed ``recall_history_python`` REPL should be
        offered to the model in this build.

        The REPL runs model-authored Python and so needs a sandbox. It is
        worth registering only when one is actually usable — meaning the
        governor's platform probe found a sandbox AND the global sandbox
        switch is enabled — or when the operator explicitly opted into
        unsandboxed recall (both the
        ``QWENPAW_ALLOW_UNSANDBOXED_RECALL`` env var and
        ``scroll_config.allow_unsandboxed``, via
        ``scroll_unsandboxed_allowed``).

        When neither holds, every call would fail closed, and the guard layer
        misreads that ``DENIED`` as a sandbox violation and escalates to a
        recurring approval prompt. So we omit the REPL and let the model recall
        through the structured ``recall_history`` tool, which needs no sandbox.
        This is narrower than
        :meth:`_scroll_recall_runnable`, which gates whether scroll is wired at
        all; here scroll is already wired and structured recall is present.

        Note: this is a build-time decision. Registration is evaluated once
        when the agent is built; toggling ``security.sandbox_enabled`` at
        runtime does NOT add or remove the REPL from an already-running
        agent. The switch is still honoured on the execution path
        (``_prepare_off_mode_sandbox`` / ``_sandbox_usable``) -- an already
        registered REPL will simply skip sandbox provisioning once the switch
        is off. Rebuild the agent to change which tools are offered.
        """
        if governor is not None:
            sandbox_usable = getattr(governor, "sandbox_usable", None)
            if sandbox_usable is None:
                # Compatibility for lightweight/custom governor objects that
                # predate the effective-usability property.
                sandbox_usable = getattr(
                    governor,
                    "sandbox_available",
                    False,
                )
            if sandbox_usable:
                return True
        try:
            from ..agents.context import scroll_unsandboxed_allowed

            sc = agent_config.running.light_context_config.scroll_config
            return scroll_unsandboxed_allowed(sc)
        except Exception:
            return False

    def _append_scroll_recall_tools(
        self,
        extra_tools: list,
        scroll: Any,
        agent_config: Any,
        agent_id: str,
        request_context: dict[str, Any],
        governor: Any,
    ) -> None:
        """Register scroll's recall tools onto ``extra_tools``.

        The structured ``recall_history`` tool is ALWAYS registered: its
        expand/search/recall_tool ops are bound read-only queries (internal
        governance type) — no sandbox, no approval, working on every platform.

        The sandboxed ``recall_history_python`` REPL is registered ONLY when
        it can actually run in a sandbox (or unsandboxed recall is explicitly
        opted in). Where no sandbox exists, or an OFF-mode path skips sandbox
        compilation, every call would fail closed, and the guard layer misreads
        that ``DENIED`` as a sandbox violation and turns it into a recurring
        approval prompt. Omitting it removes that dead-end: the model recalls
        through the structured tool.
        """
        extra_tools.append(
            self._wrap_tool(
                scroll.recall_tool,
                agent_id,
                request_context,
                governor,
            ),
        )
        if self._scroll_repl_runnable(agent_config, governor):
            extra_tools.append(
                self._wrap_tool(
                    scroll.repl_tool,
                    agent_id,
                    request_context,
                    governor,
                ),
            )
        else:
            _logger.info(
                "scroll: sandbox unavailable or disabled for "
                "recall_history_python — registering only the structured "
                "recall_history tool (no approval prompt, works without a "
                "sandbox)",
            )

    @staticmethod
    def _wrap_tool(
        fn: Any,
        agent_id: str,
        request_context: dict[str, Any],
        governor: Any,
    ) -> Any:
        """Wrap a raw tool fn in the repo's standard guard (policy or tool)."""
        if governor is not None:
            from ..governance import PolicyGuardedTool

            return PolicyGuardedTool(
                fn,
                governor=governor,
                request_context=request_context,
            )
        from .tool_guard import GuardedFunctionTool

        return GuardedFunctionTool(
            fn,
            agent_id=agent_id,
            request_context=request_context,
        )

    @staticmethod
    def _build_offloader(ctx: Any, agent_config: Any) -> Any:
        """Build the offloader for context and tool-result persistence."""
        workspace = getattr(ctx, "workspace", None)
        workspace_dir = (
            str(getattr(workspace, "workspace_dir", ""))
            if workspace is not None
            else ""
        )
        if not workspace_dir:
            return None

        import os

        from ..agents.offloader import QwenPawOffloader

        lcc = agent_config.running.light_context_config
        dialog_path = os.path.join(workspace_dir, lcc.dialog_path)
        trc = lcc.tool_result_pruning_config
        tool_results_dir = os.path.join(workspace_dir, trc.tool_results_cache)
        return QwenPawOffloader(
            dialog_path=dialog_path,
            tool_results_dir=tool_results_dir,
        )

    @staticmethod
    def _build_tool_result_pruning_middleware(
        ctx: Any,
        agent_config: Any,
    ) -> Any:
        """Build the tool-result pruning middleware."""
        import os

        from ..agents.middlewares import ToolResultPruningMiddleware

        lcc = agent_config.running.light_context_config
        trc = lcc.tool_result_pruning_config
        workspace = getattr(ctx, "workspace", None)
        workspace_dir = (
            str(getattr(workspace, "workspace_dir", ""))
            if workspace is not None
            else ""
        )
        tool_results_dir = (
            os.path.join(workspace_dir, trc.tool_results_cache)
            if workspace_dir
            else ""
        )

        return ToolResultPruningMiddleware(
            enabled=trc.enabled,
            recent_n=trc.pruning_recent_n,
            old_max_bytes=(
                trc.pruning_recent_msg_max_bytes
                if getattr(lcc, "strategy", "native") == "scroll"
                else trc.pruning_old_msg_max_bytes
            ),
            recent_max_bytes=trc.pruning_recent_msg_max_bytes,
            exempt_file_extensions={
                e.lower() for e in trc.exempt_file_extensions
            },
            exempt_tool_names={n.lower() for n in trc.exempt_tool_names},
            tool_results_dir=tool_results_dir,
            agent_id=getattr(agent_config, "id", "default"),
        )

    # pylint: disable=too-many-statements,too-many-branches
    @staticmethod
    def _build_middlewares(
        ctx: Any,
        agent_config: Any,
        visual_recovery_store: TurnRecoveryStore | None = None,
    ) -> list[Any]:
        """Build middleware list.

        Order (onion model, outermost first):
        1. ToolResultPruningMiddleware — tiered tool result pruning
        2. ToolCoordinatorMiddleware — tool call lifecycle management
        3. Plugin-registered middlewares (sorted by priority)
        4. VisualCompressionMiddleware — innermost pre-provider transform
        """
        mws: list[Any] = []

        pruning_middleware = None
        try:
            pruning_middleware = (
                AgentBuilder._build_tool_result_pruning_middleware(
                    ctx,
                    agent_config,
                )
            )
        except Exception:
            _logger.debug(
                "ToolResultPruningMiddleware not created",
                exc_info=True,
            )

        tool_coordinator = None
        app_services = getattr(ctx, "app_services", None)
        if app_services is not None:
            tool_coordinator = getattr(
                app_services,
                "tool_coordinator",
                None,
            )
            if tool_coordinator is not None:
                from ..tool_calls import ToolCoordinatorMiddleware

                if pruning_middleware is not None:
                    mws.append(pruning_middleware)
                mws.append(
                    ToolCoordinatorMiddleware(
                        coordinator=tool_coordinator,
                        background_result_processor=(
                            pruning_middleware.prune_tool_response_async
                            if pruning_middleware is not None
                            else None
                        ),
                    ),
                )

        memory_manager = AgentBuilder._get_memory_manager(ctx)
        if memory_manager is not None:
            try:
                build_middlewares = getattr(
                    memory_manager,
                    "build_middlewares",
                    None,
                )
                if callable(build_middlewares):
                    mws.extend(build_middlewares())
            except Exception:
                _logger.debug("Memory middlewares not created", exc_info=True)

        if tool_coordinator is None and pruning_middleware is not None:
            mws.append(pruning_middleware)

        # Langfuse tool observability
        try:
            from ..observability.langfuse import is_langfuse_enabled

            if is_langfuse_enabled():
                from ..agents.middlewares import LangfuseToolSpanMiddleware

                mws.append(LangfuseToolSpanMiddleware())
        except Exception:
            _logger.debug(
                "LangfuseToolSpanMiddleware not created",
                exc_info=True,
            )

        # Plugin-registered middlewares
        from ..plugins.registry import PluginRegistry

        registry = PluginRegistry()
        for reg in registry.get_middleware_factories():
            try:
                mw = reg.factory(ctx, agent_config)
                if mw is not None:
                    mws.append(mw)
            except Exception:
                _logger.warning(
                    "plugin %s middleware factory failed",
                    reg.plugin_id,
                    exc_info=True,
                )

        # Visual compression is a request-boundary middleware. It reads the
        # validated per-agent config and does not mutate it.
        from ..agents.context.visual_compression.runtime.middleware import (
            VisualCompressionMiddleware,
        )

        visual_config = (
            agent_config.running.light_context_config.visual_compact_config
        )
        mws.append(
            VisualCompressionMiddleware(
                visual_config,
                visual_recovery_store,
            ),
        )

        return mws


__all__ = ["AgentBuilder"]
