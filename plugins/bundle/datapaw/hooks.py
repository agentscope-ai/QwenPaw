# -*- coding: utf-8 -*-
"""Monkey-patches the DataPaw plugin applies to host runtime.

Three patches, all installed from ``plugin._on_startup``:

1. ``setup_runner_hooks`` — replaces ``qwenpaw.app.runner.runner.QwenPawAgent``
   with a smart factory that returns ``DataPawAgent`` when
   ``request_context["agent_id"] == "datapaw"``, plus a thin wrapper around
   ``AgentRunner.query_handler`` that stashes ``request`` / ``runner`` in
   contextvars so the adapter can wire ``_on_graph_change`` and the SSE
   queue after agent construction. **No copy of host's 500-line query_handler
   is required** — the integration uses two small mechanisms instead.
2. ``setup_channel_sse_hook`` — replaces ``ConsoleChannel.stream_one`` so the
   DAG ``TaskEvent`` queue attached to ``request._datapaw_sse_queue`` gets
   drained into SSE frames alongside the regular message stream (Phase 8).
3. ``patch_plugin_loader_unload`` — wraps ``PluginLoader.unload_plugin`` so
   uninstalling the plugin runs ``uninstall_builtin_agents`` (Phase 9).
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
from typing import Any

from constants import BUILTIN_DATAPAW_AGENT_ID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context vars carrying per-request runner / request into DataPawAgent.__init__
# ---------------------------------------------------------------------------

_datapaw_request_var: contextvars.ContextVar = contextvars.ContextVar(
    "_datapaw_request", default=None,
)
_datapaw_runner_var: contextvars.ContextVar = contextvars.ContextVar(
    "_datapaw_runner", default=None,
)


# ---------------------------------------------------------------------------
# Smart agent factory (replaces runner module's QwenPawAgent reference)
# ---------------------------------------------------------------------------


class _SmartAgentFactory:
    """Callable that dispatches to DataPawAgent or QwenPawAgent.

    ``qwenpaw.app.runner.runner.query_handler`` does ``agent = QwenPawAgent(**kw)``
    looking up ``QwenPawAgent`` from the runner module's namespace. We rebind
    that name to an instance of this factory so the call routes to the right
    class based on ``request_context["agent_id"]``.
    """

    def __init__(self, original_qwenpaw_cls):
        self._original = original_qwenpaw_cls

    def __call__(self, *args, **kwargs):
        rc = kwargs.get("request_context", {})
        agent_id = ""
        if isinstance(rc, dict):
            agent_id = rc.get("agent_id", "") or ""

        if agent_id == BUILTIN_DATAPAW_AGENT_ID:
            return _DataPawAgentAdapter(*args, **kwargs)
        return self._original(*args, **kwargs)


# ---------------------------------------------------------------------------
# Adapter: DataPawAgent + post-init wiring
# ---------------------------------------------------------------------------


def _import_data_paw_agent():
    from core.agents.base import DataPawAgent
    return DataPawAgent


def _DataPawAgentAdapter(*args, **kwargs):
    """Construct a ``DataPawAgent`` and wire datapaw-specific runtime hooks.

    ``query_handler`` passes some kwargs that are meaningful to
    ``QwenPawAgent`` but not to ``DataPawAgent`` (most importantly
    ``plan_notebook`` — the host's agentscope PlanNotebook). DataPawAgent
    provides its own ``RuntimeStateManager``; the host-supplied notebook is
    discarded here so we don't fight the post-init injection.
    """
    DataPawAgent = _import_data_paw_agent()

    # DataPawAgent's signature mirrors host's QwenPawAgent (incl.
    # plan_notebook + context_manager) plus datapaw extras, so we pass
    # everything through. plan_notebook is silently ignored inside
    # DataPawAgent.__init__ because RuntimeStateManager replaces it
    # post-init.
    agent = DataPawAgent(*args, **kwargs)

    runner = _datapaw_runner_var.get()
    request = _datapaw_request_var.get()
    rc = kwargs.get("request_context") or {}
    session_id = (rc.get("session_id") if isinstance(rc, dict) else "") or ""
    user_id = (rc.get("user_id") if isinstance(rc, dict) else "") or ""

    notebook = getattr(agent, "plan_notebook", None)
    if notebook is None:
        return agent

    if runner is not None and session_id:
        notebook._on_graph_change = _make_save_hook(
            runner=runner,
            session_id=session_id,
            user_id=user_id,
            agent=agent,
        )

    # SSE queue: prefer one already attached to request by the channel layer
    # (Phase 8 ConsoleChannel patch); otherwise create a private buffer so the
    # agent's emit calls don't crash but SSE injection is silently absent.
    queue = None
    if request is not None:
        queue = getattr(request, "_datapaw_sse_queue", None)
    if queue is None:
        queue = asyncio.Queue()
        if request is not None:
            try:
                setattr(request, "_datapaw_sse_queue", queue)
            except Exception:  # pylint: disable=broad-except
                pass
    notebook._sse_event_queue = queue
    return agent


def _make_save_hook(*, runner, session_id, user_id, agent):
    """Return an async callable suitable for ``RuntimeStateManager._on_graph_change``.

    Mirrors the closure shape from fork's ``runner.py`` (DataPawAgent
    integration block in ``query_handler``).
    """
    async def _datapaw_save_hook():
        try:
            await runner.session.save_session_state(
                session_id=session_id,
                user_id=user_id,
                agent=agent,
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "DataPaw intermediate save failed for session=%s",
                session_id,
                exc_info=True,
            )

    return _datapaw_save_hook


# ---------------------------------------------------------------------------
# query_handler wrapper
# ---------------------------------------------------------------------------


def _wrap_query_handler(orig_query_handler):
    """Build a thin ``query_handler`` wrapper that stashes contextvars for datapaw sessions."""

    async def _patched_query_handler(self, msgs, request=None, **kwargs):
        is_datapaw = (
            getattr(self, "agent_id", None) == BUILTIN_DATAPAW_AGENT_ID
        )
        if not is_datapaw:
            async for item in orig_query_handler(self, msgs, request, **kwargs):
                yield item
            return

        request_token = _datapaw_request_var.set(request)
        runner_token = _datapaw_runner_var.set(self)
        try:
            async for item in orig_query_handler(self, msgs, request, **kwargs):
                yield item
        finally:
            _datapaw_request_var.reset(request_token)
            _datapaw_runner_var.reset(runner_token)

    _patched_query_handler._datapaw_patched = True  # type: ignore[attr-defined]
    return _patched_query_handler


def setup_runner_hooks(_runner_module=None) -> None:
    """Install the smart factory + query_handler wrapper on host's runner module.

    The optional ``_runner_module`` argument is used by tests to inject a
    fake module without monkeying with ``sys.modules`` import chains.
    """
    if _runner_module is None:
        import qwenpaw.app.runner.runner as _runner_module  # noqa: F811

    if getattr(_runner_module.QwenPawAgent, "_datapaw_factory", False):
        # Already patched (idempotent re-install).
        return

    factory = _SmartAgentFactory(_runner_module.QwenPawAgent)
    factory._datapaw_factory = True  # type: ignore[attr-defined]
    _runner_module.QwenPawAgent = factory  # type: ignore[assignment]

    AgentRunner = _runner_module.AgentRunner
    orig = AgentRunner.query_handler
    if not getattr(orig, "_datapaw_patched", False):
        AgentRunner.query_handler = _wrap_query_handler(orig)


# ---------------------------------------------------------------------------
# Phase 8 / Phase 9 placeholders — implemented in subsequent tasks
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Channel SSE injection
# ---------------------------------------------------------------------------


def _extract_datapaw_metadata(metadata: Any) -> dict:
    """Extract DataPaw routing metadata from a runtime message.

    Mirrors fork's ``ConsoleChannel._extract_datapaw_metadata``: pulls out
    only ``graph_id`` / ``node_id`` keys, accepting both ``{...}`` and
    ``{"metadata": {...}}`` shapes for backward compatibility.
    """
    if not isinstance(metadata, dict):
        return {}
    raw = metadata.get("metadata")
    source = raw if isinstance(raw, dict) else metadata
    return {
        key: str(source[key])
        for key in ("graph_id", "node_id")
        if source.get(key)
    }


def _format_task_event_as_sse(event: Any) -> str:
    """Turn a DataPaw TaskEvent (or fallback dict) into an SSE ``data:`` frame."""
    import json
    if hasattr(event, "model_dump_json"):
        body = event.model_dump_json()
    else:
        body = json.dumps(
            {"object": "task_status", "text": str(event)},
            ensure_ascii=False,
        )
    return f"data: {body}\n\n"


def _wrap_stream_one(orig_stream_one):
    """Build a ``stream_one`` wrapper that drains DataPaw TaskEvents into SSE.

    Strategy: after each frame the original yields, peek at
    ``request._datapaw_sse_queue`` and emit any buffered ``TaskEvent`` as
    extra SSE frames. ``request`` is identified as ``payload`` itself in the
    typical request-object code path (HTTP POST). When ``payload`` is a dict
    (e.g. content_parts native channel input), the original constructs
    ``request`` internally and we cannot safely re-construct it without
    side effects; in that case datapaw events stay buffered (degraded mode).
    """

    async def _patched_stream_one(self, payload):
        # Pick a request reference for datapaw queue access without
        # re-running build_agent_request_from_native (which has side
        # effects). Only the request-object call path supports drain.
        request_ref = (
            None
            if isinstance(payload, dict) and "content_parts" in payload
            else payload
        )

        async for frame in orig_stream_one(self, payload):
            yield frame
            if request_ref is None:
                continue
            queue = getattr(request_ref, "_datapaw_sse_queue", None)
            if queue is None:
                continue
            while not queue.empty():
                try:
                    event = queue.get_nowait()
                except Exception:  # pylint: disable=broad-except
                    break
                try:
                    yield _format_task_event_as_sse(event)
                except Exception:  # pylint: disable=broad-except
                    logger.debug(
                        "failed to emit datapaw graph event",
                        exc_info=True,
                    )

        # Tail flush — events emitted after the last agent event
        # (e.g. finish_plan at the end of the reply loop).
        if request_ref is None:
            return
        queue = getattr(request_ref, "_datapaw_sse_queue", None)
        if queue is None:
            return
        while not queue.empty():
            try:
                event = queue.get_nowait()
            except Exception:  # pylint: disable=broad-except
                break
            try:
                yield _format_task_event_as_sse(event)
            except Exception:  # pylint: disable=broad-except
                logger.debug(
                    "failed to emit tail datapaw graph event",
                    exc_info=True,
                )

    _patched_stream_one._datapaw_patched = True  # type: ignore[attr-defined]
    return _patched_stream_one


def setup_channel_sse_hook(_channel_cls=None) -> None:
    """Wrap ``ConsoleChannel.stream_one`` and add ``_extract_datapaw_metadata``.

    The optional ``_channel_cls`` argument is for unit tests; production
    code path imports the real ``ConsoleChannel`` from host.
    """
    if _channel_cls is None:
        from qwenpaw.app.channels.console.channel import ConsoleChannel
        _channel_cls = ConsoleChannel

    if getattr(_channel_cls.stream_one, "_datapaw_patched", False):
        return  # idempotent

    orig = _channel_cls.stream_one
    _channel_cls.stream_one = _wrap_stream_one(orig)
    _channel_cls._extract_datapaw_metadata = staticmethod(  # type: ignore[attr-defined]
        _extract_datapaw_metadata,
    )


# ---------------------------------------------------------------------------
# PluginLoader.unload_plugin patch
# ---------------------------------------------------------------------------


def uninstall_builtin_agents() -> None:
    """Re-export for unload path mock-friendliness.

    Tests `patch("hooks.uninstall_builtin_agents", ...)` to intercept
    uninstall behaviour without touching agents_setup directly.
    """
    from agents_setup import uninstall_builtin_agents as _u
    return _u()


def patch_plugin_loader_unload(_loader_module=None) -> None:
    """Wrap ``PluginLoader.unload_plugin`` so plugin uninstall cleans up.

    For ``plugin_id=="datapaw"``, run ``uninstall_builtin_agents`` first,
    then defer to the host's original ``unload_plugin``. Other plugins are
    unaffected. Idempotent.

    The optional ``_loader_module`` argument is for unit tests.
    """
    if _loader_module is None:
        from qwenpaw.plugins import loader as _loader_module  # noqa: F811

    PluginLoader = _loader_module.PluginLoader
    orig = PluginLoader.unload_plugin
    if getattr(orig, "_datapaw_patched", False):
        return  # idempotent

    async def _patched_unload(self, plugin_id, delete_files=False):
        if plugin_id == "datapaw":
            try:
                uninstall_builtin_agents()
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "DataPaw uninstall_builtin_agents failed; continuing with"
                    " host PluginLoader.unload_plugin",
                    exc_info=True,
                )
        return await orig(self, plugin_id, delete_files)

    _patched_unload._datapaw_patched = True  # type: ignore[attr-defined]
    PluginLoader.unload_plugin = _patched_unload
