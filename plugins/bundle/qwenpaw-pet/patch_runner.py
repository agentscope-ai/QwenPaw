# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Wrap ``AgentRunner.stream_query`` to emit pet lifecycle events.

Emissions:
    - ``query.received`` / ``query.running``  — fired up-front
    - ``query.first_token`` (Replying)         — first ``Message``
      envelope with ``type=message`` and ``status=in_progress``
    - ``tool.detected`` (Using <name>)         — ``Message`` with
      ``type=plugin_call`` (``DataContent.data["name"]``)
    - ``tool.result``                          — ``Message`` with
      ``type=plugin_call_output`` and ``status=completed``
    - ``query.done`` / ``query.cancelled`` /
      ``query.error``                          — driven by stream exit
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from emitter import emit_pet_event, schedule_emit_pet_event

logger = logging.getLogger("qwenpaw.pet_desktop")

_ORIGINAL_STREAM_QUERY = None
_PATCHED = False

# Bound methods captured by ``make_process_from_runner`` freeze the
# function pointer at access time and bypass class-level patches; we
# track our replacements so ``restore_agent_runner`` can undo them.
_PATCHED_CHANNEL_PROCESSES: list[tuple[Any, Any]] = []


def _request_meta(runner: Any, request: Any) -> dict[str, Any]:
    return {
        "agent_id": getattr(runner, "agent_id", "default"),
        "agent_name": getattr(runner, "agent_name", "QwenPaw"),
        "session_id": getattr(request, "session_id", "") if request else "",
        "user_id": getattr(request, "user_id", "") if request else "",
        "channel": getattr(request, "channel", "") if request else "",
    }


def _content_text(content_block: Any) -> str:
    """Pull a text string out of a TextContent-shaped block."""
    text = getattr(content_block, "text", None)
    if text is None and isinstance(content_block, dict):
        text = content_block.get("text")
    return str(text) if text else ""


def _content_data(content_block: Any) -> dict | None:
    """Pull ``data`` dict out of a DataContent-shaped block."""
    data = getattr(content_block, "data", None)
    if data is None and isinstance(content_block, dict):
        data = content_block.get("data")
    return data if isinstance(data, dict) else None


def _classify_event(
    event: Any,
    seen_first_text: bool,
) -> tuple[str | None, str | None]:
    """Map a single envelope event to a pet lifecycle emission.

    Returns ``(event_name, text)`` or ``(None, None)`` for events the pet
    doesn't speak about.  ``seen_first_text`` guards the
    ``query.first_token`` emission to fire only once per turn.
    """
    object_kind = getattr(event, "object", None)
    if object_kind is None and isinstance(event, dict):
        object_kind = event.get("object")

    if object_kind != "message":
        return None, None

    msg_type = getattr(event, "type", None)
    if msg_type is None and isinstance(event, dict):
        msg_type = event.get("type")
    msg_type_val = (
        msg_type.value if hasattr(msg_type, "value") else str(msg_type or "")
    )

    status = getattr(event, "status", None)
    if status is None and isinstance(event, dict):
        status = event.get("status")
    status_val = (
        status.value if hasattr(status, "value") else str(status or "")
    )

    content = getattr(event, "content", None)
    if content is None and isinstance(event, dict):
        content = event.get("content")
    content_list = content if isinstance(content, list) else []

    if msg_type_val == "plugin_call" and status_val == "completed":
        # First content block carries {name, call_id, arguments}.
        data = _content_data(content_list[0]) if content_list else None
        name = (data or {}).get("name") or "tool"
        return "tool.detected", f"Using {str(name)[:40]}"

    if msg_type_val == "plugin_call_output" and status_val == "completed":
        return "tool.result", "Tool result"

    # Fire on the empty in_progress envelope, not the completed one —
    # TextContent deltas arrive as separate ``object="content"`` events
    # which the classifier ignores, so "Replying" needs to flip when the
    # reply starts, not after it finishes.
    if (
        msg_type_val == "message"
        and status_val == "in_progress"
        and not seen_first_text
    ):
        return "query.first_token", "Replying"

    return None, None


def patch_agent_runner() -> None:
    """Install an observing wrapper around AgentRunner.stream_query."""
    global _ORIGINAL_STREAM_QUERY, _PATCHED

    if _PATCHED:
        return

    from qwenpaw.app.runner.runner import AgentRunner

    _ORIGINAL_STREAM_QUERY = AgentRunner.stream_query

    async def patched_stream_query(self, request, *args, **kwargs):
        meta = _request_meta(self, request)
        seen_first_text = False
        last_event = None

        schedule_emit_pet_event(
            "query.received",
            text="New message",
            **meta,
        )
        schedule_emit_pet_event("query.running", text="Thinking", **meta)

        try:
            async for envelope in _ORIGINAL_STREAM_QUERY(
                self,
                request,
                *args,
                **kwargs,
            ):
                event, text = _classify_event(envelope, seen_first_text)
                if event == "query.first_token":
                    seen_first_text = True

                if event and event != last_event:
                    schedule_emit_pet_event(event, text=text, **meta)
                    last_event = event

                yield envelope

            await asyncio.to_thread(
                emit_pet_event,
                "query.done",
                text="Done",
                **meta,
            )

        except asyncio.CancelledError:
            schedule_emit_pet_event(
                "query.cancelled",
                text="Interrupted",
                duration_ms=1200,
                **meta,
            )
            raise
        except Exception as exc:
            schedule_emit_pet_event(
                "query.error",
                text=type(exc).__name__,
                duration_ms=2500,
                **meta,
            )
            raise

    AgentRunner.stream_query = patched_stream_query
    _PATCHED = True
    logger.info("QwenPaw Pet patched AgentRunner.stream_query")

    # Existing channels hold bound-method copies of
    # ``runner.stream_query`` from before the patch; the class-level
    # assignment above doesn't reach them.  Walk the live channels and
    # also intercept the factory for any workspace brought up later.
    _wire_existing_channels(patched_stream_query)
    _patch_make_process_factory(patched_stream_query)


def _wire_existing_channels(patched_fn) -> None:
    """Replace each live channel's ``_process`` with a proxy that calls
    ``patched_fn`` against the channel's owning runner.

    No-ops when the FastAPI app or its ``multi_agent_manager`` isn't
    importable (CLI-only mode, headless runner).
    """
    try:
        from qwenpaw.app._app import app as fastapi_app
    except Exception:
        logger.debug("Pet patch: FastAPI app not importable; skip rewire")
        return

    manager = getattr(
        getattr(fastapi_app, "state", None),
        "multi_agent_manager",
        None,
    )
    if manager is None:
        logger.debug("Pet patch: no multi_agent_manager; skip rewire")
        return

    workspaces = getattr(manager, "agents", {}) or {}
    rewired = 0
    for ws in workspaces.values():
        try:
            services = ws._service_manager.services
        except AttributeError:
            continue
        cm = services.get("channel_manager")
        if cm is None:
            continue
        runner = services.get("runner")
        if runner is None:
            continue
        for channel in getattr(cm, "channels", []) or []:
            original = getattr(channel, "_process", None)
            if original is None:
                continue

            def _make_proxy(_runner, _fn):
                def _proxy(request, *args, **kwargs):
                    return _fn(_runner, request, *args, **kwargs)

                _proxy.__qualname__ = "qwenpaw_pet.patched_channel_process"
                return _proxy

            channel._process = _make_proxy(runner, patched_fn)
            _PATCHED_CHANNEL_PROCESSES.append((channel, original))
            rewired += 1
    if rewired:
        logger.info(
            "QwenPaw Pet rewired %d channel _process refs to patched "
            "stream_query",
            rewired,
        )


def _patch_make_process_factory(patched_fn) -> None:
    """Wrap ``make_process_from_runner`` so workspaces created after this
    point also receive the patched proxy instead of a bound method."""
    try:
        from qwenpaw.app.channels import utils as ch_utils
    except Exception:
        logger.debug(
            "Pet patch: channels.utils not importable; skip factory patch",
        )
        return

    original = getattr(ch_utils, "make_process_from_runner", None)
    if original is None or getattr(original, "_pet_patched", False):
        return

    def patched_factory(runner):
        def _proxy(request, *args, **kwargs):
            return patched_fn(runner, request, *args, **kwargs)

        _proxy.__qualname__ = "qwenpaw_pet.patched_channel_process"
        return _proxy

    patched_factory._pet_patched = True  # type: ignore[attr-defined]
    patched_factory._original = original  # type: ignore[attr-defined]
    ch_utils.make_process_from_runner = patched_factory


def restore_agent_runner() -> None:
    """Restore the original stream_query method and channel _process refs."""
    global _PATCHED

    if not _PATCHED or _ORIGINAL_STREAM_QUERY is None:
        return

    from qwenpaw.app.runner.runner import AgentRunner

    AgentRunner.stream_query = _ORIGINAL_STREAM_QUERY

    # Undo channel rewiring
    for channel, original in _PATCHED_CHANNEL_PROCESSES:
        try:
            channel._process = original
        except Exception:
            pass
    _PATCHED_CHANNEL_PROCESSES.clear()

    # Undo factory patch
    try:
        from qwenpaw.app.channels import utils as ch_utils

        factory = getattr(ch_utils, "make_process_from_runner", None)
        if factory is not None and getattr(factory, "_pet_patched", False):
            ch_utils.make_process_from_runner = factory._original
    except Exception:
        pass
    _PATCHED = False
    logger.info("QwenPaw Pet restored AgentRunner.stream_query")
