# -*- coding: utf-8 -*-
"""Ponytail Quality Plugin v4.8.3 (official) — lazy senior dev mode (ultra).

Sources from github.com/DietrichGebert/ponytail (MIT).

Tools
-----
ponytail_review
    Review existing source code for Ponytail violations.
ponytail_lint_prompt
    Analyze a proposed code change *before* writing code.

Hooks
-----
startup
    Log Ponytail mode and version on daemon start.

Prompt sections
---------------
ponytail_rules — injected after "workspace" anchor.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

from agentscope.tool import ToolResponse

logger = logging.getLogger(__name__)

# ── Ponytail rules (single source of truth) ──────────────────────────

PONYTAIL_RULES = """
## Ponytail v4.8.3 (Official) — Lazy Senior Dev Mode (ultra)

Active globally on all coding projects. Off only: "stop ponytail" / "normal
mode".

### The ladder

Stop at the first rung that holds:

1. **Does this need to exist at all?** (YAGNI)
2. **Already in this codebase?** A helper, util, type, or pattern already
   here → reuse it. Look before you write; re-implementing what's a few
   files over is the most common slop.
3. **Stdlib does it?** Use it.
4. **Native platform feature covers it?** Use it.
5. **Already-installed dependency solves it?** Use it. Never add a new one
   for what a few lines can do.
6. **Can it be one line?** One line.
7. **Only then:** write the minimum code that works.

The ladder runs *after* you understand the problem, not instead of it: read
the task and the code it touches, trace the real flow end to end, then climb.
Two rungs work? Take the higher one and move on.

**Bug fix = root cause, not symptom.** Before you edit, grep every caller of
the function you're about to touch. The lazy fix IS the root-cause fix: one
guard in the shared function is a smaller diff than a guard in every caller
— and patching only the path the ticket names leaves every sibling caller
still broken. Fix it once, where all callers route through.

### Rules

- No unrequested abstractions: no interface with one implementation, no
  factory with one product, no config for a value that never changes.
- No boilerplate, no scaffolding "for later". Later can scaffold for itself.
- Deletion over addition. Boring over clever. Clever is what someone decodes
  at 3am.
- Fewest files possible. Shortest working diff wins — but only once you
  understand the problem. The smallest change in the wrong place isn't lazy,
  it's a second bug.
- Complex request? Ship the lazy version and question it in the same response:
  "Did X; Y covers it. Need full X? Say so." Never stall on an answer you can
  default.
- Two stdlib options, same size? Take the one that's correct on edge cases.
  Lazy means writing less code, not picking the flimsier algorithm.
- Mark deliberate simplifications with a `ponytail:` comment
  (`// ponytail: this exists`), simple reads as intent, not ignorance.
  Shortcut with a known ceiling (global lock, O(n²) scan, naive heuristic)?
  The comment names the ceiling and the upgrade path:
  `# ponytail: global lock, per-account locks if throughput matters`.
- Non-trivial logic leaves ONE runnable assert-based check behind (no
  frameworks, no fixtures). Trivial one-liners need no test.

### Not lazy about

Understanding the problem (read fully, trace flow, then climb — a small diff
you don't understand is just laziness dressed up as efficiency), input
validation at trust boundaries, error handling that prevents data loss,
security, accessibility, hardware calibration (the platform is never the spec
ideal, a real clock drifts, a real sensor reads off), anything explicitly
requested.

### Output format

Code first. Then at most three short lines: what was skipped, when to add it.
No essays, no design notes. If the explanation is longer than the code, delete
the explanation.

Pattern: `[code] → skipped: [X], add when [Y].`

### Level persistence

Default: ultra. Switch: `/ponytail lite|full|ultra`. Sticks until changed or
session end.
"""


# ── Tool functions ───────────────────────────────────────────────────


def ponytail_review(
    file_path: str = "",
    code: str = "",
) -> ToolResponse:
    """Review source code for Ponytail rule violations.

    Call this when the agent produces or modifies code to check
    compliance with Ponytail Ultra rules.

    Args:
        file_path: Path to the file to review.
        code: Source code as a string (alternative to file_path).

    Returns:
        ToolResponse with violations and suggestions.
    """
    source = _read_source(file_path, code)
    if isinstance(source, ToolResponse):
        return source

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return ToolResponse(f"⚠️  Syntax error: {e}")

    lines = source.splitlines()
    report = _ViolationReport()

    _check_line_count(report, lines)
    _check_imports(report, tree, lines)
    _check_abstractions(report, tree, lines)
    _check_dead_code(report, tree)
    _check_nesting(report, tree, lines)
    _check_comments(report, lines)
    _check_ponytail_comments(report, lines)

    return ToolResponse(report.render())


def ponytail_lint_prompt(
    plan: str = "",
    code_snippet: str = "",
) -> ToolResponse:
    """Analyze a code change plan for Ponytail violations *before* coding.

    Call this BEFORE writing code to avoid Ponytail violations.
    Feed it your planned approach or a pseudo-code sketch.

    Args:
        plan: Description of the proposed code change.
        code_snippet: Pseudo-code or actual code sketch.

    Returns:
        ToolResponse with advisories.
    """
    advisories = []

    # Heuristics on plan text
    if plan:
        plan_lower = plan.lower()
        checks = [
            (
                "new class", r"\bclass\b", "Are you sure you need a new class? "
                "Could a plain function do the job? (YAGNI → no abstraction)",
            ),
            (
                "new dependency", r"(pip install|npm install|new dep|add library)",
                "New dependency detected! Can stdlib do this? (stdlib first)",
            ),
            (
                "interface/abstract", r"(interface|abstract|protocol|ABC)",
                "Abstract layer detected. Is there a 3rd use case yet? "
                "(no abstraction unless forced)",
            ),
            (
                "new file", r"(new file|create file|add file)",
                "New file? Could this go in an existing file? "
                "(deletion over addition)",
            ),
        ]
        for rule_name, pattern, msg in checks:
            if re.search(pattern, plan_lower):
                advisories.append(f"  ⚠️  [{rule_name}] {msg}")

    if code_snippet:
        lines = code_snippet.splitlines()
        if len(lines) > 30:
            advisories.append(
                f"  ⚠️  [length] Code is {len(lines)} lines. "
                "Can you cut it down? (1 line > 50 lines)",
            )
        if re.search(r"class\s+\w+.*:", code_snippet) and \
           len([l for l in lines if l.strip().startswith("def ")]) <= 1:
            advisories.append(
                "  ⚠️  [single-method class] Class with only "
                "1 method. Make it a function. (no abstraction)",
            )

    if not advisories:
        return ToolResponse(
            "✅ **Ponytail lint**: No violations detected in proposed plan.",
        )

    header = "🔍 **Ponytail Lint Report — Pre-Code Check**\n\n"
    header += f"{len(advisories)} potential issue(s):\n"
    header += "\n".join(advisories)
    header += "\n\nConsider revising your approach before writing code."
    return ToolResponse(header)


# ── Plugin class ─────────────────────────────────────────────────────


class _PluginRegistrar:
    """Ponytail Quality Plugin — registers tools, hooks, prompt."""

    def register(self, api: Any) -> None:
        """Register all plugin capabilities."""
        plugin_dir = Path(__file__).parent

        # ── Tools ──
        api.register_tool(
            tool_name="ponytail_review",
            tool_func=ponytail_review,
            description="Review source code for Ponytail rule violations: "
                        "YAGNI, unnecessary abstractions, stdlib alternatives, "
                        "dead code, premature complexity.",
            icon="🐴",
        )
        api.register_tool(
            tool_name="ponytail_lint_prompt",
            tool_func=ponytail_lint_prompt,
            description="Analyze a proposed code change for Ponytail "
                        "violations BEFORE writing code. Call proactively "
                        "to avoid violations.",
            icon="🔍",
        )

        # ── Startup hook ──
        api.register_startup_hook(
            hook_name="ponytail_startup",
            callback=_on_startup,
            priority=100,
        )

        # ── Prompt section (inject rules into system prompt) ──
        api.register_prompt_section(
            name="ponytail_rules",
            after="workspace",
            provider=_render_ponytail_rules,
        )

        # ── Skills ──
        skills_dir = plugin_dir / "skills"
        if skills_dir.exists() and any(skills_dir.iterdir()):
            api.register_skill_provider(
                skills_dir=skills_dir,
                enabled_by_default=True,
                channels=["all"],
            )

        logger.info(
            "Ponytail plugin registered: tools=2, hooks=1, "
            "prompt_section=1, skills_provider=1",
        )


# Module-level instance — QwenPaw loader looks for 'plugin' (not 'Plugin')
plugin = _PluginRegistrar()


# ── Startup hook ─────────────────────────────────────────────────────


def _on_startup() -> None:
    """Log Ponytail configuration on daemon start."""
    mode = os.environ.get("PONYTAIL_DEFAULT_MODE", "ultra")
    logger.info(
        "🐴 Ponytail plugin loaded | mode=%s | rules=%d",
        mode, len(PONYTAIL_RULES.strip().splitlines()),
    )
    logger.info("Ponytail rules:\n%s", PONYTAIL_RULES.strip())


def _render_ponytail_rules(agent: Any = None) -> str:
    """Return Ponytail rules text for system prompt injection."""
    _ = agent  # unused — rules are static
    return PONYTAIL_RULES.strip()


# ── Internal helpers ─────────────────────────────────────────────────


def _read_source(file_path: str, code: str) -> str | ToolResponse:
    """Read source code from file_path or code argument."""
    if file_path and not code:
        p = Path(file_path)
        if not p.exists():
            return ToolResponse(f"❌ File not found: {file_path}")
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResponse(f"❌ Cannot read {file_path}: {e}")
    if code:
        return code
    return ToolResponse("❌ Provide either file_path or code.")


class _ViolationReport:
    """Accumulate violations and render a structured report."""

    def __init__(self) -> None:
        self._violations: list[dict] = []

    def add(self, rule: str, severity: str, line: int, msg: str) -> None:
        self._violations.append({
            "rule": rule, "severity": severity,
            "line": line, "message": msg,
        })

    def render(self) -> str:
        if not self._violations:
            return (
                "✅ **Ponytail Review**\n\n"
                "No violations found. Code is Ponytail-compliant! 🐴"
            )

        sev_icons = {"error": "🔴", "warning": "🟡", "info": "🔵"}
        lines = [
            "🔍 **Ponytail Review Report**\n",
            f"Found {len(self._violations)} issue(s):\n",
        ]
        for v in self._violations:
            icon = sev_icons.get(v["severity"], "⚪")
            lines.append(
                f"{icon}  **L{v['line']}** | {v['rule']} | "
                f"{v['severity'].upper()}\n"
                f"    {v['message']}\n",
            )
        lines.append(
            "\n💡 *Remember: Code not written = 0 bugs. "
            "When in doubt, don't add. Delete instead.*",
        )
        return "\n".join(lines)


# ── Check implementations ────────────────────────────────────────────


def _check_line_count(report: _ViolationReport, lines: list[str]) -> None:
    """Flag files over 200 lines (possible YAGNI / complexity risk)."""
    if len(lines) > 500:
        report.add(
            "YAGNI", "warning", 1,
            f"File is {len(lines)} lines. Consider splitting "
            f"or deleting unused code.",
        )
    elif len(lines) > 200:
        report.add(
            "YAGNI", "info", 1,
            f"File is {len(lines)} lines. Could any code be "
            f"removed?",
        )


def _check_imports(
    report: _ViolationReport,
    tree: ast.AST,
    lines: list[str],
) -> None:
    """Flag heavy external imports where stdlib alternatives exist."""
    stdlib_modules = {
        "json", "csv", "sqlite3", "xml", "re", "datetime", "os", "sys",
        "pathlib", "collections", "itertools", "functools", "math",
        "statistics", "hashlib", "uuid", "tempfile", "shutil", "glob",
        "fnmatch", "io", "base64", "textwrap", "pprint", "copy",
        "enum", "typing", "dataclasses", "contextlib", "abc",
    }
    # Known heavy deps and their stdlib alternatives
    heavy_imports = {
        "numpy": (
            "stdlib alternative: statistics, math, or list "
            "comprehensions for small operations"
        ),
        "pandas": (
            "stdlib alternative: csv, sqlite3, json for "
            "tabular data under 100k rows"
        ),
        "requests": ("stdlib alternative: urllib.request"),
        "six": ("stdlib alternative: not needed — Python 3 only"),
        "pytz": ("stdlib alternative: zoneinfo (Python 3.9+)"),
        "dataclasses_json": (
            "stdlib alternative: dataclasses + "
            "simple serialization"
        ),
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.split(".")[0]
                if name in stdlib_modules:
                    continue  # stdlib is fine
                if name in heavy_imports:
                    lineno = getattr(node, "lineno", 0)
                    report.add(
                        "Stdlib First", "warning", lineno,
                        f"Import '{name}' — {heavy_imports[name]}",
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            parent = module.split(".")[0] if module else ""
            if parent in heavy_imports:
                lineno = getattr(node, "lineno", 0)
                report.add(
                    "Stdlib First", "warning", lineno,
                    f"Import from '{module}' — "
                    f"{heavy_imports[parent]}",
                )


def _check_abstractions(
    report: _ViolationReport,
    tree: ast.AST,
    lines: list[str],
) -> None:
    """Flag unnecessary abstractions."""
    for node in ast.walk(tree):
        # Single-method class that could be a function
        if isinstance(node, ast.ClassDef):
            methods = [
                n for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not n.name.startswith("_")
            ]
            if len(methods) == 1:
                # Check if class just wraps one function
                report.add(
                    "No Abstraction", "warning",
                    node.lineno,
                    f"Class '{node.name}' has only 1 public method "
                    f"'{methods[0].name}'. Could be a function.",
                )
            decorators_named = {
                getattr(d, "id", "") or
                getattr(getattr(d, "func", None), "attr", "")
                for d in node.decorator_list
            }
            if "dataclass" in decorators_named and len(node.bases) == 0 \
                    and len(methods) == 0:
                report.add(
                    "YAGNI", "info", node.lineno,
                    f"Dataclass '{node.name}' has no methods. "
                    f"Is a plain dict or tuple sufficient?",
                )

        # Wrapper functions that just call another function
        if isinstance(node, ast.FunctionDef):
            body = node.body
            if len(body) == 1 and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Call):
                report.add(
                    "YAGNI", "info", node.lineno,
                    f"Function '{node.name}' is a one-line wrapper "
                    f"around another call. Inline if possible.",
                )


def _check_dead_code(
    report: _ViolationReport,
    tree: ast.AST,
) -> None:
    """Flag obvious dead or unreachable code."""
    for node in ast.walk(tree):
        # Function/method with just pass or ...
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if len(body) == 1:
                if isinstance(body[0], ast.Pass):
                    report.add(
                        "Dead Code", "info", node.lineno,
                        f"Function '{node.name}' is empty (pass). "
                        f"Remove if unused.",
                    )
                elif isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Constant) and \
                        body[0].value.value is ...:
                    report.add(
                        "Dead Code", "info", node.lineno,
                        f"Function '{node.name}' is empty (...). "
                        f"Remove if unused.",
                    )

        # Class with just pass or ...
        if isinstance(node, ast.ClassDef):
            body = node.body
            if len(body) == 1:
                if isinstance(body[0], ast.Pass):
                    report.add(
                        "Dead Code", "warning", node.lineno,
                        f"Class '{node.name}' is empty. Remove if unused.",
                    )


def _check_nesting(
    report: _ViolationReport,
    tree: ast.AST,
    lines: list[str],
) -> None:
    """Flag deep nesting that increases complexity."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            depth = _max_nesting_depth(node)
            if depth > 5:
                report.add(
                    "Complexity", "warning", node.lineno,
                    f"Function '{node.name}' has nesting depth of "
                    f"{depth}. Consider early returns or flattening.",
                )
            elif depth > 8:
                report.add(
                    "Complexity", "error", node.lineno,
                    f"Function '{node.name}' has nesting depth of "
                    f"{depth}. Refactor required.",
                )


def _check_comments(report: _ViolationReport, lines: list[str]) -> None:
    """Flag unnecessary or excessive comments."""
    comment_lines = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            comment_lines += 1
            # Flag obvious comments
            if re.match(
                r"#+\s*(get|set|init|main|loop|done|TODO|FIXME|XXX)",
                stripped,
                re.IGNORECASE,
            ):
                report.add(
                    "Comments", "info", i,
                    f"Stale tag comment: '{stripped.strip()[:50]}'",
                )
    total = len(lines)
    if total > 0 and comment_lines / total > 0.4:
        report.add(
            "Comments", "info", 1,
            f"Comment-to-code ratio is {comment_lines}/{total} "
            f"({comment_lines*100//total}%). Remove unnecessary comments.",
        )


def _check_ponytail_comments(
    report: _ViolationReport,
    lines: list[str],
) -> None:
    """Check that intentional shortcuts have ponytail: comments."""
    # Find patterns that look like shortcuts but lack ponytail: comment
    shortcut_patterns = [
        (
            r"#\s*(hack|fixme|workaround|temp|temporary|kludge)",
            "Hack without ponytail: ceiling annotation",
        ),
        (
            r"(except\s*:\s*pass|except\s+Exception\s*:\s*pass)",
            "Bare except:pass without ponytail: justification",
        ),
    ]
    for i, line in enumerate(lines, 1):
        for pattern, desc in shortcut_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                # Check previous line for ponytail comment
                prev = lines[i - 2] if i >= 2 else ""
                if "ponytail:" not in prev and "ponytail:" not in line:
                    report.add(
                        "Ponytail Comment", "warning", i,
                        f"{desc}. Add '// ponytail: <ceiling> — <upgrade "
                        f"path>' comment.",
                    )


def _max_nesting_depth(node: ast.AST) -> int:
    """Compute maximum nesting depth inside a function."""
    max_depth = 0
    _depth = 0

    def walk(n: ast.AST) -> None:
        nonlocal _depth, max_depth
        if isinstance(
            n, (
                ast.If, ast.For, ast.While, ast.Try, ast.With,
                ast.AsyncFor, ast.AsyncWith,
            ),
        ):
            _depth += 1
            max_depth = max(max_depth, _depth)
        for child in ast.iter_child_nodes(n):
            walk(child)
        if isinstance(
            n, (
                ast.If, ast.For, ast.While, ast.Try, ast.With,
                ast.AsyncFor, ast.AsyncWith,
            ),
        ):
            _depth -= 1

    walk(node)
    return max_depth
