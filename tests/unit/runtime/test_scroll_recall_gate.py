# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""The builder's two scroll recall gates.

``_scroll_recall_runnable`` — whether scroll is wired at all. The sandboxed
``recall_history_python`` REPL fails closed without a ``sandbox_config`` (the
governor injects it); the structured ``recall_history`` tool runs in-process
but with no governor the guard layer itself is degraded. So the gate stays
conservative: governor absent and ``allow_unsandboxed`` off → degrade to
native context management rather than evict history nothing can read back.

``_scroll_repl_runnable`` — the narrower gate applied once scroll IS wired:
whether to ALSO offer the Python REPL. It is registered only when a sandbox
actually exists (governor present AND its probe found one) or unsandboxed
recall is explicitly opted in. Otherwise it is omitted — on a no-sandbox
platform it would only fail-closed into a recurring approval prompt — and the
model recalls through the structured ``recall_history`` tool, which needs no
sandbox.
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


def test_runnable_when_unsandboxed_opt_in(monkeypatch):
    # No governor, but the deployment opted into unsandboxed recall — which
    # needs BOTH the env var and the per-agent flag (agent.json alone can't
    # bypass the sandbox).
    monkeypatch.setenv("QWENPAW_ALLOW_UNSANDBOXED_RECALL", "1")
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


# ── recall_history_python REPL gate: only offered when a sandbox exists ──
#
# Scroll is already wired (structured recall_history is present regardless);
# this narrower gate decides whether to ALSO register the sandboxed Python
# REPL. Omitting it on no-sandbox platforms is what removes the recurring
# approval prompt the user reported.


def _governor(sandbox_available: bool) -> SimpleNamespace:
    return SimpleNamespace(sandbox_available=sandbox_available)


def test_repl_offered_when_sandbox_available():
    cfg = _agent_config(allow_unsandboxed=False)
    assert AgentBuilder._scroll_repl_runnable(cfg, _governor(True)) is True


def test_repl_omitted_when_governor_present_but_no_sandbox():
    # The reported case: governor is up (so scroll wires and the structured
    # tool is present) but the platform has no sandbox (e.g. Windows without
    # WSL2). The REPL would only fail-closed → approval popup, so omit it.
    cfg = _agent_config(allow_unsandboxed=False)
    assert AgentBuilder._scroll_repl_runnable(cfg, _governor(False)) is False


def test_repl_offered_when_unsandboxed_opt_in(monkeypatch):
    # No sandbox, but the operator explicitly opted into unsandboxed recall.
    monkeypatch.setenv("QWENPAW_ALLOW_UNSANDBOXED_RECALL", "1")
    cfg = _agent_config(allow_unsandboxed=True)
    assert AgentBuilder._scroll_repl_runnable(cfg, _governor(False)) is True


def test_repl_omitted_without_governor_or_optin():
    cfg = _agent_config(allow_unsandboxed=False)
    assert AgentBuilder._scroll_repl_runnable(cfg, governor=None) is False


def test_repl_gate_survives_malformed_config():
    cfg = SimpleNamespace(running=SimpleNamespace(light_context_config=None))
    assert AgentBuilder._scroll_repl_runnable(cfg, governor=None) is False


# ── End-to-end: prove the model's tool list omits the REPL with no sandbox ──
#
# The gate above is the decision; these lock in that the decision actually
# controls REGISTRATION — i.e. with no sandbox the recall_history_python REPL
# never lands in the tool list the model sees, only the structured tool does.


def _identity_wrap(fn, *_args, **_kwargs):
    # Bypass the real guard wrapper so we can assert on the raw tools that
    # were registered.
    return fn


def _scroll(recall_tool, repl_tool) -> SimpleNamespace:
    return SimpleNamespace(recall_tool=recall_tool, repl_tool=repl_tool)


def test_no_sandbox_omits_repl_from_registered_tools(monkeypatch):
    monkeypatch.setattr(
        AgentBuilder,
        "_wrap_tool",
        staticmethod(_identity_wrap),
    )
    builder = AgentBuilder.__new__(AgentBuilder)
    extra: list = []
    builder._append_scroll_recall_tools(
        extra,
        _scroll("RECALL_HISTORY", "REPL"),
        _agent_config(allow_unsandboxed=False),
        "ag1",
        {},
        _governor(sandbox_available=False),
    )
    # Only the structured tool is registered; the REPL is absent, so the
    # model never sees recall_history_python and never hits its approval loop.
    assert extra == ["RECALL_HISTORY"]


def test_with_sandbox_registers_both_tools(monkeypatch):
    monkeypatch.setattr(
        AgentBuilder,
        "_wrap_tool",
        staticmethod(_identity_wrap),
    )
    builder = AgentBuilder.__new__(AgentBuilder)
    extra: list = []
    builder._append_scroll_recall_tools(
        extra,
        _scroll("RECALL_HISTORY", "REPL"),
        _agent_config(allow_unsandboxed=False),
        "ag1",
        {},
        _governor(sandbox_available=True),
    )
    assert extra == ["RECALL_HISTORY", "REPL"]
