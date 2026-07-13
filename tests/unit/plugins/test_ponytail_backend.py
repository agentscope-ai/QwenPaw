# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,import-outside-toplevel
"""Unit tests for Ponytail Quality Plugin backend.py v4.8.3.

Tests cover:
- ponytail_review: line count, imports, abstractions, dead code, nesting
- ponytail_lint_prompt: plan analysis heuristics
- _ViolationReport: rendering logic
- _read_source: file vs string input
- Plugin registration (register_tool, register_startup_hook, etc.)
"""

import ast
import json
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ponytail_source() -> str:
    """Read the real ponytail backend.py for import."""
    return Path(__file__).resolve().parent.parent.parent.parent \
        / "plugins" / "ponytail" / "backend.py"


@pytest.fixture(scope="module")
def ponytail():
    """Import the real ponytail backend module once."""
    import importlib.util
    import sys

    mod_name = "_ponytail_test_module"
    if mod_name in sys.modules:
        return sys.modules[mod_name]

    spec = importlib.util.spec_from_file_location(
        mod_name, str(_ponytail_source()),
    )
    mod = importlib.util.module_from_spec(spec)
    # Stub agentscope.tool so the import does not fail
    agentscope_tool = types.ModuleType("agentscope.tool")
    agentscope_tool.ToolResponse = str

    agentscope_stub = types.ModuleType("agentscope")
    agentscope_stub.tool = agentscope_tool
    sys.modules["agentscope"] = agentscope_stub
    sys.modules["agentscope.tool"] = agentscope_tool
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


_SAMPLE_GOOD_CODE = """\
def greet(name: str) -> str:
    return f"Hello, {name}!"
"""

_SAMPLE_BLOAT_CODE = """\
import pandas as pd


class GreeterService:
    \"\"\"Greeter service.\"\"\"

    def __init__(self):
        self._greeting = "Hello"

    def greet(self, name: str) -> str:
        \"\"\"Greet someone.\"\"\"
        data = pd.DataFrame({"name": [name]})
        return f"{self._greeting}, {data.iloc[0]['name']}!"
"""

_SAMPLE_DEEP_NESTING = """\
def deep(x: int) -> int:
    if x > 0:
        for i in range(10):
            try:
                if i % 2 == 0:
                    while i < 5:
                        with open("/dev/null") as f:
                            result = f.read()
                            if result:
                                print(result)
            except Exception:
                pass
    return x
"""

_SAMPLE_EMPTY_CODE = """\
def unused():
    pass


class EmptyClass:
    pass
"""


# ---------------------------------------------------------------------------
# _ViolationReport
# ---------------------------------------------------------------------------


class TestViolationReport:
    """Test the internal violation reporting class."""

    def test_empty_report(self, ponytail):
        """Empty report renders 'no violations' message."""
        report = ponytail._ViolationReport()
        result = report.render()
        assert "No violations found" in result
        assert "🐴" in result

    def test_single_violation(self, ponytail):
        """Single violation renders correctly."""
        report = ponytail._ViolationReport()
        report.add("YAGNI", "warning", 10, "File is too long")
        result = report.render()
        assert "L10" in result
        assert "YAGNI" in result
        assert "WARNING" in result
        assert "File is too long" in result

    def test_multiple_violations(self, ponytail):
        """Multiple violations are enumerated."""
        report = ponytail._ViolationReport()
        report.add("YAGNI", "error", 1, "Dead code")
        report.add("Stdlib", "info", 5, "Use built-in")
        result = report.render()
        assert "Found 2 issue(s)" in result
        assert "Dead code" in result
        assert "Use built-in" in result

    def test_all_severities(self, ponytail):
        """All severity levels get correct icons."""
        report = ponytail._ViolationReport()
        report.add("R1", "error", 1, "err")
        report.add("R2", "warning", 2, "warn")
        report.add("R3", "info", 3, "info")
        result = report.render()
        assert "🔴" in result
        assert "🟡" in result
        assert "🔵" in result


# ---------------------------------------------------------------------------
# _read_source
# ---------------------------------------------------------------------------


class TestReadSource:
    """Test the _read_source helper."""

    def test_read_from_code_string(self, ponytail):
        """code argument returns string directly."""
        result = ponytail._read_source(file_path="", code="print(1)")
        assert result == "print(1)"

    def test_read_from_file(self, ponytail, tmp_path):
        """file_path reads and returns file content."""
        f = tmp_path / "test.py"
        f.write_text("x = 1")
        result = ponytail._read_source(file_path=str(f), code="")
        assert result == "x = 1"

    def test_file_not_found(self, ponytail):
        """Missing file returns error ToolResponse."""
        result = ponytail._read_source(file_path="/nonexistent/file.py", code="")
        assert "❌ File not found" in result

    def test_no_input_returns_error(self, ponytail):
        """No file_path and no code returns error."""
        result = ponytail._read_source(file_path="", code="")
        assert "Provide either file_path or code" in result


# ---------------------------------------------------------------------------
# Review checks (integration-style — real AST analysis)
# ---------------------------------------------------------------------------


class TestReviewCheckLineCount:
    """Line count checks."""

    def test_short_file_no_warning(self, ponytail):
        """File under 200 lines produces no warning."""
        lines = ["x = 1"] * 50
        report = ponytail._ViolationReport()
        ponytail._check_line_count(report, lines)
        violations = report._violations
        line_warnings = [v for v in violations if v["rule"] == "YAGNI"]
        assert len(line_warnings) == 0

    def test_long_file_warning(self, ponytail):
        """File over 500 lines produces a warning."""
        lines = ["x = 1"] * 501
        report = ponytail._ViolationReport()
        ponytail._check_line_count(report, lines)
        violations = report._violations
        line_warnings = [v for v in violations if v["rule"] == "YAGNI"]
        assert len(line_warnings) >= 1


class TestReviewCheckImports:
    """Import checks."""

    def test_no_unnecessary_imports(self, ponytail):
        """Code without heavy imports passes."""
        tree = ast.parse("x = 1\ny = 2\nprint(x)")
        lines = ["x = 1", "y = 2", "print(x)"]
        report = ponytail._ViolationReport()
        ponytail._check_imports(report, tree, lines)
        assert len(report._violations) == 0

    def test_pandas_import_flagged(self, ponytail):
        """pandas import is flagged when csv would do."""
        tree = ast.parse("import pandas as pd\ndef f(): pass")
        lines = ["import pandas as pd", "", "def f(): pass"]
        report = ponytail._ViolationReport()
        ponytail._check_imports(report, tree, lines)
        assert any("pandas" in v["message"] for v in report._violations)

    def test_requests_import_flagged(self, ponytail):
        """requests import is flagged when urllib would do."""
        tree = ast.parse("import requests\ndef f(): pass")
        lines = ["import requests", "", "def f(): pass"]
        report = ponytail._ViolationReport()
        ponytail._check_imports(report, tree, lines)
        assert any("requests" in v["message"] for v in report._violations)


class TestReviewCheckAbstractions:
    """Abstraction checks."""

    def test_single_method_class_flagged(self, ponytail):
        """Class with one public method is flagged."""
        tree = ast.parse(
            "class Greeter:\n"
            "    def greet(self): pass\n",
        )
        lines = ["class Greeter:", "    def greet(self): pass"]
        report = ponytail._ViolationReport()
        ponytail._check_abstractions(report, tree, lines)
        assert any("1 public method" in v["message"] for v in report._violations)

    def test_multi_method_class_not_flagged(self, ponytail):
        """Class with >1 method is not flagged."""
        tree = ast.parse(
            "class Worker:\n"
            "    def run(self): pass\n"
            "    def stop(self): pass\n",
        )
        lines = ["class Worker:", "    def run(self): pass", "    def stop(self): pass"]
        report = ponytail._ViolationReport()
        ponytail._check_abstractions(report, tree, lines)
        assert not any("1 public method" in v["message"] for v in report._violations)


class TestReviewCheckDeadCode:
    """Dead code checks."""

    def test_empty_function_flagged(self, ponytail):
        """Function with only pass is flagged."""
        tree = ast.parse(
            "def unused():\n"
            "    pass\n",
        )
        report = ponytail._ViolationReport()
        ponytail._check_dead_code(report, tree)
        assert any("empty" in v["message"].lower() for v in report._violations)

    def test_empty_class_flagged(self, ponytail):
        """Class with only pass is flagged."""
        tree = ast.parse(
            "class Empty:\n"
            "    pass\n",
        )
        report = ponytail._ViolationReport()
        ponytail._check_dead_code(report, tree)
        assert any("empty" in v["message"].lower() for v in report._violations)


class TestReviewCheckNesting:
    """Nesting depth checks."""

    def test_deep_nesting_flagged(self, ponytail):
        """Deeply nested code is flagged."""
        tree = ast.parse(_SAMPLE_DEEP_NESTING)
        lines = _SAMPLE_DEEP_NESTING.splitlines()
        report = ponytail._ViolationReport()
        ponytail._check_nesting(report, tree, lines)
        assert any("nesting" in v["message"].lower() for v in report._violations)

    def test_flat_code_not_flagged(self, ponytail):
        """Flat code is not flagged."""
        tree = ast.parse("x = 1\ny = 2\nprint(x, y)")
        lines = ["x = 1", "y = 2", "print(x, y)"]
        report = ponytail._ViolationReport()
        ponytail._check_nesting(report, tree, lines)
        assert len(report._violations) == 0


class TestReviewCheckComments:
    """Comment ratio checks."""

    def test_high_comment_ratio_flagged(self, ponytail):
        """File with >40% comments is flagged."""
        lines = [
            "# comment 1",
            "# comment 2",
            "# comment 3",
            "# comment 4",
            "x = 1",
        ]
        report = ponytail._ViolationReport()
        ponytail._check_comments(report, lines)
        assert any("comment" in v["message"].lower() for v in report._violations)

    def test_low_comment_ratio_not_flagged(self, ponytail):
        """File with normal comment ratio is not flagged."""
        lines = [
            "# one comment",
            "x = 1",
            "y = 2",
            "z = 3",
            "print(x, y, z)",
        ]
        report = ponytail._ViolationReport()
        ponytail._check_comments(report, lines)
        assert len(report._violations) == 0


class TestReviewCheckPonytailComments:
    """Ponytail comment markers check."""

    def test_fixme_without_ponytail_flagged(self, ponytail):
        """FIXME without ponytail: comment is flagged."""
        lines = [
            "x = 1",
            "# FIXME: this is a hack",
        ]
        report = ponytail._ViolationReport()
        ponytail._check_ponytail_comments(report, lines)
        assert any("ponytail" in v["message"].lower() for v in report._violations)

    def test_ponytail_comment_not_flagged(self, ponytail):
        """FIXME with ponytail: comment is OK."""
        lines = [
            "x = 1",
            "# ponytail: quick fix, add proper validation later",
        ]
        report = ponytail._ViolationReport()
        ponytail._check_ponytail_comments(report, lines)
        assert len(report._violations) == 0


# ---------------------------------------------------------------------------
# ponytail_review (integration)
# ---------------------------------------------------------------------------


class TestPonytailReview:
    """End-to-end review function."""

    def test_review_good_code(self, ponytail):
        """Clean code passes review."""
        result = ponytail.ponytail_review(code=_SAMPLE_GOOD_CODE)
        assert "No violations found" in result
        assert "🐴" in result

    def test_review_bad_code(self, ponytail):
        """Bloated code gets flagged."""
        result = ponytail.ponytail_review(code=_SAMPLE_BLOAT_CODE)
        # Should flag pandas import and single-method class
        assert "Found" in result
        assert "pandas" in result

    def test_review_syntax_error(self, ponytail):
        """Syntax error returns error message."""
        result = ponytail.ponytail_review(code="def broken(")
        assert "Syntax error" in result

    def test_review_file_not_found(self, ponytail):
        """Missing file returns error."""
        result = ponytail.ponytail_review(file_path="/dev/null/nope.py")
        assert "File not found" in result


# ---------------------------------------------------------------------------
# ponytail_lint_prompt
# ---------------------------------------------------------------------------


class TestPonytailLintPrompt:
    """Pre-code lint prompt."""

    def test_clean_plan(self, ponytail):
        """Plan with no issues returns success."""
        result = ponytail.ponytail_lint_prompt(
            plan="Add a simple function to convert string to int",
        )
        assert "No violations" in result

    def test_new_class_flagged(self, ponytail):
        """Plan mentioning 'class' is flagged."""
        result = ponytail.ponytail_lint_prompt(
            plan="Create a new Parser class to parse JSON",
        )
        assert "new class" in result.lower() or "class" in result

    def test_new_dependency_flagged(self, ponytail):
        """Plan mentioning 'pip install' is flagged."""
        result = ponytail.ponytail_lint_prompt(
            plan="I'll pip install numpy and use it",
        )
        assert "dependency" in result.lower() or "numpy" in result

    def test_long_code_snippet_flagged(self, ponytail):
        """Code over 30 lines is flagged."""
        code = "\n".join([f"print({i})" for i in range(35)])
        result = ponytail.ponytail_lint_prompt(code_snippet=code)
        assert "lines" in result

    def test_single_method_class_code_flagged(self, ponytail):
        """Code snippet with single-method class is flagged."""
        code = "class X:\n    def f(self): pass\n"
        result = ponytail.ponytail_lint_prompt(code_snippet=code)
        assert "1 method" in result or "single-method" in result


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


class TestPluginRegistration:
    """Test _PluginRegistrar registration contract."""

    def test_register_registers_tools(self, ponytail):
        """register() calls api.register_tool for both tools."""
        api = MagicMock()
        registrar = ponytail._PluginRegistrar()
        registrar.register(api)
        # Should have called register_tool twice
        assert api.register_tool.call_count >= 2
        tool_names = [call.kwargs["tool_name"] for call in api.register_tool.call_args_list]
        assert "ponytail_review" in tool_names
        assert "ponytail_lint_prompt" in tool_names

    def test_register_registers_startup_hook(self, ponytail):
        """register() registers a startup hook."""
        api = MagicMock()
        registrar = ponytail._PluginRegistrar()
        registrar.register(api)
        api.register_startup_hook.assert_called_once()

    def test_register_registers_prompt_section(self, ponytail):
        """register() registers a prompt section."""
        api = MagicMock()
        registrar = ponytail._PluginRegistrar()
        registrar.register(api)
        api.register_prompt_section.assert_called_once()

    def test_register_registers_skill_provider(self, ponytail):
        """register() registers skill provider if skills dir exists."""
        api = MagicMock()
        registrar = ponytail._PluginRegistrar()
        registrar.register(api)
        api.register_skill_provider.assert_called_once()

    def test_module_level_plugin_instance(self, ponytail):
        """The module exports a 'plugin' instance."""
        assert hasattr(ponytail, "plugin")
        assert isinstance(ponytail.plugin, ponytail._PluginRegistrar)


# ---------------------------------------------------------------------------
# Startup hook
# ---------------------------------------------------------------------------


class TestStartup:
    """Test _on_startup hook."""

    def test_logs_on_startup(self, ponytail):
        """Startup hook logs without crashing."""
        with patch.object(ponytail, "logger") as mock_logger:
            ponytail._on_startup()
            assert mock_logger.info.call_count >= 1
            first_call = mock_logger.info.call_args_list[0]
            assert "Ponytail" in str(first_call)

    def test_render_rules_returns_string(self, ponytail):
        """Prompt section provider returns rules text."""
        rules = ponytail._render_ponytail_rules()
        assert isinstance(rules, str)
        assert len(rules) > 100
        assert "v4.8.3" in rules
        assert "YAGNI" in rules
