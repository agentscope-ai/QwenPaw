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
import re
import uuid
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

from agentscope.agent import Agent, InjectionConfig, ReActConfig
from agentscope.agent._utils import Exit
from agentscope.event import (
    DataBlockDeltaEvent,
    DataBlockEndEvent,
    DataBlockStartEvent,
    ModelCallEndEvent,
    ReplyEndEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
    ThinkingBlockDeltaEvent,
    ThinkingBlockEndEvent,
    ThinkingBlockStartEvent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from agentscope.message import DataBlock, HintBlock, Msg, TextBlock
from agentscope.model import FinishedReason
from agentscope.state import AgentState
from agentscope.tool import Toolkit

from ..constant import (
    LOOP_CONTINUATION_MESSAGE_TAG,
    MEDIA_UNSUPPORTED_PLACEHOLDER,
    QWENPAW_MESSAGE_TAG_KEY,
    WORKING_DIR,
)
from ..loop.gates import StopAction, StopHandlerResult
from ..modes.coding import CodingModeMixin
from ..providers.error_utils import extract_status_code
from ..providers.fallback_chat_model import install_fallback_notice_sink
from ..providers.model_capability_cache import get_capability_cache
from ..runtime.reply_cycle import (
    InternalResultInput,
    TIMELINE_ORDER_METADATA_KEY,
)
from ..utils.io_utils import run_sync_io
from ..utils.tool_call_extra import (
    collect_transient_tool_call_extras,
    persist_tool_call_extras,
)
from .context.base import ContextManager
from .context.overflow_recovery import call_with_overflow_recovery
from .context.scroll.serialize import strip_headline
from .skill_system import get_workspace_skills_dir
from .utils.image_freezing import freeze_local_images_async
from .utils.message_request_normalizer import _is_media_block
from .utils.tool_call_coerce import _coerce_tool_input

if TYPE_CHECKING:
    from ..config.config import AgentProfileConfig

logger = logging.getLogger(__name__)


_GLOBAL_MEDIA_CAPABILITY_PATTERNS = (
    re.compile(r"\bmodel\s+is\s+text[- ]only\b", re.IGNORECASE),
    re.compile(
        r"\b(?:this|the|selected)?\s*model\b.{0,80}"
        r"\b(?:does not|doesn't|cannot|can't)\s+support\b.{0,40}"
        r"\b(?:media|multimodal)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmultimodal\s+(?:input|capability)?\s*"
        r"(?:is\s+)?not\s+enabled\b.{0,40}"
        r"\b(?:model|deployment)\b",
        re.IGNORECASE,
    ),
)

# A global capability rejection must also trigger the one-request fallback.
# Keep the global patterns as an explicit subset so the two classifiers
# cannot silently drift apart.
_EXPLICIT_UNSUPPORTED_MEDIA_PATTERNS = (
    *_GLOBAL_MEDIA_CAPABILITY_PATTERNS,
    re.compile(
        r"\b(?:this|the|selected)?\s*model\b.{0,80}"
        r"\b(?:does not|doesn't|cannot|can't)\s+support\b.{0,40}"
        r"\b(?:images?|audios?|videos?|vision|media|multimodal)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:image|audio|video|media)\s+(?:input|modality)\b"
        r".{0,40}\b(?:is|are)\s+not supported\b.{0,40}"
        r"\b(?:by|for)\b.{0,30}\b(?:model|deployment)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:image|audio|video|media)\b.{0,60}"
        r"\b(?:is|are)\s+not supported\b.{0,40}"
        r"\b(?:model|deployment)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bvision\s+is\s+not\s+enabled\s+for\s+"
        r"(?:this\s+)?(?:model|deployment)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bunsupported\s+modality\s*:?\s*(?:image|audio|video)\b",
        re.IGNORECASE,
    ),
)

# These messages reject only the current media shape, not the model's
# overall multimodal capability. They may justify a media-free retry, but
# must never poison the model-wide ``rejects_media`` cache.
_REQUEST_SCOPED_MEDIA_LIMIT_SIGNALS = (
    "multiple image",
    "multiple video",
    "multiple audio",
    "more than one image",
    "more than 1 image",
    "single image",
    "image count",
    "too many image",
    "animated image",
    "animated gif",
    "animation",
    "dimensions",
    "dimension",
    "resolution",
    "image width",
    "image height",
    "pixel",
    "megapixel",
    "frame rate",
    "sample rate",
    "video duration",
    "audio duration",
    "larger than",
    "smaller than",
    "per image",
    "file size",
)


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
        model: Any,
        system_prompt: str,
        toolkit: Toolkit,
        react_config: ReActConfig,
        middlewares: list,
        agent_config: "AgentProfileConfig",
        workspace_dir: Path | None = None,
        request_context: Optional[dict[str, str]] = None,
        run_input_mailbox: Any = None,
        reply_cycle_context: Any = None,
        offloader: Any = None,
        context_config: Any = None,
        context_manager: ContextManager | None = None,
        effective_skills: Optional[list[str]] = None,
        governor: Any = None,
    ):
        """Initialize QwenPawAgent.

        All construction dependencies (model, prompt, toolkit, middlewares)
        are provided externally by :class:`AgentBuilder`. The agent does
        not build any of these internally.
        """
        self._agent_config = agent_config
        self._request_context = dict(request_context or {})
        self._run_input_mailbox = run_input_mailbox
        self._reply_cycle_context = reply_cycle_context
        self._pending_results: list[InternalResultInput] = []
        self._observed_result_ids: set[str] = set()
        self._feedback_result_ids: set[str] = set()
        self._active_result_ids: set[str] = set()
        self._workspace_dir = workspace_dir
        self._language = agent_config.language
        # Optional context-management strategy. When None, the agent keeps its
        # native AgentScope compression (see compress_context /
        # _save_to_context).
        self._context_manager = context_manager

        # Register skills metadata on toolkit
        self._register_skills(toolkit, effective_skills=effective_skills or [])

        self._governor = governor
        self._gate_pending_stop = None

        # Tool name -> parameter schema index for tool-call input
        # coercion (issue #6839); rebuilt by ``_call_model`` from exactly
        # the tool list the model sees on every call.
        self._tool_schema_index: dict[str, dict[str, Any]] = {}

        init_kwargs: dict[str, Any] = {
            "name": name,
            "model": model,
            "system_prompt": system_prompt,
            "toolkit": toolkit,
            "react_config": react_config,
            "injection_config": InjectionConfig(
                inject_runtime_state=False,
            ),
            "middlewares": middlewares,
            "offloader": offloader,
        }
        if context_config is not None:
            init_kwargs["context_config"] = context_config
        super().__init__(**init_kwargs)

        # Bypass agentscope's built-in permission engine — qwenpaw uses
        # its own PolicyGuardedTool.check_permissions for tool-guard.
        from agentscope.permission import PermissionMode

        self.state.permission_context.mode = PermissionMode.BYPASS

        self._register_tool_call_hooks()

    def _append_pending_run_inputs(
        self,
        *,
        activate: bool,
        steer_only: bool = False,
    ) -> tuple[str, ...]:
        """Append one mailbox batch and optionally activate its reply cycle."""
        mailbox = self._run_input_mailbox
        if mailbox is None:
            pending = []
        elif steer_only:
            pending = mailbox.drain_steer()
        else:
            pending = mailbox.drain_after_reply()
        if not pending:
            return ()
        from ..runtime.message_convert import _request_input_to_msgs
        from ..constant import (
            CHAT_CONVERSATION_CONTEXT_KEY,
            CHAT_INPUT_TARGET_KEY,
        )
        from ..schemas import Message, Role

        input_ids: list[str] = []
        reply_cycle = getattr(self, "_reply_cycle_context", None)
        for item in pending:
            if isinstance(item, InternalResultInput):
                results = self._request_context.get("_background_results")
                if results is None or results.is_cancelled(item.work_id):
                    continue
                if item.work_id in self._feedback_result_ids:
                    results.replied(item.work_id, reply_cycle.run_id)
                    continue
                self._pending_results.append(item)
                input_ids.extend(item.input_ids)
                continue
            input_ids.append(item.idempotency_key)
            metadata = {
                "admission_mode": item.mode,
                "idempotency_key": item.idempotency_key,
                **(item.message_metadata or {}),
            }
            if item.timeline_order > 0:
                metadata[TIMELINE_ORDER_METADATA_KEY] = item.timeline_order
            if reply_cycle is not None:
                metadata.update(
                    {
                        "run_id": reply_cycle.run_id,
                        "timeline_group_id": item.idempotency_key,
                    },
                )
            if item.request_context:
                public_context = {
                    key: value for key, value in item.request_context.items()
                    if key not in {
                        CHAT_CONVERSATION_CONTEXT_KEY,
                        CHAT_INPUT_TARGET_KEY,
                    }
                }
                if public_context:
                    metadata["request_context"] = public_context
            if item.model_slot_override is not None:
                metadata["model_slot_override"] = item.model_slot_override
            messages = _request_input_to_msgs(
                [
                    Message(
                        role=Role.USER,
                        content=list(item.content_parts),
                        metadata=metadata,
                    ),
                ],
                conversation_context=(item.request_context or {}).get(
                    CHAT_CONVERSATION_CONTEXT_KEY, ""
                ),
                input_target=(item.request_context or {}).get(
                    CHAT_INPUT_TARGET_KEY, "",
                ),
            )
            for message in messages:
                self.state.context.append(message)
                if self._context_manager is not None:
                    self._context_manager.on_save(self, message.content)
        if not input_ids:
            return self._append_pending_run_inputs(
                activate=activate, steer_only=steer_only
            )
        if activate and reply_cycle is not None:
            self._activate_reply_cycle(tuple(input_ids))
        return tuple(input_ids)

    def accept_background_tool_result(self, work_id: str) -> None:
        """Join polling and push acknowledgement without a second observation."""
        results = self._request_context.get("_background_results")
        if results is None or results.is_cancelled(work_id):
            return
        work = results.works[work_id]
        current = self._reply_cycle_context.snapshot.responds_to_input_ids
        self._activate_reply_cycle(
            tuple(dict.fromkeys((*current, *work.input_ids)))
        )
        self._observed_result_ids.add(work_id)
        self._active_result_ids.add(work_id)
        results.observed(work_id, self._reply_cycle_context.run_id)

    async def observe_background_result(
        self, item: InternalResultInput
    ) -> bool:
        """Idempotent late observation, independent of the tool's old receipt."""
        results = self._request_context.get("_background_results")
        if results is None or results.is_cancelled(item.work_id):
            return False
        run_id = self._reply_cycle_context.run_id
        if item.work_id in self._feedback_result_ids:
            results.replied(item.work_id, run_id)
            return False
        if item.work_id not in self._observed_result_ids:
            message = item.message.model_copy(deep=True)
            message.name = (
                "background_result"
                if self.name != "background_result"
                else "background_observation"
            )
            message.metadata = {
                **(message.metadata or {}),
                "internal_result_id": item.work_id,
                **self._reply_cycle_context.snapshot.metadata(),
            }
            # Execution instructions are a separate typed runtime hint, not
            # part of the business result subsequently shown or spoken.
            from agentscope.message import HintBlock

            message.content = [
                HintBlock(
                    hint=(
                        "This is a result of the original request, not a new user request. "
                        "Report the result to the user; do not repeat completed work."
                    )
                ),
                *message.content,
            ]
            await self.observe(message)
            self._observed_result_ids.add(item.work_id)
            if self._context_manager is not None:
                self._context_manager.on_save(self, message.content)
        results.observed(item.work_id, run_id)
        self._active_result_ids.add(item.work_id)
        return True

    def _activate_reply_cycle(
        self,
        input_ids: tuple[str, ...],
    ) -> None:
        """Start one user reply cycle and reset reply-local loop state."""
        reply_cycle = getattr(self, "_reply_cycle_context", None)
        if reply_cycle is None:
            return
        reply_cycle.activate(input_ids)
        from ..loop.gates.runner import reset_reply_cycle_handlers

        reset_reply_cycle_handlers(self._get_stop_handlers())

    def _consume_pending_run_inputs(self, *, steer_only: bool = False) -> bool:
        """Append and activate the next eligible mailbox batch."""
        return bool(
            self._append_pending_run_inputs(
                activate=True,
                steer_only=steer_only,
            ),
        )

    def _next_action(self, final_msg: Msg | None = None) -> Any:
        """Advance queued input only after the current reply can exit."""
        mailbox = self._run_input_mailbox
        next_action = super()._next_action(final_msg)
        completed = False
        if isinstance(next_action, Exit):
            ends = [
                event
                for event in next_action.exit_events or []
                if isinstance(event, ReplyEndEvent)
            ]
            reason = (
                getattr(
                    ends[-1].finished_reason, "value", ends[-1].finished_reason
                )
                if ends
                else None
            )
            completed = reason == "completed"
            reply_failed = bool(
                final_msg is not None
                and (final_msg.metadata or {}).get("reply_error")
            )
            cycle = getattr(self, "_reply_cycle_context", None)
            if (
                completed
                and not reply_failed
                and final_msg is not None
                and cycle is not None
            ):
                final_ids = {
                    block.id
                    for block in final_msg.content
                    if hasattr(block, "id")
                }
                last_message = self._get_last_msg()
                if last_message is not None and isinstance(
                    last_message.content, list
                ):
                    for block in last_message.content:
                        if block.id in final_ids and getattr(
                            block, "metadata", None
                        ):
                            block.metadata["reply_phase"] = "final"
                    cycle.reply_content_changed(last_message)
            if completed and not reply_failed:
                results = (getattr(self, "_request_context", None) or {}).get(
                    "_background_results"
                )
                if results is not None:
                    for work_id in self._active_result_ids:
                        results.replied(
                            work_id, self._reply_cycle_context.run_id
                        )
                    self._feedback_result_ids.update(self._active_result_ids)
                    self._active_result_ids.clear()
            reply_cycle = getattr(self, "_reply_cycle_context", None)
            if reply_cycle is not None:
                reply_cycle.finish_reply(
                    "completed"
                    if completed and not reply_failed
                    else "failed"
                    if ends
                    else "waiting"
                )
        if completed and self._consume_pending_run_inputs():
            # The completed answer is already persisted and its public text
            # events have been emitted.  Re-evaluate from the newly appended
            # user input instead of ending the owning Agent run.
            return super()._next_action(None)
        if isinstance(next_action, Exit) and mailbox:
            mailbox.close()
        return next_action

    async def compress_context(
        self,
        context_config: Any = None,
        instructions: HintBlock | None = None,
    ) -> None:
        """Run context compression through AgentScope's middleware chain.

        The actual Scroll/native dispatch lives in
        :meth:`_compress_context_impl`, which is AgentScope's extension point
        beneath ``on_compress_context`` middlewares. Keeping the public entry
        point on the base path ensures memory and plugin middlewares observe
        both strategies consistently.
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

        if self._context_manager is None:
            try:
                lcc = self._agent_config.running.light_context_config
                if not lcc.context_compact_config.enabled:
                    return
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
        """Dispatch the middleware-wrapped compression implementation."""
        if self._context_manager is not None:
            if instructions is None:
                # Preserve compatibility with third-party managers that
                # implemented the original two-argument protocol.
                await self._context_manager.compress(self, context_config)
            else:
                await self._context_manager.compress(
                    self,
                    context_config,
                    instructions=instructions,
                )
            return

        await super()._compress_context_impl(
            context_config,
            instructions=instructions,
        )

    def _save_to_context(self, blocks: Any, usage: Any = None) -> None:
        """Append blocks, then let the context manager write them through."""
        from agentscope.message import (
            DataBlock,
            ToolCallBlock,
            ToolResultBlock,
        )

        block_list = list(blocks or [])
        tool_call_extras = collect_transient_tool_call_extras(block_list)
        reply_cycle = getattr(self, "_reply_cycle_context", None)
        if reply_cycle is not None:
            for block in block_list:
                owner = reply_cycle.output_snapshot
                if isinstance(block, ToolCallBlock):
                    owner = reply_cycle.bind_call(block.id)
                elif isinstance(block, ToolResultBlock):
                    owner = reply_cycle.owner_of_call(block.id) or owner
                metadata = dict(getattr(block, "metadata", None) or {})
                metadata.update(owner.metadata())
                if isinstance(block, (TextBlock, DataBlock)):
                    metadata["reply_phase"] = getattr(
                        self, "_model_reply_phase", "progress"
                    )
                try:
                    block.metadata = metadata
                except (AttributeError, ValueError) as exc:
                    raise RuntimeError(
                        "AgentScope content blocks must support metadata",
                    ) from exc

        super()._save_to_context(block_list, usage)
        last_msg = self._get_last_msg()
        if last_msg is not None and last_msg.role == "assistant":
            if reply_cycle is not None:
                metadata = dict(getattr(last_msg, "metadata", None) or {})
                # A single AgentScope assistant Msg may accumulate several
                # model/tool iterations. Keep only semantic reply ownership on
                # the Msg; visible occurrence order belongs to each block.
                metadata.update(reply_cycle.snapshot.metadata())
                last_msg.metadata = metadata
            if tool_call_extras:
                persist_tool_call_extras(last_msg, tool_call_extras)
            if reply_cycle is not None:
                reply_cycle.reply_content_changed(last_msg)
        if self._context_manager is not None:
            self._context_manager.on_save(self, block_list)

    # Session persistence calls state_dict/load_state_dict on the agent;
    # these round-trip through self.state (AgentState pydantic model).
    def state_dict(self) -> dict:
        """Serialize the agent's 2.0 ``AgentState`` to a JSON-safe dict."""
        state = getattr(self, "state", None)
        if state is None:
            return {}
        out = {"state": state.model_dump(mode="json")}
        # Persist the scroll manager's dedup bookkeeping + eviction index so a
        # resumed session doesn't re-append its restored window to history.db.
        cm = getattr(self, "_context_manager", None)
        if cm is not None and hasattr(cm, "to_dict"):
            out["scroll"] = cm.to_dict()
        reply_cycle = getattr(self, "_reply_cycle_context", None)
        if reply_cycle is not None:
            out["waiting_inputs"] = reply_cycle.waiting_inputs()
        if hasattr(self, "_observed_result_ids"):
            results = self._request_context.get("_background_results")
            retained = set(results.works) if results is not None else set()
            out["background_result_observations"] = sorted(
                self._observed_result_ids & retained
            )
            out["background_result_feedback"] = sorted(
                self._feedback_result_ids & retained
            )
        return out

    def load_state_dict(self, state_dict: dict, strict: bool = True) -> None:
        """Restore ``self.state`` from a dict produced by :meth:`state_dict`.

        Handles two formats:
        - **2.0**: ``{"state": {AgentState dump}}``
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
                self.state = AgentState.model_validate(raw)
            except Exception as exc:
                raise KeyError(
                    f"Could not load AgentState from snapshot: {exc}",
                ) from exc
            # ── Sanitize loaded context: orphan tool_result messages can
            # persist in session JSON from an evicted tool_call and leak
            # across session boundaries when the session is reloaded.
            self._sanitize_loaded_context()
            self._observed_result_ids = set(
                state_dict.get("background_result_observations", [])
            )
            self._feedback_result_ids = set(
                state_dict.get("background_result_feedback", [])
            )
            reply_cycle = getattr(self, "_reply_cycle_context", None)
            if reply_cycle is not None:
                reply_cycle.resume_inputs(state_dict.get("waiting_inputs", []))
            # Rehydrate the scroll manager's bookkeeping so the restored window
            # is recognized as already durable (no re-append on resume).
            cm = getattr(self, "_context_manager", None)
            scroll = state_dict.get("scroll")
            if (
                cm is not None
                and scroll is not None
                and hasattr(cm, "load_state")
            ):
                cm.load_state(scroll)
                if hasattr(cm, "reconcile_loaded_context"):
                    cm.reconcile_loaded_context(self)
            return

        # --- 1.x legacy format: migrate ``memory`` → ``state`` ---
        memory_raw = state_dict.get("memory")
        if isinstance(memory_raw, dict):
            from qwenpaw.app.chats.utils import parse_legacy_memory_state

            msgs, summary = parse_legacy_memory_state(memory_raw)
            self.state = AgentState()
            self.state.context.extend(msgs)
            self.state.summary = summary
            # Same sanitize as 2.0 path above.
            self._sanitize_loaded_context()
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
        cm = getattr(self, "_context_manager", None)
        if cm is not None:
            if hasattr(cm, "purge_old"):
                try:
                    lcc = self._agent_config.running.light_context_config
                    await run_sync_io(
                        cm.purge_old,
                        lcc.scroll_config.history_retention_days,
                    )
                except Exception:
                    logger.debug(
                        "history retention purge failed",
                        exc_info=True,
                    )
            if hasattr(cm, "close"):
                try:
                    await run_sync_io(cm.close)
                except Exception:
                    logger.debug(
                        "context manager close failed",
                        exc_info=True,
                    )

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

    def _model_rejects_audio(self) -> bool:
        """Check the capability cache for a learned audio rejection."""
        key = self._get_model_key()
        if key is None:
            return False
        return get_capability_cache().get(key, "rejects_audio", False)

    def _proactive_strip_media_blocks(self) -> int:
        """Proactively strip media blocks from memory before model call.

        Only called when the active model does not support multimodal.
        Returns the number of blocks stripped.
        """
        return self._strip_media_blocks_from_memory()

    def _uses_request_time_media_normalization(self) -> bool:
        """Return True when request-time normalization can handle media."""
        return self._get_active_formatter() is not None

    def _get_active_formatter(self) -> Any | None:
        """Resolve the formatter through current and legacy model layouts."""
        formatter = getattr(self, "formatter", None)
        if formatter is not None:
            return formatter

        current = getattr(self, "model", None)
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            formatter = getattr(current, "formatter", None)
            if formatter is not None:
                return formatter
            current = getattr(current, "_inner", None) or getattr(
                current,
                "_model",
                None,
            )
        return None

    def _set_formatter_media_strip(self, enabled: bool) -> None:
        """Toggle request-time media stripping on the active formatter."""
        formatter = self._get_active_formatter()
        if formatter is None:
            return
        setattr(formatter, "_qwenpaw_force_strip_media", enabled)

    def _set_formatter_audio_strip(self, enabled: bool) -> None:
        """Toggle request-time audio stripping on the active formatter."""
        formatter = self._get_active_formatter()
        if formatter is None:
            return
        setattr(formatter, "_qwenpaw_force_strip_audio", enabled)

    def _set_formatter_thinking_omit_ids(self, block_ids: set[str]) -> bool:
        """Propagate reasoning omissions through model wrappers."""
        model_setter = getattr(self.model, "set_thinking_omit_ids", None)
        if callable(model_setter):
            return bool(model_setter(set(block_ids)))

        formatter = self._get_active_formatter()
        if formatter is None:
            return False
        formatter_setter = getattr(formatter, "set_thinking_omit_ids", None)
        if callable(formatter_setter):
            return bool(formatter_setter(set(block_ids)))
        # Compatibility for third-party OpenAI-chat formatters that predate
        # the explicit interface but consume the QwenPaw extension attribute.
        setattr(formatter, "_qwenpaw_omit_thinking_ids", set(block_ids))
        return True

    def _last_wire_request_had_media(self) -> bool:
        """Return whether the last completed formatting emitted media."""
        formatter = self._get_active_formatter()
        if formatter is None:
            return False
        count = getattr(formatter, "_qwenpaw_last_wire_media_count", 0)
        return (
            isinstance(count, int)
            and not isinstance(count, bool)
            and (count > 0)
        )

    def _last_wire_request_had_audio(self) -> bool:
        """Return whether the last completed formatting emitted audio."""
        formatter = self._get_active_formatter()
        if formatter is None:
            return False
        count = getattr(formatter, "_qwenpaw_last_wire_audio_count", 0)
        return (
            isinstance(count, int)
            and not isinstance(count, bool)
            and (count > 0)
        )

    @staticmethod
    def _is_audio_fallback_error(exc: Exception) -> bool:
        """Return whether DashScope rejected the current audio payload."""
        error_str = " ".join(str(exc).lower().split())
        status = extract_status_code(exc)
        has_bad_request_status = status == 400 or "<400>" in error_str
        invalid_modal = all(
            marker in error_str
            for marker in (
                "incorrect modal",
                "audio",
                "was entered",
                "may not be supported by the model",
                "wrong position",
            )
        )
        return (
            has_bad_request_status
            and "internalerror.algo.invalidparameter" in error_str
            and invalid_modal
        )

    async def _prepare_model_input(self) -> dict[str, Any]:
        """Freeze local images before they enter a provider request."""
        await freeze_local_images_async(self.state.context)
        return await super()._prepare_model_input()

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
        self._index_tool_schemas(tools)
        return await call_with_overflow_recovery(
            super()._call_model,
            partial(self._recover_model_overflow, tool_choice=tool_choice),
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )

    async def _recover_model_overflow(
        self,
        exc: Exception,
        tool_choice: Any,
    ) -> Any:
        """Compact rejected input and retry once through AgentScope."""
        context_manager = getattr(self, "_context_manager", None)
        if not isinstance(
            context_manager,
            ContextManager,
        ) or not self._is_context_overflow_error(exc):
            raise exc

        before = len(getattr(self.state, "context", []) or [])
        logger.warning(
            "Model input exceeded the provider context limit; attempting "
            "one context recovery.",
        )
        input_changed = await context_manager.recover_from_context_overflow(
            self,
        )
        if not input_changed:
            logger.warning(
                "Context-overflow recovery did not change the model "
                "input; skipping the retry.",
            )
            raise exc
        after = len(getattr(self.state, "context", []) or [])

        # The original `messages` list was prepared before compaction and
        # can still reference evicted turns.  Always rebuild it from the
        # updated agent state before retrying.
        refreshed = await self._prepare_model_input()
        refreshed_messages = refreshed["messages"]
        refreshed_tools = refreshed.get("tools", [])
        self._index_tool_schemas(refreshed_tools)
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

    def _index_tool_schemas(self, tools: list[dict] | None) -> None:
        """Index ``tool name -> parameter schema`` for input coercion.

        Built in :meth:`_call_model` from exactly the tool list handed to
        the model (issue #6839), so the coercion schema always matches
        what the model saw.  Looking schemas up through
        ``toolkit.check_tool_available`` at tool-call time instead would
        issue ``list_tools`` against every registered MCP client on
        every tool call.
        """
        index: dict[str, dict[str, Any]] = {}
        for tool in tools or []:
            func = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(func, dict):
                continue
            name = func.get("name")
            params = func.get("parameters")
            if isinstance(name, str) and isinstance(params, dict):
                index[name] = params
        self._tool_schema_index = index

    def _coerce_tool_call_input(self, tool_call: Any) -> None:
        """Coerce ``tool_call.input`` in place against the indexed schema.

        Models sometimes emit unquoted numbers/booleans for string-typed
        tool parameters (issue #6839); agentscope's shared validation
        rejects those values and every such tool call fails.  The
        rewrite happens on the block stored in the message, so the
        repaired input travels with the persisted context, and it runs
        before the permission check, so a call paused for user
        confirmation resumes already repaired.  No-op when the tool name
        is not indexed.
        """
        index = getattr(self, "_tool_schema_index", None)
        if not index:
            return
        if isinstance(tool_call, dict):
            name = tool_call.get("name")
        else:
            name = getattr(tool_call, "name", None)
        if not isinstance(name, str):
            return
        schema = index.get(name)
        if not isinstance(schema, dict):
            return
        if isinstance(tool_call, dict):
            raw_input = tool_call.get("input")
        else:
            raw_input = getattr(tool_call, "input", None)
        if not isinstance(raw_input, str):
            return
        coerced = _coerce_tool_input(raw_input, schema)
        if coerced == raw_input:
            return
        if isinstance(tool_call, dict):
            tool_call["input"] = coerced
        else:
            tool_call.input = coerced
        logger.info(
            "Coerced tool %r input to match string-typed schema fields "
            "(#6839)",
            name,
        )

    async def _execute_tool_call(
        self,
        tool_call: Any,
        kept_rules: Any | None = None,
    ):
        """Coerce the tool input, then delegate to the base funnel.

        ``Agent._execute_tool_call`` is the single funnel for tool-call
        execution — both the sequential and the concurrent paths reach
        it — and it runs immediately before agentscope parses and
        validates the input, which is where the #6839 failure happens.
        Coercing here covers every provider, not just OpenAI.

        The signature mirrors the base method exactly: the concurrent
        execution path calls this with two positional arguments
        (``tool_call`` and the batch-shared ``kept_rules`` accumulator),
        so accepting only ``tool_call`` raised ``TypeError`` on every
        concurrent tool call.
        """
        self._coerce_tool_call_input(tool_call)
        async for evt in super()._execute_tool_call(tool_call, kept_rules):
            yield evt

    # pylint: disable=too-many-branches,too-many-statements
    async def _reasoning(
        self,
        tool_choice: Literal["auto", "none", "required"] | None = None,
    ):
        """Forward 2.0 ``_reasoning`` events with proactive media
        stripping, passive bad-request retry, and auto-continue on
        text-only responses."""

        # agentscope drops ChatResponse.metadata during event conversion;
        # collect model-fallback transparency data out-of-band instead.
        fallback_sink = install_fallback_notice_sink()

        # A tool may have completed while the user added Voice input. Consume
        # it before building the next model request so no stale final reply is
        # streamed first. _next_action remains the completion-race fallback.
        self._consume_pending_run_inputs(steer_only=True)

        pending_results = getattr(self, "_pending_results", [])
        self._pending_results = []
        for result_input in pending_results:
            await self.observe_background_result(result_input)

        # ── Inject background-tool results before each reasoning step ──
        await self._inject_pending_hints()

        # ── Pre-check: pending gate actions from previous iter ──
        from ..loop.gates.runner import check_pending_gates

        pending_stop = check_pending_gates(self)
        if pending_stop is not None:
            reply_cycle = getattr(self, "_reply_cycle_context", None)
            if reply_cycle is not None:
                await reply_cycle.start_occurrence()
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

        # ModelInfo controls per-model request normalization. Only learned
        # rejections belong here; a global lookup can misclassify fallbacks.
        should_strip_media = self._model_rejects_media()
        should_strip_audio = (
            not should_strip_media and self._model_rejects_audio()
        )
        if should_strip_media:
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
        elif (
            should_strip_audio
            and self._uses_request_time_media_normalization()
        ):
            self._set_formatter_audio_strip(True)

        # ── Model call with passive retry on media error ──
        final_msg: Msg | None = None
        deferred_text_events: list[Any] = []
        context_manager = self._context_manager
        pending_seen_ids: set[str] = set()
        pending_seen_thinking_ids: set[str] = set()
        occurrence_started = False

        async def start_occurrence_for(evt: Any) -> None:
            nonlocal occurrence_started
            if occurrence_started or not isinstance(
                evt,
                (
                    TextBlockStartEvent,
                    TextBlockDeltaEvent,
                    TextBlockEndEvent,
                    ThinkingBlockStartEvent,
                    ThinkingBlockDeltaEvent,
                    ThinkingBlockEndEvent,
                    DataBlockStartEvent,
                    DataBlockDeltaEvent,
                    DataBlockEndEvent,
                    ToolCallStartEvent,
                    ToolCallDeltaEvent,
                    ToolCallEndEvent,
                ),
            ):
                return
            reply_cycle = getattr(self, "_reply_cycle_context", None)
            if reply_cycle is not None:
                await reply_cycle.start_occurrence()
            occurrence_started = True
        if context_manager is not None and hasattr(
            context_manager,
            "model_input_tool_result_ids",
        ):
            pending_seen_ids = context_manager.model_input_tool_result_ids(
                self,
            )
        if context_manager is not None and hasattr(
            context_manager,
            "model_input_thinking_block_ids",
        ):
            pending_seen_thinking_ids = (
                context_manager.model_input_thinking_block_ids(self)
            )

        def acknowledge_seen_inputs(evt: Any) -> None:
            """Acknowledge inputs only after a completed model request."""
            if isinstance(evt, ModelCallEndEvent):
                self._model_reply_phase = (
                    "progress"
                    if evt.finished_reason == FinishedReason.COMPLETED
                    else "incomplete"
                )
            if (
                isinstance(evt, ModelCallEndEvent)
                and evt.finished_reason == FinishedReason.COMPLETED
                and context_manager is not None
            ):
                if hasattr(
                    context_manager,
                    "acknowledge_model_input_tool_results",
                ):
                    context_manager.acknowledge_model_input_tool_results(
                        pending_seen_ids,
                    )
                if hasattr(
                    context_manager,
                    "acknowledge_model_input_thinking_blocks",
                ):
                    context_manager.acknowledge_model_input_thinking_blocks(
                        pending_seen_thinking_ids,
                    )

        try:
            self._inject_input_context()
            async for evt in super()._reasoning(tool_choice=tool_choice):
                await start_occurrence_for(evt)
                acknowledge_seen_inputs(evt)
                if isinstance(evt, Msg):
                    final_msg = evt
                elif isinstance(
                    evt,
                    (
                        TextBlockStartEvent,
                        TextBlockDeltaEvent,
                        TextBlockEndEvent,
                    ),
                ):
                    deferred_text_events.append(evt)
                else:
                    self._attach_fallback_notices(evt, fallback_sink)
                    yield evt
        except Exception as e:
            audio_fallback_retry = (
                self._last_wire_request_had_audio()
                and self._is_audio_fallback_error(e)
            )
            media_capability_retry = (
                self._last_wire_request_had_media()
                and self._is_explicit_media_capability_error(e)
            )
            if not (audio_fallback_retry or media_capability_retry):
                if self._uses_request_time_media_normalization():
                    if should_strip_media:
                        self._set_formatter_media_strip(False)
                    if should_strip_audio:
                        self._set_formatter_audio_strip(False)
                raise

            model_key = self._get_model_key()
            learn_global_rejection = (
                media_capability_retry
                and self._is_global_media_capability_error(e)
            )
            if audio_fallback_retry:
                logger.warning(
                    "_reasoning failed because the provider rejected an "
                    "audio payload (%s); stripping audio and retrying.",
                    e,
                )
                self._set_formatter_audio_strip(True)
            else:
                logger.warning(
                    "_reasoning failed because the provider explicitly "
                    "rejected the model's media capability (%s); stripping "
                    "media and retrying.",
                    e,
                )
                if self._uses_request_time_media_normalization():
                    self._set_formatter_media_strip(True)
                else:
                    self._strip_media_blocks_from_memory()

            try:
                deferred_text_events.clear()
                self._inject_input_context()
                async for evt in super()._reasoning(
                    tool_choice=tool_choice,
                ):
                    await start_occurrence_for(evt)
                    acknowledge_seen_inputs(evt)
                    if isinstance(evt, Msg):
                        final_msg = evt
                    elif isinstance(
                        evt,
                        (
                            TextBlockStartEvent,
                            TextBlockDeltaEvent,
                            TextBlockEndEvent,
                        ),
                    ):
                        deferred_text_events.append(evt)
                    else:
                        self._attach_fallback_notices(evt, fallback_sink)
                        yield evt
                if model_key and learn_global_rejection:
                    get_capability_cache().learn(
                        model_key,
                        "rejects_media",
                        True,
                    )
                if model_key and audio_fallback_retry:
                    get_capability_cache().learn(
                        model_key,
                        "rejects_audio",
                        True,
                    )
            finally:
                if self._uses_request_time_media_normalization():
                    self._set_formatter_audio_strip(False)
                    self._set_formatter_media_strip(False)
        else:
            if self._uses_request_time_media_normalization():
                if should_strip_media:
                    self._set_formatter_media_strip(False)
                if should_strip_audio:
                    self._set_formatter_audio_strip(False)

        for evt in deferred_text_events:
            self._attach_fallback_notices(evt, fallback_sink)
            yield evt

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

        outgoing_msg = stop_result.final_message or final_msg
        self._attach_fallback_notices(outgoing_msg, fallback_sink)
        if not self._has_public_reply(outgoing_msg):
            # An ended model request is not necessarily an answer. Diagnose
            # locally; another model/tool pass could repeat completed work.
            outgoing_msg.metadata = {
                **(outgoing_msg.metadata or {}),
                "reply_error": "empty_response",
            }
            notice = TextBlock(
                text="模型未生成可用答复。不会自动重跑已执行的操作，请稍后重试。",
                metadata={"reply_error": "empty_response"},
            )
            start = TextBlockStartEvent(
                reply_id=self.state.reply_id,
                block_id=notice.id,
            )
            await start_occurrence_for(start)
            self._model_reply_phase = "final"
            self._save_to_context([notice])
            outgoing_msg.content.append(notice)
            yield start
            yield TextBlockDeltaEvent(
                reply_id=self.state.reply_id,
                block_id=notice.id,
                delta=notice.text,
            )
            yield TextBlockEndEvent(
                reply_id=self.state.reply_id,
                block_id=notice.id,
            )
        yield outgoing_msg

    @staticmethod
    def _attach_fallback_notices(
        evt: Any,
        sink: dict[str, Any],
    ) -> None:
        """Copy pending model-fallback notices onto an outgoing event."""
        if evt is None or not sink["events"]:
            return
        metadata = getattr(evt, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            try:
                evt.metadata = metadata
            except (AttributeError, TypeError, ValueError):
                return
        metadata["qwenpaw_model_fallbacks"] = [
            dict(event) for event in sink["events"]
        ]
        if sink.get("actual_model"):
            metadata["qwenpaw_actual_model"] = dict(sink["actual_model"])

    def _has_public_reply(self, message: Msg) -> bool:
        if getattr(message, "structured_output", None) is not None or getattr(
            getattr(self.state, "reply_context", None),
            "structured_schema",
            None,
        ) is not None:
            return True
        return any(
            isinstance(block, DataBlock)
            or (
                isinstance(block, TextBlock)
                and strip_headline(block.text).strip()
            )
            for block in message.content
        )

    @staticmethod
    def _is_content_safety_error(exc: Exception) -> bool:
        """Return True for provider-side content safety rejections."""
        error_str = str(exc).lower()
        safety_markers = (
            "new_sensitive",
            "image is sensitive",
            "sensitive content",
            "content sensitivity",
            "content policy",
            "content_policy",
            "moderation",
            "content_safety",
            "safety_filter",
            "(1026)",
        )
        return any(marker in error_str for marker in safety_markers)

    @staticmethod
    def _is_explicit_media_capability_error(exc: Exception) -> bool:
        """Return whether an explicit media rejection permits fallback."""
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

        invalid_asset_signals = (
            "corrupt",
            "decode",
            "invalid image",
            "invalid media",
            "mime",
            "unsupported image format",
        )
        if any(signal in error_str for signal in invalid_asset_signals):
            return False

        return any(
            pattern.search(error_str) is not None
            for pattern in _EXPLICIT_UNSUPPORTED_MEDIA_PATTERNS
        )

    @staticmethod
    def _is_global_media_capability_error(exc: Exception) -> bool:
        """Return whether an error proves model-wide media rejection."""
        error_str = str(exc).lower()
        if any(
            signal in error_str
            for signal in _REQUEST_SCOPED_MEDIA_LIMIT_SIGNALS
        ):
            return False
        return any(
            pattern.search(error_str) is not None
            for pattern in _GLOBAL_MEDIA_CAPABILITY_PATTERNS
        )

    def _is_media_block(self, block: Any) -> bool:
        """Return True if *block* carries model media/document data."""
        return _is_media_block(block)

    # ------------------------------------------------------------------
    # Tool call enhancement: hint injection + hook registration
    # ------------------------------------------------------------------

    def _get_tool_coordinator(self) -> Any:
        """Return the ToolCoordinator from request_context, or None."""
        return (self._request_context or {}).get("tool_coordinator")

    def _inject_input_context(self) -> None:
        """Read committed updates at the model boundary, not at admission."""
        from ..runtime.input_context import INPUT_CONTEXT_INSTRUCTION

        mailbox = self._run_input_mailbox
        owner = mailbox.input_context if mailbox is not None else None
        cycle = getattr(self, "_reply_cycle_context", None)
        if owner is None or cycle is None:
            return
        snapshot = owner.capture(cycle.snapshot.responds_to_input_ids)
        if not snapshot:
            return
        if snapshot == getattr(self, "_last_input_context", "") and any(
            message.id == getattr(self, "_input_context_message_id", None)
            for message in self.state.context
        ):
            return
        message = Msg(
            name="chat_input_context", role="assistant",
            content=[HintBlock(
                source="chat_input_context",
                hint=INPUT_CONTEXT_INSTRUCTION + snapshot,
            )],
        )
        self.state.context.append(message)
        if self._context_manager is not None:
            self._context_manager.on_save(self, message.content)
        self._last_input_context = snapshot
        self._input_context_message_id = message.id

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
        mgr.hooks.register(
            "spawn_subagent",
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
        final_msg: Optional[Msg],
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
