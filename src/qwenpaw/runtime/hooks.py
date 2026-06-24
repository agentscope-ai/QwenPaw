# -*- coding: utf-8 -*-
"""Runtime hook abstraction — context, action, base class, registry.

Hooks here are the **runtime-orchestration** layer, executed by
``Runtime.run()`` around the fixed build/execute steps. They are distinct
from ``agentscope.middleware`` (which wraps an individual agent's reply
loop) and from ``app/channels`` command routing.

Three return semantics (``HookAction``):

* ``CONTINUE``      — default; proceed to the next hook / phase.
* ``SHORT_CIRCUIT`` — Runtime emits the payload and ends; current phase
                      stops, but ``ON_ERROR`` (if any) and ``FINALLY``
                      still run.
* ``SKIP_AGENT``    — only the two fixed steps (``AgentBuilder.build`` and
                      ``AgentExecutor.run``) are skipped; all hook phases
                      still execute in order.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..exceptions import HookCycleError
from .phases import Phase

if TYPE_CHECKING:
    from agentscope.agent import Agent
    from agentscope.message import Msg

    from ..schemas import AgentRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action / Result
# ---------------------------------------------------------------------------


class HookAction(str, Enum):
    """The three return semantics a hook may emit."""

    CONTINUE = "continue"
    SHORT_CIRCUIT = "short_circuit"
    SKIP_AGENT = "skip_agent"


@dataclass
class HookResult:
    """Wrap a hook's outcome.

    ``payload`` is contractually a ``Msg`` instance when
    ``action == SHORT_CIRCUIT``; the envelope state machine uses it to emit
    a complete SSE sequence. Other shapes are rejected by the envelope
    layer.
    """

    action: HookAction = HookAction.CONTINUE
    payload: "Msg | None" = None


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass
class HookContext:
    """Per-request context handed to every hook.

    Stable, long-lived state is exposed as explicit named fields so IDE
    navigation works. ``extras`` and ``mode_state`` exist as the two
    escape hatches:

    * ``mode_state`` — namespaced by mode name (``"coding"``, ``"mission"``,
      …) for per-mode private state.
    * ``extras`` — true ad-hoc dict for short-lived hook-pair traffic
      (e.g. context-manager handles to ``__exit__`` in ``FINALLY``).
    """

    # ── Identity ──
    request: "AgentRequest"
    session_id: str
    agent_id: str
    root_session_id: str
    root_agent_id: str
    workspace_dir: Path | None

    # ── Containers (read by hooks; never mutated) ──
    workspace: (Any)  # forward ref: app/workspace/workspace.py:Workspace
    app_services: Any  # forward ref: AppServiceManager

    # ── Per-request mutable state, filled in across phases ──
    input_msgs: list = field(default_factory=list)
    agent_config: Any | None = None
    session_state: dict | None = None
    agent: "Agent | None" = None
    error: BaseException | None = None

    # ── Escape hatches ──
    mode_state: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Base hook
# ---------------------------------------------------------------------------


class HookBase:
    """Base class for runtime-level hooks.

    Subclasses set ``phase`` and ``name``; optionally ``priority`` (lower
    runs first as the tie-breaker) and ``before``/``after`` ordering
    constraints, each a tuple of other hook names.
    """

    phase: Phase
    name: str
    priority: int = 100
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()

    async def run(self, _ctx: HookContext) -> HookResult:  # noqa: D401
        return HookResult()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _topo_sort(
    hooks: list[HookBase],
) -> list[HookBase]:
    """Topologically sort ``hooks`` respecting
    ``before``/``after`` constraints.

    Ties are broken by (priority ascending, registration index ascending) so
    the result is deterministic across runs. Constraints referencing unknown
    names produce a warning but do not fail (they're a no-op).
    Cycles raise :class:`HookCycleError` so misconfiguration fails fast at
    startup rather than silently misbehaving in production.
    """
    name_to_hook: dict[str, HookBase] = {h.name: h for h in hooks}
    order_index: dict[str, int] = {h.name: i for i, h in enumerate(hooks)}

    # edge u -> v means "u must run before v"
    incoming: dict[str, set[str]] = {h.name: set() for h in hooks}
    outgoing: dict[str, set[str]] = {h.name: set() for h in hooks}

    def _add_edge(u: str, v: str) -> None:
        if u not in name_to_hook or v not in name_to_hook:
            return
        if v in outgoing[u]:
            return
        outgoing[u].add(v)
        incoming[v].add(u)

    for h in hooks:
        for nm in h.before:
            if nm not in name_to_hook:
                logger.warning(
                    "hook %s declares before=%s but"
                    " %s is not registered; ignoring",
                    h.name,
                    nm,
                    nm,
                )
                continue
            _add_edge(h.name, nm)
        for nm in h.after:
            if nm not in name_to_hook:
                logger.warning(
                    "hook %s declares after=%s but"
                    " %s is not registered; ignoring",
                    h.name,
                    nm,
                    nm,
                )
                continue
            _add_edge(nm, h.name)

    ready: list[str] = sorted(
        (n for n, deps in incoming.items() if not deps),
        key=lambda n: (name_to_hook[n].priority, order_index[n]),
    )
    result: list[HookBase] = []
    while ready:
        n = ready.pop(0)
        result.append(name_to_hook[n])
        # Releasing edges in name order to keep the run stable.
        for m in sorted(outgoing[n]):
            incoming[m].discard(n)
            if not incoming[m]:
                # Insert in sorted (priority, order_index) position.
                key = (name_to_hook[m].priority, order_index[m])
                lo, hi = 0, len(ready)
                while lo < hi:
                    mid = (lo + hi) // 2
                    other = ready[mid]
                    other_key = (
                        name_to_hook[other].priority,
                        order_index[other],
                    )
                    if other_key <= key:
                        lo = mid + 1
                    else:
                        hi = mid
                ready.insert(lo, m)
        outgoing[n].clear()

    if len(result) != len(hooks):
        unresolved = [h.name for h in hooks if h not in result]
        raise HookCycleError(
            f"hook ordering cycle detected; unresolved: {unresolved}",
        )
    return result


class HookRegistry:
    """Register hooks by phase; topologically order them; execute the phase.

    One instance per workspace (held by ``Workspace.plugins.hook_registry``)
    plus optional cross-workspace registries that can be ``merge()``d in.
    Topological order is cached per phase and invalidated on every
    ``register`` call.
    """

    def __init__(self) -> None:
        self._by_phase: dict[Phase, list[HookBase]] = defaultdict(list)
        self._sorted_cache: dict[Phase, list[HookBase]] = {}

    def register(self, hook: HookBase) -> None:
        if not isinstance(hook, HookBase):
            raise TypeError(
                "register() requires a HookBase instance,"
                f" got {type(hook).__name__}",
            )
        if not getattr(hook, "name", None):
            raise ValueError("hook.name must be a non-empty string")
        if not isinstance(hook.phase, Phase):
            raise TypeError(
                f"hook {hook.name!r} has invalid phase {hook.phase!r}",
            )
        self._by_phase[hook.phase].append(hook)
        self._sorted_cache.pop(hook.phase, None)

    def hooks_for(self, phase: Phase) -> list[HookBase]:
        """Return the topologically sorted hooks registered for ``phase``."""
        cached = self._sorted_cache.get(phase)
        if cached is not None:
            return cached
        ordered = _topo_sort(self._by_phase[phase])
        self._sorted_cache[phase] = ordered
        return ordered

    async def run(self, phase: Phase, ctx: HookContext) -> HookResult:
        """Execute all hooks for ``phase`` in topological order.

        * ``SHORT_CIRCUIT`` from any hook stops the phase immediately and
          is returned to the caller.
        * ``SKIP_AGENT`` is sticky: subsequent hooks still run, but the
          final result of the phase carries ``SKIP_AGENT`` so the Runtime
          can skip the two fixed agent steps.
        * Any hook raising propagates to the runtime's ``ON_ERROR`` chain
          via the normal exception path — the registry does **not** swallow
          exceptions; tests rely on this contract.
        """
        final_action = HookAction.CONTINUE
        for hook in self.hooks_for(phase):
            result = await hook.run(ctx)
            if result.action == HookAction.SHORT_CIRCUIT:
                return result
            if result.action == HookAction.SKIP_AGENT:
                final_action = HookAction.SKIP_AGENT
        return HookResult(action=final_action)

    @classmethod
    def merge(cls, *registries: "HookRegistry") -> "HookRegistry":
        """Combine multiple registries into a new one.

        Uses left-to-right register order.
        """
        merged = cls()
        for r in registries:
            for (
                hooks
            ) in r._by_phase.values():  # pylint: disable=protected-access
                for h in hooks:
                    merged.register(h)
        return merged


__all__ = [
    "HookAction",
    "HookBase",
    "HookContext",
    "HookCycleError",
    "HookRegistry",
    "HookResult",
]
