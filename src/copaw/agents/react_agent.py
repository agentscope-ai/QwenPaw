# -*- coding: utf-8 -*-
"""CoPaw Agent - Main agent implementation.

This module provides the main CoPawAgent class built on ReActAgent,
with integrated tools, skills, and memory management.
"""
import json
import logging
import os
import asyncio
import time
from typing import Any, List, Optional, Type

from agentscope.agent import ReActAgent
from agentscope.message import Msg, TextBlock
from agentscope.tool import Toolkit
from pydantic import BaseModel

from .command_handler import CommandHandler
from .hooks import BootstrapHook, MemoryCompactionHook, ToolResultVLMPrepassHook
from .memory import CoPawInMemoryMemory
from .model_capabilities import supports_input_capability
from .model_factory import (
    create_model_and_formatter,
    create_model_from_config,
    create_text_and_vlm_models,
)
from .image_understanding import (
    get_last_message,
    run_media_understanding_prepass,
)
from .vision_prepass import format_vlm_prepass_context
from .vlm_auto_discover import auto_discover_vlm
from .prompt import build_system_prompt_from_working_dir
from .skills_manager import (
    ensure_skills_initialized,
    get_working_skills_dir,
    list_available_skills,
)
from .tools import (
    browser_use,
    create_memory_search_tool,
    desktop_screenshot,
    edit_file,
    execute_shell_command,
    get_current_time,
    read_file,
    send_file_to_user,
    write_file,
)
from .utils import process_file_and_media_blocks_in_message
from ..agents.memory import MemoryManager
from ..config import load_config
from ..constant import (
    MEMORY_COMPACT_KEEP_RECENT,
    MEMORY_COMPACT_RATIO,
    WORKING_DIR,
)
from ..providers import (
    get_active_llm_config,
    get_active_vlm_config,
    get_active_vlm_fallback_configs,
    load_providers_json,
)

logger = logging.getLogger(__name__)
_MEDIA_CAPABILITIES_ORDER = ("image", "audio", "video")


class CoPawAgent(ReActAgent):
    """CoPaw Agent with integrated tools, skills, and memory management.

    This agent extends ReActAgent with:
    - Built-in tools (shell, file operations, browser, etc.)
    - Dynamic skill loading from working directory
    - Memory management with auto-compaction
    - Bootstrap guidance for first-time setup
    - System command handling (/compact, /new, etc.)
    """

    def __init__(
        self,
        env_context: Optional[str] = None,
        enable_memory_manager: bool = True,
        mcp_clients: Optional[List[Any]] = None,
        memory_manager: MemoryManager | None = None,
        max_iters: int = 50,
        max_input_length: int = 128 * 1024,  # 128K = 131072 tokens
    ):
        """Initialize CoPawAgent.

        Args:
            env_context: Optional environment context to prepend to
                system prompt
            enable_memory_manager: Whether to enable memory manager
            mcp_clients: Optional list of MCP clients for tool
                integration
            memory_manager: Optional memory manager instance
            max_iters: Maximum number of reasoning-acting iterations
                (default: 50)
            max_input_length: Maximum input length in tokens for model
                context window (default: 128K = 131072)
        """
        self._env_context = env_context
        self._max_input_length = max_input_length
        self._mcp_clients = mcp_clients or []

        # Memory compaction threshold: configurable ratio of max_input_length
        self._memory_compact_threshold = int(
            max_input_length * MEMORY_COMPACT_RATIO,
        )

        # Initialize toolkit with built-in tools
        toolkit = self._create_toolkit()

        # Load and register skills
        self._register_skills(toolkit)

        # Build system prompt
        sys_prompt = self._build_sys_prompt()

        # Create text model and optional VLM models for capability-aware routing.
        self._active_llm_cfg = get_active_llm_config()
        self._active_vlm_cfg = get_active_vlm_config()
        self._active_vlm_fallback_cfgs = get_active_vlm_fallback_configs()
        self._vision_settings = load_providers_json().vision

        # Auto-discover a VLM if none is explicitly configured.
        if (
            self._active_vlm_cfg is None
            and not self._active_vlm_fallback_cfgs
            and self._active_llm_cfg is not None
            and not supports_input_capability(self._active_llm_cfg, "image")
        ):
            discovered = auto_discover_vlm(self._active_llm_cfg)
            if discovered is not None:
                logger.info(
                    "Auto-discovered VLM: %s/%s",
                    discovered.provider_id,
                    discovered.model,
                )
                self._active_vlm_cfg = discovered

        if self._active_llm_cfg is not None:
            model, self._vlm_model, formatter = create_text_and_vlm_models(
                self._active_llm_cfg,
                self._active_vlm_cfg,
            )
        else:
            # Keep backward-compatible env fallback behavior.
            model, formatter = create_model_and_formatter()
            self._vlm_model = None
        self._vlm_fallback_models = []
        for cfg in self._active_vlm_fallback_cfgs:
            fallback_model, _ = create_model_from_config(cfg)
            self._vlm_fallback_models.append((cfg, fallback_model))

        # Initialize parent ReActAgent
        super().__init__(
            name="Friday",
            model=model,
            sys_prompt=sys_prompt,
            toolkit=toolkit,
            memory=CoPawInMemoryMemory(),
            formatter=formatter,
            max_iters=max_iters,
        )

        # Setup memory manager
        self._setup_memory_manager(
            enable_memory_manager,
            memory_manager,
        )

        # Setup command handler
        self.command_handler = CommandHandler(
            agent_name=self.name,
            memory=self.memory,
            formatter=self.formatter,
            memory_manager=self.memory_manager,
            enable_memory_manager=self._enable_memory_manager,
        )

        # Register hooks
        self._register_hooks()

    def _create_toolkit(self) -> Toolkit:
        """Create and populate toolkit with built-in tools.

        Returns:
            Configured toolkit instance
        """
        toolkit = Toolkit()

        # Register built-in tools
        toolkit.register_tool_function(execute_shell_command)
        toolkit.register_tool_function(read_file)
        toolkit.register_tool_function(write_file)
        toolkit.register_tool_function(edit_file)
        toolkit.register_tool_function(browser_use)
        toolkit.register_tool_function(desktop_screenshot)
        toolkit.register_tool_function(send_file_to_user)
        toolkit.register_tool_function(get_current_time)

        return toolkit

    def _register_skills(self, toolkit: Toolkit) -> None:
        """Load and register skills from working directory.

        Args:
            toolkit: Toolkit to register skills to
        """
        # Check skills initialization
        ensure_skills_initialized()

        working_skills_dir = get_working_skills_dir()
        available_skills = list_available_skills()

        for skill_name in available_skills:
            skill_dir = working_skills_dir / skill_name
            if skill_dir.exists():
                try:
                    toolkit.register_agent_skill(str(skill_dir))
                    logger.debug("Registered skill: %s", skill_name)
                except Exception as e:
                    logger.error(
                        "Failed to register skill '%s': %s",
                        skill_name,
                        e,
                    )

    def _build_sys_prompt(self) -> str:
        """Build system prompt from working dir files and env context.

        Returns:
            Complete system prompt string
        """
        sys_prompt = build_system_prompt_from_working_dir()
        if self._env_context is not None:
            sys_prompt = self._env_context + "\n\n" + sys_prompt
        return sys_prompt

    def _setup_memory_manager(
        self,
        enable_memory_manager: bool,
        memory_manager: MemoryManager | None,
    ) -> None:
        """Setup memory manager and register memory search tool if enabled.

        Args:
            enable_memory_manager: Whether to enable memory manager
            memory_manager: Optional memory manager instance
        """
        # Check env var: if ENABLE_MEMORY_MANAGER=false, disable memory manager
        env_enable_mm = os.getenv("ENABLE_MEMORY_MANAGER", "")
        if env_enable_mm.lower() == "false":
            enable_memory_manager = False

        self._enable_memory_manager: bool = enable_memory_manager
        self.memory_manager = memory_manager

        # Register memory_search tool if enabled and available
        if self._enable_memory_manager and self.memory_manager is not None:
            self.memory_manager.chat_model = self.model
            self.memory_manager.formatter = self.formatter

            memory_search_tool = create_memory_search_tool(self.memory_manager)
            self.toolkit.register_tool_function(memory_search_tool)
            logger.debug("Registered memory_search tool")

    def _register_hooks(self) -> None:
        """Register pre-reasoning hooks for bootstrap and memory compaction."""
        # Bootstrap hook - checks BOOTSTRAP.md on first interaction
        config = load_config()
        bootstrap_hook = BootstrapHook(
            working_dir=WORKING_DIR,
            language=config.agents.language,
        )
        self.register_instance_hook(
            hook_type="pre_reasoning",
            hook_name="bootstrap_hook",
            hook=bootstrap_hook.__call__,
        )
        logger.debug("Registered bootstrap hook")

        # Memory compaction hook - auto-compact when context is full
        if self._enable_memory_manager and self.memory_manager is not None:
            memory_compact_hook = MemoryCompactionHook(
                memory_manager=self.memory_manager,
                memory_compact_threshold=self._memory_compact_threshold,
                keep_recent=MEMORY_COMPACT_KEEP_RECENT,
            )
            self.register_instance_hook(
                hook_type="pre_reasoning",
                hook_name="memory_compact_hook",
                hook=memory_compact_hook.__call__,
            )
            logger.debug("Registered memory compaction hook")

        # Tool-result VLM prepass hook - describe images in tool results
        # when the primary LLM is text-only and a VLM is available.
        if self._vlm_model is not None and (
            self._active_llm_cfg is None
            or not supports_input_capability(self._active_llm_cfg, "image")
        ):
            tool_result_vlm_hook = ToolResultVLMPrepassHook()
            self.register_instance_hook(
                hook_type="pre_reasoning",
                hook_name="tool_result_vlm_prepass_hook",
                hook=tool_result_vlm_hook.__call__,
            )
            logger.debug("Registered tool-result VLM prepass hook")

    def rebuild_sys_prompt(self) -> None:
        """Rebuild and replace the system prompt.

        Useful after load_session_state to ensure the prompt reflects
        the latest AGENTS.md / SOUL.md / PROFILE.md on disk.

        Updates both self._sys_prompt and the first system-role
        message stored in self.memory.content (if one exists).
        """
        self._sys_prompt = self._build_sys_prompt()

        for msg, _marks in self.memory.content:
            if msg.role == "system":
                msg.content = self.sys_prompt
            break

    async def register_mcp_clients(self) -> None:
        """Register MCP clients on this agent's toolkit after construction."""
        for client in self._mcp_clients:
            await self.toolkit.register_mcp_client(client)

    async def reply(
        self,
        msg: Msg | list[Msg] | None = None,
        structured_model: Type[BaseModel] | None = None,
    ) -> Msg:
        """Override reply to process file blocks and handle commands.

        Args:
            msg: Input message(s) from user
            structured_model: Optional pydantic model for structured output

        Returns:
            Response message
        """
        # OpenClaw-style hygiene: prune image blocks from already-answered
        # user turns in history to avoid stale multimodal payload buildup.
        self._prune_processed_history_images()

        # Process file and media blocks in messages
        if msg is not None:
            await process_file_and_media_blocks_in_message(msg)

        # Check if message is a system command
        last_msg = msg[-1] if isinstance(msg, list) else msg
        query = (
            last_msg.get_text_content() if isinstance(last_msg, Msg) else None
        )

        if self.command_handler.is_command(query):
            logger.info(f"Received command: {query}")
            msg = await self.command_handler.handle_command(query)
            await self.print(msg)
            return msg

        # Capability-aware routing: media input goes to prepass only when
        # primary LLM lacks required modalities.
        capabilities = self._message_media_capabilities(msg)
        should_route = bool(capabilities) and self._should_route_to_vlm(msg, capabilities)
        if should_route:
            raw_analyses: list[str] = []
            readable_analyses: list[str] = []
            failures: list[str] = []
            source = self._get_last_message(msg)
            user_text = source.get_text_content() if isinstance(source, Msg) else ""
            for capability in _MEDIA_CAPABILITIES_ORDER:
                if capability not in capabilities:
                    continue
                result = await self._run_media_understanding(msg, capability)
                if result.decision.outcome == "success" and result.analysis:
                    logger.info(
                        "%s prepass completed with %s/%s (%d item(s), %d attempt(s))",
                        capability,
                        result.used.provider_id if result.used else "unknown",
                        result.used.model if result.used else "unknown",
                        result.decision.selected_item_count,
                        len(result.decision.attempts),
                    )
                    raw_analyses.append(f"[{capability}] {result.analysis}")
                    readable = format_vlm_prepass_context(
                        capability,
                        result.analysis,
                        user_text=user_text,
                        include_user_text=False,
                    )
                    if readable:
                        readable_analyses.append(readable)
                else:
                    reason = result.decision.reason or result.decision.outcome
                    logger.warning(
                        "%s prepass unavailable (%s); continue with degraded context",
                        capability,
                        reason,
                    )
                    failures.append(f"{capability}: {reason}")

            if raw_analyses:
                msg = self._inject_vlm_analysis_for_llm(
                    msg,
                    raw_analysis="\n".join(raw_analyses),
                    readable_analysis=self._compose_media_understanding_context(
                        readable_analyses,
                        user_text=user_text,
                    ),
                )
            if failures:
                msg = self._inject_vlm_failure_for_llm(
                    msg,
                    "; ".join(failures),
                )
            # OpenClaw-aligned behavior: when routed through VLM because
            # primary LLM lacks multimodal input, do not forward raw media
            # blocks to the primary LLM request.
            msg = self._strip_media_blocks_for_primary_llm(msg)

        # Normal message processing (or no VLM configured)
        reply_msg = await super().reply(msg=msg, structured_model=structured_model)

        # Log the final AI reply
        if isinstance(reply_msg, Msg):
            reply_text = reply_msg.get_text_content() if hasattr(reply_msg, "get_text_content") else str(reply_msg.content)
            if reply_text:
                preview = reply_text.strip()
                if len(preview) > 500:
                    preview = preview[:497] + "..."
                logger.info("AI reply:\n%s", preview)

        return reply_msg

    def _prune_processed_history_images(self) -> None:
        """Prune image blocks in answered user turns from memory history."""
        entries = getattr(self.memory, "content", None)
        if not isinstance(entries, list) or not entries:
            return
        msgs: list[Msg] = []
        for entry in entries:
            if isinstance(entry, tuple) and len(entry) > 0 and isinstance(entry[0], Msg):
                msgs.append(entry[0])
        last_assistant_idx = -1
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].role == "assistant":
                last_assistant_idx = i
                break
        if last_assistant_idx < 0:
            return
        replaced_blocks = 0
        for i in range(last_assistant_idx):
            msg = msgs[i]
            if msg.role != "user" or not isinstance(msg.content, list):
                continue
            for j, block in enumerate(msg.content):
                if isinstance(block, dict) and block.get("type") == "image":
                    msg.content[j] = {
                        "type": "text",
                        "text": "[image data removed - already processed by model]",
                    }
                    replaced_blocks += 1

    @staticmethod
    def _compose_media_understanding_context(
        sections: list[str],
        *,
        user_text: str = "",
    ) -> str:
        """Compose sections in OpenClaw-style merge order."""
        clean_sections = [s.strip() for s in sections if isinstance(s, str) and s.strip()]
        if not clean_sections:
            return ""
        cleaned_user_text = (user_text or "").strip()
        if cleaned_user_text and len(clean_sections) > 1:
            return "User text:\n" + cleaned_user_text + "\n\n" + "\n\n".join(clean_sections)
        if cleaned_user_text and len(clean_sections) == 1:
            return "User text:\n" + cleaned_user_text + "\n\n" + clean_sections[0]
        return "\n\n".join(clean_sections)

    def _should_route_to_vlm(
        self,
        msg: Msg | list[Msg] | None,
        capabilities: set[str] | None = None,
    ) -> bool:
        caps = capabilities or self._message_media_capabilities(msg)
        if not caps:
            logger.debug("Media routing skipped: no media blocks")
            return False
        if self._active_llm_cfg is not None and all(
            supports_input_capability(self._active_llm_cfg, cap) for cap in caps
        ):
            logger.debug(
                "Media routing skipped: active LLM supports requested capabilities (%s/%s)",
                self._active_llm_cfg.provider_id,
                self._active_llm_cfg.model,
            )
            return False
        if self._vlm_model is not None:
            logger.debug("Vision routing enabled: using active VLM model")
            return True
        use_fallback = len(self._vlm_fallback_models) > 0
        if use_fallback:
            logger.debug("Vision routing enabled: using VLM fallback chain only")
        else:
            logger.debug("Vision routing skipped: no VLM configured")
        return use_fallback

    @staticmethod
    def _message_media_capabilities(msg: Msg | list[Msg] | None) -> set[str]:
        messages = (
            [msg] if isinstance(msg, Msg) else msg if isinstance(msg, list) else []
        )
        capabilities: set[str] = set()
        for message in messages:
            if not isinstance(message, Msg):
                continue
            if not isinstance(message.content, list):
                continue
            for block in message.content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type in {"image", "audio", "video"}:
                    capabilities.add(block_type)
        return capabilities

    async def _run_media_understanding(
        self,
        msg: Msg | list[Msg] | None,
        capability: str,
    ):
        settings = getattr(self._vision_settings, capability)
        attachments_mode, max_items = self._resolve_media_selection_policy(
            capability=capability,
            settings=settings,
        )

        return await run_media_understanding_prepass(
            msg=msg,
            capability=capability,
            enabled=settings.enabled,
            attachments_mode=attachments_mode,
            max_items=max_items,
            prompt_override=settings.prompt_override,
            timeout_seconds=settings.timeout_seconds,
            max_output_chars=settings.max_output_chars,
            active_vlm_cfg=self._active_vlm_cfg,
            vlm_fallback_models=self._vlm_fallback_models,
            active_vlm_model=self._vlm_model,
            run_with_runtime_model=self._run_runtime_prepass,
        )

    @staticmethod
    def _resolve_media_selection_policy(
        *,
        capability: str,
        settings: Any,
    ) -> tuple[str, int]:
        env_mode = os.getenv(
            f"COPAW_{capability.upper()}_ATTACHMENTS_MODE",
            "",
        ).strip().lower()
        # Keep old image env compatibility.
        if capability == "image" and not env_mode:
            env_mode = os.getenv("COPAW_VISION_ATTACHMENTS_MODE", "").strip().lower()
        attachments_mode = env_mode if env_mode in {"first", "all"} else settings.attachments_mode

        env_max_raw = os.getenv(f"COPAW_{capability.upper()}_MAX_ITEMS", "").strip()
        # Keep old image env compatibility.
        if capability == "image" and not env_max_raw:
            env_max_raw = os.getenv("COPAW_VISION_MAX_IMAGES", "").strip()

        default_max = getattr(settings, "max_images", None) or settings.max_items
        try:
            max_items = max(1, int(env_max_raw)) if env_max_raw else default_max
        except ValueError:
            max_items = default_max
        return attachments_mode, max_items

    async def _run_runtime_prepass(
        self,
        runtime_model,
        msg: Msg,
        timeout_seconds: int,
    ) -> str:
        prepass_reply = await asyncio.wait_for(
            self._reply_with_runtime_model(
                runtime_model,
                msg=msg,
                structured_model=None,
                persist_to_memory=False,
                suppress_output=True,
                disable_tools=True,
            ),
            timeout=max(1, timeout_seconds),
        )
        analysis = prepass_reply.get_text_content()
        if not analysis:
            raise RuntimeError("VLM prepass returned empty analysis")
        return analysis

    @staticmethod
    def _get_last_message(msg: Msg | list[Msg] | None) -> Msg:
        return get_last_message(msg)

    def _inject_vlm_analysis_for_llm(
        self,
        msg: Msg | list[Msg] | None,
        raw_analysis: str,
        readable_analysis: str = "",
    ) -> Msg | list[Msg] | None:
        """Inject media analysis context in a description-first style.

        OpenClaw-style behavior: avoid injecting raw machine JSON into the
        primary LLM prompt. Keep only human-readable description text.
        """
        target = self._get_last_message(msg)
        clean_readable = (readable_analysis or "").strip()
        if not clean_readable:
            clean_readable = "[Image]\nDescription:\n- No reliable visual details extracted."
        analysis_block = TextBlock(
            type="text",
            text=clean_readable,
        )

        if isinstance(target.content, list):
            target.content = [*target.content, analysis_block]
        elif isinstance(target.content, str):
            target.content = (
                f"{target.content}\n\n[Vision analysis from helper model]\n"
                f"{analysis_block.text}\n[End vision analysis]"
            )
        else:
            target.content = [analysis_block]
        return msg

    def _inject_vlm_failure_for_llm(
        self,
        msg: Msg | list[Msg] | None,
        error_text: str,
    ) -> Msg | list[Msg] | None:
        """Inject graceful degradation note when VLM prepass fails."""
        target = self._get_last_message(msg)
        if isinstance(target.content, list):
            target.content = [
                *target.content,
                TextBlock(
                    type="text",
                    text=(
                        "[VisionPrepassFailed]\n"
                        "Media analysis is unavailable for this turn. "
                        "Proceed with best-effort text-only reasoning and "
                        "state visual uncertainty explicitly.\n"
                        f"Reason: {error_text}\n"
                        "[/VisionPrepassFailed]"
                    ),
                ),
            ]
        return msg

    @staticmethod
    def _strip_media_blocks_for_primary_llm(
        msg: Msg | list[Msg] | None,
    ) -> Msg | list[Msg] | None:
        """Remove image/audio/video blocks from latest user message."""
        target = get_last_message(msg)
        if not isinstance(target, Msg) or not isinstance(target.content, list):
            return msg
        before_count = len(target.content)
        target.content = [
            block
            for block in target.content
            if not (
                isinstance(block, dict)
                and block.get("type") in {"image", "audio", "video"}
            )
        ]
        return msg

    # ------------------------------------------------------------------
    # Override _acting / _reasoning for detailed terminal logging
    # ------------------------------------------------------------------

    async def _reasoning(self, tool_choice=None) -> Msg:
        """Override to log LLM reasoning output to terminal."""
        msg = await super()._reasoning(tool_choice=tool_choice)

        text_parts = []
        tool_calls = []
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_calls.append(block)

        if text_parts:
            text = "".join(text_parts).strip()
            if text:
                logger.info("LLM reasoning:\n%s", text)

        for tc in tool_calls:
            args_str = json.dumps(
                tc.get("input", {}), ensure_ascii=False, indent=2,
            )
            logger.info(
                "Tool call: %s(%s)",
                tc.get("name", "?"),
                args_str,
            )

        return msg

    async def _acting(self, tool_call) -> dict | None:
        """Override to log tool inputs and outputs to terminal."""
        name = tool_call.get("name", "unknown")
        args = tool_call.get("input", {})
        args_str = json.dumps(args, ensure_ascii=False, indent=2)

        logger.info(">>> Tool call: %s\n%s", name, args_str)
        t0 = time.monotonic()

        result = await super()._acting(tool_call)

        elapsed = time.monotonic() - t0

        # Extract the tool result text from memory (last entry added by super)
        output_summary = self._summarize_tool_output(name)
        logger.info(
            "<<< Tool result: %s (%.1fs)\n%s",
            name,
            elapsed,
            output_summary,
        )
        return result

    def _summarize_tool_output(self, tool_name: str) -> str:
        """Extract a loggable summary of the last tool result from memory."""
        entries = getattr(self.memory, "content", None)
        if not entries:
            return "(no output captured)"

        for entry in reversed(entries):
            msg = entry[0] if isinstance(entry, tuple) else entry
            if not isinstance(msg, Msg) or not isinstance(msg.content, list):
                continue
            for block in msg.content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if block.get("name") != tool_name:
                    continue
                output = block.get("output", [])
                if not isinstance(output, list):
                    return str(output)[:2000]
                parts: list[str] = []
                for ob in output:
                    if not isinstance(ob, dict):
                        parts.append(str(ob)[:500])
                        continue
                    if ob.get("type") == "text":
                        text = ob.get("text", "")
                        if len(text) > 1000:
                            text = text[:997] + "..."
                        parts.append(text)
                    elif ob.get("type") == "image":
                        src = ob.get("source", {})
                        if isinstance(src, dict) and src.get("url"):
                            parts.append(f"[Image: {src['url'][:200]}]")
                        elif isinstance(src, dict) and src.get("type") == "base64":
                            parts.append("[Image: base64 data]")
                        else:
                            parts.append("[Image]")
                    else:
                        parts.append(f"[{ob.get('type', '?')}]")
                return "\n".join(parts) if parts else "(empty output)"
        return "(tool result not found in memory)"

    async def _reply_with_runtime_model(
        self,
        runtime_model,
        msg: Msg | list[Msg] | None,
        structured_model: Type[BaseModel] | None,
        persist_to_memory: bool = True,
        suppress_output: bool = False,
        disable_tools: bool = False,
    ) -> Msg:
        original_model = self.model
        old_memory_chat_model = None
        original_memory_len = len(self.memory.content)
        original_toolkit = self.toolkit
        original_print = self.print
        if self.memory_manager is not None:
            old_memory_chat_model = self.memory_manager.chat_model

        self.model = runtime_model
        if disable_tools:
            self.toolkit = Toolkit()
        if suppress_output:
            async def _silent_print(*_args, **_kwargs):
                return None
            self.print = _silent_print
        if self.memory_manager is not None:
            self.memory_manager.chat_model = runtime_model
        try:
            return await super().reply(msg=msg, structured_model=structured_model)
        finally:
            if not persist_to_memory and len(self.memory.content) > original_memory_len:
                self.memory.content = self.memory.content[:original_memory_len]
            self.model = original_model
            self.toolkit = original_toolkit
            self.print = original_print
            if self.memory_manager is not None:
                self.memory_manager.chat_model = old_memory_chat_model
