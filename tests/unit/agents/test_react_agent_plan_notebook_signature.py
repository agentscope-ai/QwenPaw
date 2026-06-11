# -*- coding: utf-8 -*-
"""Static (AST) checks for the ``plan_notebook`` wiring on QwenPawAgent.

``runner.py`` constructs ``QwenPawAgent(..., plan_notebook=plan_notebook)``
and ``react_agent.py`` later reads ``getattr(self, "plan_notebook", None)``.
Before the fix, ``__init__`` did not accept ``plan_notebook`` (TypeError at
runtime) and never set the attribute.

These tests parse the source with :mod:`ast` instead of importing the
modules, because ``react_agent`` imports ``agentscope`` at module load and
agentscope is not installed in this environment. The checks therefore pin
the exact contract the runner depends on without needing the heavy runtime
dependency.
"""

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[3] / "src" / "qwenpaw"
_REACT_AGENT = _SRC / "agents" / "react_agent.py"
_RUNNER = _SRC / "app" / "runner" / "runner.py"


def _find_class(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name!r} not found")


def _find_method(class_node, name):
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"method {name!r} not found")


def _param_names(func_node):
    args = func_node.args
    return [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]


def test_init_accepts_plan_notebook_param():
    """QwenPawAgent.__init__ declares a ``plan_notebook`` parameter."""
    tree = ast.parse(_REACT_AGENT.read_text(encoding="utf-8"))
    cls = _find_class(tree, "QwenPawAgent")
    init = _find_method(cls, "__init__")

    assert "plan_notebook" in _param_names(init)


def test_init_assigns_self_plan_notebook():
    """__init__ assigns ``self.plan_notebook`` so getattr resolves it."""
    tree = ast.parse(_REACT_AGENT.read_text(encoding="utf-8"))
    cls = _find_class(tree, "QwenPawAgent")
    init = _find_method(cls, "__init__")

    assigns_attr = False
    for node in ast.walk(init):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "plan_notebook"
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                assigns_attr = True

    assert assigns_attr, "self.plan_notebook is never assigned in __init__"


def test_runner_passes_plan_notebook_kwarg():
    """runner.py constructs QwenPawAgent with a ``plan_notebook`` kwarg."""
    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))

    passes_kwarg = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = (
            func.id
            if isinstance(func, ast.Name)
            else getattr(
                func,
                "attr",
                None,
            )
        )
        if callee != "QwenPawAgent":
            continue
        if any(kw.arg == "plan_notebook" for kw in node.keywords):
            passes_kwarg = True

    assert passes_kwarg, "runner does not pass plan_notebook= to QwenPawAgent"
