# -*- coding: utf-8 -*-
"""QwenPaw Agent - Main agent implementation.

This module provides the main QwenPawAgent class built on ReActAgent,
with integrated tools, skills, and memory management.

Agent construction is fully delegated to :class:`AgentBuilder` — the
agent accepts all dependencies (model, prompt, toolkit, middlewares)
as constructor parameters and does not build them internally.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING

from agentscope.agent import Agent, ContextConfig, ReActConfig
from agentscope.event import (
    ModelCallEndEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
)
from agentscope.message import HintBlock, Msg, TextBlock
from agentscope.middleware import MiddlewareBase
from agentscope.model import ChatModelBase, FinishedReason
from agentscope.state import AgentState
from agentscope.tool import Toolkit
from agentscope.workspace import Offloader

from .skill_system import get_workspace_skills_dir
from ..modes.coding import CodingModeMixin
from ..utils.io_utils import run_sync_io
from ..constant import (
    LOOP_CONTINUATION_MESSAGE_TAG,
    MEDIA_UNSUPPORTED_PLACEHOLDER,
    QWENPAW_MESSAGE_TAG_KEY,
    SCROLL_MIDDLE_CONTEXT_KEY,
    WORKING_DIR,
)
from ..loop.gates import StopAction, StopHandlerResult
from ..providers.error_utils import extract_status_code
from ..providers.model_capability_cache import get_capability_cache
from ..utils.tool_call_extra import (
    collect_transient_tool_call_extras,
    persist_tool_call_extras,
)

if TYPE_CHECKING:
    from .context.scroll.manager import ScrollContextManager
    from ..config.config import AgentProfileConfig

logger = logging.getLogger(__name__)


def _effective_artifact_retention_days(light_context_config: Any) -> int:
    """Return the independently configured tool-result artifact lifetime."""
    return (
        light_context_config.tool_result_pruning_config.offload_retention_days
    )


class QwenPawAgent(CodingModeMixin, Agent):
    """QwenPaw Agent with integrated tools, skills, and memory management.

    This agent extends agentscope 2.0 ``Agent`` with:
    - Built-in tools (shell, file operations, browser, etc.)
    - Dynamic skill loading from working directory
    - Memory management with auto-compaction
    - Bootstrap guidance for first-time setup
    - Tool-guard security (via ``PolicyGuardedTool.check_permissions``)
    - Coding Mode features: Inline Diff (via CodingModeMixin)
    """

    def __init__(
        self,
        *,
        name: str,
        model: ChatModelBase,
        system_prompt: str,
        toolkit: Toolkit,
        react_config: ReActConfig,
        middlewares: list[MiddlewareBase],
        agent_config: "AgentProfileConfig",
        workspace_dir: Path | None = None,
        request_context: dict[str, str] | None = None,
        offloader: Offloader | None = None,
        context_config: ContextConfig | None = None,
        scroll_context: "ScrollContextManager",
        effective_skills: list[str] | None = None,
        governor: Any = None,
    ):
        """Initialize QwenPawAgent.

        All construction dependencies (model, prompt, toolkit, middlewares)
        are provided externally by :class:`AgentBuilder`. The agent does
        not build any of these internally.
        """
        self._agent_config = agent_config
        self._request_context = dict(request_context or {})
        self._workspace_dir = workspace_dir
        self._language = agent_config.language
        # Scroll owns context state while this Agent subclass adapts it to
        # AgentScope's protected extension hooks.
        self._scroll_context = scroll_context

        # Register skills metadata on toolkit
        self._register_skills(toolkit, effective_skills=effective_skills or [])

        self._governor = governor
        self._gate_pending_stop = None

        super().__init__(
            name=name,
            model=model,
            system_prompt=system_prompt,
            toolkit=toolkit,
            react_config=react_config,
            middlewares=middlewares,
            offloader=offloader,
            context_config=context_config,
        )

        # Bypass agentscope's built-in permission engine — qwenpaw uses
        # its own PolicyGuardedTool.check_permissions for tool-guard.
        from agentscope.permission import PermissionMode

        self.state.permission_context.mode = PermissionMode.BYPASS

        self._register_tool_call_hooks()

    async def compress_context(
        self,
        context_config: Any = None,
        instructions: HintBlock | None = None,
    ) -> None:
        """Run context compression through AgentScope's middleware chain.

        ``_compress_context_impl`` is AgentScope's extension point beneath
        ``on_compress_context`` middlewares. Keeping the public entry point on
        the base path ensures memory and plugin middlewares observe Scroll.
        """
        # ── Always sanitize tool messages before any model call ──
        # Orphan tool_result messages (whose tool_call was evicted by a
        # prior compression) can survive in context across session
        # boundaries. compress() itself only cleans during an active split;
        # if the context is already corrupted but under the trigger
        # threshold, the corrupt messages still reach the model → 400.
        # This unconditional guard runs on every compress_context() call
        # (which fires before every reasoning step), catching orphans that
        # leaked through any path: loaded sessions, pre-patch corruption,
        # or unaccounted edge cases.
        try:
            from .utils.tool_message_utils import _sanitize_tool_messages

            sanitized = _sanitize_tool_messages(self.state.context)
            if sanitized is not self.state.context:
                self.state.context = sanitized
        except Exception:
            pass

        await super().compress_context(
            context_config,
            instructions=instructions,
        )

    async def _compress_context_impl(
        self,
        context_config: Any = None,
        instructions: HintBlock | None = None,
    ) -> None:
        """Implement AgentScope's compression hook with Scroll."""
        # ``None`` is the automatic path used by AgentScope before reasoning.
        # An explicit config comes from callers such as ``/compact`` and must
        # remain usable even when automatic compaction is disabled.
        if context_config is None:
            try:
                light_context = self._agent_config.running.light_context_config
                compact_config = light_context.context_compact_config
                if not compact_config.enabled:
                    return
            except (AttributeError, TypeError):
                pass
        await self._scroll_context.compress(
            self,
            context_config,
            instructions=instructions,
        )

    def _save_to_context(self, blocks: Any, usage: Any = None) -> None:
        """Append blocks, then write them through to Scroll history."""
        block_list = list(blocks or [])
        tool_call_extras = collect_transient_tool_call_extras(block_list)

        super()._save_to_context(block_list, usage)
        if tool_call_extras:
            last_msg = self._get_last_msg()
            if last_msg is not None and last_msg.role == "assistant":
                persist_tool_call_extras(last_msg, tool_call_extras)
        self._scroll_context.on_save(self, block_list)

    def state_dict(self) -> dict:
        """Serialize all runtime state through AgentScope's ``AgentState``."""
        scroll_state = self._scroll_context.to_dict()
        self.state.middle_context[SCROLL_MIDDLE_CONTEXT_KEY] = scroll_state
        return {"state": self.state.model_dump(mode="json")}

    def load_state_dict(self, state_dict: dict, strict: bool = True) -> None:
        """Restore ``self.state`` from a dict produced by :meth:`state_dict`.

        Handles three formats:
        - **current**: Scroll state in ``AgentState.middle_context``
        - **early 2.0**: Scroll state in a top-level ``scroll`` key
        - **1.x legacy**: ``{"memory": {"content": [[msg, marks], ...],
          "_compressed_summary": "..."}}`` — converted on-the-fly so
          existing sessions survive the upgrade.
        """
        if not isinstance(state_dict, dict):
            if strict:
                raise KeyError("state_dict is not a dict")
            return

        # --- 2.0 format (preferred) ---
        raw = state_dict.get("state")
        if raw is not None:
            try:
                self._restore_agent_state(AgentState.model_validate(raw))
            except Exception as exc:
                raise KeyError(
                    f"Could not load AgentState from snapshot: {exc}",
                ) from exc
            # ── Sanitize loaded context: orphan tool_result messages can
            # persist in session JSON from an evicted tool_call and leak
            # across session boundaries when the session is reloaded.
            self._sanitize_loaded_context()
            # Accept the PR's early top-level checkpoint while converging all
            # new state on AgentScope's persisted middleware context.
            scroll = self.state.middle_context.get(
                SCROLL_MIDDLE_CONTEXT_KEY,
                state_dict.get("scroll"),
            )
            if scroll is not None:
                self._scroll_context.load_state(scroll)
                self._scroll_context.reconcile_loaded_context(self)
            return

        # --- 1.x legacy format: migrate ``memory`` → ``state`` ---
        memory_raw = state_dict.get("memory")
        if isinstance(memory_raw, dict):
            from qwenpaw.app.chats.utils import parse_legacy_memory_state

            msgs, summary = parse_legacy_memory_state(memory_raw)
            self._restore_agent_state(AgentState())
            self.state.context.extend(msgs)
            self.state.summary = summary
            # Same sanitize as 2.0 path above.
            self._sanitize_loaded_context()
            scroll = state_dict.get("scroll")
            if scroll is not None:
                self._scroll_context.load_state(scroll)
                self._scroll_context.reconcile_loaded_context(self)
            logger.info(
                "Migrated 1.x session: %d messages + summary(%d chars)",
                len(msgs),
                len(self.state.summary),
            )
            return

        if strict:
            raise KeyError(
                "state_dict has neither 'state' nor 'memory' key",
            )

    def _restore_agent_state(self, state: AgentState) -> None:
        """Replace state and keep AgentScope's permission engine in sync."""
        from agentscope.permission import PermissionEngine, PermissionMode

        state.permission_context.mode = PermissionMode.BYPASS
        self.state = state
        self._engine = PermissionEngine(state.permission_context)

    def _sanitize_loaded_context(self) -> None:
        """Strip orphan tool_result messages from the loaded context.

        Orphan tool_result messages (whose tool_call has been evicted)
        can persist in session JSON and leak across session boundaries
        when loaded by ``load_state_dict``.  Without sanitization here
        they reach the model and cause ``400 - Messages with role 'tool'
        must be a response to a preceding message with 'tool_calls'``.
        """
        try:
            from .utils.tool_message_utils import _sanitize_tool_messages

            self.state.context = _sanitize_tool_messages(
                self.state.context,
            )
        except Exception:
            # Best-effort: a corrupt context will be caught again by
            # compress_context() on the next reasoning cycle.
            pass

    async def close(self) -> None:
        """Shut down governor, release the history store, and clean up expired
        tool-result files."""
        gov = getattr(self, "_governor", None)
        if gov is not None:
            try:
                gov.stop()
            except Exception:
                logger.debug("governor stop failed", exc_info=True)

        # Scroll history: apply the retention window (if any) while the
        # connection is still open, then release it (db + -wal + -shm fds —
        # otherwise they accumulate across requests on a long-lived server).
        try:
            lcc = self._agent_config.running.light_context_config
            await run_sync_io(
                self._scroll_context.purge_old,
                lcc.scroll_config.history_retention_days,
            )
        except Exception:
            logger.debug("history retention purge failed", exc_info=True)
        try:
            await run_sync_io(self._scroll_context.close)
        except Exception:
            logger.debug("scroll context close failed", exc_info=True)

        offloader = getattr(self, "offloader", None)
        if offloader is not None and hasattr(
            offloader,
            "cleanup_expired",
        ):
            try:
                lcc = self._agent_config.running.light_context_config
                retention_days = _effective_artifact_retention_days(lcc)
                if retention_days > 0:
                    await run_sync_io(
                        offloader.cleanup_expired,
                        retention_days=retention_days,
                    )
            except Exception:
                logger.debug("offloader cleanup failed", exc_info=True)

    def _register_skills(
        self,
        toolkit: Toolkit,
        effective_skills: list[str],
    ) -> None:
        """Load and register skills from workspace directory.

        Skills are stored in ``toolkit._qp_skills`` (a dict) for downstream
        consumption (e.g. ``/skill_name`` slash commands in the runner).
        """
        if not hasattr(toolkit, "_qp_skills"):
            toolkit._qp_skills = {}  # pylint: disable=protected-access
        workspace_dir = self._workspace_dir or WORKING_DIR
        working_skills_dir = get_workspace_skills_dir(Path(workspace_dir))

        for skill_name in effective_skills:
            skill_dir = working_skills_dir / skill_name
            if skill_dir.exists():
                try:
                    # pylint: disable=protected-access
                    toolkit._qp_skills[skill_name] = {
                        "dir": str(skill_dir),
                    }
                    logger.debug("Registered skill: %s", skill_name)
                except Exception as e:
                    logger.error(
                        "Failed to register skill '%s': %s",
                        skill_name,
                        e,
                    )

    # ------------------------------------------------------------------
    # Media-block fallback: strip unsupported media blocks (image, audio,
    # video, file) from memory and retry when the model rejects them.
    # Unlike ``model_factory._fixup_media_list`` (which converts file
    # blocks to text placeholders so the user-facing message history
    # stays readable), this fallback strips them entirely — its purpose
    # is to make a previously-rejected request retryable, so leaving
    # residue would defeat the point.
    # ------------------------------------------------------------------

    _MEDIA_BLOCK_TYPES = {"image", "audio", "video", "file"}
    _MEDIA_MIME_PREFIXES = ("image/", "audio/", "video/")

    def _get_model_key(self) -> str | None:
        """Return the capability-cache key for the active model."""
        model = getattr(self, "model", None)
        return getattr(model, "model_key", None)

    def _model_rejects_media(self) -> bool:
        """Check the capability cache for a learned ``rejects_media`` flag."""
        key = self._get_model_key()
        if key is None:
            return False
        return get_capability_cache().get(key, "rejects_media", False)

    def _proactive_strip_media_blocks(self) -> int:
        """Proactively strip media blocks from memory before model call.

        Only called when the active model does not support multimodal.
        Returns the number of blocks stripped.
        """
        return self._strip_media_blocks_from_memory()

    def _uses_request_time_media_normalization(self) -> bool:
        """Return True when request-time normalization can handle media."""
        return getattr(self, "formatter", None) is not None

    def _set_formatter_media_strip(self, enabled: bool) -> None:
        """Toggle request-time media stripping on the active formatter."""
        formatter = getattr(self, "formatter", None)
        if formatter is None:
            return
        setattr(formatter, "_qwenpaw_force_strip_media", enabled)

    @staticmethod
    def _is_context_overflow_error(exc: Exception) -> bool:
        """Return whether *exc* is a provider 400 for an oversized input.

        A bare 400 is deliberately insufficient: malformed tool schemas,
        unsupported parameters, and media errors must keep their existing
        handling.  Prefer the structured status code when the SDK exposes it,
        with the rendered exception as a compatibility fallback for gateways
        that wrap the original response.
        """
        status = extract_status_code(exc)
        error_str = str(exc).lower()
        if status != 400 and "error code: 400" not in error_str:
            return False

        overflow_markers = (
            "range of input length",
            "context length exceeded",
            "context_length_exceeded",
            "maximum context length",
            "maximum context window",
            "max input length",
            "input length should be",
            "input is too long",
            "prompt is too long",
            "prompt too long",
            "too many input tokens",
        )
        if any(marker in error_str for marker in overflow_markers):
            return True

        gemini_overflow_marker_groups = (
            (
                "input token count",
                "exceeds the maximum number of tokens allowed",
            ),
            (
                "input token count",
                "model only supports up to",
            ),
        )
        return any(
            all(marker in error_str for marker in marker_group)
            for marker_group in gemini_overflow_marker_groups
        )

    async def _call_model(
        self,
        messages: list[Msg],
        tools: list[dict],
        tool_choice: Any = None,
    ) -> Any:
        """Call the model, recovering once from a provider input overflow.

        When the provider rejects the request as too large, let the configured
        context manager attempt recovery. Rebuild and retry only when that
        recovery changed the model input. The retry calls AgentScope directly,
        so a second overflow propagates instead of entering a recovery loop.
        """
        try:
            return await super()._call_model(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
            )
        except Exception as exc:
            if not self._is_context_overflow_error(exc):
                raise

            before = len(getattr(self.state, "context", []) or [])
            logger.warning(
                "Model input exceeded the provider context limit; attempting "
                "one context recovery.",
            )
            input_changed = (
                await self._scroll_context.recover_from_context_overflow(self)
            )
            if not input_changed:
                logger.warning(
                    "Context-overflow recovery did not change the model "
                    "input; skipping the retry.",
                )
                raise
            after = len(getattr(self.state, "context", []) or [])

            # The original `messages` list was prepared before compaction and
            # can still reference evicted turns.  Always rebuild it from the
            # updated agent state before retrying.
            refreshed = await self._prepare_model_input()
            refreshed_messages = refreshed["messages"]
            refreshed_tools = refreshed.get("tools", [])
            logger.info(
                "Context-overflow recovery rebuilt model input "
                "(messages %d -> %d).",
                before,
                after,
            )
            return await super()._call_model(
                messages=refreshed_messages,
                tools=refreshed_tools,
                tool_choice=tool_choice,
            )

    # pylint: disable=too-many-branches,too-many-statements
    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ):
        """Forward 2.0 ``_reasoning`` events with proactive media
        stripping, passive bad-request retry, and auto-continue on
        text-only responses."""

        # ── Inject background-tool results before each reasoning step ──
        await self._inject_pending_hints()

        # ── Pre-check: pending gate actions from previous iter ──
        from ..loop.gates.runner import check_pending_gates

        pending_stop = check_pending_gates(self)
        if pending_stop is not None:
            stop_text = pending_stop.reason or "Stopped by loop gate."
            block_id = uuid.uuid4().hex
            yield TextBlockStartEvent(
                reply_id=self.state.reply_id,
                block_id=block_id,
            )
            yield TextBlockDeltaEvent(
                reply_id=self.state.reply_id,
                block_id=block_id,
                delta=stop_text,
            )
            yield TextBlockEndEvent(
                reply_id=self.state.reply_id,
                block_id=block_id,
            )
            yield Msg(
                name=self.name,
                role="assistant",
                content=[
                    TextBlock(type="text", text=stop_text),
                ],
            )
            return

        # ── Proactive media stripping ──
        from .model_factory import _supports_multimodal_for_current_model

        should_strip = (
            not _supports_multimodal_for_current_model()
            or self._model_rejects_media()
        )
        if should_strip:
            if self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(True)
            else:
                n = self._proactive_strip_media_blocks()
                if n > 0:
                    logger.warning(
                        "Proactively stripped %d media block(s) before "
                        "_reasoning (model lacks multimodal support).",
                        n,
                    )

        # ── Model call with passive retry on media error ──
        final_msg: Msg | None = None
        pending_seen_ids = self._scroll_context.model_input_tool_result_ids(
            self,
        )

        def acknowledge_seen_results(evt: Any) -> None:
            """Acknowledge inputs only after a completed model request."""
            if (
                isinstance(evt, ModelCallEndEvent)
                and evt.finished_reason != FinishedReason.INTERRUPTED
            ):
                self._scroll_context.acknowledge_model_input_tool_results(
                    pending_seen_ids,
                )

        try:
            async for evt in super()._reasoning(tool_choice=tool_choice):
                acknowledge_seen_results(evt)
                if isinstance(evt, Msg):
                    final_msg = evt
                else:
                    yield evt
        except Exception as e:
            if not self._is_bad_request_or_media_error(e):
                raise

            model_key = self._get_model_key()
            if model_key:
                get_capability_cache().learn(
                    model_key,
                    "rejects_media",
                    True,
                )
            logger.warning(
                "_reasoning failed with media error (%s); "
                "stripping media and retrying.",
                e,
            )
            if self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(True)
            else:
                self._strip_media_blocks_from_memory()

            try:
                async for evt in super()._reasoning(
                    tool_choice=tool_choice,
                ):
                    acknowledge_seen_results(evt)
                    if isinstance(evt, Msg):
                        final_msg = evt
                    else:
                        yield evt
            finally:
                if self._uses_request_time_media_normalization():
                    self._set_formatter_media_strip(False)
        else:
            if should_strip and self._uses_request_time_media_normalization():
                self._set_formatter_media_strip(False)

        # ── Stop Hook: run every iteration ──
        stop_result = await self._run_stop_handlers(final_msg)

        if final_msg is None:
            from ..loop.gates.runner import apply_stop_result

            apply_stop_result(
                self,
                stop_result,
                is_tool_call=True,
            )
            return

        # Model produced text (wants to stop).
        if stop_result.action == StopAction.INTERRUPT_AND_CONTINUE:
            logger.info(
                "Stop handler BLOCKED exit: %s",
                stop_result.reason,
            )
            continuation = (
                stop_result.continuation_message
                or "Continue working on the task."
            )
            continuation_metadata = stop_result.continuation_metadata or {
                QWENPAW_MESSAGE_TAG_KEY: (LOOP_CONTINUATION_MESSAGE_TAG),
            }
            self.state.context.append(
                Msg(
                    name="user",
                    role="user",
                    content=[
                        TextBlock(
                            type="text",
                            text=continuation,
                        ),
                    ],
                    metadata=continuation_metadata,
                ),
            )
            return  # outer loop continues

        yield stop_result.final_message or final_msg

    @staticmethod
    def _is_content_safety_error(exc: Exception) -> bool:
        """Return True for provider-side content safety rejections."""
        error_str = str(exc).lower()
        safety_markers = (
            "new_sensitive",
            "image is sensitive",
            "content policy",
            "content_policy",
            "moderation",
            "content_safety",
            "safety_filter",
            "(1026)",
        )
        return any(marker in error_str for marker in safety_markers)

    @staticmethod
    def _is_bad_request_or_media_error(exc: Exception) -> bool:
        """Return True only for errors that genuinely look media-related.

        A bare 400 is no longer sufficient — provider gateways return
        400 for many unrelated reasons (request too large, malformed
        block fields, exceeded context length) and treating them all as
        "media rejected" poisons the capability cache, causing
        subsequent requests to silently drop user-uploaded images.
        """
        error_str = str(exc).lower()

        # Veto: content safety/moderation rejections are about a
        # particular input, not about whether the model supports media.
        if QwenPawAgent._is_content_safety_error(exc):
            return False

        # Veto: errors clearly about request size / context length are
        # never about media support — stripping media may incidentally
        # make the next request fit, but it's a coincidence, not a
        # learned capability.
        size_signals = (
            "too large",
            "toolarge",
            "max bytes",
            "request body",
            "context length",
            "context_length",
            "maximum context",
            "max_tokens",
        )
        if any(sig in error_str for sig in size_signals):
            return False

        # Match only when the error message itself names a media modality.
        media_keywords = (
            "image",
            "audio",
            "video",
            "vision",
            "multimodal",
            "image_url",
        )
        return any(kw in error_str for kw in media_keywords)

    def _is_media_block(self, block: Any) -> bool:
        """Return True if *block* carries image/audio/video data."""
        if isinstance(block, dict):
            return block.get("type") in self._MEDIA_BLOCK_TYPES
        btype = getattr(block, "type", None)
        if btype in self._MEDIA_BLOCK_TYPES:
            return True
        if btype == "data":
            source = getattr(block, "source", None)
            mt = getattr(source, "media_type", "") or ""
            return mt.startswith(self._MEDIA_MIME_PREFIXES)
        return False

    # ------------------------------------------------------------------
    # Tool call enhancement: hint injection + hook registration
    # ------------------------------------------------------------------

    def _get_tool_coordinator(self) -> Any:
        """Return the ToolCoordinator from request_context, or None."""
        return (self._request_context or {}).get("tool_coordinator")

    async def _inject_pending_hints(self) -> None:
        """Pop background-tool hints and append them to agent context."""
        mgr = self._get_tool_coordinator()
        if mgr is None:
            return
        session_id = (self._request_context or {}).get("session_id", "")
        if not session_id:
            return
        hints = await mgr.pop_pending_hints(session_id)
        for hint in hints:
            self.state.context.append(hint)

    async def _reply(self, **kwargs: Any) -> Any:
        """Override kept as extension point; hint injection moved to
        ``_reasoning`` so each ReAct iteration picks up new hints."""
        async for evt in super()._reply(**kwargs):
            yield evt

    def _register_tool_call_hooks(self) -> None:
        """Register per-tool default timeouts on the ToolCoordinator."""
        mgr = self._get_tool_coordinator()
        if mgr is None:
            return

        from ..tool_calls import COORDINATOR_OWNED_EXEC_TIMEOUT_SECS

        # Sandbox / A2A HTTP still use a 24h coordinator-owned ceiling; expose
        # the same cap so extend/no_deadline cannot promise more than the
        # executor will actually allow.
        _owned_cap = float(COORDINATOR_OWNED_EXEC_TIMEOUT_SECS)
        mgr.hooks.register(
            "execute_shell_command",
            default_timeout_secs=60.0,
            max_internal_timeout_secs=_owned_cap,
        )
        mgr.hooks.register(
            "chat_with_agent",
            default_timeout_secs=300.0,
            max_internal_timeout_secs=_owned_cap,
        )
        mgr.hooks.register("check_agent_task", default_timeout_secs=30.0)
        mgr.hooks.register("grep_search", default_timeout_secs=30.0)
        mgr.hooks.register("glob_search", default_timeout_secs=15.0)
        mgr.hooks.register("ast_search", default_timeout_secs=35.0)
        mgr.hooks.register(
            "desktop_screenshot",
            default_timeout_secs=30.0,
        )
        for name in (
            "lsp_definition",
            "lsp_references",
            "lsp_rename",
            "lsp_hover",
            "lsp_diagnostics",
        ):
            mgr.hooks.register(name, default_timeout_secs=20.0)

        agent_id = (self._request_context or {}).get(
            "agent_id",
            self.name,
        )
        mgr.clear_agent_tool_timeouts(agent_id)
        builtin_tools = (
            getattr(
                getattr(self._agent_config, "tools", None),
                "builtin_tools",
                None,
            )
            or {}
        )
        for tool_name, cfg in builtin_tools.items():
            t = getattr(cfg, "timeout_seconds", None)
            if t is not None and t > 0:
                mgr.set_agent_tool_timeout(
                    agent_id,
                    tool_name,
                    float(t),
                )

    # ------------------------------------------------------------------
    # Stop Hook: loop continuation support
    # ------------------------------------------------------------------

    def _get_stop_handlers(self) -> list:
        """Retrieve stop handlers for this agent."""
        from ..app.agent_context import (
            get_current_agent_id,
        )
        from ..plugins.registry import PluginRegistry

        agent_id = get_current_agent_id()
        handlers = PluginRegistry.get_stop_handlers(
            agent_id=agent_id,
        )
        logger.debug(
            "stop_handlers: agent=%s count=%d",
            agent_id,
            len(handlers),
        )
        return handlers

    async def _run_stop_handlers(
        self,
        final_msg: Msg | None,
    ) -> StopHandlerResult:
        """Run registered stop handlers every iteration."""
        from ..loop.gates.runner import run_stop_handlers

        handlers = self._get_stop_handlers()
        return await run_stop_handlers(
            handlers,
            agent=self,
            final_msg=final_msg,
            iteration=self.state.cur_iter,
        )

    # pylint: disable=too-many-nested-blocks
    def _strip_media_blocks_from_memory(self) -> int:
        """Remove media blocks (image/audio/video/DataBlock) from all messages.

        Also strips media blocks nested inside ToolResultBlock outputs.
        Inserts placeholder text when stripping leaves content empty to
        avoid malformed API requests.

        Returns:
            Total number of media blocks removed.
        """
        total_stripped = 0

        for msg in self.state.context:
            if not isinstance(msg.content, list):
                continue

            new_content = []
            stripped_this_message = 0
            for block in msg.content:
                if self._is_media_block(block):
                    total_stripped += 1
                    stripped_this_message += 1
                    continue

                btype = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if btype == "tool_result":
                    output = (
                        block.get("output")
                        if isinstance(block, dict)
                        else getattr(block, "output", None)
                    )
                    if isinstance(output, list):
                        filtered = [
                            item
                            for item in output
                            if not self._is_media_block(item)
                        ]
                        stripped_count = len(output) - len(filtered)
                        total_stripped += stripped_count
                        stripped_this_message += stripped_count
                        if stripped_count > 0:
                            if isinstance(block, dict):
                                block["output"] = (
                                    filtered or MEDIA_UNSUPPORTED_PLACEHOLDER
                                )
                            else:
                                block.output = (
                                    filtered or MEDIA_UNSUPPORTED_PLACEHOLDER
                                )

                new_content.append(block)

            if not new_content and stripped_this_message > 0:
                new_content.append(
                    TextBlock(type="text", text=MEDIA_UNSUPPORTED_PLACEHOLDER),
                )

            msg.content = new_content

        return total_stripped
