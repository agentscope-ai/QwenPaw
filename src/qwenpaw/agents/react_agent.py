# -*- coding: utf-8 -*-
"""QwenPaw Agent - Main agent implementation.

This module provides the main QwenPawAgent class built on ReActAgent,
with integrated tools, skills, and memory management.

Agent construction is fully delegated to :class:`AgentBuilder` — the
agent accepts all dependencies (model, prompt, toolkit, middlewares)
as constructor parameters and does not build them internally.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from inspect import isasyncgen
from pathlib import Path
from typing import Any, Literal, Optional, TYPE_CHECKING

from agentscope.agent import Agent, InjectionConfig, ReActConfig
from agentscope.event import (
    ModelCallEndEvent,
    ReplyEndEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
)
from agentscope.message import HintBlock, Msg, TextBlock
from agentscope.model import FinishedReason
from agentscope.state import AgentState
from agentscope.tool import Toolkit

from .context.base import ContextManager
from .context.overflow_recovery import call_with_overflow_recovery
from .context.types import DecisionCompactionResult
from .injected_events import merge_injected_events
from .skill_system import get_workspace_skills_dir
from .utils.image_freezing import freeze_local_images_async
from .utils.message_request_normalizer import (
    _is_media_block,
    mark_media_omitted_after_overflow,
    omitted_media_marker,
)
from .utils.text_block_utils import (
    drop_empty_text_blocks,
    has_answer_content,
    sanitize_empty_text_blocks,
)
from ..providers.completion_reason import COMPLETION_METADATA_KEY
from ..utils.io_utils import run_async_to_completion, run_sync_io
from ..constant import (
    LOOP_CONTINUATION_MESSAGE_TAG,
    MEDIA_UNSUPPORTED_PLACEHOLDER,
    QWENPAW_MESSAGE_TAG_KEY,
    WORKING_DIR,
)
from ..loop.gates import StopAction, StopHandlerResult
from ..providers.error_utils import (
    extract_status_code,
    is_request_body_too_large,
)
from ..providers.fallback_chat_model import install_fallback_notice_sink
from ..providers.model_capability_cache import get_capability_cache
from ..providers.adapters.request_context import model_session
from ..utils.tool_call_extra import (
    collect_transient_tool_call_extras,
    persist_tool_call_extras,
)
from .utils.tool_call_coerce import _coerce_tool_input

if TYPE_CHECKING:
    from ..config.config import AgentProfileConfig

logger = logging.getLogger(__name__)


_VIDEO_COUNT_LIMIT_RE = re.compile(
    r"\bat most (\d+) video(?:\(s\)|s)?(?!\w)",
)
_AUDIO_COUNT_LIMIT_RE = re.compile(
    r"\bat most (\d+) audio(?:\(s\)|s)?(?!\w)",
)
_MULTIPLE_AUDIO_RE = re.compile(r"\bmultiple audio(?:\(s\)|s)?(?!\w)")
_IMAGE_COUNT_LIMIT_RE = re.compile(
    r"\bat most \d+ image(?:\(s\)|s)?(?!\w)",
)
# An error that names only audio or video, with no mention of images or the
# media payload: its own modality handler owns it, and the generic media path
# must not answer it by dropping images from history.
_MODALITY_ONLY_LIMIT_RE = re.compile(
    r"\bat most \d+ (?:audio|video)(?:\(s\)|s)?(?!\w)"
    r"|\bmultiple (?:audio|video)(?:\(s\)|s)?(?!\w)"
    r"|\b(?:unknown|unexpected)\s+(?:variant|field|part|content(?: type)?)"
    r"\s*[`'\"](?:audio|video)_url",
)
_VIDEO_PART_REJECTION_RE = re.compile(
    r"\b(?:unknown|unexpected)\s+(?:variant|field|part|content(?: type)?)"
    r"\s*[:=]?\s*[`'\"]?(?:video_url|input_video)\b",
)


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

# Asset-level media failures: the provider refused these bytes (undecodable
# data, an unsupported container, a declared MIME type it cannot render).
# They say nothing about the model, so they must never be learned as a
# capability loss — the payload classifier below owns the recovery.
_INVALID_MEDIA_ASSET_SIGNALS = (
    "corrupt",
    "decode",
    "invalid image",
    "invalid media",
    "mime",
    "unsupported image format",
)

# The gate for the media-free retry promised by
# ``_REQUEST_SCOPED_MEDIA_LIMIT_SIGNALS``: those signals reject the current
# media shape, and asset-level failures reject the current bytes. Both are
# recoverable by dropping the media, and neither says anything about the
# model's multimodal capability.
#
# Recovery is not optional here: the offending block is replayed from the
# stored context on every later turn, so without a media-free retry the
# provider keeps returning the same 400 and the session never heals.
# DeepSeek, for example, answers an image whose side exceeds its 8192 px
# limit with "You have uploaded an unsupported image" — the message names
# neither the limit nor the model's capability.
_MEDIA_PAYLOAD_REJECTION_SIGNALS = (
    *_REQUEST_SCOPED_MEDIA_LIMIT_SIGNALS,
    *_INVALID_MEDIA_ASSET_SIGNALS,
    "uploaded an unsupported image",
    "unsupported image",
    "unsupported media format",
    "unsupported media type",
    "unsupported image dimensions",
    "unsupported dimensions",
    "image is not valid",
    "image is invalid",
    "image too large",
    "image is too large",
    "image dimensions",
    # OpenAI-compatible gateways (LM Studio, issue #8171) report a zero
    # per-prompt media budget as "At most 0 video(s) may be provided ...".
    "at most 0 image",
    "at most 0 video",
    "at most 0 audio",
    # "Message content supports text content only. Images, audio and files
    # are not enabled." (issue #8290). The media-noun gate above keeps
    # unrelated "not enabled" errors out.
    "are not enabled",
)

# Payload rejections a smaller rendition cannot fix: the provider refused
# the media shape (an animation it cannot decode, more images than it
# accepts), not the bytes of one image. Retrying with tightened limits
# resends the same payload, so these belong to the media-free fallback.
_RESIZE_INEFFECTIVE_MEDIA_SIGNALS = (
    "animated image",
    "animated gif",
    "animation",
    "multiple image",
    "more than one image",
    "more than 1 image",
    "single image",
    "image count",
    "too many image",
)

# A payload rejection only counts when the provider actually names the media
# it refused; "invalid request" alone must keep its existing handling.
_MEDIA_PAYLOAD_MEDIA_NOUNS = (
    "image",
    "audio",
    "video",
    "media",
    "picture",
    "photo",
)


# A tool-schema validation error names the failing parameter path. Its
# message can contain incidental media words ("resize_image", "dimensions"),
# which must not turn it into a media rejection: no media was involved.
_TOOL_PARAMETERS_PATH_RE = re.compile(
    r"\btools\[\d+\]\.function\.parameters\b",
)


def _structured_error_text(exc: Exception) -> str:
    """Return the machine-readable part of an SDK error, lowercased.

    An SDK exception's ``str()`` is the sentence meant for a human; the
    failing parameter lives in ``body``. A schema error whose message
    mentions ``resize_image`` and ``dimensions`` therefore looks like a
    media rejection to a string-only check, so both are consulted.
    """
    body = getattr(exc, "body", None)
    if isinstance(body, (dict, list)):
        try:
            return " ".join(
                json.dumps(body, sort_keys=True, default=str).lower().split(),
            )
        except (TypeError, ValueError):
            return ""
    if isinstance(body, str):
        return " ".join(body.lower().split())
    return ""


def _effective_artifact_retention_days(light_context_config: Any) -> int:
    """Return the independently configured tool-result artifact lifetime."""
    return (
        light_context_config.tool_result_pruning_config.offload_retention_days
    )


class QwenPawAgent(Agent):
    """QwenPaw Agent with integrated tools, skills, and memory management.

    This agent extends agentscope 2.0 ``Agent`` with:
    - Built-in tools (shell, file operations, browser, etc.)
    - Dynamic skill loading from working directory
    - Memory management with auto-compaction
    - Bootstrap guidance for first-time setup
    - Tool-guard security (via ``PolicyGuardedTool.check_permissions``)
    """

    # Events a middleware wants shown in the chat stream (an injected
    # advisor plan, for example). ``__init__`` arms the queue only when a
    # middleware says it emits them. ``_reasoning`` then merges them live
    # into the events it forwards.
    _injected_events: asyncio.Queue[Any] | None = None

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
        self._model_session_id = uuid.uuid4().hex
        self._workspace_dir = workspace_dir
        if any(
            getattr(mw, "emits_injected_exchanges", False)
            for mw in middlewares
        ):
            self._injected_events = asyncio.Queue()
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

    @property
    def decision_compaction_enabled(self) -> bool:
        """Whether automatic context compaction may use the decision model."""
        lcc = self._agent_config.running.light_context_config
        return (
            lcc.context_compact_config.enabled
            and lcc.decision_compact_config.enabled
        )

    async def try_decision_compact(
        self,
        *,
        tokens: int,
        source_refs: dict[str, str] | None = None,
    ) -> DecisionCompactionResult:
        """Return semantic-preview commit status and its token measurement."""
        if not self.decision_compaction_enabled:
            return DecisionCompactionResult(changed=False, tokens_after=tokens)
        from .context.decision_compaction import DecisionCompactor

        compactor = getattr(self, "_decision_compactor", None)
        if compactor is None:
            compactor = self._decision_compactor = DecisionCompactor()
        return await compactor.compact(
            self,
            tokens=tokens,
            source_refs=source_refs,
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

        if self.decision_compaction_enabled:
            from .context import _as_internals as as_internals

            cfg = context_config or self.context_config
            target = cfg.trigger_ratio * self.model.context_size
            # Manual /compact and overflow recovery keep explicit eviction.
            if cfg.trigger_ratio >= self.context_config.trigger_ratio:
                kwargs = await as_internals.prepare_model_input(self)
                tokens = await as_internals.count_model_input_tokens(
                    self,
                    kwargs,
                )
                if tokens > target:
                    result = await self.try_decision_compact(tokens=tokens)
                    if result.changed and result.tokens_after <= target:
                        return

        await super()._compress_context_impl(
            context_config,
            instructions=instructions,
        )

    def _save_to_context(self, blocks: Any, usage: Any = None) -> None:
        """Append blocks, then let the context manager write them through."""
        # A reasoning-only turn arrives as an empty text block.  Persisting
        # it replays ``{"type": "output_text", "text": ""}`` on every later
        # request, which providers such as Volcengine Ark reject with
        # ``400 MissingParameter: input.content.text`` — one empty turn
        # would otherwise poison the rest of the session.
        block_list = drop_empty_text_blocks(list(blocks or []))
        tool_call_extras = collect_transient_tool_call_extras(block_list)

        super()._save_to_context(block_list, usage)
        if tool_call_extras:
            last_msg = self._get_last_msg()
            if last_msg is not None and last_msg.role == "assistant":
                persist_tool_call_extras(last_msg, tool_call_extras)
        if self._context_manager is not None:
            if getattr(self, "_defer_context_save", False):
                pending = getattr(self, "_pending_context_save", None)
                if pending is None:
                    pending = self._pending_context_save = []
                pending.extend(block_list)
            else:
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
        """Strip replay-breaking blocks from the loaded context.

        Orphan tool_result messages (whose tool_call has been evicted)
        can persist in session JSON and leak across session boundaries
        when loaded by ``load_state_dict``.  Without sanitization here
        they reach the model and cause ``400 - Messages with role 'tool'
        must be a response to a preceding message with 'tool_calls'``.

        Empty assistant text blocks are the same class of defect with a
        different block type: they make providers such as Volcengine Ark
        answer ``400 MissingParameter: input.content.text``.  Sessions
        poisoned before the save-time guard existed heal here.
        """
        try:
            from .utils.tool_message_utils import _sanitize_tool_messages

            self.state.context = sanitize_empty_text_blocks(
                _sanitize_tool_messages(self.state.context),
            )
        except Exception:
            # Best-effort: a corrupt context will be caught again by
            # compress_context() on the next reasoning cycle.
            pass

    async def _close_decision_compactor(self):
        """Release the optional model without interrupting other cleanup."""
        compactor = getattr(self, "_decision_compactor", None)
        if compactor is not None:
            try:
                await compactor.close()
            except Exception:
                logger.warning(
                    "Decision model client close failed",
                    exc_info=True,
                )
            else:
                self._decision_compactor = None

    async def close(self) -> None:
        """Shut down governor, release the history store, and clean up expired
        tool-result files."""
        await run_async_to_completion(self._close_resources())

    async def _close_resources(self) -> None:
        """Keep all cleanup alive until resources are released."""
        gov = getattr(self, "_governor", None)
        if gov is not None:
            try:
                gov.stop()
            except Exception:
                logger.debug("governor stop failed", exc_info=True)

        await self._close_decision_compactor()

        # Apply retention while history is available, then retire the request's
        # manager. Workspace-owned history stays open for subsequent requests;
        # standalone managers close their own connection.
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

    def _model_rejects_video(self) -> bool:
        """Check the capability cache for a learned video rejection."""
        key = self._get_model_key()
        if key is None:
            return False
        return get_capability_cache().get(key, "rejects_video", False)

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

    def _set_formatter_video_strip(self, enabled: bool) -> None:
        """Toggle request-time video stripping on the active formatter.

        Narrower than ``_qwenpaw_force_strip_media``: images and audio in the
        same request stay untouched, so a session that only tripped over an
        unsupported ``video_url`` part keeps its other media.
        """
        formatter = self._get_active_formatter()
        if formatter is None:
            return
        setattr(formatter, "_qwenpaw_force_strip_video", enabled)

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
            # Dynamic formatter implementations supply this optional method.
            # pylint: disable-next=not-callable
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

    def _last_wire_media_summary(self) -> list[str]:
        """Return labels for the media blocks the last formatting emitted.

        A rejection only says the request was unacceptable. These labels let
        the retry log name the images instead of saying "some media" while
        every image in the request is dropped.
        """
        formatter = self._get_active_formatter()
        if formatter is None:
            return []
        summary = getattr(
            formatter,
            "_qwenpaw_last_wire_media_summary",
            None,
        )
        if not isinstance(summary, list):
            return []
        return [str(item) for item in summary]

    #: Floor for the one-shot media-limit tightening. Below this the image is
    #: already unusable for most vision models, so another retry buys nothing.
    _MEDIA_LIMIT_SIDE_FLOOR = 512
    _MEDIA_LIMIT_BYTES_FLOOR = 128 * 1024

    def _active_media_limits(self) -> tuple[int, int]:
        """Return the active formatter's ``(max_image_side, max_bytes)``.

        ``(0, 0)`` means the formatter does not expose the fields or caps are
        disabled, which the caller reads as "cannot tighten".
        """
        formatter = self._get_active_formatter()
        if formatter is None:
            return (0, 0)
        side = getattr(formatter, "max_image_side", 0)
        max_bytes = getattr(formatter, "max_bytes", 0)
        if not isinstance(side, int) or isinstance(side, bool):
            return (0, 0)
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool):
            return (0, 0)
        return (side, max_bytes)

    def _tighten_media_limits(  # pylint: disable=too-many-return-statements,too-many-branches
        self,
        *,
        enforce_payload_check: bool = False,
    ) -> tuple[int, int] | None:
        """Halve the request-scoped media limits once, for a single retry.

        Only the request copy is affected: the stored message keeps its
        original bytes, so the user can still retrieve the full-resolution
        image. Returns the previous ``(max_image_side, max_bytes)`` pair, or
        ``None`` when there is nothing left to tighten or the limits were
        already tightened for this request.

        Each limit tightens only when it exceeds its own floor: the floor is
        a lower bound, not a new target, so a limit already below it must not
        be raised to it. When neither limit changes there is no smaller
        rendition to send, and the retry is skipped instead of resending the
        bytes the provider just refused.

        The side limit starts from the largest image this request actually
        carried. Halving a configured 8192 px cap to 4096 px does nothing to
        a 2000 px image the provider rejected for its dimensions; basing the
        new cap on that image gives the retry a genuinely smaller rendition.
        """
        formatter = self._get_active_formatter()
        if formatter is None:
            return None
        if getattr(formatter, "_qwenpaw_media_limits_tightened", False):
            return None
        side, max_bytes = self._active_media_limits()
        if side <= 0 and max_bytes <= 0:
            return None
        # No image in this request can be re-encoded: an HTTPS ``image_url``
        # is forwarded verbatim, so a smaller limit changes nothing and the
        # retry would carry the exact payload the provider just refused.
        # Returning ``None`` lets the caller fall back to omitting the media,
        # which is the only recovery this request has.
        if getattr(formatter, "_qwenpaw_last_wire_resizable_images", 0) == 0:
            return None
        observed_side = getattr(
            formatter,
            "_qwenpaw_last_wire_max_image_side",
            0,
        )
        if not isinstance(observed_side, int) or isinstance(
            observed_side,
            bool,
        ):
            observed_side = 0
        # A later model call in the same turn rebuilds the request from the
        # stored bytes, so it would send the original image again: the limits
        # were restored after the previous call. Reuse the rendition this
        # turn already got accepted, keyed by the size that needed it, rather
        # than resending what the provider already refused. If the observed
        # size moved (the earlier attempt was still too large), fall through
        # and compute a smaller target.
        #
        # The key is the source image, not the last rejected rendition: one
        # recovery chain walks 2000 -> 1000 -> 512, so the accepted limits
        # belong to the source that entered the chain. Keying the rendition
        # made the next call start from the original again and replay the
        # whole chain.
        if (
            getattr(self, "_media_rendition_source", None) is None
            and observed_side > 0
        ):
            self._media_rendition_source = observed_side
        accepted = getattr(self, "_media_rendition_target", None)
        if isinstance(accepted, tuple) and len(accepted) == 2:
            # pylint: disable=unpacking-non-sequence
            accepted_key, accepted_limits = accepted
            if observed_side > 0 and accepted_key == observed_side:
                formatter.max_image_side, formatter.max_bytes = accepted_limits
                setattr(formatter, "_qwenpaw_media_limits_tightened", True)
                return (side, max_bytes)
        # Never raise the configured cap. A single request can carry images
        # of different sizes (a 500 px animated GIF next to a 600 px PNG with
        # ``max_image_side=256``): the observed side belongs to the largest
        # image in the request, and adopting it as the new cap let that image
        # drag every other one above the configured limit (256 → 500 on the
        # retry). Only ever shrink below the configured cap.
        effective = side
        if observed_side > 0:
            effective = min(side, observed_side) if side > 0 else observed_side
        new_side = side
        if effective <= self._MEDIA_LIMIT_SIDE_FLOOR:
            # The image is already at the smallest side worth sending. Keep
            # that size instead of climbing back to the configured limit —
            # halving the limit here rebuilt a much larger target and the
            # retry would have carried a bigger image than the refused one.
            # Only the byte budget may move from this point on.
            new_side = effective
        else:
            new_side = max(self._MEDIA_LIMIT_SIDE_FLOOR, effective // 2)
        new_bytes = max_bytes
        if max_bytes > self._MEDIA_LIMIT_BYTES_FLOOR:
            new_bytes = max(self._MEDIA_LIMIT_BYTES_FLOOR, max_bytes // 2)
        if (new_side, new_bytes) == (side, max_bytes):
            return None
        # A smaller budget only helps when it is below the image actually on
        # the wire. Passing a 2 MiB limit down to 1 MiB cannot change a
        # 120-byte PNG: the retry would carry the identical payload and be
        # refused again. Compare against the encoded size instead of against
        # the previous limit.
        observed_bytes = getattr(
            formatter,
            "_qwenpaw_last_wire_max_image_bytes",
            0,
        )
        if not isinstance(observed_bytes, int) or isinstance(
            observed_bytes,
            bool,
        ):
            observed_bytes = 0
        if enforce_payload_check and new_side >= observed_side:
            if 0 < observed_bytes <= new_bytes:
                return None
        # A target identical to one this turn already sent cannot fix the
        # refusal: the formatted request would be byte-for-byte the same and
        # the provider would reject it again. Record every target this turn
        # tried and stop before replaying one.
        #
        # The side is the key, not the byte budget: once the rendition is at
        # its smallest side, halving the byte limit again re-encodes the same
        # pixels, so a 2000 -> 1000 -> 512 chain would keep retrying 512 while
        # only the byte number moved (the reviewer saw the last two requests
        # carry the identical 120-byte PNG).
        signature = (observed_side, new_side)
        history = getattr(self, "_media_tighten_history", None)
        if history is None:
            history = []
            self._media_tighten_history = history
        if signature in history:
            return None
        history.append(signature)
        formatter.max_image_side = new_side
        formatter.max_bytes = new_bytes
        setattr(formatter, "_qwenpaw_media_limits_tightened", True)
        # A target computed before the call is only a guess: the provider
        # may refuse it as well. It becomes reusable only once a call
        # completes, which _accept_media_rendition() records.
        self._media_rendition_pending = (observed_side, (new_side, new_bytes))
        return (side, max_bytes)

    def _accept_media_rendition(self) -> None:
        """Promote a pending rendition once the provider accepted it.

        ``_tighten_media_limits`` runs before the request, so the target it
        computes is a guess: the provider may refuse that size too. Caching
        the guess made every later call in the same turn replay the refused
        size (2000 → 1000 → 1000 → 1000). Only a completed call proves a
        rendition was accepted, and only the rendition that call actually
        carried may be keyed: when the provider refused 1000 px and accepted
        512 px, the reusable key is 512. Keying the pending guess recorded
        1000 and the next call rebuilt the size the provider had already
        rejected.
        """
        pending = getattr(self, "_media_rendition_pending", None)
        if pending is None:
            return
        formatter = self._get_active_formatter()
        observed = 0
        limits = pending[1]
        wire_images = -1
        if formatter is not None:
            wire_side = getattr(
                formatter,
                "_qwenpaw_last_wire_max_image_side",
                0,
            )
            if isinstance(wire_side, int) and not isinstance(wire_side, bool):
                observed = wire_side
            wire_count = getattr(
                formatter,
                "_qwenpaw_last_wire_media_count",
                0,
            )
            if isinstance(wire_count, int) and not isinstance(
                wire_count,
                bool,
            ):
                wire_images = wire_count
            limits = (formatter.max_image_side, formatter.max_bytes)
        # ``summary`` is only written by a completed ``format`` call, so a
        # list (even an empty one) proves the request was formatted and shows
        # what it carried. Without it there is nothing to prove either way.
        formatted = isinstance(
            getattr(formatter, "_qwenpaw_last_wire_media_summary", None),
            list,
        )
        if formatted and wire_images == 0:
            # The call succeeded with no media at all, so it proved nothing
            # about the rendition the pending step computed: caching it would
            # let a later call in the same turn resend the size the provider
            # never accepted (500 px recorded off a media-free success).
            self._media_rendition_pending = None
            self._media_rendition_target = None
            return
        key = getattr(self, "_media_rendition_source", None)
        if not key:
            key = observed if observed > 0 else pending[0]
        self._media_rendition_target = (key, limits)
        self._media_rendition_pending = None

    def _restore_media_limits(self, saved: tuple[int, int] | None) -> None:
        """Undo one :meth:`_tighten_media_limits` call."""
        if saved is None:
            return
        formatter = self._get_active_formatter()
        if formatter is None:
            return
        formatter.max_image_side, formatter.max_bytes = saved
        setattr(formatter, "_qwenpaw_media_limits_tightened", False)

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

    def _last_wire_request_had_video(self) -> bool:
        """Return whether the last completed formatting emitted video."""
        formatter = self._get_active_formatter()
        if formatter is None:
            return False
        count = getattr(formatter, "_qwenpaw_last_wire_video_count", 0)
        return (
            isinstance(count, int)
            and not isinstance(count, bool)
            and (count > 0)
        )

    @staticmethod
    def _is_audio_count_limit_error(exc: Exception) -> bool:
        """Return whether *exc* is an audio-count limit with any budget.

        ``Multiple audio(s): at most 1 audio(s) may be provided`` names only
        audio. Reaching the generic media path marked every block as
        omitted, so with one image and two audio clips in history the image
        the user was still asking about became unreachable. The audio-only
        strip handles it without learning a capability loss, which a
        request-shape limit must not do.
        """
        text = " ".join(str(exc).lower().split())
        if "image" in text or "media" in text:
            return False
        return bool(
            _AUDIO_COUNT_LIMIT_RE.search(text)
            or _MULTIPLE_AUDIO_RE.search(text),
        )

    @staticmethod
    def _is_audio_fallback_error(exc: Exception) -> bool:
        """Return whether the provider rejected the current audio payload.

        Recognized rejection shapes:

        1. DashScope modality error — HTTP 400 with
           ``InternalError.Algo.InvalidParameter`` and the
           "incorrect modal ... audio ..." wording.
        2. DashScope URL-shape error — HTTP 400 with
           "The provided URL does not appear to be valid" when local
           audio is serialized as raw base64 (issue #7015, first
           failure mode).
        3. llama.cpp ``llama-server`` (OpenAI-compatible) backed by a
           vision-only mmproj — HTTP 500 with
           "audio input is not supported".
        4. Providers that reject the ``input_audio`` wire part as an
           unknown / unexpected field or variant.
        5. LM Studio (OpenAI-compatible) serving a model without audio
           support — HTTP 400 "At most 0 audio(s) may be provided in one
           prompt." (issue #8171).

        Callers gate this classifier on ``_last_wire_request_had_audio()``,
        so shape 2 cannot misclassify genuinely malformed image/video
        URLs: those requests carry no audio blocks and never reach the
        audio-strip retry.
        """
        error_str = " ".join(str(exc).lower().split())
        status = extract_status_code(exc)
        has_bad_request_status = status == 400 or "<400>" in error_str
        rejects_unknown_audio_part = "input_audio" in error_str and any(
            marker in error_str
            for marker in (
                "unknown variant",
                "unknown field",
                "unknown part",
                "unexpected variant",
                "unexpected field",
            )
        )
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
        if rejects_unknown_audio_part:
            return True
        if (
            has_bad_request_status
            and "internalerror.algo.invalidparameter" in error_str
            and invalid_modal
        ):
            return True
        if (
            has_bad_request_status
            and "the provided url does not appear to be valid" in error_str
        ):
            return True
        if "audio input is not supported" in error_str:
            return True
        if "at most 0 audio" in error_str and "may be provided" in error_str:
            return True
        return False

    @staticmethod
    def _is_video_fallback_error(exc: Exception) -> bool:
        """Recognize video type/capability rejections and count limits."""
        if QwenPawAgent._is_content_safety_error(exc):
            return False
        error_str = " ".join(str(exc).lower().split())
        # Schema errors can list image/audio parts as accepted alternatives.
        if _VIDEO_PART_REJECTION_RE.search(error_str):
            return True
        # Broader rejections must retain the existing media-free fallback.
        if re.search(
            r"\b(?:images?|image_url|input_image|audios?|input_audio|"
            r"files?|input_file|pdf|vision|media|multimodal)\b",
            error_str,
        ):
            return False
        return bool(
            _VIDEO_COUNT_LIMIT_RE.search(error_str)
            or "video input is not supported" in error_str
            or re.search(
                r"\bmodel\b.{0,40}\b(?:does not|doesn't|cannot|can't) "
                r"support videos?\b",
                error_str,
            )
            or re.search(r"\bunsupported modality\s*:\s*video\b", error_str),
        )

    @staticmethod
    def _is_video_capability_error(exc: Exception) -> bool:
        """Allow learning only for rejected video types or zero budgets."""
        if not QwenPawAgent._is_video_fallback_error(exc):
            return False
        limit = _VIDEO_COUNT_LIMIT_RE.search(str(exc).lower())
        return limit is None or int(limit.group(1)) == 0

    def _is_video_only_media_rejection(self, exc: Exception) -> bool:
        """Return whether *exc* refuses video and says nothing about images.

        ``At most 0 video(s) may be provided`` is a video-count limit. Treating
        it as a generic media-payload rejection marked every media block as
        omitted, so a stored image the user was still asking about became
        unreachable on the next turn. Such an error keeps its own video
        fallback path instead.
        """
        return (
            self._last_wire_request_had_video()
            and QwenPawAgent._is_video_capability_error(exc)
        )

    @staticmethod
    def _is_modality_specific_media_rejection(exc: Exception) -> bool:
        """Return whether *exc* refuses audio or video alone.

        ``At most 0 audio(s)`` and ``Multiple videos: at most 1 video may be
        provided`` are per-modality count limits, not statements about the
        media payload as a whole. The generic media path answers a refusal by
        marking media blocks as omitted, which would drop the images the user
        is still asking about. These errors belong to the audio and video
        handlers, which strip only their own modality.

        A rejection that also names images or the media payload in general is
        a mixed refusal: the generic path is exactly what it needs, so such
        text is not treated as modality-specific.
        """
        text = str(exc).lower()
        if "image" in text or "media" in text:
            return False
        return bool(_MODALITY_ONLY_LIMIT_RE.search(text))

    async def _prepare_model_input(self) -> dict[str, Any]:
        """Freeze local images before they enter a provider request."""
        await freeze_local_images_async(self.state.context)
        return await super()._prepare_model_input()

    @staticmethod
    def _is_context_overflow_error(exc: Exception) -> bool:
        """Return whether *exc* rejects the token context length.

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

        overflow_marker_groups = (
            (
                "the input (",
                "tokens)",
                "is longer than the model's context length",
            ),
            ("tokens", "exceeds the available context size"),
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
            for marker_group in overflow_marker_groups
        )

    async def _call_model(
        self,
        messages: list[Msg],
        tools: list[dict],
        tool_choice: Any = None,
    ) -> Any:
        """Call the model with at most two context recovery attempts.

        Body-size rejections omit media from request copies; token overflows
        delegate to the context manager. Rebuild and retry only when recovery
        changed the model input. Invocation and streaming share the budget.
        """
        self._index_tool_schemas(tools)
        # Retry history is per call: a later call in the same turn may carry
        # different content and deserves its own attempt. Only the recovery
        # steps inside this call share it.
        self._media_tighten_history = None
        # The source image of this call's recovery chain, recorded on the
        # first tighten. Reset per call for the same reason as the history:
        # a later call may carry different media.
        self._media_rendition_source = None
        remaining = 2
        call_model = super()._call_model

        async def recover(exc: Exception) -> Any:
            nonlocal remaining
            if remaining == 0:
                raise exc
            remaining -= 1
            return await self._recover_model_overflow(
                exc,
                tool_choice=tool_choice,
                retry=call,
            )

        async def call(**kwargs: Any) -> Any:
            return await call_with_overflow_recovery(
                call_model,
                recover,
                **kwargs,
            )

        result = await call(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )

        def capture_completion(response: Any) -> None:
            metadata = getattr(response, f"metadata", None) or {}
            completion = metadata.get(COMPLETION_METADATA_KEY)
            self._model_completion = (
                dict(completion) if isinstance(completion, dict) else None
            )

        if not isasyncgen(result):
            capture_completion(result)
            return result

        async def capture_stream():
            try:
                async for chunk in result:
                    if getattr(chunk, f"is_last", False):
                        capture_completion(chunk)
                    yield chunk
            finally:
                await result.aclose()

        return capture_stream()

    async def _recover_model_overflow(
        self,
        exc: Exception,
        tool_choice: Any,
        retry: Callable[..., Awaitable[Any]] | None = None,
    ) -> Any:
        """Perform one recovery step within the caller's shared budget."""
        body_overflow = is_request_body_too_large(exc)
        # A 400 that names the media payload ("image dimensions exceed the
        # maximum", "too many images") is a request-scoped media refusal,
        # not a context-length overflow. It reaches this path only when the
        # non-streaming call failed, so the streaming classifier has to be
        # consulted here too — otherwise the block stays in state.context
        # and every later turn replays the same rejection.
        has_media = self._last_wire_request_had_media()
        media_rejection = (
            not body_overflow
            and has_media
            and not QwenPawAgent._is_modality_specific_media_rejection(exc)
            and self._is_media_payload_rejection_error(exc)
        )
        if (body_overflow or media_rejection) and has_media:
            omitted = mark_media_omitted_after_overflow(self.state.context)
            if omitted:
                self._note_media_omission(
                    omitted,
                    (
                        "request body size limit"
                        if body_overflow
                        else "provider media limit"
                    ),
                )
                logger.warning(
                    "The provider rejected the request media (%s); "
                    "omitting %d historical media block(s) and retrying "
                    "once.",
                    "body size" if body_overflow else "media limit",
                    omitted,
                )
                return await self._retry_with_refreshed_input(tool_choice)
            # Nothing historical to drop: the refusal is about media in the
            # active turn, which must not be deleted — the user is asking
            # about it. Shrink the request-scoped limits once and retry with
            # a smaller rendition instead of replaying the same rejection.
            if QwenPawAgent._is_resize_ineffective_media_rejection(exc):
                # An animation or an image-count limit is not about bytes: a
                # smaller rendition carries the same block, so this step would
                # resend what was just refused. Go straight to the media-free
                # fallback, the same one the streaming path uses.
                removed = len(self._last_wire_media_summary())
                if removed:
                    self._note_media_omission(
                        removed,
                        "provider media limit",
                    )
                logger.warning(
                    "The provider rejected the media shape (%s); resizing "
                    "cannot change it, so the retry drops media.",
                    exc,
                )
                self._set_formatter_media_strip(True)
                try:
                    return await self._retry_with_refreshed_input(
                        tool_choice,
                        retry=retry,
                    )
                finally:
                    self._set_formatter_media_strip(False)
            saved_limits = self._tighten_media_limits(
                enforce_payload_check=not body_overflow,
            )
            if saved_limits is not None:
                current_side, current_bytes = self._active_media_limits()
                logger.warning(
                    "The provider rejected the request media and no "
                    "historical block could be omitted; shrinking the "
                    "request media limits to max_image_side=%d, "
                    "max_bytes=%d and retrying once.",
                    current_side,
                    current_bytes,
                )
                try:
                    result = await self._retry_with_refreshed_input(
                        tool_choice,
                    )
                    # Only a call that completes proves the smaller
                    # rendition was acceptable; a refusal leaves the
                    # pending target unused so the next attempt shrinks
                    # further or drops media.
                    self._accept_media_rendition()
                    return result
                finally:
                    self._restore_media_limits(saved_limits)
            # No smaller rendition is available. For a body-size rejection
            # that means the request body is still too large and another
            # attempt would be identical: stop instead of replaying it.
            if body_overflow:
                raise exc
            # For a media refusal, drop the media for this request: the user
            # still gets an answer and the block stays in context for later
            # turns.
            removed = len(self._last_wire_media_summary())
            if removed:
                self._note_media_omission(
                    removed,
                    "provider media limit",
                )
            logger.warning(
                "The provider rejected the request media and it cannot be "
                "shrunk further; retrying without media.",
            )
            self._set_formatter_media_strip(True)
            try:
                return await self._retry_with_refreshed_input(
                    tool_choice,
                    retry=retry,
                )
            finally:
                self._set_formatter_media_strip(False)
            # Context recovery can fold consumed tool results in the active
            # turn. Do not silently remove media the user is asking about.
            raise exc

        context_manager = getattr(self, "_context_manager", None)
        if not isinstance(
            context_manager,
            ContextManager,
        ) or not (body_overflow or self._is_context_overflow_error(exc)):
            raise exc

        before = len(getattr(self.state, "context", []) or [])
        logger.warning(
            "Model input exceeded a size limit; attempting "
            "a context recovery step.",
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

        logger.info(
            "Context-overflow recovery rebuilt model input "
            "(messages %d -> %d).",
            before,
            after,
        )
        return await self._retry_with_refreshed_input(tool_choice, retry=retry)

    async def _retry_with_refreshed_input(
        self,
        tool_choice: Any,
        retry: Callable[..., Awaitable[Any]] | None = None,
    ) -> Any:
        """Rebuild input and use the caller's bounded retry when supplied."""
        refreshed = await self._prepare_model_input()
        refreshed_tools = refreshed.get("tools", [])
        self._index_tool_schemas(refreshed_tools)
        call_model = retry or super()._call_model
        return await call_model(
            messages=refreshed["messages"],
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
        self._model_completion = None
        # The media-omission count spans every reasoning iteration of a user
        # turn: a tool call starts another iteration, so resetting it here
        # lost the notice before the final reply could carry it. It is reset
        # once per turn in :meth:`_reply`.

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

        # ModelInfo controls per-model request normalization. Only learned
        # rejections belong here; a global lookup can misclassify fallbacks.
        should_strip_media = self._model_rejects_media()
        should_strip_audio = (
            not should_strip_media and self._model_rejects_audio()
        )
        should_strip_video = (
            not should_strip_media and self._model_rejects_video()
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

        if (
            should_strip_video
            and self._uses_request_time_media_normalization()
        ):
            self._set_formatter_video_strip(True)

        # ── Model call with passive retry on media error ──
        final_msg: Msg | None = None
        context_manager = self._context_manager
        pending_seen_ids: set[str] = set()
        pending_seen_thinking_ids: set[str] = set()
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
                self._attach_model_completion(evt)
            if (
                isinstance(evt, ModelCallEndEvent)
                and evt.finished_reason != FinishedReason.INTERRUPTED
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
            async for evt in self._reasoning_events(tool_choice):
                acknowledge_seen_inputs(evt)
                if isinstance(evt, Msg):
                    final_msg = evt
                else:
                    self._attach_fallback_notices(evt, fallback_sink)
                    self._attach_media_omission_notice(evt)
                    yield evt
        except Exception as e:
            video_fallback_retry = (
                self._last_wire_request_had_video()
                and self._is_video_fallback_error(e)
            )
            audio_fallback_retry = (
                self._last_wire_request_had_audio()
                and self._is_audio_fallback_error(e)
            )
            audio_count_retry = (
                self._last_wire_request_had_audio()
                and QwenPawAgent._is_audio_count_limit_error(e)
            )
            media_capability_retry = (
                self._last_wire_request_had_media()
                and self._is_explicit_media_capability_error(e)
            )
            media_payload_retry = (
                not media_capability_retry
                and self._uses_request_time_media_normalization()
                and self._last_wire_request_had_media()
                and self._is_media_payload_rejection_error(e)
            )
            if not (
                video_fallback_retry
                or audio_fallback_retry
                or audio_count_retry
                or media_capability_retry
                or media_payload_retry
            ):
                if self._uses_request_time_media_normalization():
                    if should_strip_media:
                        self._set_formatter_media_strip(False)
                    if should_strip_audio:
                        self._set_formatter_audio_strip(False)
                    if should_strip_video:
                        self._set_formatter_video_strip(False)
                raise

            model_key = self._get_model_key()
            tightened_limits: tuple[int, int] | None = None
            learn_global_rejection = (
                media_capability_retry
                and self._is_global_media_capability_error(e)
            )
            if video_fallback_retry:
                logger.warning(
                    "_reasoning failed because the provider rejected a "
                    "video input (%s); stripping only video and retrying.",
                    e,
                )
                self._set_formatter_video_strip(True)
            elif audio_fallback_retry:
                logger.warning(
                    "_reasoning failed because the provider rejected an "
                    "audio payload (%s); stripping audio and retrying.",
                    e,
                )
                self._set_formatter_audio_strip(True)
            elif audio_count_retry:
                logger.warning(
                    "_reasoning failed because the provider allows fewer "
                    "audio clips than this request carried (%s); stripping "
                    "audio and retrying without touching other media.",
                    e,
                )
                self._set_formatter_audio_strip(True)
            elif media_payload_retry:
                # The offending block is replayed from history on every
                # later turn, so dropping it from this request alone returns
                # the same rejection next turn. Mark the historical copies
                # as omitted once (the active turn keeps its media) and
                # strip this request; only when nothing historical is left
                # is the refusal about the active turn itself, in which case
                # a smaller rendition is the only recovery left.
                omitted = mark_media_omitted_after_overflow(
                    self.state.context,
                )
                if (
                    not omitted
                    and not QwenPawAgent._is_resize_ineffective_media_rejection(
                        e,
                    )
                ):
                    tightened_limits = self._tighten_media_limits()
                # Count what this request actually stops sending. Historical
                # blocks are removed by the omit pass; the active turn's
                # media is only removed when the formatter is told to strip
                # it, which happens when no smaller rendition is available.
                # A successful tighten sends the same block at a smaller size
                # and removes nothing, so reporting the whole summary there
                # claimed an omission that never happened.
                removed = omitted
                if not omitted and tightened_limits is None:
                    removed = len(self._last_wire_media_summary())
                if removed:
                    self._note_media_omission(removed, "provider media limit")
                logger.warning(
                    "_reasoning failed because the provider rejected the "
                    "media payload itself (%s); stripping %s from the "
                    "retry request, marking %d historical block(s) as "
                    "omitted, limits shrunk=%s. No capability loss is "
                    "cached.",
                    e,
                    ", ".join(self._last_wire_media_summary())
                    or "unlabelled media",
                    omitted,
                    tightened_limits is not None,
                )
                if not omitted and tightened_limits is None:
                    # Dropping every media block is the only recovery left
                    # when no smaller rendition is available and nothing
                    # historical could be omitted. It is wrong once
                    # historical blocks were omitted: those are removed
                    # from the request already, and stripping would also
                    # delete the active-turn image the user is asking
                    # about. It is wrong after a successful tighten too:
                    # that would leave the retry with zero images and
                    # defeat the shrink that was just applied.
                    self._set_formatter_media_strip(True)
            else:
                logger.warning(
                    "_reasoning failed because the provider explicitly "
                    "rejected the model's media capability (%s); stripping "
                    "%s and retrying.",
                    e,
                    ", ".join(self._last_wire_media_summary())
                    or "unlabelled media",
                )
                if self._uses_request_time_media_normalization():
                    self._set_formatter_media_strip(True)
                else:
                    self._strip_media_blocks_from_memory()

            try:
                async for evt in self._reasoning_events(tool_choice):
                    acknowledge_seen_inputs(evt)
                    if isinstance(evt, Msg):
                        final_msg = evt
                    else:
                        self._attach_fallback_notices(evt, fallback_sink)
                        self._attach_media_omission_notice(evt)
                        yield evt
                if (
                    model_key
                    and video_fallback_retry
                    and self._is_video_capability_error(e)
                ):
                    get_capability_cache().learn(
                        model_key,
                        "rejects_video",
                        True,
                    )
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
                # The stream reached its end without an error, so the
                # rendition the retry carried was acceptable and may be
                # reused within this turn.
                self._accept_media_rendition()
            finally:
                if self._uses_request_time_media_normalization():
                    self._set_formatter_video_strip(False)
                    self._set_formatter_audio_strip(False)
                    self._set_formatter_media_strip(False)
                self._restore_media_limits(tightened_limits)
        else:
            if self._uses_request_time_media_normalization():
                if should_strip_media:
                    self._set_formatter_media_strip(False)
                if should_strip_audio:
                    self._set_formatter_audio_strip(False)
                if should_strip_video:
                    self._set_formatter_video_strip(False)

        stored_msg = self._get_last_msg()
        if stored_msg is not None and stored_msg.id == self.state.reply_id:
            self._attach_model_completion(stored_msg)
        self._attach_model_completion(final_msg)

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
        completion = (outgoing_msg.metadata or {}).get(COMPLETION_METADATA_KEY)
        self._model_completion = (
            dict(completion) if isinstance(completion, dict) else None
        )
        if stored_msg is not None and stored_msg.id == self.state.reply_id:
            self._attach_model_completion(stored_msg)
        if not has_answer_content(outgoing_msg.content):
            raise RuntimeError(
                f"The model returned an empty answer. "
                f"Please retry or switch models.",
            )
        self._attach_fallback_notices(outgoing_msg, fallback_sink)
        self._attach_media_omission_notice(outgoing_msg)
        yield outgoing_msg

    def _note_media_omission(self, count: int, reason: str) -> None:
        """Record that *count* media items were left out of this request.

        The notice is user-facing: when media is dropped silently the model
        simply answers as if the file was never sent, and the user has no way
        to tell. Accumulating per response cycle keeps one summary line
        instead of one line per retry.
        """
        if count <= 0:
            return
        notice = getattr(self, "_media_omission_notice", None)
        if not isinstance(notice, dict):
            notice = {"count": 0, "reason": reason}
            self._media_omission_notice = notice
        notice["count"] = int(notice.get("count", 0)) + count
        notice["reason"] = reason

    def _attach_media_omission_notice(self, target: Any) -> None:
        """Copy the per-cycle media-omission summary onto an outgoing event.

        ``AgentExecutor`` drives ``reply_stream`` without yielding the final
        ``Msg``, and the envelope returns nothing at all for
        ``REPLY_END`` — so a notice attached only to those reaches neither
        Console nor a channel. It has to ride the same events the model
        fallback notice rides, which are the ones consumers actually see.
        """
        notice = getattr(self, "_media_omission_notice", None)
        if not isinstance(notice, dict) or not notice.get("count"):
            return
        metadata = dict(getattr(target, "metadata", None) or {})
        metadata["qwenpaw_media_omitted"] = dict(notice)
        try:
            target.metadata = metadata
        except (AttributeError, TypeError, ValueError):
            logger.warning(
                "Could not attach the media-omission notice to the reply.",
            )

    def _attach_model_completion(self, target: Any) -> None:
        """Keep raw completion details in events and persisted messages."""
        if target is None:
            return
        completion = getattr(self, f"_model_completion", None)
        metadata = dict(target.metadata or {})
        if completion:
            metadata[COMPLETION_METADATA_KEY] = dict(completion)
        else:
            metadata.pop(COMPLETION_METADATA_KEY, None)
        target.metadata = metadata

    @staticmethod
    def _attach_fallback_notices(
        evt: Any,
        sink: dict[str, Any],
    ) -> None:
        """Copy pending model-fallback notices onto an outgoing event.

        Consumers (Console SSE parsing and channel notifiers) read
        ``qwenpaw_model_fallbacks``/``qwenpaw_actual_model`` from event
        or message metadata; this is the only point where QwenPaw still
        owns the stream after agentscope's conversion dropped the
        model response metadata.
        """
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

        # Asset-level failures describe these bytes, never the model; the
        # payload classifier below is responsible for recovering from them.
        if any(signal in error_str for signal in _INVALID_MEDIA_ASSET_SIGNALS):
            return False

        return any(
            pattern.search(error_str) is not None
            for pattern in _EXPLICIT_UNSUPPORTED_MEDIA_PATTERNS
        )

    @staticmethod
    def _is_media_payload_rejection_error(exc: Exception) -> bool:
        """Return whether the provider rejected this media payload.

        Covers the request-scoped media limits documented by
        ``_REQUEST_SCOPED_MEDIA_LIMIT_SIGNALS`` — too many images, a
        resolution or a video duration the provider refuses — plus
        asset-level failures: undecodable bytes, an unsupported container,
        a declared MIME type the provider cannot render. None of them says
        anything about the model, so recovery is a media-free retry, never
        a cached model-wide ``rejects_media`` capability loss.

        This matters for session health: the offending block is replayed
        from history on every later turn, so an unrecovered payload
        rejection returns the same 400 until the media is repaired in the
        stored context (see the caller in :meth:`_reasoning`).
        """
        error_str = " ".join(str(exc).lower().split())
        # A tool-schema failure is not about media, even when the tool or
        # field names contain media words: ``resize_image`` with a
        # ``dimensions`` field used to mark a valid historical image as
        # omitted. The failing parameter is only in the structured body of
        # an SDK error, so check that too and propagate the schema error
        # untouched.
        if _TOOL_PARAMETERS_PATH_RE.search(
            error_str,
        ) or _TOOL_PARAMETERS_PATH_RE.search(_structured_error_text(exc)):
            return False
        if not any(noun in error_str for noun in _MEDIA_PAYLOAD_MEDIA_NOUNS):
            return False
        if QwenPawAgent._is_content_safety_error(exc):
            return False
        # An image-count limit is a payload rejection for any positive
        # budget, not only the zero-budget wording above. The bounded
        # media-free fallback is the recovery; resizing cannot satisfy it.
        if _IMAGE_COUNT_LIMIT_RE.search(error_str):
            return True
        return any(
            signal in error_str for signal in _MEDIA_PAYLOAD_REJECTION_SIGNALS
        )

    @staticmethod
    def _is_resize_ineffective_media_rejection(exc: Exception) -> bool:
        """Return whether shrinking the image cannot satisfy *exc*.

        An animated GIF is forwarded unchanged, and an image-count limit
        counts blocks rather than pixels. Both used to consume the resize
        retry and resend the identical payload three times.
        """
        text = " ".join(str(exc).lower().split())
        if _IMAGE_COUNT_LIMIT_RE.search(text):
            return True
        return any(
            signal in text for signal in _RESIZE_INEFFECTIVE_MEDIA_SIGNALS
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
    # Middleware-injected exchanges, surfaced to the UI as tool calls
    # ------------------------------------------------------------------

    def _reasoning_events(self, tool_choice: Any) -> Any:
        """The base reasoning stream, with injected exchanges merged in
        when a middleware emits them."""
        inner = super()._reasoning(tool_choice=tool_choice)
        queue = self._injected_events
        if queue is None:
            return inner
        return merge_injected_events(inner, queue)

    def emit_injected_event(self, event: Any) -> bool:
        """Show ``event`` in the chat stream as soon as possible.

        Middlewares run inside a model call while the UI only sees what
        ``_reasoning`` yields, so this queue is the bridge. Returns False
        when no middleware armed the queue (the event is dropped).
        """
        queue = self._injected_events
        if queue is None:
            return False
        queue.put_nowait(event)
        return True

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

    async def _flush_context_save(self) -> None:
        """Finish deferred history writes before publishing the next event."""
        pending = getattr(self, "_pending_context_save", None)
        if pending is not None:
            self._pending_context_save = None
            await run_sync_io(self._context_manager.on_save, self, pending)

    async def _reply(self, **kwargs: Any) -> Any:
        """Drain history writes off the event loop at stream boundaries."""
        # One user turn: the omission count accumulates across every
        # reasoning iteration this turn runs, including the ones a tool call
        # starts.
        self._media_omission_notice = None
        self._media_rendition_target = None
        self._media_rendition_pending = None
        self._media_tighten_history = None
        # Source image of the recovery chain in progress; cleared with the
        # rest of the per-turn media state.
        self._media_rendition_source = None
        stream = super()._reply(**kwargs)
        self._defer_context_save = True
        try:
            while True:
                # Heartbeat consumers may resume each event in a new task.
                # Never carry a ContextVar token across an outward yield.
                with model_session(
                    self._request_context,
                    self._model_session_id,
                ):
                    try:
                        evt = await anext(stream)
                    except StopAsyncIteration:
                        return
                    finally:
                        await self._flush_context_save()
                if isinstance(evt, ReplyEndEvent):
                    self._attach_model_completion(evt)
                    # None explicitly clears the last model call's marker.
                    evt.metadata.setdefault(COMPLETION_METADATA_KEY, None)
                yield evt
        finally:
            try:
                with model_session(
                    self._request_context,
                    self._model_session_id,
                ):
                    try:
                        await stream.aclose()
                    finally:
                        await self._flush_context_save()
            finally:
                self._defer_context_save = False

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
        mgr.hooks.register(
            "desktop_screenshot",
            default_timeout_secs=30.0,
        )

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

        agent_id = (self._request_context or {}).get(
            "agent_id",
        ) or get_current_agent_id()
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
                            replacement: Any = (
                                filtered or MEDIA_UNSUPPORTED_PLACEHOLDER
                            )
                            if filtered:
                                # Some content survived the strip, so the
                                # removed media would otherwise vanish without
                                # a trace ("Image loaded: x.png" with no image).
                                replacement = filtered + [
                                    omitted_media_marker(filtered),
                                ]
                            if isinstance(block, dict):
                                block["output"] = replacement
                            else:
                                block.output = replacement

                new_content.append(block)

            if not new_content and stripped_this_message > 0:
                new_content.append(
                    TextBlock(type="text", text=MEDIA_UNSUPPORTED_PLACEHOLDER),
                )

            msg.content = new_content

        return total_stripped
