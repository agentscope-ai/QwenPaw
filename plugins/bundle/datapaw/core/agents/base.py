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
from typing import TYPE_CHECKING, Any, List, Literal, Optional, Type

from agentscope.message import Msg
from pydantic import BaseModel
from qwenpaw.agents.react_agent import NamesakeStrategy, QwenPawAgent
from qwenpaw.agents.skill_system.store import get_workspace_skills_dir

from ..i18n import tr
from ..mcp_cm import apply_cm_mcp_long_timeouts, is_cm_mcp_client
from ..orchestration import RuntimeStateManager
from ..path_context import PathContext, default_artifacts_root
from ..sse_metadata import NODE_ROUTING_METADATA_KEYS
from ..tools import DEFAULT_TOOL_NAMES, TOOL_REGISTRY
from .pending_edits import format_pending_edits
from .subagent_config import build_spawn_subagent_fn, acting_spawn_subagent

try:
    from ...constants import is_spawn_subagent_enabled
except ImportError:  # pragma: no cover - compatibility for legacy test imports
    from constants import is_spawn_subagent_enabled

if TYPE_CHECKING:
    from qwenpaw.agents.memory import BaseMemoryManager
    from qwenpaw.config.config import AgentProfileConfig

logger = logging.getLogger("qwenpaw.datapaw.agents")


PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent
PLUGIN_PROMPTS_DIR = PLUGIN_DIR / "prompts"
SUBAGENT_SECTION_BEGIN = "<!-- DATAPAW_SUBAGENT_BEGIN -->"
SUBAGENT_SECTION_END = "<!-- DATAPAW_SUBAGENT_END -->"


_HOST_PLAN_MODE_FLAGS: tuple[str, ...] = (
    "_plan_tool_gate",
    "_plan_awaiting_user_confirm",
    "_plan_just_mutated",
    "_plan_recently_finished",
    "_plan_text_only_after_mutation",
)


# MCP client whose tool calls must carry the request's ``datasource_id`` in
# their ``metadata`` argument. Tool names are collected from this client at
# registration (see ``register_mcp_clients``) and matched in ``_acting``.
CM_MCP_NAME = "DataAgent Context Manager"


def _read_master_md(lang: str = "zh") -> str:
    """Read the plugin's MASTER.{lang}.md runtime-section."""
    candidates = [
        PLUGIN_PROMPTS_DIR / f"MASTER.{lang}.md",
        PLUGIN_PROMPTS_DIR / "MASTER.zh.md",
        PLUGIN_PROMPTS_DIR / "MASTER.md",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            return _render_master_md(path.read_text(encoding="utf-8"))
        except OSError:
            logger.warning(
                "Failed to read DataPaw prompt file %s",
                path,
                exc_info=True,
            )
    return ""


def _render_master_md(content: str) -> str:
    """Render the master prompt according to runtime feature toggles."""
    if is_spawn_subagent_enabled():
        return _strip_subagent_markers(content)
    return _remove_subagent_section(content)


def _strip_subagent_markers(content: str) -> str:
    content = content.replace(f"{SUBAGENT_SECTION_BEGIN}\n", "")
    content = content.replace(f"{SUBAGENT_SECTION_END}\n", "")
    content = content.replace(SUBAGENT_SECTION_BEGIN, "")
    return content.replace(SUBAGENT_SECTION_END, "")


def _remove_subagent_section(content: str) -> str:
    start = content.find(SUBAGENT_SECTION_BEGIN)
    if start < 0:
        return content
    stop = content.find(
        SUBAGENT_SECTION_END,
        start + len(SUBAGENT_SECTION_BEGIN),
    )
    if stop < 0:
        return _strip_subagent_markers(content)
    stop += len(SUBAGENT_SECTION_END)
    before = content[:start].rstrip()
    after = content[stop:].lstrip()
    if before and after:
        return f"{before}\n\n{after}"
    return f"{before}{after}"


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

    tools: List[str] = field(default_factory=lambda: list(DEFAULT_TOOL_NAMES))
    """DataPaw-owned tool names.

    Real data query tools such as ``execute_sql`` are expected to come from
    ``agent_config.mcp``. Large result downloads use ``execute_shell_command``
    with ``curl`` (see MASTER prompt).
    """

    sub_agent_dispatcher: Any = None
    """P1 extension point for a sub-agent dispatcher. ``None`` in MVP."""


# ---------------------------------------------------------------------------
# DataPawAgent
# ---------------------------------------------------------------------------


class DataPawAgent(QwenPawAgent):
    """DataPaw MasterAgent.

    Inheritance: ``QwenPawAgent → ToolGuardMixin → ReActAgent → ...``.
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
        self._datapaw_config = datapaw_config or DataPawConfig()
        self._sub_agent_dispatcher = self._datapaw_config.sub_agent_dispatcher
        self._lang = getattr(agent_config, "language", None) or "zh"
        self._datapaw_workspace_dir = workspace_dir

        if workspace_dir is not None:
            skills_path = get_workspace_skills_dir(
                Path(workspace_dir),
            ).resolve()
            if skills_path.exists():
                logger.debug("DataPaw skills dir present at %s", skills_path)

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
            parallel_tool_calls=True,
        )

        self._disable_send_file_to_user_tool()

        if runtime_state is None:
            runtime_state = RuntimeStateManager(lang=self._lang)
        else:
            runtime_state.lang = self._lang
        self.plan_notebook = runtime_state

        if plan_notebook is not None and plan_notebook is not runtime_state:
            for attr in _HOST_PLAN_MODE_FLAGS:
                if hasattr(plan_notebook, attr):
                    setattr(runtime_state, attr, getattr(plan_notebook, attr))
        self._configure_artifact_path_resolver(workspace_dir)

        self._register_plan_tools(namesake_strategy)
        self._register_datapaw_tools(namesake_strategy)

    # --- Internal helpers -----------------------------------------------------

    def _disable_send_file_to_user_tool(self) -> None:
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
        try:
            return _get_in_progress_node_id(self.plan_notebook.current_plan)
        except Exception:  # pylint: disable=broad-except
            logger.debug(
                "DataPawAgent: failed to resolve current node_id",
                exc_info=True,
            )
            return None

    def _current_graph_id(self) -> str | None:
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

    def _artifact_base_dir(self, workspace_dir: Path | None) -> Path:
        return default_artifacts_root(
            agent_id=self._agent_config.id,
            workspace_dir=workspace_dir,
        )

    def _configure_artifact_path_resolver(
        self,
        workspace_dir: Path | None,
    ) -> None:
        context = PathContext(
            mount_dir=self._artifact_base_dir(workspace_dir),
            lang=self._lang,
        )
        self.plan_notebook.path_resolver = context.resolve_artifact_path

    # --- SSE metadata annotation ----------------------------------------------

    def _annotate_msg_node_id(self, msg: Msg) -> Msg:
        """Attach graph_id / node_id to message metadata for SSE routing."""
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

    # --- Tool registration ----------------------------------------------------

    def _register_plan_tools(
        self,
        namesake_strategy: NamesakeStrategy = "skip",
    ) -> None:
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

        if not is_spawn_subagent_enabled():
            self._remove_spawn_subagent_tool()
            return

        try:
            spawn_fn = build_spawn_subagent_fn(self)
            self.toolkit.register_tool_function(
                spawn_fn,
                namesake_strategy="override",
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "Failed to register spawn_subagent tool",
                exc_info=True,
            )

    def _remove_spawn_subagent_tool(self) -> None:
        if "spawn_subagent" not in getattr(self.toolkit, "tools", {}):
            return
        try:
            self.toolkit.remove_tool_function("spawn_subagent")
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "Failed to disable spawn_subagent for DataPaw agent",
                exc_info=True,
            )

    def _register_datapaw_tools(
        self,
        namesake_strategy: NamesakeStrategy = "skip",
    ) -> None:
        """Register DataPaw built-in tools listed in ``DataPawConfig.tools``.

        Data query tools are expected to come from MCP clients configured on
        ``agent_config.mcp``. Unknown names log a warning so misconfigurations
        are visible.
        """
        tool_registry: dict[str, Any] = TOOL_REGISTRY
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

    # --- reply ----------------------------------------------------------------

    async def reply(
        self,
        msg: Msg | list[Msg] | None = None,
        structured_model: Type[BaseModel] | None = None,
    ) -> Msg:
        trigger_msg_id = ""
        if isinstance(msg, Msg):
            trigger_msg_id = getattr(msg, "id", "") or ""
        elif isinstance(msg, list) and msg:
            trigger_msg_id = getattr(msg[0], "id", "") or ""
        self.plan_notebook.set_trigger_msg_id(trigger_msg_id)

        pending = self.plan_notebook.pop_pending_edits()
        if pending:
            summary = format_pending_edits(pending, self._lang)
            prefix = tr("edit.notify_prefix", self._lang)
            edit_msg = Msg(
                "system",
                f"{prefix}\n{summary}",
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

    # --- ReAct hooks ----------------------------------------------------------

    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ) -> Msg:
        msg = await super()._reasoning(tool_choice=tool_choice)
        self.plan_notebook.append_to_trace(msg)
        return msg

    async def register_mcp_clients(
        self,
        namesake_strategy: NamesakeStrategy = "skip",
    ) -> None:
        """Register MCP clients, then collect ``CM_MCP_NAME`` tool names.

        The collected (already sanitized) tool names are matched in
        ``_acting`` to inject the request's ``datasource_id`` into the
        tool's ``metadata`` argument before execution.
        """
        for client in self._mcp_clients:
            if is_cm_mcp_client(client):
                apply_cm_mcp_long_timeouts(client)

        await super().register_mcp_clients(namesake_strategy=namesake_strategy)

        self._cm_tool_names: set[str] = set()
        for client in self._mcp_clients:
            if not is_cm_mcp_client(client):
                continue
            try:
                tools = await client.list_tools()
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "Failed to collect %s tool names for metadata injection",
                    CM_MCP_NAME,
                    exc_info=True,
                )
                continue
            self._cm_tool_names.update(
                name for t in tools if (name := getattr(t, "name", ""))
            )

    def _inject_datasource_metadata(self, tool_call: dict) -> None:
        """Replace ``metadata`` with the request's datasource_id in place.

        Only applies to tools exposed by ``CM_MCP_NAME`` (collected in
        ``register_mcp_clients``) when the request carries a
        ``datasource_id``. The replacement is intentional: the model's own
        ``metadata`` value, if any, is overwritten.
        """
        cm_tool_names = getattr(self, "_cm_tool_names", set())
        if tool_call.get("name") not in cm_tool_names:
            return
        datasource_id = (self._request_context or {}).get("datasource_id")
        if not datasource_id:
            return
        inp = tool_call.get("input")
        if not isinstance(inp, dict):
            inp = {}
            tool_call["input"] = inp
        inp["metadata"] = {"datasource_id": datasource_id}

    async def _acting(  # type: ignore[override]
        self,
        tool_call: dict,
    ) -> dict | None:
        """Run the tool, then append its result to the current node's trace.

        For ``spawn_subagent``, delegates to ``acting_spawn_subagent``
        which captures trace metadata for SSE and session persistence.
        """
        self._inject_datasource_metadata(tool_call)
        tool_name = tool_call.get("name", "")

        if tool_name == "spawn_subagent":
            result = await acting_spawn_subagent(self, tool_call)
        else:
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

    # --- handle_interrupt -----------------------------------------------------

    async def handle_interrupt(
        self,
        msg: Msg | list[Msg] | None = None,
        structured_model: Type[BaseModel] | None = None,
    ) -> Msg:
        _ = (msg, structured_model)

        graph = self.plan_notebook.current_plan
        if graph is not None:
            progress = graph.to_markdown()
            text = (
                f"{tr('intr.paused_head', self._lang)}\n"
                f"{progress}\n\n"
                f"{tr('intr.options', self._lang)}"
            )
        else:
            text = tr("intr.no_plan", self._lang)

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

    # --- state_dict / load_state_dict -----------------------------------------

    def state_dict(self) -> dict:
        notebook = self.plan_notebook
        dag_store = getattr(notebook, "_dag_store", None)
        dag_session_id = getattr(notebook, "_dag_session_id", "")
        if dag_store is not None and dag_session_id:
            try:
                dag_store.write_sync(dag_session_id, notebook.state_dict())
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "DataPawAgent: DAGStore final save failed",
                    exc_info=True,
                )

        state = super().state_dict()
        state.pop("plan_notebook", None)
        state.pop("runtime_state", None)
        return state

    def load_state_dict(
        self,
        state_dict: dict,
        strict: bool = True,  # pylint: disable=unused-argument
    ) -> None:
        mapped = dict(state_dict)
        mapped.pop("runtime_state", None)
        mapped.pop("plan_notebook", None)
        QwenPawAgent.load_state_dict(self, mapped, strict=False)
        notebook = self.plan_notebook
        dag_store = getattr(notebook, "_dag_store", None)
        dag_session_id = getattr(notebook, "_dag_session_id", "")

        stored = None
        if dag_store is not None and dag_session_id:
            stored = dag_store.read_sync(dag_session_id)

        if isinstance(stored, dict):
            notebook.restore_state(stored)
