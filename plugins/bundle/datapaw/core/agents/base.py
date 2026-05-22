# -*- coding: utf-8 -*-
"""DataPawAgent: DataPaw's MasterAgent implementation.

Inherits the full ``QwenPawAgent`` capability stack (ReAct loop, tools,
MCP, ToolGuard, command/skill/memory) and at post-init injects a
``RuntimeStateManager`` as ``plan_notebook`` to gain DAG planning,
execution and resume.

Sole entry point: ``reply()``. External state changes (frontend edits,
SOP load, interrupt recovery) flow in via the session file and are
surfaced through ``_pending_edits``.

Artifacts land in ``default_artifacts_root``. The system prompt is
assembled in three layers: host's ``AGENTS.md`` / ``SOUL.md`` /
``PROFILE.md`` (via ``super()._build_sys_prompt()``), then this
package's ``prompts/MASTER.md``, then a host-workspace environment
hint.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Literal, Optional, TYPE_CHECKING, Type

from agentscope.message import Msg
from pydantic import BaseModel

from core.orchestration import RuntimeStateManager
from core.path_context import PathContext, default_artifacts_root
from qwenpaw.agents.react_agent import NamesakeStrategy, QwenPawAgent
from qwenpaw.agents.skill_system.store import get_workspace_skills_dir

if TYPE_CHECKING:
    from qwenpaw.agents.memory import BaseMemoryManager
    from qwenpaw.config.config import AgentProfileConfig

logger = logging.getLogger(__name__)


# This file lives at plugins/bundle/datapaw/core/agents/base.py; three
# ``parent`` hops reach the plugin root where ``prompts/`` sits.
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent
PLUGIN_PROMPTS_DIR = PLUGIN_DIR / "prompts"


def _read_master_md() -> str:
    """Read the plugin's MASTER.md runtime-section; empty string on failure."""
    p = PLUGIN_PROMPTS_DIR / "MASTER.md"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:  # pylint: disable=broad-except
        logger.warning("Failed to read DataPaw MASTER.md", exc_info=True)
        return ""


def _get_in_progress_node_id(plan: Any) -> Optional[str]:
    """Return the id of the (single) in-progress node, if any."""
    if plan is None:
        return None
    try:
        for node in plan.nodes.values():
            if getattr(node, "state", None) == "in_progress":
                return getattr(node, "node_id", None)
    except Exception:  # pylint: disable=broad-except
        logger.debug("DataPaw: in-progress node lookup failed", exc_info=True)
    return None


# ---------------------------------------------------------------------------
# DataPawConfig
# ---------------------------------------------------------------------------


@dataclass
class DataPawConfig:
    """DataPawAgent-specific config."""

    prompt_dir: Path = field(default_factory=lambda: PLUGIN_PROMPTS_DIR)
    """Prompt template directory; defaults to the plugin's ``prompts/``."""

    tools: List[str] = field(default_factory=list)
    """DataPaw-owned tool names. Currently none built-in — real data tools
    such as ``get_data`` are expected to come from ``agent_config.mcp``."""

    sub_agent_dispatcher: Any = None
    """P1 extension point for a sub-agent dispatcher. ``None`` in MVP."""


# ---------------------------------------------------------------------------
# _pending_edits formatter
# ---------------------------------------------------------------------------


def format_pending_edits(edits: list[dict]) -> str:
    """Render ``_pending_edits`` into an LLM-readable Chinese summary."""
    lines: list[str] = []
    for edit in edits:
        etype = edit.get("type")
        if etype in ("sop_replaced", "sop_loaded"):
            # ``sop_loaded`` is the legacy name kept for old session files.
            name = edit.get("name", "未命名")
            node_count = edit.get("node_count", "?")
            replaced = edit.get("replaced_graph_id")
            node_summary = edit.get("node_summary") or []
            summary_lines = "\n".join(
                f"  - `{x['id']}`: {x['name']}" f" deps={x.get('deps') or []}"
                for x in node_summary
                if isinstance(x, dict)
            )
            head = f"已加载 SOP 模板「{name}」（{node_count} 个节点）"
            if replaced:
                head += f"，已替换旧图 {replaced}"
            body = (
                f"{head}。这是用户提供的执行计划，请按 ready 节点的 deps "
                f"顺序逐步执行；如无修改诉求，不要再调用 create_plan。"
            )
            if summary_lines:
                body = body + "\n" + summary_lines
            lines.append(body)
        elif etype == "dag_merged":
            name = edit.get("name", "未命名")
            added = edit.get("added") or []
            removed = edit.get("removed") or []
            modified = edit.get("modified") or []
            overridden = edit.get("state_overridden") or []
            stale = edit.get("stale_propagated") or []
            lines.append(
                f"用户修订了任务图「{name}」：\n"
                f"- 新增节点：{added}\n"
                f"- 修改节点：{modified}（结构变更节点按需 STALE）\n"
                f"- 删除节点：{removed}\n"
                f"- 用户显式改变状态：{overridden}\n"
                f"- 下游级联 STALE：{stale}\n"
                f"- 已 done 节点保留进度，请勿重新执行。",
            )
        elif etype == "node_edited":
            # Legacy rendering for old session files.
            node_id = edit.get("node_id", "?")
            changes = edit.get("changes", {})
            lines.append(f"用户在任务面板修改了节点 `{node_id}`：{changes}")
            stale = edit.get("stale_propagated") or []
            if stale:
                lines.append(
                    f"  → 下游节点 {stale} 已被标记为 STALE，需要重跑。",
                )
        elif etype == "graph_replaced":
            # Legacy rendering for old session files.
            lines.append(
                "当前活跃图被前端替换。请检查新的 current_plan 并按其执行。",
            )
        else:
            lines.append(f"未知外部变更：{edit}")
    return "\n".join(lines) if lines else "(no pending edits)"


# ---------------------------------------------------------------------------
# DataPawAgent
# ---------------------------------------------------------------------------


class DataPawAgent(QwenPawAgent):
    """DataPaw MasterAgent.

    Inheritance: ``QwenPawAgent → ToolGuardMixin → ReActAgent → ...``.

    Overridden methods (kept minimal):
    - ``_build_sys_prompt``: append DataPaw's MASTER.md and the env hint
      on top of the host's three-piece prompt set.
    - ``reply``: consume ``_pending_edits``, then delegate to super.
    - ``_reasoning`` / ``_acting`` / ``_summarizing``: append to the
      current node's trace.
    - ``handle_interrupt``: return a Msg containing the DAG progress.
    - ``state_dict`` / ``load_state_dict``: rename ``plan_notebook`` to
      ``runtime_state`` in the persisted session JSON and tolerate
      cross-version schema drift.
    - ``print``: inject ``graph_id`` / ``node_id`` into message metadata
      for SSE downstream consumption.
    """

    def __init__(
        self,
        agent_config: "AgentProfileConfig",
        datapaw_config: Optional[DataPawConfig] = None,
        runtime_state: Optional[RuntimeStateManager] = None,
        *,
        env_context: Optional[str] = None,
        mcp_clients: Optional[List[Any]] = None,
        memory_manager: "BaseMemoryManager | None" = None,
        context_manager: Any | None = None,
        request_context: Optional[dict[str, str]] = None,
        namesake_strategy: NamesakeStrategy = "skip",
        workspace_dir: Path | None = None,
        task_tracker: Any | None = None,
        plan_notebook: Any | None = None,
    ) -> None:
        # _build_sys_prompt runs inside super().__init__ and reads
        # self._datapaw_config, so configure it before super().
        self._datapaw_config = datapaw_config or DataPawConfig()
        self._sub_agent_dispatcher = self._datapaw_config.sub_agent_dispatcher

        # Diagnostic-only: avoid calling host helpers on a missing skills dir.
        if workspace_dir is not None:
            skills_path = get_workspace_skills_dir(
                Path(workspace_dir),
            ).resolve()
            if skills_path.exists():
                logger.debug("DataPaw skills dir present at %s", skills_path)

        # Don't forward plan_notebook: the host runner hands in an
        # agentscope PlanNotebook, but we replace it entirely with our
        # RuntimeStateManager below — forwarding wastes one init.
        super().__init__(
            agent_config=agent_config,
            env_context=env_context,
            mcp_clients=mcp_clients,
            memory_manager=memory_manager,
            context_manager=context_manager,
            request_context=request_context,
            namesake_strategy=namesake_strategy,
            workspace_dir=workspace_dir,
            task_tracker=task_tracker,
        )

        self._disable_send_file_to_user_tool()

        # Post-init: assigning to ``self.plan_notebook`` triggers
        # StateModule.__setattr__, which registers the StateModule under
        # ``_module_dict["plan_notebook"]`` so state_dict / load_state_dict
        # automatically cover the entire runtime state.
        if runtime_state is None:
            # DataPawPlanToHint is RuntimeStateManager's default — no need
            # to pass graph_to_hint explicitly.
            runtime_state = RuntimeStateManager()
        self.plan_notebook = runtime_state

        # Migrate host plan-mode flags from the discarded host
        # PlanNotebook (constructed by runner when plan.enabled=True) to
        # our RuntimeStateManager. Without this, /plan command's
        # _plan_tool_gate (set on host PlanNotebook before agent init)
        # would be lost.
        if plan_notebook is not None and plan_notebook is not runtime_state:
            for attr in (
                "_plan_tool_gate",
                "_plan_awaiting_user_confirm",
                "_plan_just_mutated",
                "_plan_recently_finished",
                "_plan_text_only_after_mutation",
            ):
                if hasattr(plan_notebook, attr):
                    setattr(runtime_state, attr, getattr(plan_notebook, attr))
        self._configure_artifact_path_resolver(workspace_dir)

        self._register_plan_tools(namesake_strategy)
        self._register_datapaw_tools(namesake_strategy)

    def _disable_send_file_to_user_tool(self) -> None:
        """DataPaw uses artifacts / preview APIs, not direct file pushing."""
        if not getattr(self, "toolkit", None):
            return
        if "send_file_to_user" not in getattr(self.toolkit, "tools", {}):
            return
        try:
            self.toolkit.remove_tool_function("send_file_to_user")
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "Failed to disable send_file_to_user for DataPaw agent",
                exc_info=True,
            )

    def _current_node_id(self) -> str | None:
        """Return the current in-progress DataPaw node id, if any."""
        try:
            return _get_in_progress_node_id(self.plan_notebook.current_plan)
        except Exception:  # pylint: disable=broad-except
            logger.debug(
                "DataPawAgent: failed to resolve current node_id",
                exc_info=True,
            )
            return None

    def _artifact_base_dir(self, workspace_dir: Path | None) -> Path:
        """Artifact root for this agent."""
        return default_artifacts_root(
            agent_id=self._agent_config.id,
            workspace_dir=workspace_dir,
        )

    def _configure_artifact_path_resolver(
        self,
        workspace_dir: Path | None,
    ) -> None:
        """Give the RuntimeStateManager a resolver for artifact size stat."""
        context = PathContext(mount_dir=self._artifact_base_dir(workspace_dir))
        self.plan_notebook.path_resolver = context.resolve_artifact_path

    def _current_graph_id(self) -> str | None:
        """Return the current DataPaw graph id, if any."""
        try:
            plan = self.plan_notebook.current_plan
            if plan is None:
                return None
            return getattr(plan, "id", None)
        except Exception:  # pylint: disable=broad-except
            logger.debug(
                "DataPawAgent: failed to resolve current graph_id",
                exc_info=True,
            )
            return None

    def _annotate_msg_node_id(self, msg: Msg) -> Msg:
        """Attach the current DataPaw graph/node ids to message metadata.

        ``graph_id`` is set whenever an active plan exists; ``node_id`` is
        set only when a node is currently ``in_progress``. The frontend
        routes content frames by ``graph_id`` alone (plan-level grouping)
        when ``node_id`` is absent — necessary for LLM output emitted
        between nodes (post-finish_subtask, pre-update_subtask_state),
        during plan-confirmation wait, or in the final summary phase.
        """
        graph_id = self._current_graph_id()
        if not graph_id:
            return msg

        metadata = dict(getattr(msg, "metadata", None) or {})
        metadata.setdefault("graph_id", graph_id)

        node_id = self._current_node_id()
        if node_id:
            metadata.setdefault("node_id", node_id)

        msg.metadata = metadata
        return msg

    async def print(
        self,
        msg: Msg,
        last: bool = True,
        speech: Any = None,
    ) -> None:
        if isinstance(msg, Msg):
            msg = self._annotate_msg_node_id(msg)
        return await super().print(msg, last, speech=speech)

    # --- Tool registration --------------------------------------------------

    def _register_plan_tools(
        self,
        namesake_strategy: NamesakeStrategy = "skip",
    ) -> None:
        """Register all 9 plan tools from plan_notebook (no mode filter)."""
        for tool in self.plan_notebook.list_tools():
            try:
                self.toolkit.register_tool_function(
                    tool,
                    namesake_strategy=namesake_strategy,
                )
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "Failed to register plan tool '%s'",
                    getattr(tool, "__name__", repr(tool)),
                    exc_info=True,
                )

    def _register_datapaw_tools(
        self,
        namesake_strategy: NamesakeStrategy = "skip",
    ) -> None:
        """Register DataPaw built-in tools listed in ``DataPawConfig.tools``.

        Currently no built-in tools — fetchers like ``get_data`` are expected
        to come from MCP clients configured on ``agent_config.mcp``. This
        method stays as an extension point: unknown names log a warning so
        misconfigurations are visible.
        """
        tool_registry: dict[str, Any] = {}
        for tool_name in self._datapaw_config.tools:
            fn = tool_registry.get(tool_name)
            if fn is None:
                logger.warning(
                    "Unknown DataPaw tool name '%s' (no built-in "
                    "implementation; configure an MCP server exposing "
                    "this tool instead).",
                    tool_name,
                )
                continue
            try:
                self.toolkit.register_tool_function(
                    fn,
                    namesake_strategy=namesake_strategy,
                )
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "Failed to register DataPaw tool '%s'",
                    tool_name,
                    exc_info=True,
                )

    # --- System-prompt assembly (override) ---------------------------------

    def _analysis_environment_hint(self) -> str:
        """DataPaw env hint describing the host workspace paths."""
        workspace_dir = getattr(self, "_workspace_dir", None)
        artifacts_root = self._artifact_base_dir(workspace_dir)
        return (
            "<datapaw-analysis-environment>\n"
            "当前 DataPaw 分析环境：host workspace。\n"
            "- 使用 host 提供的 `execute_shell_command` 执行命令；"
            "工作目录是 agent workspace。\n"
            f"- 数据文件和产物存储在 `{artifacts_root}`；引用时使用 "
            "`artifacts/<session_id>/<graph_id>/<node_id>/...`。\n"
            "- Python 脚本可来自 workspace、skills 目录或临时生成文件；"
            "不要假设脚本必须位于 `artifacts/` 下。\n"
            "- Matplotlib/Seaborn 绘图时，不要假设宿主机存在某一平台字体；"
            "如需中文字体，请先探测当前 Python 环境可用字体，再设置 "
            "`font.sans-serif`。\n"
            "- 记录 `finish_subtask(files=...)` 时，文件路径仍使用相对 "
            "artifacts 根的路径，例如 `session/graph/node/chart.png`。\n"
            "</datapaw-analysis-environment>"
        )

    def _build_sys_prompt(self) -> str:
        """Assemble the system prompt in four layers:
        1. host three-piece set (``AGENTS.md`` / ``SOUL.md`` / ``PROFILE.md``)
        2. plugin ``MASTER.md`` (DataPaw runtime section)
        3. host workspace env hint (paths & shell rules)
        4. ``_env_context`` if set
        """
        parts: list[str] = []

        try:
            base = super()._build_sys_prompt()
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "DataPawAgent: super()._build_sys_prompt() failed; "
                "falling back to MASTER-only prompt",
                exc_info=True,
            )
            base = ""
        if base:
            parts.append(base)

        master = _read_master_md()
        if master:
            parts.append(master)

        parts.append(self._analysis_environment_hint())

        sys_prompt = "\n\n".join(p for p in parts if p)

        env_ctx = getattr(self, "_env_context", None)
        if env_ctx:
            sys_prompt = sys_prompt + "\n\n" + env_ctx

        return sys_prompt

    # --- reply (light override) --------------------------------------------

    async def reply(
        self,
        msg: Msg | list[Msg] | None = None,
        structured_model: Type[BaseModel] | None = None,
    ) -> Msg:
        """Drain ``_pending_edits`` into memory, then defer to super().reply().

        The behavior delta from base ReAct is driven by RuntimeStateManager
        through the hint + prompt, not by additional dispatch logic here.
        """
        trigger_msg_id = ""
        if isinstance(msg, Msg):
            trigger_msg_id = getattr(msg, "id", "") or ""
        elif isinstance(msg, list) and msg:
            trigger_msg_id = getattr(msg[0], "id", "") or ""
        self.plan_notebook.set_trigger_msg_id(trigger_msg_id)

        pending = self.plan_notebook.pop_pending_edits()
        if pending:
            summary = format_pending_edits(pending)
            edit_msg = Msg(
                "system",
                f"[外部变更通知]\n{summary}",
                role="system",
            )
            try:
                await self.memory.add(edit_msg)
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "Failed to inject _pending_edits summary to memory",
                    exc_info=True,
                )

        return await super().reply(msg=msg, structured_model=structured_model)

    # --- ReAct hooks: append to the current node's trace -------------------

    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ) -> Msg:
        msg = await super()._reasoning(tool_choice=tool_choice)
        self.plan_notebook.append_to_trace(msg)
        return msg

    async def _acting(  # type: ignore[override]
        self,
        tool_call: dict,
    ) -> dict | None:
        """Run the tool, then append its result to the current node's trace."""
        result = await super()._acting(tool_call)

        if self.memory.content:
            latest_msg, _ = self.memory.content[-1]
            if latest_msg.role == "system":
                self.plan_notebook.append_to_trace(latest_msg)
        return result

    async def _summarizing(self) -> Msg:
        msg = await super()._summarizing()
        self.plan_notebook.append_to_trace(msg)
        return msg

    # --- handle_interrupt (full override) ----------------------------------

    async def handle_interrupt(
        self,
        msg: Msg | list[Msg] | None = None,
        structured_model: Type[BaseModel] | None = None,
    ) -> Msg:
        """On interrupt, return a progress message; never mutate node state."""
        _ = (msg, structured_model)

        graph = self.plan_notebook.current_plan
        if graph is not None:
            progress = graph.to_markdown()
            text = (
                f"任务已暂停。当前进度：\n{progress}\n\n"
                "你可以：\n"
                "- 直接说「继续」恢复执行\n"
                "- 告诉我需要修改的内容（如「灵敏度改成 2.0」）\n"
                "- 在任务面板中修改后点击继续"
            )
        else:
            text = "已中断。有什么需要调整的吗？"

        response_msg = Msg(
            self.name,
            text,
            "assistant",
            metadata={"_is_interrupted": True},
        )
        try:
            await self.print(response_msg, True)
        except Exception:  # pylint: disable=broad-except
            logger.debug("print interrupted msg failed", exc_info=True)
        try:
            await self.memory.add(response_msg)
        except Exception:  # pylint: disable=broad-except
            logger.debug("memory.add interrupted msg failed", exc_info=True)
        return response_msg

    # --- state_dict / load_state_dict --------------------------------------
    #
    # Persist DataPaw's RuntimeStateManager under the standard
    # ``plan_notebook`` key (no rename). Host runner's "ensure
    # plan_notebook dict" check (runner.py:657-685) keys on
    # ``agent.plan_notebook`` — using a different name causes host to
    # write its own empty PlanNotebook stub each turn, polluting the
    # session file and breaking RuntimeStateManager.load_state_dict
    # (KeyError on the missing ``artifacts`` field).
    #
    # state_dict is inherited unchanged: super().state_dict() naturally
    # serializes ``plan_notebook`` because we did
    # ``self.plan_notebook = runtime_state`` (StateModule registers the
    # attribute under that name automatically).

    def load_state_dict(
        self,
        state_dict: dict,
        strict: bool = True,  # pylint: disable=unused-argument
    ) -> None:
        """Tolerate legacy ``runtime_state`` field name.

        Earlier plugin builds saved DataPaw state under ``runtime_state``
        instead of ``plan_notebook``; rename it back. If both keys exist
        (e.g., legacy DataPaw save + host pre-populated stub from a
        botched turn), DataPaw's ``runtime_state`` wins. ``strict=False``
        so schema drift between versions doesn't raise.
        """
        mapped = dict(state_dict)
        if "runtime_state" in mapped:
            mapped["plan_notebook"] = mapped.pop("runtime_state")
        QwenPawAgent.load_state_dict(self, mapped, strict=False)
