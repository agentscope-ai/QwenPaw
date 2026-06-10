# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Monkey-patch hooks for tools, prompts, and mission mode."""

import json
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


def _check_environment_ready() -> (  # pylint: disable=too-many-branches
    str | None
):
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


_CLOUDPAW_PRD_FIX_PROMPT = """\
⚠️ **prd.json schema validation FAILED**. Problems found:
{problems}

You MUST fix prd.json using the `manage_prd` tool.
Do NOT use `write_file` or `edit_file` to modify prd.json.

If prd.json does not exist yet, use:
```
manage_prd(
    loop_dir="{loop_dir}",
    operation="create",
    project="<short name>",
    description="<one-line summary>",
    stories=[
        {{
            "id": "US-001",
            "title": "<short title>",
            "description": "As a <user>, I want <feature> so that <benefit>",
            "acceptanceCriteria": ["<verifiable criterion 1>", ...],
            "priority": 1
        }}
    ]
)
```

If prd.json exists but has wrong structure, delete it and recreate:
```
manage_prd(loop_dir="{loop_dir}", operation="delete", \
story_ids=[<all existing IDs>])
```
Then use `manage_prd(operation="create", ...)` to recreate with the \
correct format.

**Rules:**
- The `manage_prd` tool automatically creates `userStories` with correct schema
- Each story MUST have: id, title, description, acceptanceCriteria, priority
- `id` format: "US-001", "US-002", etc.
- `acceptanceCriteria` MUST be a non-empty array of strings
- `priority` MUST be a positive integer (NOT boolean)

Fix prd.json NOW using `manage_prd`. Keep the same task decomposition \
but use the tool instead of writing the file directly.
"""


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
    2. Honours ``is_hard_blocked`` (rm -rf /, mkfs, paths escaping cwd, …) —
       those are denied just like before.
    3. Otherwise picks the most permissive allow-like option and returns
       immediately, without suspending the tool for an external respond.

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

    ACPHostedClient.request_permission = _patched_request_permission
    logger.info(
        "[CloudPaw] Patched ACPHostedClient.request_permission for "
        "auto-approve on runners: %s",
        ", ".join(_AUTO_APPROVE_RUNNERS),
    )


def setup_tool_and_prompt_hooks() -> (  # pylint: disable=too-many-statements
    None
):
    """Monkey-patch QwenPawAgent to add cloudpaw tools and prompt sections."""
    # IaC operations are delegated to iac-code via the built-in async
    # `delegate_external_agent` tool (qwenpaw >= v1.1.7b1).  No CloudPaw-side
    # ACP wrapper is required — the plugin only enables the built-in tool
    # with `async_execution=True` via constants.py.
    try:
        from qwenpaw.agents.react_agent import QwenPawAgent
    except ImportError as exc:
        logger.error(
            "Cannot import QwenPawAgent; tool/prompt hooks skipped: %s",
            exc,
        )
        return

    _original_create_toolkit = QwenPawAgent._create_toolkit
    _original_build_sys_prompt = QwenPawAgent._build_sys_prompt

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

    def _patched_create_toolkit(self, *args, **kwargs):
        namesake_strategy = kwargs.get("namesake_strategy", "skip")
        toolkit = _original_create_toolkit(
            self,
            *args,
            **kwargs,
        )

        agent_id = (
            self._request_context.get("agent_id")
            if self._request_context
            else None
        )

        try:
            from .tools.proposal_choice import (
                proposal_choice as _proposal_choice_fn,
            )
            from .tools.manage_prd import (
                manage_prd as _manage_prd_fn,
            )

            if agent_id == BUILTIN_ORCHESTRATION_AGENT_ID:
                try:
                    toolkit.register_tool_function(
                        _proposal_choice_fn,
                        namesake_strategy=namesake_strategy,
                    )
                    logger.debug("Registered plugin tool: proposal_choice")
                except Exception as e:
                    logger.debug("proposal_choice registration skipped: %s", e)

                try:
                    toolkit.register_tool_function(
                        _manage_prd_fn,
                        namesake_strategy=namesake_strategy,
                    )
                    logger.debug("Registered plugin tool: manage_prd")
                except Exception as e:
                    logger.debug("manage_prd registration skipped: %s", e)

        except Exception as e:
            logger.warning(
                "Failed to register plugin tools: %s",
                e,
                exc_info=True,
            )

        # A2A tools: register for orchestration agent
        if agent_id == BUILTIN_ORCHESTRATION_AGENT_ID:
            try:
                from .tools.a2a_list import a2a_list as _a2a_list_fn
                from .tools.a2a_call import a2a_call as _a2a_call_fn

                try:
                    toolkit.register_tool_function(
                        _a2a_list_fn,
                        namesake_strategy=namesake_strategy,
                    )
                    logger.debug("Registered plugin tool: a2a_list")
                except Exception as e:
                    logger.debug("a2a_list registration skipped: %s", e)

                try:
                    toolkit.register_tool_function(
                        _a2a_call_fn,
                        namesake_strategy=namesake_strategy,
                    )
                    logger.debug("Registered plugin tool: a2a_call")
                except Exception as e:
                    logger.debug("a2a_call registration skipped: %s", e)

            except Exception as e:
                logger.warning(
                    "Failed to register A2A tools: %s",
                    e,
                    exc_info=True,
                )

        return toolkit

    def _patched_build_sys_prompt(self):
        sys_prompt = _original_build_sys_prompt(self)

        agent_id = (
            self._request_context.get("agent_id")
            if self._request_context
            else None
        )

        # Runtime environment check for orchestrator
        if agent_id == BUILTIN_ORCHESTRATION_AGENT_ID:
            env_warning = _check_environment_ready()
            if env_warning:
                sys_prompt = env_warning + "\n\n" + sys_prompt
                return sys_prompt

        if agent_id == BUILTIN_ORCHESTRATION_AGENT_ID:
            sys_prompt += "\n\n" + _render_base_supplement()

        return sys_prompt

    _original_interrupt = QwenPawAgent.interrupt

    async def _patched_interrupt(self, msg=None):
        """Cancel async tasks on stop (e.g. delegate_external_agent)."""
        toolkit = getattr(self, "toolkit", None)
        if toolkit is not None:
            async_tasks = getattr(toolkit, "_async_tasks", {})
            for task_id, task in list(async_tasks.items()):
                if not task.done():
                    task.cancel()
                    logger.info(
                        "[CloudPaw] Cancelled background async task %s "
                        "during interrupt",
                        task_id,
                    )
        await _original_interrupt(self, msg)

    QwenPawAgent._create_toolkit = _patched_create_toolkit
    QwenPawAgent._build_sys_prompt = _patched_build_sys_prompt
    QwenPawAgent.interrupt = _patched_interrupt
    logger.info(
        "Patched QwenPawAgent with cloudpaw tools, prompt hooks, "
        "and interrupt",
    )

    _setup_a2a_query_rewrite()


def _setup_a2a_query_rewrite() -> None:
    """Intercept ``/a2a <name> <msg>`` via query_handler patch.

    When a user types ``/a2a <agent_name> <message>``, the patch rewrites the
    user message into a natural-language instruction that tells the LLM to call
    the ``a2a_call`` tool with the specified alias and message.  Because the
    rewritten text no longer starts with ``/``, it bypasses the control-command
    path and flows through the normal agent query pipeline, giving the LLM full
    control over the remote A2A call (including streaming tool output).

    ``/a2a`` without arguments is left untouched so the control-command handler
    can list registered agents as before.
    """
    try:
        from qwenpaw.app.runner.runner import AgentRunner
        from qwenpaw.app.runner.command_dispatch import _get_last_user_text
    except ImportError as exc:
        logger.warning(
            "Cannot import AgentRunner; /a2a query rewrite skipped: %s",
            exc,
        )
        return

    _original_query_handler = AgentRunner.query_handler

    async def _patched_query_handler(self, msgs, request=None, **kwargs):
        query = _get_last_user_text(msgs)
        if query and query.strip().startswith("/a2a "):
            rewritten = _try_rewrite_a2a_query(
                query.strip(),
                self.workspace_dir,
            )
            if rewritten is not None:
                AgentRunner._rewrite_last_message_text(msgs, rewritten)
                logger.info(
                    "[CloudPaw] /a2a query rewritten for agent processing",
                )

        async for item in _original_query_handler(
            self,
            msgs,
            request,
            **kwargs,
        ):
            yield item

    AgentRunner.query_handler = _patched_query_handler
    logger.info(
        "[CloudPaw] Patched AgentRunner.query_handler for /a2a rewrite",
    )


def _try_rewrite_a2a_query(  # pylint: disable=too-many-return-statements
    query: str,
    workspace_dir: Path | None,
) -> str | None:
    """Parse ``/a2a <agent_name> <message>`` and return a rewritten prompt.

    Returns ``None`` if the query cannot be rewritten (missing workspace,
    unknown alias, bad syntax), in which case the control-command path will
    handle it and show an appropriate error or listing.
    """
    rest = query[len("/a2a") :].strip()
    if not rest:
        return None

    parts = rest.split(None, 1)
    if len(parts) < 2:
        return None

    agent_name, message = parts[0].strip(), parts[1].strip()
    if not message or workspace_dir is None:
        return None

    config_path = workspace_dir / "a2a_config.json"
    if not config_path.exists():
        return None

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        agents_cfg = data.get("agents", {})
    except (json.JSONDecodeError, OSError):
        return None

    if agent_name not in agents_cfg:
        return None

    return (
        f"请使用 a2a_call 工具调用远程 A2A Agent。\n"
        f'调用参数：agent_alias="{agent_name}"，'
        f'message="{message}"\n\n'
        f"请直接调用 a2a_call 工具完成此任务，不需要做其他额外操作。"
    )


def setup_mission_hooks() -> None:
    """Monkey-patch mission prompts for CloudPaw mission mode.

    Users must explicitly invoke /mission to enter mission mode.
    """
    _patch_mission_master_prompt()
    _patch_stream_task_timeout()


_CLOUDPAW_STREAM_TASK_TIMEOUT = 3600  # 60 minutes


def _patch_stream_task_timeout() -> None:
    """Increase stream_task_timeout so long-running agent tasks
    (e.g. ROS CreateStack + polling) are not cancelled prematurely.

    The default is 300s (5 min) which is too short for cloud resource
    provisioning workflows that can take 10+ minutes.
    """
    try:
        from qwenpaw.app._app import agent_app

        old = agent_app.stream_task_timeout
        agent_app.stream_task_timeout = _CLOUDPAW_STREAM_TASK_TIMEOUT
        logger.info(
            "[CloudPaw] Patched stream_task_timeout: %s -> %s",
            old,
            _CLOUDPAW_STREAM_TASK_TIMEOUT,
        )
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "Failed to patch stream_task_timeout: %s",
            exc,
        )


def _patch_mission_master_prompt() -> None:
    """Conditionally replace build_master_prompt for CloudPaw agents.

    When the agent_id belongs to a CloudPaw agent (cloud-orchestrator,
    cloud-executor, cloud-verifier), uses a custom master prompt template
    that integrates manage_prd tool usage and CloudPaw-specific deployment
    instructions.  For all other agents, the original upstream prompt
    builder is called unchanged.
    """
    try:
        from qwenpaw.agents.mission import prompts as mission_prompts
        from qwenpaw.agents.mission.prompts import (
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

    mission_prompts.build_master_prompt = _patched_build_master_prompt

    try:
        from qwenpaw.agents.mission import handler as mission_handler

        mission_handler.build_master_prompt = _patched_build_master_prompt
    except (ImportError, AttributeError):
        pass

    # Also patch _PRD_FIX_PROMPT in mission_runner so that when PRD
    # validation fails, the fix prompt tells the agent to use manage_prd
    # instead of write_file.
    try:
        from qwenpaw.agents.mission import mission_runner

        mission_runner._PRD_FIX_PROMPT = _CLOUDPAW_PRD_FIX_PROMPT
        logger.info("[CloudPaw] Patched _PRD_FIX_PROMPT to use manage_prd")
    except (ImportError, AttributeError) as exc:
        logger.warning("Failed to patch _PRD_FIX_PROMPT: %s", exc)

    logger.info(
        "[CloudPaw] Replaced build_master_prompt with CloudPaw version "
        "(CloudPaw agents only)",
    )
