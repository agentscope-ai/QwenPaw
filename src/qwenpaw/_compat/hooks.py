# -*- coding: utf-8 -*-
"""Shim for the agentscope 1.x ``Agent.register_instance_hook`` API.

agentscope 2.0 removed the ``register_instance_hook`` / ``register_class_hook``
/ ``register_static_hook`` family and replaced them with
:class:`agentscope.middleware.MiddlewareBase` subclasses passed via the
``Agent(middlewares=[...])`` constructor.  The new hook points are
``on_reply`` / ``on_reasoning`` / ``on_acting`` / ``on_model_call`` /
``on_system_prompt``.

qwenpaw's react_agent registers five 1.x hooks at construction time
(``pre_reasoning`` from the bootstrap hook, plus four context-manager hooks:
``pre_reply``, ``pre_reasoning``, ``post_acting``, ``post_reply``).  This
module monkey-patches ``register_instance_hook`` back onto
:class:`agentscope.agent.Agent` and routes the legacy callbacks through a
single :class:`_LegacyHookMiddleware` per agent instance.

1.x hook → 2.0 middleware hook mapping:

    pre_reply     → on_reply (before yielding from next_handler)
    post_reply    → on_reply (after collecting all events from next_handler)
    pre_reasoning → on_reasoning (before yielding)
    pre_acting    → on_acting (before yielding)
    post_acting   → on_acting (after the final yield)

TODO(as2-migration): replace each 1.x hook registration with a proper
:class:`MiddlewareBase` subclass passed via the agent constructor, then
delete this module.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List

logger = logging.getLogger(__name__)


_HOOK_TYPE_TO_PHASE: Dict[str, tuple[str, str]] = {
    "pre_reply": ("on_reply", "pre"),
    "post_reply": ("on_reply", "post"),
    "pre_reasoning": ("on_reasoning", "pre"),
    "pre_acting": ("on_acting", "pre"),
    "post_acting": ("on_acting", "post"),
}


def install_hook_shim() -> None:
    """Attach ``Agent.register_instance_hook`` to the 2.0 ``Agent`` class.

    Idempotent — checks for the attribute before patching, so a future
    agentscope release that re-adds the method takes precedence.
    """
    try:
        from agentscope.agent import Agent
        from agentscope.middleware import MiddlewareBase
    except Exception:  # pragma: no cover - keep import tolerant
        return

    if hasattr(Agent, "register_instance_hook"):
        return

    class _LegacyHookMiddleware(MiddlewareBase):
        """Single middleware instance per Agent that dispatches all legacy
        instance hooks to the corresponding 2.0 ``on_*`` hook points."""

        def __init__(self) -> None:
            self.pre_reply: Dict[str, Callable[..., Awaitable]] = {}
            self.post_reply: Dict[str, Callable[..., Awaitable]] = {}
            self.pre_reasoning: Dict[str, Callable[..., Awaitable]] = {}
            self.pre_acting: Dict[str, Callable[..., Awaitable]] = {}
            self.post_acting: Dict[str, Callable[..., Awaitable]] = {}

        def has_phase(self, hook_attr: str, phase: str) -> bool:
            mapping = getattr(self, hook_attr, None)
            return bool(mapping)

        async def _run_pre_hooks(
            self,
            hooks: Dict[str, Callable[..., Awaitable]],
            agent: Any,
            kwargs: dict,
        ) -> dict:
            """Run pre-hooks in registration order.

            Each hook may return a replacement ``kwargs`` dict.  A return
            value of ``None`` (the 1.x convention for "no change") leaves
            ``kwargs`` untouched.
            """
            current = kwargs
            for name, hook in hooks.items():
                try:
                    updated = await hook(agent, current)
                    if isinstance(updated, dict):
                        current = updated
                except Exception:  # pragma: no cover - mirror 1.x best-effort
                    logger.exception("Pre-hook '%s' raised; continuing.", name)
            return current

        async def _run_post_hooks(
            self,
            hooks: Dict[str, Callable[..., Awaitable]],
            agent: Any,
            kwargs: dict,
            output: Any,
        ) -> Any:
            """Run post-hooks in registration order.

            Each hook may return a replacement output ``Msg``.  ``None``
            leaves the output untouched.
            """
            current = output
            for name, hook in hooks.items():
                try:
                    replacement = await hook(agent, kwargs, current)
                    if replacement is not None:
                        current = replacement
                except Exception:  # pragma: no cover - mirror 1.x best-effort
                    logger.exception("Post-hook '%s' raised; continuing.", name)
            return current

        # The middleware base's ``is_implemented`` reflects which methods
        # this subclass overrides; since we always override the three onion
        # hooks, all three get installed into the agent's middleware chains.
        # That is fine — when no concrete legacy hooks are registered for a
        # given phase the pre/post helpers are no-ops.

        async def on_reply(
            self,
            agent: Any,
            input_kwargs: dict,
            next_handler: Callable,
        ):
            input_kwargs = await self._run_pre_hooks(
                self.pre_reply,
                agent,
                input_kwargs,
            )
            events: List[Any] = []
            async for event in next_handler():
                events.append(event)
                yield event
            if self.post_reply:
                last = events[-1] if events else None
                await self._run_post_hooks(
                    self.post_reply,
                    agent,
                    input_kwargs,
                    last,
                )

        async def on_reasoning(
            self,
            agent: Any,
            input_kwargs: dict,
            next_handler: Callable,
        ):
            input_kwargs = await self._run_pre_hooks(
                self.pre_reasoning,
                agent,
                input_kwargs,
            )
            async for event in next_handler():
                yield event

        async def on_acting(
            self,
            agent: Any,
            input_kwargs: dict,
            next_handler: Callable,
        ):
            input_kwargs = await self._run_pre_hooks(
                self.pre_acting,
                agent,
                input_kwargs,
            )
            outputs: List[Any] = []
            async for event in next_handler():
                outputs.append(event)
                yield event
            if self.post_acting:
                last = outputs[-1] if outputs else None
                await self._run_post_hooks(
                    self.post_acting,
                    agent,
                    input_kwargs,
                    last,
                )

    def _get_or_create_middleware(agent: Any) -> _LegacyHookMiddleware:
        """Lazily attach a single :class:`_LegacyHookMiddleware` to the agent
        and wire it into all three onion-hook middleware lists."""
        existing = getattr(agent, "_legacy_hook_middleware", None)
        if existing is not None:
            return existing

        mw = _LegacyHookMiddleware()
        agent._legacy_hook_middleware = mw  # type: ignore[attr-defined]

        # Append to each filtered middleware list the Agent built at __init__
        # time.  Each list defaults to an empty list, so this works even when
        # the agent was constructed without an explicit ``middlewares=`` arg.
        for attr in (
            "_reply_middlewares",
            "_reasoning_middlewares",
            "_acting_middlewares",
        ):
            lst = getattr(agent, attr, None)
            if lst is None:
                # Defensive: 2.0 always sets these, but tolerate odd subclasses.
                lst = []
                setattr(agent, attr, lst)
            lst.append(mw)
        return mw

    def _register_instance_hook(  # type: ignore[no-untyped-def]
        self,
        hook_type: str,
        hook_name: str,
        hook: Callable[..., Awaitable],
    ) -> None:
        """Legacy entry point — store ``hook`` under ``hook_name`` for the
        appropriate phase in the agent's :class:`_LegacyHookMiddleware`."""
        mapping = _HOOK_TYPE_TO_PHASE.get(hook_type)
        if mapping is None:
            logger.warning(
                "register_instance_hook: unknown hook_type '%s' (name=%s); "
                "ignoring.",
                hook_type,
                hook_name,
            )
            return
        attr, _phase = mapping
        # ``attr`` here is e.g. "on_reply"; the middleware stores hooks under
        # the 1.x hook_type ("pre_reply", "post_reply", ...) directly.
        _ = attr  # silence unused — we map via hook_type below
        mw = _get_or_create_middleware(self)
        bucket = getattr(mw, hook_type, None)
        if bucket is None:  # pragma: no cover - defensive
            logger.warning(
                "register_instance_hook: middleware missing bucket for '%s'.",
                hook_type,
            )
            return
        bucket[hook_name] = hook
        logger.debug(
            "Shim-registered legacy hook %s/%s on agent %s.",
            hook_type,
            hook_name,
            getattr(self, "name", type(self).__name__),
        )

    Agent.register_instance_hook = _register_instance_hook  # type: ignore[attr-defined]

    # Provide the 1.x ``remove_instance_hook`` symmetrically so unregistration
    # call sites (if any appear later) keep working.
    if not hasattr(Agent, "remove_instance_hook"):

        def _remove_instance_hook(self, hook_type: str, hook_name: str) -> None:  # type: ignore[no-untyped-def]
            mw = getattr(self, "_legacy_hook_middleware", None)
            if mw is None:
                return
            bucket = getattr(mw, hook_type, None)
            if isinstance(bucket, dict):
                bucket.pop(hook_name, None)

        Agent.remove_instance_hook = _remove_instance_hook  # type: ignore[attr-defined]
