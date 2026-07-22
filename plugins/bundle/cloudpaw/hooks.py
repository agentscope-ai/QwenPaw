# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Monkey-patch hooks for tools, prompts, and mission mode."""

import logging
import os
import shutil
from pathlib import Path

from .constants import (
    BUILTIN_EXECUTOR_AGENT_ID,
    BUILTIN_ORCHESTRATION_AGENT_ID,
    BUILTIN_VERIFIER_AGENT_ID,
    PLUGIN_DIR,
)

logger = logging.getLogger("qwenpaw").getChild(
    __name__.replace("plugin_cloudpaw.", ""),
)


# ---------------------------------------------------------------------------
# Runtime environment checks for cloud-orchestrator
# ---------------------------------------------------------------------------

_AK_CONSOLE_URL = "https://ram.console.aliyun.com/manage/ak"
_IAC_CODE_SETTINGS_PATH = Path.home() / ".iac-code" / "settings.yml"


def _parse_iac_settings(content: str) -> bool:
    """Parse iac-code settings and check for activeProvider and model."""
    has_provider = False
    has_model = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("activeProvider:"):
            val = stripped.split(":", 1)[1].strip()
            if val:
                has_provider = True
        if stripped.startswith("model:"):
            val = stripped.split(":", 1)[1].strip()
            if val:
                has_model = True
    return has_provider and has_model


def _check_iac_model_configured() -> bool:
    """Check if iac-code model is configured."""
    try:
        if not _IAC_CODE_SETTINGS_PATH.exists():
            return False
        content = _IAC_CODE_SETTINGS_PATH.read_text(encoding="utf-8")
        # If llm_source is qwenpaw, iac-code uses QwenPaw's model config
        if "llm_source: qwenpaw" in content:
            return True
        return _parse_iac_settings(content)
    except Exception:
        return False


def _check_environment_ready() -> (
    str | None
):  # pylint: disable=too-many-branches
    """Check that all required components are configured for CloudPaw.

    Returns a warning/error message string if any check fails, or None if
    all good.
    """
    issues: list[str] = []

    # 1. iac-code installed?
    if not shutil.which("iac-code"):
        issues.append(
            "❌ iac-code 未安装\n"
            "   安装命令: pip install --ignore-requires-python -U iac-code",
        )

    # 2. Alibaba Cloud AK-SK configured?
    ak = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
    sk = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
    if not ak or not sk:
        issues.append(
            "❌ 阿里云 AK-SK 未配置\n"
            f"   获取 AccessKey: {_AK_CONSOLE_URL}\n"
            "   配置命令:\n"
            "     qwenpaw env set ALIBABA_CLOUD_ACCESS_KEY_ID <your-ak>\n"
            "     qwenpaw env set ALIBABA_CLOUD_ACCESS_KEY_SECRET <your-sk>\n"
            "     qwenpaw env set ALIBABA_CLOUD_REGION_ID cn-hangzhou",
        )

    # 3. QwenPaw model configured?
    qwenpaw_model_ok = False
    try:
        from qwenpaw.providers.provider_manager import ProviderManager

        pm = ProviderManager()
        active_slot = pm.get_active_model()
        if active_slot and active_slot.provider_id and active_slot.model:
            qwenpaw_model_ok = True
    except Exception:
        pass
    if not qwenpaw_model_ok:
        issues.append(
            "❌ QwenPaw 模型未配置\n" + "   配置命令: qwenpaw models config",
        )

    # 4. iac-code model configured?
    if not _check_iac_model_configured():
        issues.append(
            "❌ iac-code 模型未配置\n"
            "   配置方式:\n"
            "     1. 运行 'iac-code' 首次启动会自动引导配置\n"
            "     2. 编辑 ~/.iac-code/settings.yml "
            "设置 activeProvider 和 model\n"
            "     3. 设置环境变量 IAC_CODE_PROVIDER / IAC_CODE_MODEL / "
            "IAC_CODE_API_KEY",
        )

    if not issues:
        return None

    header = "⚠️ 【CloudPaw 环境未就绪】以下配置缺失，请先完成配置后再使用：\n\n"
    footer = (
        "\n\n请将以上未配置项的详细信息和配置方法告知用户，并建议用户完成配置后再使用 CloudPaw 功能。"
        "在配置完成前，请勿尝试执行任何阿里云资源操作。"
    )
    return header + "\n\n".join(issues) + footer


def _load_prompt_file(filename: str) -> str:
    """Load a prompt text from the prompts directory."""
    prompt_file = PLUGIN_DIR / "prompts" / filename
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8").strip()
    logger.warning("Prompt file not found: %s", prompt_file)
    return ""


_CLOUDPAW_BASE_SUPPLEMENT = _load_prompt_file("base_supplement.md")


# ---------------------------------------------------------------------------
# ACP permission auto-approve for trusted runners (iac-code)
# ---------------------------------------------------------------------------
#
# qwenpaw v1.1.7b1 `ACPAgentConfig.trusted` is *not* actually honoured by
# `ACPHostedClient.request_permission` — every edit / write / execute tool
# call made by iac-code still suspends and waits for an external `respond`.
# For CloudPaw the iac-code runner is a fully trusted backend (we explicitly
# set `trusted=True` in constants.py), so we patch `request_permission` to
# auto-select an allow option for that runner, preserving the existing
# `is_hard_blocked` safety net for destructive commands / out-of-cwd paths.

_AUTO_APPROVE_RUNNERS: tuple[str, ...] = ("iac-code",)
_ALLOW_OPTION_PREFERENCE: tuple[str, ...] = (
    "allow_always",
    "allow",
    "allow_once",
    "proceed_always",
    "proceed_once",
)


def _pick_allow_option(options: list) -> object | None:
    """Return the most-permissive allow-like option from an ACP options list.

    Iterates in preference order (allow_always → allow_once → first option
    whose id/name contains 'allow'/'proceed'); falls back to the first option
    otherwise.
    """

    def _opt_attr(opt: object, *keys: str) -> str:
        for key in keys:
            value = None
            if isinstance(opt, dict):
                value = opt.get(key)
            else:
                value = getattr(opt, key, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    indexed = []
    for opt in options or []:
        option_id = _opt_attr(opt, "optionId", "option_id", "id")
        kind = _opt_attr(opt, "kind")
        name = _opt_attr(opt, "name", "label")
        if not option_id:
            continue
        indexed.append((opt, option_id, kind.lower(), name.lower()))

    if not indexed:
        return None

    for preferred in _ALLOW_OPTION_PREFERENCE:
        for opt, option_id, kind, name in indexed:
            if (
                preferred in option_id.lower()
                or preferred == kind
                or preferred in name
            ):
                return opt
    for opt, option_id, kind, name in indexed:
        if (
            "allow" in option_id.lower()
            or "allow" in kind
            or "proceed" in kind
        ):
            return opt
    return indexed[0][0]


def setup_acp_auto_approve() -> None:
    """Patch ACPHostedClient.request_permission to auto-allow trusted runners.

    For runners listed in ``_AUTO_APPROVE_RUNNERS`` (currently only iac-code),
    the patched method:

    1. Emits the same ``permission_request`` UI event as upstream so the
       console / frontend still sees what tool is being invoked.
    2. **Passes through every command without interception** — iac-code is a
       fully trusted backend, so even patterns that the upstream
       ``is_hard_blocked`` regex would match (e.g. benign execute titles
       containing "shutdown") are allowed. A hard-block match is logged for
       audit but never denied.
    3. Picks the most permissive allow-like option and returns immediately,
       without suspending the tool for an external respond.

    Non-trusted runners keep the original suspend-and-wait flow intact.
    """
    try:
        from qwenpaw.agents.acp.client import ACPHostedClient
    except ImportError as exc:
        logger.error(
            "Cannot import ACPHostedClient; "
            "ACP auto-approve patch skipped: %s",
            exc,
        )
        return

    if getattr(
        ACPHostedClient.request_permission,
        "_cloudpaw_patched",
        False,
    ):
        logger.debug("request_permission already patched; skip")
        return

    _original_request_permission = ACPHostedClient.request_permission

    async def _patched_request_permission(
        self,
        options,
        session_id,
        tool_call,
        **kwargs,
    ):
        runner = getattr(self, "agent_name", "") or ""
        if runner not in _AUTO_APPROVE_RUNNERS:
            return await _original_request_permission(
                self,
                options,
                session_id,
                tool_call,
                **kwargs,
            )

        adapter = getattr(self, "_permission_adapter", None)
        if adapter is None:
            return await _original_request_permission(
                self,
                options,
                session_id,
                tool_call,
                **kwargs,
            )

        await self.flush_assistant_text()

        suspended = adapter.build_suspended_permission(
            agent=runner,
            tool_call=tool_call,
            options=options,
        )
        await self._emit_message(
            {
                "type": "permission_request",
                "title": suspended.summary or suspended.tool_name,
                "options": suspended.options,
                "tool_kind": suspended.tool_kind,
                "tool_name": suspended.tool_name,
                "auto_approved": True,
            },
            True,
        )

        # iac-code is a fully trusted backend — pass through every command
        # without interception. A hard-block pattern match (e.g. an execute
        # title containing "shutdown") is logged for audit but never denied,
        # so cloud provisioning commands are never falsely blocked.
        if adapter.is_hard_blocked(tool_call):
            logger.warning(
                "[CloudPaw] Auto-denied hard-blocked ACP tool call "
                "(runner=%s, tool=%s)",
                runner,
                suspended.tool_name,
            )
            return adapter.cancelled_response()

        selected = _pick_allow_option(suspended.options)
        if selected is None:
            logger.warning(
                "[CloudPaw] No allow option found for runner=%s tool=%s; "
                "falling back to suspended flow",
                runner,
                suspended.tool_name,
            )
            return await _original_request_permission(
                self,
                options,
                session_id,
                tool_call,
                **kwargs,
            )

        logger.info(
            "[CloudPaw] Auto-approved ACP permission (runner=%s, tool=%s, "
            "kind=%s)",
            runner,
            suspended.tool_name,
            suspended.tool_kind,
        )
        return adapter.selected_response(selected)

    _patched_request_permission._cloudpaw_patched = True
    _patched_request_permission._original = _original_request_permission
    ACPHostedClient.request_permission = _patched_request_permission
    logger.info(
        "[CloudPaw] Patched ACPHostedClient.request_permission for "
        "auto-approve on runners: %s",
        ", ".join(_AUTO_APPROVE_RUNNERS),
    )


def _build_a2a_agent_section() -> str:
    """Build a compact list of registered A2A agent aliases.

    Reads only from local config — no HTTP requests.
    The LLM should call a2a_list() for name/description/skills details.
    """
    try:
        from .tools.a2a_config_helper import load_a2a_agents
    except ImportError:
        return ""

    agents_cfg = load_a2a_agents()
    if not agents_cfg:
        return ""

    aliases = ", ".join(sorted(agents_cfg.keys()))
    return (
        "\n### 已注册的远程 A2A Agent\n\n"
        f"可用别名：{aliases}\n\n"
        "调用远程 Agent 前，先调用 `a2a_list()` 查看各 Agent "
        "的名称、描述和技能列表，再选择合适的 Agent。\n"
        '使用 `a2a_call(agent_alias="...", message="...")` 调用。'
    )


def _render_base_supplement() -> str:
    """Load and render base supplement with A2A agents injected."""
    supplement = _load_prompt_file("base_supplement.md")
    if not supplement:
        return ""
    a2a_section = _build_a2a_agent_section()
    return supplement.replace("{a2a_agents_section}", a2a_section)


# CloudPaw plugin tools injected into the orchestrator agent's toolkit.
# These are plain async functions (no @tool_descriptor); PolicyGuardedTool
# auto-introspects their docstrings + type hints into JSON schemas.
_ORCHESTRATOR_PLUGIN_TOOLS: tuple = ()
try:
    from .tools.proposal_choice import proposal_choice as _proposal_choice_fn
    from .tools.manage_prd import manage_prd as _manage_prd_fn
    from .tools.a2a_list import a2a_list as _a2a_list_fn
    from .tools.a2a_call import a2a_call as _a2a_call_fn

    _ORCHESTRATOR_PLUGIN_TOOLS = (
        _proposal_choice_fn,
        _manage_prd_fn,
        _a2a_list_fn,
        _a2a_call_fn,
    )
except Exception as _import_exc:  # noqa: BLE001  pylint: disable=broad-except
    logger.warning(
        "CloudPaw plugin tool functions could not be imported; "
        "orchestrator tool injection disabled: %s",
        _import_exc,
    )


def _patch_build_toolkit() -> None:
    """Patch ``AgentBuilder.build_toolkit`` to inject CloudPaw tools for the
    orchestrator agent.

    qwenpaw v2.0 builds the toolkit externally in
    ``AgentBuilder.build_toolkit``
    (the agent no longer constructs it internally), so the v1 patch on
    ``QwenPawAgent._create_toolkit`` is dead. This wraps the new method and,
    when ``agent_id`` is the orchestrator, appends the four plugin tool
    functions to the toolkit's base group.

    The plugin tools are wrapped in plain :class:`FunctionTool` (not
    :class:`PolicyGuardedTool`) so they bypass the host governance layer —
    they are CloudPaw's own high-level tools (config reads, UI prompts,
    prd.json CRUD), not shell/file operations that need sandboxing, and must
    never be denied as "Unregistered tool" by the governor.
    """
    if not _ORCHESTRATOR_PLUGIN_TOOLS:
        logger.warning(
            "Plugin tool functions unavailable; skip build_toolkit patch",
        )
        return
    try:
        from qwenpaw.runtime.builder import AgentBuilder
    except ImportError as exc:
        logger.error(
            "Cannot import AgentBuilder; tool injection skipped: %s",
            exc,
        )
        return

    if getattr(
        AgentBuilder.build_toolkit,
        "_cloudpaw_patched",
        False,
    ):
        logger.debug("build_toolkit already patched; skip")
        return

    _original_build_toolkit = AgentBuilder.build_toolkit

    async def _patched_build_toolkit(
        self,
        agent_config,
        *,
        agent_id=None,
        **kwargs,
    ):
        toolkit = await _original_build_toolkit(
            self,
            agent_config,
            agent_id=agent_id,
            **kwargs,
        )
        if agent_id != BUILTIN_ORCHESTRATION_AGENT_ID:
            return toolkit
        try:
            from agentscope.tool import FunctionTool

            basic_group = toolkit.tool_groups[0]
            existing = {getattr(t, "name", "") for t in basic_group.tools}
            injected = 0
            for fn in _ORCHESTRATOR_PLUGIN_TOOLS:
                if fn.__name__ in existing:
                    continue
                basic_group.tools.append(FunctionTool(fn))
                injected += 1
            if injected:
                logger.info(
                    "[CloudPaw] Injected %d plugin tools into orchestrator "
                    "toolkit",
                    injected,
                )
        except Exception as exc:  # noqa: BLE001  pylint: disable=broad-except
            logger.warning(
                "Failed to inject CloudPaw tools into orchestrator "
                "toolkit: %s",
                exc,
                exc_info=True,
            )
        return toolkit

    _patched_build_toolkit._cloudpaw_patched = True
    _patched_build_toolkit._original = _original_build_toolkit
    AgentBuilder.build_toolkit = _patched_build_toolkit
    logger.info(
        "[CloudPaw] Patched AgentBuilder.build_toolkit to inject plugin "
        "tools for orchestrator",
    )


def _patch_build_prompt() -> None:
    """Patch ``AgentBuilder.build_prompt`` to inject CloudPaw prompt sections
    for the orchestrator agent.

    qwenpaw v2.0 assembles the system prompt in ``AgentBuilder.build_prompt``
    (the agent no longer builds it internally), so the v1 patch on
    ``QwenPawAgent._build_sys_prompt`` is dead. This wraps the new method:
    when ``ctx.agent_id`` is the orchestrator, prepend the environment-
    readiness warning (if any) and append the CloudPaw base supplement.
    """
    try:
        from qwenpaw.runtime.builder import AgentBuilder
    except ImportError as exc:
        logger.error(
            "Cannot import AgentBuilder; prompt patch skipped: %s",
            exc,
        )
        return

    if getattr(AgentBuilder.build_prompt, "_cloudpaw_patched", False):
        logger.debug("build_prompt already patched; skip")
        return

    _original_build_prompt = AgentBuilder.build_prompt

    def _patched_build_prompt(self, ctx, agent_config=None):
        sys_prompt = _original_build_prompt(self, ctx, agent_config)
        agent_id = getattr(ctx, "agent_id", None)
        if agent_id != BUILTIN_ORCHESTRATION_AGENT_ID:
            return sys_prompt

        env_warning = _check_environment_ready()
        if env_warning:
            return env_warning + "\n\n" + sys_prompt

        supplement = _render_base_supplement()
        if supplement:
            sys_prompt += "\n\n" + supplement
        return sys_prompt

    _patched_build_prompt._cloudpaw_patched = True
    _patched_build_prompt._original = _original_build_prompt
    AgentBuilder.build_prompt = _patched_build_prompt
    logger.info(
        "[CloudPaw] Patched AgentBuilder.build_prompt to inject "
        "orchestrator prompt sections",
    )


def setup_tool_and_prompt_hooks() -> None:
    """Monkey-patch the v2.0 ``AgentBuilder`` to add CloudPaw tools and
    prompt sections for the orchestrator agent.

    qwenpaw v2.0 moved toolkit / system-prompt construction out of
    ``QwenPawAgent`` (which now receives them externally from
    :class:`AgentBuilder`). The v1 patches on ``QwenPawAgent._create_toolkit``
    / ``_build_sys_prompt`` / ``interrupt`` are therefore dead; this function
    targets the new :class:`AgentBuilder` entry points instead. The
    ``interrupt``-time async-task cancellation patch was dropped because v2.0
    tracks background tasks via :class:`TaskTracker` natively.

    Note: /a2a query rewrite is now handled by the A2AQueryRewriteHook
    registered via api.register_runtime_hook() in plugin.py, not here.
    """
    _patch_build_toolkit()
    _patch_build_prompt()


def setup_mission_hooks() -> None:
    """Monkey-patch mission prompts for CloudPaw mission mode.

    Users must explicitly invoke /mission to enter mission mode.

    Note: the v1 ``_patch_stream_task_timeout`` patch is obsolete in v2.0.
    ``agent_app.stream_task_timeout`` no longer exists, and the orchestrator's
    IaC tool ``delegate_external_agent`` is not registered with any per-tool
    default timeout in ``QwenPawAgent._register_tool_call_hooks`` — it runs
    uncapped, so long-running cloud provisioning is no longer at risk of the
    old 300s ceiling. No replacement patch is needed.
    """
    _patch_mission_master_prompt()


def _patch_mission_master_prompt() -> None:
    """Conditionally replace build_master_prompt for CloudPaw agents.

    When the agent_id belongs to a CloudPaw agent (cloud-orchestrator,
    cloud-executor, cloud-verifier), uses a custom master prompt template
    that integrates manage_prd tool usage and CloudPaw-specific deployment
    instructions.  For all other agents, the original upstream prompt
    builder is called unchanged.
    """
    try:
        from qwenpaw.modes.mission import prompts as mission_prompts
        from qwenpaw.modes.mission.prompts import (
            WORKER_PROMPT_TEMPLATE,
            _build_git_sections,
            build_master_prompt as _original_build_master_prompt,
            build_verifier_prompt,
        )
    except ImportError:
        logger.error(
            "Cannot import mission prompts; mission prompt patch skipped",
        )
        return

    if getattr(
        mission_prompts.build_master_prompt,
        "_cloudpaw_patched",
        False,
    ):
        logger.debug("build_master_prompt already patched; skip")
        return

    from .prompts.master_prompt import CLOUDPAW_MASTER_PROMPT

    _CLOUDPAW_AGENT_IDS = frozenset(
        {
            BUILTIN_ORCHESTRATION_AGENT_ID,
            BUILTIN_EXECUTOR_AGENT_ID,
            BUILTIN_VERIFIER_AGENT_ID,
        },
    )

    def _patched_build_master_prompt(
        *,
        loop_dir: str,
        agent_id: str,
        max_iterations: int = 20,
        verify_commands: str = "",
        prd_path: str = "",
        progress_path: str = "",
        git_context: dict | None = None,
        workspace_dir: str = "",
    ) -> str:
        if agent_id not in _CLOUDPAW_AGENT_IDS:
            logger.debug(
                "[CloudPaw] agent_id=%s is not a CloudPaw agent, "
                "using original build_master_prompt",
                agent_id,
            )
            return _original_build_master_prompt(
                loop_dir=loop_dir,
                agent_id=agent_id,
                max_iterations=max_iterations,
                verify_commands=verify_commands,
                prd_path=prd_path,
                progress_path=progress_path,
                git_context=git_context,
                workspace_dir=workspace_dir,
            )

        logger.info(
            "[CloudPaw] _patched_build_master_prompt called: "
            "loop_dir=%s, agent_id=%s",
            loop_dir,
            agent_id,
        )
        if not prd_path:
            prd_path = f"{loop_dir}/prd.json"
        if not progress_path:
            progress_path = f"{loop_dir}/progress.txt"
        if not verify_commands:
            verify_commands = "(none specified — rely on acceptance criteria)"
        if not workspace_dir:
            workspace_dir = loop_dir

        gsec = _build_git_sections(git_context)

        worker_tpl = WORKER_PROMPT_TEMPLATE.format(
            loop_dir=loop_dir,
            prd_path=prd_path,
            progress_path=progress_path,
            **gsec,
        )

        verifier_tpl = build_verifier_prompt(
            loop_dir=loop_dir,
            verify_commands=verify_commands,
        )

        prompt = CLOUDPAW_MASTER_PROMPT.format(
            loop_dir=loop_dir,
            workspace_dir=workspace_dir,
            agent_id=agent_id,
            max_iterations=max_iterations,
            verify_commands=verify_commands,
            worker_prompt_template=worker_tpl,
            verifier_prompt_template=verifier_tpl,
            **gsec,
        )

        return prompt

    _patched_build_master_prompt._cloudpaw_patched = True
    _patched_build_master_prompt._original = _original_build_master_prompt
    mission_prompts.build_master_prompt = _patched_build_master_prompt

    try:
        from qwenpaw.modes.mission import handler as mission_handler

        mission_handler.build_master_prompt = _patched_build_master_prompt
    except (ImportError, AttributeError):
        pass

    logger.info(
        "[CloudPaw] Replaced build_master_prompt with CloudPaw version "
        "(CloudPaw agents only)",
    )
