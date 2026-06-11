# -*- coding: utf-8 -*-
"""Contract test for the ``plan_notebook`` constructor parameter.

BUG 2 (agentscope 1.x -> 2.0 migration residue): the runner constructs the
agent with ``QwenPawAgent(..., plan_notebook=plan_notebook)`` and the agent's
``_acting`` plan gate reads ``getattr(self, "plan_notebook", None)``, but the
``__init__`` signature was missing the parameter entirely -- so the runner
call raised ``TypeError`` (pylint E1123 "unexpected-keyword-arg").

The fix adds ``plan_notebook: Any | None = None`` to ``__init__`` (after
``task_tracker``) and stores it as ``self.plan_notebook``. These tests lock in
that contract via ``inspect`` so the agent never needs to be fully booted
(which would require a complete model/skill stack). They also assert the
runner still passes the kwarg, so the two sides stay in sync.
"""

from __future__ import annotations

import inspect

from qwenpaw.agents.react_agent import QwenPawAgent


def test_init_accepts_plan_notebook_keyword_with_none_default():
    """``__init__`` must accept ``plan_notebook`` defaulting to ``None``."""
    sig = inspect.signature(QwenPawAgent.__init__)
    assert "plan_notebook" in sig.parameters
    assert sig.parameters["plan_notebook"].default is None


def test_plan_notebook_is_positioned_after_task_tracker():
    """BUG 2 requires the new param to follow ``task_tracker``."""
    params = list(inspect.signature(QwenPawAgent.__init__).parameters)
    assert "task_tracker" in params
    assert params.index("plan_notebook") > params.index("task_tracker")


def test_init_source_stores_plan_notebook_on_self():
    """The constructor must persist the value so ``_acting`` can read it.

    ``_acting`` consults ``getattr(self, "plan_notebook", None)``; if the
    constructor does not assign ``self.plan_notebook`` the gate silently
    never triggers. Asserting against the source keeps this lightweight
    (no full agent boot) while still pinning the assignment.
    """
    src = inspect.getsource(QwenPawAgent.__init__)
    assert "self.plan_notebook = plan_notebook" in src


def test_runner_passes_plan_notebook_to_constructor():
    """The runner call site must keep forwarding the kwarg (E1123 guard)."""
    from qwenpaw.app.runner import runner as runner_mod

    src = inspect.getsource(runner_mod)
    assert "plan_notebook=plan_notebook" in src
