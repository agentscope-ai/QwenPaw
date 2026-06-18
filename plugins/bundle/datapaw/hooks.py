# -*- coding: utf-8 -*-
# pylint: disable=protected-access,relative-beyond-top-level
# Monkey-patches by definition reach into host internals
# (``notebook._sse_event_queue`` / ``channel._datapaw_*`` /
# ``_patched_query_handler._datapaw_patched`` / ...). The entire module
# operates in that regime; per-site disables would be noise.
"""Monkey-patches the DataPaw plugin applies to host runtime.

Four patches, installed from ``plugin._on_startup``:

1. ``setup_mcp_timeout_hook`` — extends CM ``HttpStatefulClient`` MCP /
   httpx read timeouts so long ``execute_sql`` calls can run up to ~40min.
2. ``setup_runner_hooks`` — replaces ``qwenpaw.app.runner.runner.QwenPawAgent``
   with a smart factory that returns ``DataPawAgent`` when
   ``request_context["agent_id"] == "datapaw"``, plus a thin wrapper around
   ``AgentRunner.query_handler`` that stashes ``request`` / ``runner`` in
   contextvars so the adapter can wire ``DAGStore`` and the SSE queue after
   agent construction.
3. ``setup_channel_sse_hook`` — replaces ``ConsoleChannel.stream_one`` so the
   DAG ``TaskEvent`` queue attached to ``request._datapaw_sse_queue`` gets
   drained into SSE frames alongside the regular message stream.
4. ``setup_console_request_context_hook`` — restores the top-level
   ``request_context`` (e.g. ``{"datasource_id": ...}``) that the console
   chat router otherwise drops, so it reaches the agent's ``_request_context``.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
from typing import Any

from .constants import BUILTIN_DATAPAW_AGENT_ID
from .core.sse_metadata import NODE_ROUTING_METADATA_KEYS

logger = logging.getLogger(__name__)


_PATCH_MARKER_ATTRS = ("_datapaw_factory", "_datapaw_patched")


# ---------------------------------------------------------------------------
# Context vars carrying per-request runner / request into DataPawAgent.__init__
# ---------------------------------------------------------------------------

_datapaw_request_var: contextvars.ContextVar = contextvars.ContextVar(
    "_datapaw_request",
    default=None,
)
_datapaw_runner_var: contextvars.ContextVar = contextvars.ContextVar(
    "_datapaw_runner",
    default=None,
)


# ---------------------------------------------------------------------------
# CM MCP long-timeout patch (HttpStatefulClient build hook)
# ---------------------------------------------------------------------------


def setup_mcp_timeout_hook(_manager_cls=None) -> None:
    """Patch ``MCPClientManager._build_client`` for CM long ``execute_sql``.

    The optional ``_manager_cls`` argument is for unit tests.
    """
    from .core.mcp_cm import apply_cm_mcp_long_timeouts, is_cm_mcp_config

    if _manager_cls is None:
        from qwenpaw.app.mcp.manager import MCPClientManager

        _manager_cls = MCPClientManager

    orig = _manager_cls._build_client
    if getattr(orig, "_datapaw_mcp_timeout_patched", False):
        return

    def _patched_build_client(client_config):
        client = orig(client_config)
        if is_cm_mcp_config(client_config):
            apply_cm_mcp_long_timeouts(client)
        return client

    _patched_build_client._datapaw_mcp_timeout_patched = True  # type: ignore[attr-defined]
    _manager_cls._build_client = staticmethod(_patched_build_client)


# ---------------------------------------------------------------------------
# Smart agent factory (replaces runner module's QwenPawAgent reference)
# ---------------------------------------------------------------------------


class _SmartAgentFactory:
    """Callable that dispatches to DataPawAgent or QwenPawAgent.

    The host's ``query_handler`` does ``agent = QwenPawAgent(**kw)``
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
            return _build_datapaw_agent(*args, **kwargs)
        return self._original(*args, **kwargs)


# ---------------------------------------------------------------------------
# Adapter: DataPawAgent + post-init wiring
# ---------------------------------------------------------------------------


def _import_data_paw_agent():
    from .core.agents.base import DataPawAgent

    return DataPawAgent


def _build_datapaw_agent(*args, **kwargs):
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
        try:
            from .core.orchestration.dag_store import DAGStore

            notebook.configure_dag_store(
                DAGStore.from_session(
                    runner.session,
                    user_id=user_id or "default",
                ),
                session_id=session_id,
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "DataPaw DAGStore wiring failed for session=%s",
                session_id,
                exc_info=True,
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
            except AttributeError:
                # Real Starlette ``Request`` objects accept arbitrary
                # attributes; the only realistic failure is a frozen test
                # double. Log a debug line and move on so the agent can
                # still emit events to its private queue.
                logger.debug(
                    "Could not attach _datapaw_sse_queue to request"
                    " (frozen object?); SSE events stay in a private"
                    " queue.",
                    exc_info=True,
                )
    notebook._sse_event_queue = queue

    # Broadcast hook: pipe DAG-change events to host's per-agent SSE
    # broadcaster (/api/plan/stream long-lived connection). Lets idle /
    # multi-tab clients see DAG updates without a chat request.
    agent_id = (rc.get("agent_id") if isinstance(rc, dict) else "") or ""
    if agent_id and session_id:
        notebook._on_broadcast = _make_broadcast_hook(
            agent_id=agent_id,
            session_id=session_id,
        )

    return agent


def _make_broadcast_hook(*, agent_id, session_id):
    """Return an async hook that pushes graph events to host's broadcaster.

    Payload uses ``type="datapaw_graph_update"`` (distinct from host's
    ``type="plan_update"``) so frontend code can route by type without
    confusing DAG snapshots with linear plan responses.
    """

    async def _broadcast(event_type: str, payload: dict) -> None:
        try:
            from qwenpaw.plan.broadcast import broadcast_plan_update

            broadcast_plan_update(agent_id, payload, session_id=session_id)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "DataPaw broadcast failed for session=%s event=%s",
                session_id,
                event_type,
                exc_info=True,
            )

    return _broadcast


# ---------------------------------------------------------------------------
# query_handler wrapper
# ---------------------------------------------------------------------------


def _wrap_query_handler(orig_query_handler):
    """Build a ``query_handler`` wrapper that stashes contextvars per turn."""

    async def _patched_query_handler(self, msgs, request=None, **kwargs):
        is_datapaw = (
            getattr(self, "agent_id", None) == BUILTIN_DATAPAW_AGENT_ID
        )
        if not is_datapaw:
            async for item in orig_query_handler(
                self,
                msgs,
                request,
                **kwargs,
            ):
                yield item
            return

        request_token = _datapaw_request_var.set(request)
        runner_token = _datapaw_runner_var.set(self)
        try:
            async for item in orig_query_handler(
                self,
                msgs,
                request,
                **kwargs,
            ):
                yield item
        finally:
            _datapaw_request_var.reset(request_token)
            _datapaw_runner_var.reset(runner_token)

    _patched_query_handler._datapaw_patched = True
    return _patched_query_handler


def setup_runner_hooks(_runner_module=None) -> None:
    """Install the smart factory + query_handler wrapper on the runner module.

    The optional ``_runner_module`` argument is used by tests to inject a
    fake module without monkeying with ``sys.modules`` import chains.
    """
    if _runner_module is None:
        from importlib import import_module

        _runner_module = import_module("qwenpaw.app.runner.runner")

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

    Pulls out only ``graph_id`` / ``node_id`` keys, accepting both
    ``{...}`` and ``{"metadata": {...}}`` shapes. Used by
    ``_maybe_inject_node_metadata`` and exposed as a static method on
    ``ConsoleChannel`` so other code can reuse it.
    """
    if not isinstance(metadata, dict):
        return {}
    raw = metadata.get("metadata")
    source = raw if isinstance(raw, dict) else metadata
    return {
        key: str(source[key])
        for key in NODE_ROUTING_METADATA_KEYS
        if source.get(key)
    }


def _maybe_inject_node_metadata(
    frame: str,
    store: dict,
) -> str:
    """Parse one SSE frame and inject DataPaw node metadata when applicable.

    Two-stage logic:

    - ``message`` frames carry ``metadata.{graph_id, node_id}`` of their
      own — extract and store them under ``store[msg_id]``, pass the
      frame through unchanged.
    - ``content`` frames look up the same ``msg_id`` in ``store``; on a
      hit, inject the metadata into the payload and re-serialize the
      frame. The frontend uses the metadata to route streamed tokens to
      the matching DAG node (task panel drawer fold/unfold).

    Other frames pass through unchanged. Failure to parse a frame (or any
    unexpected shape) silently returns the original frame — this layer
    must never break the SSE stream.
    """
    if not frame.startswith("data: "):
        return frame
    try:
        payload = json.loads(frame[len("data: ") :].rstrip("\n"))
    except (json.JSONDecodeError, ValueError):
        return frame
    if not isinstance(payload, dict):
        return frame

    obj = payload.get("object")
    if obj == "message":
        msg_id = payload.get("id")
        dp = _extract_datapaw_metadata(payload.get("metadata"))
        if msg_id and dp:
            store[str(msg_id)] = dp
        return frame

    if obj == "content":
        msg_id = payload.get("msg_id")
        if msg_id is not None and str(msg_id) in store:
            payload["metadata"] = store[str(msg_id)]
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return frame


def _format_task_event_as_sse(event: Any) -> str:
    """Turn a TaskEvent (or fallback dict) into an SSE ``data:`` frame."""
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

    Strategy: keep chat metadata injection in this wrapper. Legacy TaskEvent
    drain is attempted only when ``payload`` is already a request object with
    ``_datapaw_sse_queue``; DAG updates now have their own
    ``/api/tasks/{sid}/dag/events`` stream.
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
        # msg_id -> {graph_id, node_id}, populated from message frames
        # and reused by later content frames with the same msg_id.
        metadata_by_msg_id: dict = {}

        async for frame in orig_stream_one(self, payload):
            frame = _maybe_inject_node_metadata(frame, metadata_by_msg_id)
            yield frame
            if request_ref is None:
                continue
            queue = getattr(request_ref, "_datapaw_sse_queue", None)
            if queue is None:
                continue
            while not queue.empty():
                try:
                    event = queue.get_nowait()
                except asyncio.QueueEmpty:
                    # Already guarded by ``not queue.empty()`` above; the
                    # only race is another consumer draining concurrently.
                    break
                try:
                    yield _format_task_event_as_sse(event)
                except Exception:  # pylint: disable=broad-except
                    # SSE stream must not break on a single bad event.
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
            except asyncio.QueueEmpty:
                # Already guarded by ``not queue.empty()`` above; the
                # only race is another consumer draining concurrently.
                break
            try:
                yield _format_task_event_as_sse(event)
            except Exception:  # pylint: disable=broad-except
                # SSE stream must not break on a single bad event.
                logger.debug(
                    "failed to emit tail datapaw graph event",
                    exc_info=True,
                )

    _patched_stream_one._datapaw_patched = True  # type: ignore[attr-defined]
    return _patched_stream_one


def setup_channel_sse_hook(_channel_cls=None) -> None:
    """Wrap ``ConsoleChannel.stream_one`` + add ``_extract_datapaw_metadata``.

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
    _channel_cls._extract_datapaw_metadata = staticmethod(
        _extract_datapaw_metadata,
    )


# ---------------------------------------------------------------------------
# Console request_context pass-through
#
# The ``/console/chat`` router rebuilds a ``native_payload`` that drops the
# top-level ``request_context`` (e.g. ``{"datasource_id": ...}``) before it
# reaches the channel. Two cooperating patches restore it:
#
# 1. ``_extract_session_and_payload`` — copy ``request_context`` into the
#    native payload so it survives the router → channel hand-off.
# 2. ``ConsoleChannel.build_agent_request_from_native`` — attach it to the
#    ``AgentRequest`` so the host runner's existing merge into
#    ``base_request_context`` carries it to the agent's ``_request_context``.
# ---------------------------------------------------------------------------


def _read_request_context(request_data: Any) -> dict | None:
    """Pull a dict ``request_context`` from an AgentRequest or raw dict."""
    if isinstance(request_data, dict):
        rc = request_data.get("request_context")
    else:
        rc = getattr(request_data, "request_context", None)
    return rc if isinstance(rc, dict) and rc else None


def _wrap_extract_session_and_payload(orig):
    """Wrap router ``_extract_session_and_payload`` to keep request_context."""

    def _patched(request_data):
        native_payload = orig(request_data)
        request_context = _read_request_context(request_data)
        if request_context is not None and isinstance(native_payload, dict):
            native_payload["request_context"] = request_context
        return native_payload

    _patched._datapaw_patched = True  # type: ignore[attr-defined]
    return _patched


def _wrap_build_agent_request_from_native(orig):
    """Wrap channel ``build_agent_request_from_native`` to set request_context."""

    def _patched(self, native_payload):
        request = orig(self, native_payload)
        payload = native_payload if isinstance(native_payload, dict) else {}
        request_context = payload.get("request_context")
        if isinstance(request_context, dict) and request_context:
            try:
                request.request_context = request_context
            except AttributeError:
                logger.debug(
                    "Could not attach request_context to AgentRequest"
                    " (frozen object?); datasource context will be absent.",
                    exc_info=True,
                )
        return request

    _patched._datapaw_patched = True  # type: ignore[attr-defined]
    return _patched


def setup_console_request_context_hook(
    _console_module=None,
    _channel_cls=None,
) -> None:
    """Restore ``request_context`` pass-through on the console chat path.

    The optional arguments inject fakes for unit tests; production imports
    the real router module and ``ConsoleChannel`` from host.
    """
    if _console_module is None:
        from importlib import import_module

        _console_module = import_module("qwenpaw.app.routers.console")
    if _channel_cls is None:
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        _channel_cls = ConsoleChannel

    orig_extract = _console_module._extract_session_and_payload
    if not getattr(orig_extract, "_datapaw_patched", False):
        _console_module._extract_session_and_payload = (
            _wrap_extract_session_and_payload(orig_extract)
        )

    orig_build = _channel_cls.build_agent_request_from_native
    if not getattr(orig_build, "_datapaw_patched", False):
        _channel_cls.build_agent_request_from_native = (
            _wrap_build_agent_request_from_native(orig_build)
        )
