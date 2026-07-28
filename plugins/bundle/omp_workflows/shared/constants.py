# -*- coding: utf-8 -*-
"""Shared constants for OMP workflow modes."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Registered tool names used in OMP role configs / controller prompts.
# Keep in sync with QwenPaw ToolRegistry names (not display labels).
# ---------------------------------------------------------------------------
TOOL_READ_FILE = "read_file"
TOOL_GREP_SEARCH = "grep_search"
TOOL_GLOB_SEARCH = "glob_search"
TOOL_WRITE_FILE = "write_file"
TOOL_AST_SEARCH = "ast_search"
TOOL_EXECUTE_SHELL = "execute_shell_command"

# Read-oriented defaults used by multiple reviewer roles.
_TOOLS_READ = (
    TOOL_READ_FILE,
    TOOL_GREP_SEARCH,
    TOOL_GLOB_SEARCH,
)
_TOOLS_READ_AST = _TOOLS_READ + (TOOL_AST_SEARCH,)
_TOOLS_READ_SHELL = _TOOLS_READ + (TOOL_EXECUTE_SHELL,)
_TOOLS_READ_AST_SHELL = _TOOLS_READ_AST + (TOOL_EXECUTE_SHELL,)
_TOOLS_READ_WRITE_SHELL = _TOOLS_READ + (
    TOOL_WRITE_FILE,
    TOOL_EXECUTE_SHELL,
)
_TOOLS_ARCHITECT = _TOOLS_READ + (
    TOOL_WRITE_FILE,
    TOOL_AST_SEARCH,
    TOOL_EXECUTE_SHELL,
)
_TOOLS_PLANNER = _TOOLS_READ + (TOOL_WRITE_FILE, TOOL_AST_SEARCH)

# Role -> allowed_tools.  ``None`` means inherit the parent's full set.
ROLE_ALLOWED_TOOLS: dict[str, list[str] | None] = {
    "executor": None,
    "debugger": None,
    "architect": list(_TOOLS_ARCHITECT),
    "analyst": list(_TOOLS_READ_WRITE_SHELL),
    "critic": list(_TOOLS_READ_AST),
    "security-reviewer": list(_TOOLS_READ_AST_SHELL),
    "code-reviewer": list(_TOOLS_READ_AST_SHELL),
    "qa-tester": list(_TOOLS_READ_SHELL),
    "planner": list(_TOOLS_PLANNER),
    "explore": list(_TOOLS_READ_AST),
    "verifier": list(_TOOLS_READ_AST_SHELL),
}

# Role -> skills whitelist.  Empty list clears inherited skills.
ROLE_SKILLS: dict[str, list[str] | None] = {
    "executor": None,
    "debugger": [],
    "architect": [],
    "analyst": [],
    "critic": [],
    "security-reviewer": [],
    "code-reviewer": [],
    "qa-tester": [],
    "planner": [],
    "explore": [],
    "verifier": [],
}

ULTRAQA_MAX_CYCLES = 5
ULTRAQA_MAX_SAME_FAILURE = 3

AUTOPILOT_MAX_ITERATIONS = 60
AUTOPILOT_MAX_PHASE_ITERATIONS = 10
AUTOPILOT_MAX_VALIDATION_ROUNDS = 3

RALPH_MAX_ITERATIONS = 20
RALPH_MAX_SAME_ISSUE = 3

TEAM_MAX_FIX_ATTEMPTS = 3
TEAM_MAX_ITERATIONS = 30

ULTRAWORK_MAX_ITERATIONS = 30
