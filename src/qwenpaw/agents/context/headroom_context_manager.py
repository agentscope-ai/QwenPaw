# -*- coding: utf-8 -*-
"""Headroom-backed context manager for QwenPaw agents.

Provides optional context compression via Headroom SDK, supporting:
- Message compression via ``headroom.compress()``
- Tool-result compression via SmartCrusher/LogCompressor
- CCR (Compress-Cache-Retrieve) for reversible compression
- Configurable compression strategies per agent

Usage in agent config::

    context_manager: "headroom"
    headroom:
      enabled: true
      mode: token
      protect_recent: 4
"""
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentscope.message import Msg

from .agent_context import AgentContext
from .base_context_manager import BaseContextManager, context_registry

if TYPE_CHECKING:
    from ..react_agent import QwenPawAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class HeadroomCCRConfig:
    """CCR (Compress-Cache-Retrieve) configuration."""

    enabled: bool = False
    """Enable reversible compression via CCR tool injection."""
    use_mcp: bool = False
    """Use MCP protocol for CCR retrieval (vs tool injection)."""


@dataclass
class HeadroomMemoryConfig:
    """Headroom Memory configuration."""

    enabled: bool = False
    """Enable persistent memory via Headroom Memory module."""
    backend: str = "local"
    """Memory backend: 'local' (SQLite+HNSW) or 'qdrant-neo4j'."""


@dataclass
class HeadroomConfig:
    """Configuration for Headroom context compression."""

    enabled: bool = False
    """Master switch — must be True for any compression to apply."""

    # Compression strategy
    mode: str = "token"
    """Optimization mode: 'token' (prioritize compression) or 'cache' (maximise
    provider prefix-cache hit rate)."""
    target_ratio: float | None = None
    """Keep ratio for Kompress. None = model decides (~15% kept)."""
    protect_recent: int = 4
    """Don't compress the last N messages (active conversation turns)."""
    min_tokens_to_compress: int = 250
    """Minimum token count for a message to be compressed."""

    # Message type control
    compress_user_messages: bool = False
    """Compress user messages (default: skip for coding agents)."""
    compress_system_messages: bool = True
    """Compress system messages (default: True)."""
    compress_tool_results: bool = True
    """Compress tool result messages (default: True)."""

    # CCR
    ccr: HeadroomCCRConfig = field(default_factory=HeadroomCCRConfig)

    # Memory
    memory: HeadroomMemoryConfig = field(default_factory=HeadroomMemoryConfig)


# ---------------------------------------------------------------------------
# Context Manager Implementation
# ---------------------------------------------------------------------------


@context_registry.register("headroom")
class HeadroomContextManager(BaseContextManager):
    """Headroom-backed context manager with compression and CCR support.

    Integrates Headroom SDK as a drop-in replacement for LightContextManager.
    Compression happens in ``pre_reasoning()`` via ``headroom.compress()``,
    and tool-result pruning happens in ``post_acting()``.

    Configuration is loaded from the agent's YAML config under the
    ``headroom`` key.  See :class:`HeadroomConfig` for available options.
    """

    def __init__(self, working_dir: str, agent_id: str):
        super().__init__(working_dir=working_dir, agent_id=agent_id)
        self._config: HeadroomConfig | None = None
        self._headroom_available: bool = False
        self._context_tracker: Any = None
        self._agent_context: AgentContext | None = None
        logger.info(
            "HeadroomContextManager init: agent_id=%s, working_dir=%s",
            agent_id,
            working_dir,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize Headroom SDK and load configuration."""
        try:
            # Lazy import — Headroom is an optional dependency
            import headroom  # noqa: F401

            self._headroom_available = True
        except ImportError:
            logger.warning(
                "Headroom SDK not installed. "
                "Install with: pip install headroom",
            )
            self._headroom_available = False
            return

        # Load configuration from agent config
        self._config = self._load_config()

        if not self._config.enabled:
            logger.info(
                "Headroom compression disabled for agent %s",
                self.agent_id,
            )
            return

        logger.info(
            "HeadroomContextManager started: agent_id=%s, mode=%s",
            self.agent_id,
            self._config.mode,
        )

        # Initialize CCR context tracker if enabled
        if self._config.ccr.enabled:
            try:
                from headroom.ccr import ContextTracker

                self._context_tracker = ContextTracker()
                logger.info("CCR context tracker initialized")
            except ImportError:
                logger.warning(
                    "CCR module not available in this Headroom version",
                )

        # Initialize AgentContext
        self._agent_context = AgentContext(
            working_dir=self.working_dir,
            agent_id=self.agent_id,
        )

    async def close(self) -> bool:
        """Shut down and release resources."""
        logger.info(
            "HeadroomContextManager closing: agent_id=%s",
            self.agent_id,
        )
        self._context_tracker = None
        self._agent_context = None
        return True

    # ------------------------------------------------------------------
    # Agent lifecycle hooks
    # ------------------------------------------------------------------

    async def pre_reasoning(
        self,
        agent: Any,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Compress messages before each reasoning step.

        This is the primary compression entry point.  Uses Headroom's
        ``compress()`` to reduce token count of the current message list,
        then returns the modified kwargs with compressed messages.
        """
        if not self._headroom_available or not self._config:
            return None
        if not self._config.enabled:
            return None

        messages = kwargs.get("messages", [])
        if not messages:
            return None

        try:
            from headroom import compress as headroom_compress
            from headroom.compress import CompressConfig

            # Build CompressConfig from our config
            cfg = CompressConfig(
                compress_user_messages=self._config.compress_user_messages,
                compress_system_messages=self._config.compress_system_messages,
                protect_recent=self._config.protect_recent,
                min_tokens_to_compress=self._config.min_tokens_to_compress,
                target_ratio=self._config.target_ratio,
            )

            # Convert Msg objects to dict format expected by headroom
            raw_messages = self._messages_to_dicts(messages)

            result = headroom_compress(
                messages=raw_messages,
                model=agent.model.config_name if hasattr(agent, "model") else "default",
                config=cfg,
                optimize=True,
            )

            if result.tokens_saved > 0:
                logger.info(
                    "Headroom compressed %d → %d tokens (saved %d, %.1f%%)",
                    result.tokens_before,
                    result.tokens_after,
                    result.tokens_saved,
                    result.compression_ratio * 100,
                )

                # Convert back to Msg objects
                compressed_msgs = self._dicts_to_messages(result.messages)
                kwargs["messages"] = compressed_msgs

                # Track compressed context for CCR
                if self._config.ccr.enabled and self._context_tracker:
                    self._context_tracker.record_compression(
                        original=messages,
                        compressed=compressed_msgs,
                        transforms=result.transforms_applied,
                    )

            return kwargs

        except Exception as e:
            logger.warning(
                "Headroom compression failed, using original messages: %s",
                e,
            )
            return None

    async def post_acting(
        self,
        agent: Any,
        kwargs: dict[str, Any],
        output: Any,
    ) -> Msg | None:
        """Compress tool outputs after each tool-use step.

        Applies Headroom's SmartCrusher to JSON tool results and
        LogCompressor to log-style outputs for additional savings
        beyond what ``pre_reasoning`` already handled.
        """
        if not self._headroom_available or not self._config:
            return None
        if not self._config.enabled or not self._config.compress_tool_results:
            return None

        if not isinstance(output, Msg):
            return None

        content = output.content
        if not content:
            return None

        try:
            from headroom.transforms import ContentRouter, ContentRouterConfig

            router = ContentRouter(
                config=ContentRouterConfig(
                    compress_json=True,
                    compress_logs=True,
                    compress_search_results=True,
                ),
            )

            # Wrap content as a message for the router
            route_result = router.route(
                messages=[{"role": "tool", "content": content}],
            )

            if route_result.tokens_saved > 0:
                logger.debug(
                    "Headroom post_acting compressed tool output: "
                    "saved %d tokens",
                    route_result.tokens_saved,
                )
                # Extract compressed content
                if route_result.messages:
                    compressed_content = route_result.messages[0].get("content", content)
                    output.content = compressed_content

            return output

        except Exception as e:
            logger.debug(
                "Headroom post_acting compression skipped: %s",
                e,
            )
            return None

    async def pre_reply(
        self,
        agent: Any,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Hook before final reply — currently a no-op."""
        return None

    async def post_reply(
        self,
        agent: Any,
        kwargs: dict[str, Any],
        output: Any,
    ) -> Msg | None:
        """Hook after final reply — update CCR tracker if enabled."""
        if self._config and self._config.ccr.enabled and self._context_tracker:
            self._context_tracker.advance_turn()
        return None

    async def compact_context(
        self,
        messages: list[Msg],
        previous_summary: str = "",
        extra_instruction: str = "",
    ) -> dict:
        """Compact messages into a summary using Headroom compression.

        Args:
            messages: Messages to compact.
            previous_summary: Previous compaction summary (optional).
            extra_instruction: Extra instruction for compaction (optional).

        Returns:
            Dict with keys: success, reason, history_compact,
            before_tokens, after_tokens.
        """
        if not self._headroom_available:
            return {
                "success": False,
                "reason": "Headroom SDK not available",
                "history_compact": "",
                "before_tokens": 0,
                "after_tokens": 0,
            }

        try:
            from headroom import compress as headroom_compress
            from headroom.compress import CompressConfig

            cfg = CompressConfig(
                compress_user_messages=True,
                compress_system_messages=True,
                protect_recent=0,
                target_ratio=0.3,
            )

            raw_messages = self._messages_to_dicts(messages)
            result = headroom_compress(
                messages=raw_messages,
                model="default",
                config=cfg,
            )

            # Extract compressed text as summary
            compressed_text = ""
            for msg in result.messages:
                content = msg.get("content", "")
                if isinstance(content, str):
                    compressed_text += content + "\n"
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            compressed_text += block.get("text", "") + "\n"

            return {
                "success": True,
                "reason": "ok",
                "history_compact": compressed_text.strip(),
                "before_tokens": result.tokens_before,
                "after_tokens": result.tokens_after,
            }

        except Exception as e:
            logger.warning("Headroom compact_context failed: %s", e)
            return {
                "success": False,
                "reason": str(e),
                "history_compact": "",
                "before_tokens": 0,
                "after_tokens": 0,
            }

    def get_agent_context(self, **kwargs: Any) -> AgentContext:
        """Return the AgentContext instance for this agent."""
        if self._agent_context is None:
            self._agent_context = AgentContext(
                working_dir=self.working_dir,
                agent_id=self.agent_id,
            )
        return self._agent_context

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_config(self) -> HeadroomConfig:
        """Load Headroom configuration from agent config.

        Falls back to defaults if no headroom config section exists.
        """
        try:
            from ...config.config import load_agent_config

            agent_config = load_agent_config(self.agent_id)
            hr_config = getattr(agent_config, "headroom", None)
            if hr_config is None:
                return HeadroomConfig()

            return HeadroomConfig(
                enabled=getattr(hr_config, "enabled", False),
                mode=getattr(hr_config, "mode", "token"),
                target_ratio=getattr(hr_config, "target_ratio", None),
                protect_recent=getattr(hr_config, "protect_recent", 4),
                min_tokens_to_compress=getattr(
                    hr_config, "min_tokens_to_compress", 250,
                ),
                compress_user_messages=getattr(
                    hr_config, "compress_user_messages", False,
                ),
                compress_system_messages=getattr(
                    hr_config, "compress_system_messages", True,
                ),
                compress_tool_results=getattr(
                    hr_config, "compress_tool_results", True,
                ),
                ccr=HeadroomCCRConfig(
                    enabled=getattr(hr_config.ccr, "enabled", False)
                    if hasattr(hr_config, "ccr")
                    else False,
                    use_mcp=getattr(hr_config.ccr, "use_mcp", False)
                    if hasattr(hr_config, "ccr")
                    else False,
                ),
                memory=HeadroomMemoryConfig(
                    enabled=getattr(hr_config.memory, "enabled", False)
                    if hasattr(hr_config, "memory")
                    else False,
                    backend=getattr(hr_config.memory, "backend", "local")
                    if hasattr(hr_config, "memory")
                    else "local",
                ),
            )
        except Exception as e:
            logger.debug(
                "Failed to load headroom config for %s: %s",
                self.agent_id,
                e,
            )
            return HeadroomConfig()

    @staticmethod
    def _messages_to_dicts(messages: list[Msg]) -> list[dict[str, Any]]:
        """Convert QwenPaw Msg objects to dicts for Headroom.

        Headroom's ``compress()`` expects messages in OpenAI/Anthropic
        dict format: ``{"role": "...", "content": "..."}``.
        """
        result = []
        for msg in messages:
            entry: dict[str, Any] = {"role": msg.role or "user"}
            content = msg.content
            if isinstance(content, str):
                entry["content"] = content
            elif isinstance(content, list):
                # Flatten list blocks to text
                texts = []
                for block in content:
                    if isinstance(block, dict):
                        texts.append(block.get("text", "") or block.get("output", ""))
                    elif isinstance(block, str):
                        texts.append(block)
                entry["content"] = "\n".join(texts)
            else:
                entry["content"] = str(content) if content else ""
            result.append(entry)
        return result

    @staticmethod
    def _dicts_to_messages(dicts: list[dict[str, Any]]) -> list[Msg]:
        """Convert Headroom dicts back to QwenPaw Msg objects."""
        messages = []
        for d in dicts:
            msg = Msg(
                name=d.get("role", "user"),
                role=d.get("role", "user"),
                content=d.get("content", ""),
            )
            messages.append(msg)
        return messages
