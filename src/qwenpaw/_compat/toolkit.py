# -*- coding: utf-8 -*-
"""Shim for the agentscope 1.x ``Toolkit.register_*`` API.

agentscope 2.0 removed dynamic tool registration: :class:`agentscope.tool.Toolkit`
now takes everything (tools, MCP clients, skills, tool groups) at construction
time, with no ``register_tool_function`` / ``register_mcp_client`` methods and
no ``view_task`` / ``wait_task`` / ``cancel_task`` built-in helpers.

qwenpaw still does post-construction registration in many places (the
``react_agent`` toolkit builder, ``coding_mode_mixin`` for lsp/ast tools,
``reme_light_memory_manager`` for memory tools, ``proactive_responder`` for
background tools).  This module monkey-patches the 1.x methods onto the 2.0
:class:`Toolkit` so those call sites keep working: each registration wraps the
function in a :class:`FunctionTool` and appends it to the reserved
``"basic"`` tool group.

TODO(as2-migration): delete this once every call site is rewritten to pass
tools via the ``Toolkit(tools=[...])`` constructor (or otherwise uses the 2.0
``ToolGroup`` API directly).
"""
from __future__ import annotations

import contextvars
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


# Carried for the duration of a ``QwenPawAgent`` construction so the shim's
# ``register_tool_function`` wraps each tool in :class:`GuardedFunctionTool`
# (which routes ``check_permissions`` through qwenpaw's tool guard) instead of
# the plain 2.0 :class:`FunctionTool`.  ``_build_qwenpaw_agent`` in
# ``runtime_engine.py`` sets this before constructing the agent and resets it
# in a ``finally`` block.  When unset, the shim falls back to plain
# ``FunctionTool`` so existing call sites that build toolkits outside the
# runtime-engine path stay untouched.
_CURRENT_AGENT_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_qp_toolkit_current_agent_id",
    default=None,
)


def _adapt_qwenpaw_tool(func: Callable) -> Callable:
    """Wrap a qwenpaw tool function so its return value satisfies the
    agentscope 2.0 toolkit contract.

    qwenpaw tools return ``ToolResponse`` (1.x shape).  agentscope 2.0's
    :meth:`Toolkit.call_tool` accepts only ``ToolChunk`` or
    ``AsyncGenerator[ToolChunk]`` and raises
    ``DeveloperOrientedException`` otherwise (see
    ``agentscope.tool._toolkit:333``).  This adapter awaits the inner
    function and re-wraps the completed response into a single
    ``ToolChunk`` with ``is_last=True``.

    ``functools.wraps`` plus the auto-set ``__wrapped__`` attribute lets
    :class:`FunctionTool`'s introspection see through to the original
    function so ``_extract_input_schema`` / ``_extract_func_description``
    still produce the correct schema / description.

    Idempotent: ``__qp_tool_adapted__`` marker on the wrapper prevents
    double-wrapping if the same function gets re-registered.
    """
    import functools
    import inspect

    if getattr(func, "__qp_tool_adapted__", False):
        return func

    # Tools defined as async generators (yielding multiple ToolResponses
    # incrementally) need a different wrapper shape; none of the current
    # Phase 1 tools take this path, but assert defensively so a future
    # tool that does yields a clear error instead of producing silent
    # mis-wrapped output.
    if inspect.isasyncgenfunction(func):
        raise NotImplementedError(
            f"async-generator tools not yet supported in the compat shim: "
            f"{getattr(func, '__name__', func)!r}",
        )

    from agentscope.tool import ToolChunk

    @functools.wraps(func)
    async def adapter(**kwargs: Any) -> Any:
        tr = await func(**kwargs)
        # Tools that already return a ToolChunk (rare) pass through
        # unchanged; the common case is ToolResponse(content=..., state=...).
        if isinstance(tr, ToolChunk):
            return tr
        return ToolChunk(
            content=getattr(tr, "content", None),
            state=getattr(tr, "state", None),
            is_last=True,
        )

    adapter.__qp_tool_adapted__ = True  # type: ignore[attr-defined]
    return adapter


def _matching_tool(group_tools: list, name: str) -> int:
    """Return the index of the first tool in ``group_tools`` named ``name``,
    or ``-1`` if no match."""
    for i, tool in enumerate(group_tools):
        if getattr(tool, "name", None) == name:
            return i
    return -1


def install_toolkit_shim() -> None:
    """Attach 1.x ``register_*`` helpers to :class:`agentscope.tool.Toolkit`.

    Idempotent — checks for ``register_tool_function`` before patching, so a
    future agentscope release that re-adds the method will take precedence.
    """
    try:
        from agentscope.tool import FunctionTool, Toolkit
    except Exception:  # pragma: no cover - keep import tolerant
        return

    if not hasattr(Toolkit, "register_tool_function"):

        def _register_tool_function(  # type: ignore[no-untyped-def]
            self,
            func: Callable,
            *,
            namesake_strategy: str = "skip",
            async_execution: bool = False,  # noqa: ARG001 - 1.x kwarg
            description: str | None = None,
            name: str | None = None,
            **_unused: Any,
        ) -> None:
            """Wrap ``func`` in a :class:`FunctionTool` and append it to the
            reserved ``"basic"`` tool group.

            ``namesake_strategy`` mirrors the 1.x options: ``"skip"`` /
            ``"override"`` / ``"raise"`` / ``"rename"``.  ``async_execution``
            is accepted for source compatibility but ignored — the 2.0 toolkit
            handles async execution via the ``call_tool`` event stream and
            there is no equivalent registration knob.
            """
            tool_name = name or getattr(func, "__name__", None) or "tool"

            basic_group = self.tool_groups[0]
            if basic_group.name != "basic":
                # Shouldn't happen — agentscope 2.0 always prepends "basic".
                # Fall back to the first group anyway so we don't crash.
                logger.warning(
                    "tool_groups[0] is %r, expected 'basic'; tool '%s' will "
                    "be appended there anyway.",
                    basic_group.name,
                    tool_name,
                )

            existing_idx = _matching_tool(basic_group.tools, tool_name)
            if existing_idx >= 0:
                if namesake_strategy == "skip":
                    logger.debug(
                        "Skipping namesake tool '%s' (already registered).",
                        tool_name,
                    )
                    return
                if namesake_strategy == "override":
                    basic_group.tools.pop(existing_idx)
                elif namesake_strategy == "raise":
                    raise ValueError(
                        f"Tool '{tool_name}' is already registered.",
                    )
                elif namesake_strategy == "rename":
                    suffix = 2
                    while (
                        _matching_tool(
                            basic_group.tools,
                            f"{tool_name}_{suffix}",
                        )
                        >= 0
                    ):
                        suffix += 1
                    tool_name = f"{tool_name}_{suffix}"
                else:
                    logger.warning(
                        "Unknown namesake_strategy '%s' for tool '%s'; "
                        "falling back to 'skip'.",
                        namesake_strategy,
                        tool_name,
                    )
                    return

            # Wrap the raw qwenpaw function (returns ``ToolResponse``) so
            # the toolkit's strict ``ToolChunk``/``AsyncGenerator[ToolChunk]``
            # contract is satisfied at call time.
            adapted = _adapt_qwenpaw_tool(func)
            agent_id = _CURRENT_AGENT_ID.get()
            if agent_id is not None:
                # Late import — runtime_engine imports `_compat.toolkit`
                # transitively during shim install, so a top-level import
                # here would form a cycle.
                from .runtime_engine import GuardedFunctionTool

                tool = GuardedFunctionTool(
                    adapted,
                    agent_id=agent_id,
                    name=tool_name,
                    description=description,
                )
            else:
                tool = FunctionTool(
                    adapted,
                    name=tool_name,
                    description=description,
                )
            basic_group.tools.append(tool)
            logger.debug(
                "Shim-registered tool '%s' (guarded=%s)",
                tool_name,
                agent_id is not None,
            )

        Toolkit.register_tool_function = _register_tool_function  # type: ignore[attr-defined]

    if not hasattr(Toolkit, "register_mcp_client"):

        async def _register_mcp_client(  # type: ignore[no-untyped-def]
            self,
            client: Any,
            *,
            namesake_strategy: str = "skip",  # noqa: ARG001
            execution_timeout: Any = None,  # noqa: ARG001
            **_unused: Any,
        ) -> None:
            """Append an already-connected MCP client to the basic group.

            The 1.x ``execution_timeout`` / ``namesake_strategy`` kwargs are
            accepted for source compatibility but ignored — the 2.0 toolkit
            handles those internally based on the ``MCPClient`` config.
            """
            basic_group = self.tool_groups[0]
            if client not in basic_group.mcps:
                basic_group.mcps.append(client)
                logger.debug(
                    "Shim-registered MCP client '%s'",
                    getattr(client, "name", repr(client)),
                )

        Toolkit.register_mcp_client = _register_mcp_client  # type: ignore[attr-defined]

    # 1.x exposed ``view_task`` / ``wait_task`` / ``cancel_task`` as built-in
    # methods that callers passed back into ``register_tool_function``.  2.0
    # replaced them with ``TaskGet`` / ``TaskList`` / ``TaskCreate`` /
    # ``TaskUpdate`` tool classes that take a different shape.  Until qwenpaw
    # migrates to those, expose harmless no-op callables so the registration
    # call sites don't ``AttributeError``.  The resulting tools will be
    # callable but report "background tasks are unavailable".

    def _make_unavailable_stub(name: str) -> Callable:
        async def _stub(**_kwargs: Any) -> str:  # noqa: ANN401
            return (
                f"{name} is not yet ported to agentscope 2.0 "
                "(see qwenpaw._compat.toolkit)."
            )

        _stub.__name__ = name
        _stub.__doc__ = (
            f"Stub for the legacy Toolkit.{name} background-task helper. "
            "Reports unavailability until the agentscope 2.0 TaskCreate/"
            "TaskGet/TaskUpdate tools are wired in."
        )
        return _stub

    for legacy_name in ("view_task", "wait_task", "cancel_task"):
        if not hasattr(Toolkit, legacy_name):
            setattr(Toolkit, legacy_name, _make_unavailable_stub(legacy_name))

    # 1.x exposed ``Toolkit.skills`` (dict[name -> metadata]) and a
    # ``register_agent_skill(skill)`` method.  2.0 dropped the skill concept
    # from Toolkit entirely (skills became a runner-side notion).  Provide an
    # empty-dict ``skills`` property and a no-op ``register_agent_skill`` so
    # call sites that still expect them (``_maybe_inject_skill``,
    # ``_register_skills``) work without raising.
    # TODO(as2-migration): wire skills through the new agentscope.skill API.
    if not hasattr(Toolkit, "skills"):
        # Backed by an instance dict so callers can mutate it if they want.
        def _skills_getter(self):  # type: ignore[no-untyped-def]
            existing = self.__dict__.get("_compat_skills")
            if existing is None:
                existing = {}
                self.__dict__["_compat_skills"] = existing
            return existing

        Toolkit.skills = property(_skills_getter)  # type: ignore[attr-defined]

    if not hasattr(Toolkit, "register_agent_skill"):

        def _register_agent_skill(  # type: ignore[no-untyped-def]
            self,
            skill: Any,
            *_args: Any,
            **_kwargs: Any,
        ) -> None:
            name = getattr(skill, "name", None) or repr(skill)
            self.skills[name] = skill
            logger.debug("Shim-registered agent skill '%s' (no-op).", name)

        Toolkit.register_agent_skill = _register_agent_skill  # type: ignore[attr-defined]
