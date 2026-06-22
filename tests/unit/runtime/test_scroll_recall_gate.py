# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""The builder must not wire scroll when its recall tool cannot run.

Scroll's only recall path is the sandboxed ``recall_history_python`` tool,
which fails closed without a ``sandbox_config`` — that config is injected by
the governor. If the governor is absent and ``allow_unsandboxed`` is off,
wiring scroll would evict history into an index nothing can read back, so the
builder degrades to native context management.
"""

from types import SimpleNamespace

from qwenpaw.runtime.builder import AgentBuilder


def _agent_config(allow_unsandboxed: bool) -> SimpleNamespace:
    return SimpleNamespace(
        running=SimpleNamespace(
            light_context_config=SimpleNamespace(
                scroll_config=SimpleNamespace(
                    allow_unsandboxed=allow_unsandboxed,
                ),
            ),
        ),
    )


def test_runnable_when_governor_present():
    # Governor injects sandbox_config, so recall runs regardless of the flag.
    cfg = _agent_config(allow_unsandboxed=False)
    assert AgentBuilder._scroll_recall_runnable(cfg, governor=object()) is True


def test_runnable_when_unsandboxed_opt_in():
    # No governor, but the operator opted into unsandboxed recall.
    cfg = _agent_config(allow_unsandboxed=True)
    assert AgentBuilder._scroll_recall_runnable(cfg, governor=None) is True


def test_not_runnable_without_governor_or_optin():
    # The reported failure: governor down, no opt-in → recall cannot run.
    cfg = _agent_config(allow_unsandboxed=False)
    assert AgentBuilder._scroll_recall_runnable(cfg, governor=None) is False


def test_not_runnable_on_malformed_config():
    # Missing scroll_config must fail closed (degrade to native), not raise.
    cfg = SimpleNamespace(running=SimpleNamespace(light_context_config=None))
    assert AgentBuilder._scroll_recall_runnable(cfg, governor=None) is False
