# -*- coding: utf-8 -*-
# pylint: disable=unused-argument too-many-branches too-many-statements
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import frontmatter as fm
from agentscope.message import Msg, TextBlock
from dotenv import load_dotenv

from qwenpaw.runtime_engine import Runner

from .session import SafeJSONSession
from ...agents.utils.file_handling import (
    read_text_file_with_encoding_fallback,
)
from ...config.config import load_agent_config
from ...constant import WORKING_DIR

if TYPE_CHECKING:
    from ...agents.memory import BaseMemoryManager
    from ...agents.context import BaseContextManager

logger = logging.getLogger(__name__)


class AgentRunner(Runner):
    def __init__(
        self,
        agent_id: str = "default",
        workspace_dir: Path | None = None,
        task_tracker: Any | None = None,
    ) -> None:
        super().__init__()
        self.framework_type = "agentscope"
        self.agent_id = agent_id  # Store agent_id for config loading
        self.workspace_dir = (
            workspace_dir  # Store workspace_dir for prompt building
        )
        self._chat_manager = None  # Store chat_manager reference
        self._mcp_manager = None  # MCP client manager for hot-reload
        self._workspace: Any = None  # Workspace instance for control commands
        self.memory_manager: BaseMemoryManager | None = None
        self.context_manager: BaseContextManager | None = None
        self._task_tracker = task_tracker  # Task tracker for background tasks
        self._agent_name: str | None = None

    @property
    def agent_name(self) -> str:
        """Agent display name from config, cached after first access."""
        if self._agent_name is None:
            try:
                cfg = load_agent_config(self.agent_id)
                self._agent_name = cfg.name if cfg and cfg.name else "QwenPaw"
            except Exception:
                self._agent_name = "QwenPaw"
        return self._agent_name

    def invalidate_agent_name_cache(self) -> None:
        """Clear cached agent_name so next access re-reads config."""
        self._agent_name = None

    def set_chat_manager(self, chat_manager):
        """Set chat manager for auto-registration.

        Args:
            chat_manager: ChatManager instance
        """
        self._chat_manager = chat_manager

    def set_mcp_manager(self, mcp_manager):
        """Set MCP client manager for hot-reload support.

        Args:
            mcp_manager: MCPClientManager instance
        """
        self._mcp_manager = mcp_manager

    def set_workspace(self, workspace):
        """Set workspace for control command handlers.

        Args:
            workspace: Workspace instance
        """
        self._workspace = workspace

    @staticmethod
    def _parse_skill_query(
        query: str,
    ) -> tuple[str, str] | None:
        """Parse ``/name [input]`` or ``/[name with spaces] [input]``.

        Bracket form ``/[...]`` handles spaces in skill names and
        bypasses built-in command priority.

        Returns ``(skill_name, user_input)`` or ``None``.
        """
        stripped = query.strip()
        if not stripped.startswith("/"):
            return None

        rest = stripped[1:]  # drop leading /

        # /[skill name] input — bracket form
        if rest.startswith("["):
            close = rest.find("]")
            if close < 0:
                return None
            name = rest[1:close].strip().lower()
            user_input = rest[close + 1 :].strip()
            return (name, user_input) if name else None

        # /name input — plain form
        parts = rest.split(None, 1)
        if not parts:
            return None
        name = parts[0].lower()
        user_input = parts[1] if len(parts) > 1 else ""
        return (name, user_input) if name else None

    def _maybe_inject_skill(
        self,
        query: str | None,
        msgs: list,
        skills: dict,
    ) -> Msg | None:
        """Handle ``/<skill_name> [input]`` or ``/[skill name] [input]``.

        *skills* is ``agent.toolkit._qp_skills`` — already resolved for
        the current channel during agent init.  Hot-reload safe because
        the agent is recreated on every query.

        Returns a ``Msg`` to short-circuit (skill info), or ``None``
        to continue to the LLM with rewritten ``msgs``.
        """
        if not query or not query.startswith("/") or not msgs:
            return None

        parsed = AgentRunner._parse_skill_query(query)
        if not parsed:
            return None
        name, user_input = parsed

        # Lookup by folder name
        skill = next(
            (
                s
                for s in skills.values()
                if Path(s["dir"]).name.lower() == name
            ),
            None,
        )
        if not skill:
            return None

        skill_dir = Path(skill["dir"])
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None

        raw = read_text_file_with_encoding_fallback(skill_md)
        post = fm.loads(raw)
        display_name = post.get("name") or name

        # /<name> without input → return skill info.
        if not user_input:
            desc = post.get("description") or "No description."
            logger.info("Skill info: %s", name)
            return Msg(
                name=self.agent_name,
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"**{name}**\n\n"
                            f"- **command**: `/{name} <input>` to invoke\n"
                            f"- **name**: {display_name}\n"
                            f"- **description**: {desc}\n"
                            f"- **path**: `{skill_dir}`"
                        ),
                    ),
                ],
            )

        # /<name> <input> → rewrite user message with skill body.
        merged = (
            f"Use the [{display_name}] skill in "
            f"`{skill_dir}` to fulfill "
            f"user's task: {user_input}\n\n"
            f"{post.content}"
        )
        AgentRunner._rewrite_last_message_text(msgs, merged)
        logger.info("Skill invocation: %s", name)
        return None

    @staticmethod
    def _rewrite_last_message_text(
        msgs: list,
        new_text: str,
    ) -> None:
        """Rewrite the text content of the last message in-place."""
        if not msgs:
            return
        last = msgs[-1]
        content = getattr(last, "content", None)
        if isinstance(content, list):
            for i, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    content[i] = TextBlock(
                        type="text",
                        text=new_text,
                    )
                    return
            content.insert(
                0,
                TextBlock(type="text", text=new_text),
            )
        elif isinstance(content, str):
            last.content = new_text

    async def _persist_exchange_to_session(
        self,
        session_id: str,
        user_id: str,
        channel: str,
        msgs: list,
        response_msg: "Msg",
    ) -> None:
        """Persist a user-message + response to session memory.

        Used by early-exit paths (/mission info, /skill info) that bypass
        the full agent pipeline and would otherwise leave session memory
        unsaved — causing the response to vanish when the frontend
        reloads the session from the backend.
        """
        if not session_id or not user_id:
            return
        try:
            from agentscope.state import AgentState

            raw = await self.session.get_session_state_dict(
                session_id,
                user_id,
                channel,
                allow_not_exist=True,
            )
            agent_raw = (raw or {}).get("agent", {})
            state_raw = agent_raw.get("state")
            if isinstance(state_raw, dict):
                try:
                    state = AgentState.model_validate(state_raw)
                except Exception:
                    state = AgentState()
            else:
                state = AgentState()

            if msgs:
                last_msg = msgs[-1]
                if isinstance(last_msg, Msg):
                    state.context.append(last_msg)
            if isinstance(response_msg, Msg):
                state.context.append(response_msg)

            await self.session.update_session_state(
                session_id=session_id,
                key="agent.state",
                value=state.model_dump(mode="json"),
                user_id=user_id,
                channel=channel,
            )
            preview = session_id[:12] if len(session_id) >= 12 else session_id
            logger.debug("Persisted exchange to session %s", preview)
        except Exception:
            logger.debug(
                "Failed to persist exchange to session",
                exc_info=True,
            )

    async def init_handler(self, *args, **kwargs):
        """
        Init handler.
        """
        # Load environment variables from .env file
        # env_path = Path(__file__).resolve().parents[4] / ".env"
        env_path = Path("./") / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug(f"Loaded environment variables from {env_path}")
        else:
            logger.debug(
                f".env file not found at {env_path}, "
                "using existing environment variables",
            )

        session_dir = str(
            (self.workspace_dir if self.workspace_dir else WORKING_DIR)
            / "sessions",
        )
        self.session = SafeJSONSession(save_dir=session_dir)

    async def shutdown_handler(self, *args, **kwargs):
        """
        Shutdown handler.
        """
