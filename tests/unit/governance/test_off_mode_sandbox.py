# -*- coding: utf-8 -*-
"""UT for OFF-mode sandbox provisioning.

approval_level=OFF skips "ask the user" but must NOT skip "run it in a
sandbox". These tests pin that only fail-closed tools (the REPL) get a
sandbox_config compiled in OFF mode, that fail-open shell tools (Bash) are
left untouched, and that no sandbox platform → no-op.
"""
from __future__ import annotations

# pylint: disable=protected-access

from qwenpaw.governance import tool_adapter
from qwenpaw.governance.tool_registry import DEFAULT_REGISTRY


class _FakeGovernor:
    def __init__(self, sandbox_available: bool = True) -> None:
        self.sandbox_available = sandbox_available
        self.compiled: list = []

    def compile_sandbox_config(self, tc_spec):  # noqa: ANN
        self.compiled.append(tc_spec)
        return f"sandbox-cfg-for-{tc_spec}"


class _FakeTool:
    """Minimal stand-in for a PolicyGuardedTool instance."""

    def __init__(self, name: str) -> None:
        self.name = name

    def _build_tc_spec(self):  # noqa: ANN
        return f"tc:{self.name}"


class TestRegistryFlag:
    def test_repl_requires_sandbox(self):
        assert DEFAULT_REGISTRY.requires_sandbox("RecallHistoryPython") is True

    def test_bash_does_not_require_sandbox(self):
        assert DEFAULT_REGISTRY.requires_sandbox("Bash") is False

    def test_unknown_tool_defaults_false(self):
        assert DEFAULT_REGISTRY.requires_sandbox("NopeTool") is False


class TestOffModeSandbox:
    def test_repl_gets_sandbox_compiled(self):
        tool = _FakeTool("recall_history_python")
        gov = _FakeGovernor(sandbox_available=True)

        tool_adapter._prepare_off_mode_sandbox(tool, gov)

        assert tool._qp_sandbox_mode is True
        assert (
            tool._qp_sandbox_config
            == "sandbox-cfg-for-tc:recall_history_python"
        )
        assert gov.compiled, "compile_sandbox_config was never called"

    def test_bash_left_untouched(self):
        """Fail-open Bash must stay unsandboxed in OFF mode."""
        tool = _FakeTool("execute_shell_command")
        gov = _FakeGovernor(sandbox_available=True)

        tool_adapter._prepare_off_mode_sandbox(tool, gov)

        assert not hasattr(tool, "_qp_sandbox_mode")
        assert not hasattr(tool, "_qp_sandbox_config")
        assert not gov.compiled

    def test_no_sandbox_platform_is_noop(self):
        """No sandbox available → REPL is a no-op (config stays unset)."""
        tool = _FakeTool("recall_history_python")
        gov = _FakeGovernor(sandbox_available=False)

        tool_adapter._prepare_off_mode_sandbox(tool, gov)

        assert not hasattr(tool, "_qp_sandbox_mode")
        assert not hasattr(tool, "_qp_sandbox_config")
        assert not gov.compiled

    def test_no_governor_is_noop(self):
        tool = _FakeTool("recall_history_python")
        tool_adapter._prepare_off_mode_sandbox(tool, None)
        assert not hasattr(tool, "_qp_sandbox_mode")

    def test_compile_failure_leaves_config_unset(self):
        """A compile error must fail closed, not run unsandboxed."""

        class _BoomGovernor(_FakeGovernor):
            def compile_sandbox_config(self, tc_spec):  # noqa: ANN
                raise RuntimeError("boom")

        tool = _FakeTool("recall_history_python")
        gov = _BoomGovernor(sandbox_available=True)

        tool_adapter._prepare_off_mode_sandbox(tool, gov)

        # sandbox_mode is only set AFTER a successful compile, so it stays
        # unset — the tool's own fail-closed guard then denies the call.
        assert not hasattr(tool, "_qp_sandbox_mode")
