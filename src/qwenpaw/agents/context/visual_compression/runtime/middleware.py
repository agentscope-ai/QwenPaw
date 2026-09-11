# -*- coding: utf-8 -*-
"""AgentScope pre-model hook for request-time visual compression."""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, Any, Callable

from agentscope.middleware import MiddlewareBase

from ..config import effort_preset

logger = logging.getLogger(__name__)
_TRANSFORM_EXECUTOR = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="qwenpaw-visual-compact",
)

if TYPE_CHECKING:
    from agentscope.agent import Agent


def _model_key(current_model: Any) -> str | None:
    """Return QwenPaw's exact per-model capability-cache key."""
    try:
        key = getattr(current_model, "model_key", None)
    except Exception:  # pragma: no cover - defensive third-party model
        return None
    return key if isinstance(key, str) and key else None


def _agent_will_strip_media(
    agent: "Agent",
    current_model: Any = None,
) -> bool:
    """Whether QwenPaw will discard media for this exact model call."""
    formatter = getattr(agent, "formatter", None)
    if bool(getattr(formatter, "_qwenpaw_force_strip_media", False)):
        return True
    key = _model_key(current_model)
    if key is not None:
        from .....providers.model_capability_cache import get_capability_cache

        return bool(
            get_capability_cache().get(key, "rejects_media", False),
        )
    rejects_media = getattr(agent, "_model_rejects_media", None)
    if not callable(rejects_media):
        return False
    try:
        return bool(rejects_media())
    except Exception:  # pragma: no cover - defensive host integration
        logger.debug(
            "Could not read the agent's learned media capability",
            exc_info=True,
        )
        return False


class VisualCompressionMiddleware(MiddlewareBase):
    """Rewrite one prepared request immediately before provider I/O."""

    def __init__(
        self,
        config: Any,
    ) -> None:
        self._enabled = bool(config.enabled)
        self._effort_preset = effort_preset(str(config.effort))

    def _log_skipped(
        self,
        *,
        model_key: str | None,
        reason: str,
    ) -> None:
        logger.debug(
            "Visual Compact skipped: model=%s effort=%s reason=%s",
            model_key or "-",
            self._effort_preset.effort,
            reason,
        )

    async def on_model_call(  # pylint: disable=R0914
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., Any],
    ) -> Any:
        current_model = input_kwargs.get("current_model")
        model_key = _model_key(current_model)
        if not self._enabled:
            return await next_handler(**input_kwargs)

        from ....prompt import get_model_supports_image

        if _agent_will_strip_media(agent, current_model):
            self._log_skipped(
                model_key=model_key,
                reason="media_stripped",
            )
            return await next_handler(
                **input_kwargs,
            )
        if not get_model_supports_image(current_model):
            self._log_skipped(
                model_key=model_key,
                reason="model_without_image_support",
            )
            return await next_handler(
                **input_kwargs,
            )

        request = dict(input_kwargs)
        messages = request.get("messages") or []
        try:
            from ..pipeline.request import transform_model_request
            from ..rendering import render_cache_info

            cache_before = render_cache_info()
            started = time.perf_counter()
            # Rendering and PNG encoding are synchronous CPU work. Keep them
            # off the event loop and bound their process-wide concurrency.
            # Cancelling this await cannot stop work already running in the
            # executor, but the event loop remains responsive.
            transform = partial(
                transform_model_request,
                messages,
                context_message_ids=frozenset(
                    message.id for message in agent.state.context
                ),
                effort_preset=self._effort_preset,
            )
            (
                transformed,
                receipt,
            ) = await asyncio.get_running_loop().run_in_executor(
                _TRANSFORM_EXECUTOR,
                transform,
            )
            transform_ms = (time.perf_counter() - started) * 1000
            cache_after = render_cache_info()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Visual compression failed; sending the original request "
                "(model=%s effort=%s)",
                model_key or "-",
                self._effort_preset.effort,
            )
            return await next_handler(
                **request,
            )
        request["messages"] = transformed
        saved_tokens = max(
            0,
            receipt.source_estimated_tokens
            - receipt.replacement_estimated_tokens,
        )
        savings_ratio = (
            saved_tokens / receipt.source_estimated_tokens
            if receipt.source_estimated_tokens
            else 0.0
        )
        applied = bool(receipt.regions)
        logger.debug(
            "Visual Compact transform: model=%s effort=%s "
            "applied=%s regions=%s "
            "blocks=%d images=%d compressed_chars=%d "
            "estimated_source_tokens=%d estimated_replacement_tokens=%d "
            "estimated_saved_tokens=%d estimated_savings_pct=%.1f "
            "transform_ms=%.1f render_cache_hits=%d render_cache_misses=%d",
            model_key or "-",
            self._effort_preset.effort,
            applied,
            receipt.regions,
            sum(receipt.regions.values()),
            receipt.image_count,
            receipt.compressed_chars,
            receipt.source_estimated_tokens,
            receipt.replacement_estimated_tokens,
            saved_tokens,
            savings_ratio * 100,
            transform_ms,
            cache_after.hits - cache_before.hits,
            cache_after.misses - cache_before.misses,
        )
        return await next_handler(**request)


__all__ = ["VisualCompressionMiddleware"]
