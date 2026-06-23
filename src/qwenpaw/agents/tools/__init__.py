# -*- coding: utf-8 -*-
"""Built-in tool functions for QwenPaw agents.

Every tool function decorated with ``@tool_descriptor`` is automatically
collected into a global registry at import time.  Adding a new built-in
tool requires only two things:

1. Decorate the function with ``@tool_descriptor(...)`` in its module.
2. Import the module here so that the decorator executes.

:func:`discover_builtin_tool_funcs` returns all auto-collected built-in
tools — no manual list maintenance or filesystem scanning required.

Note: ``execute_python_code`` / ``view_text_file`` / ``write_text_file``
are intentionally not re-exported — qwenpaw's react_agent does not
register them. The literal names still appear in
``security/tool_guard`` guardians for backward compatibility with
pre-existing allowlists.
"""
from __future__ import annotations

from typing import Callable

# Each import triggers the @tool_descriptor decorator, which auto-
# collects the function into the global registry.
from .file_io import read_file, write_file, edit_file, append_file
from .file_search import grep_search, glob_search
from .shell import execute_shell_command
from .send_file import send_file_to_user
from .browser_control import browser_use
from .desktop_screenshot import desktop_screenshot
from .view_media import view_image, view_video
from .get_current_time import get_current_time, set_user_timezone
from .get_token_usage import get_token_usage
from .agent_management import (
    list_agents,
    chat_with_agent,
    submit_to_agent,
    check_agent_task,
    spawn_subagent,
)
from .delegate_external_agent import delegate_external_agent
from .make_skill_tools import materialize_skill
from .ast_tool import ast_search


def discover_builtin_tool_funcs() -> list[Callable]:
    """Return all built-in tool functions auto-collected by
    ``@tool_descriptor``.

    The decorator registers each function at import time.  This function
    simply returns the collected built-in tools — no ``pkgutil`` /
    ``importlib`` scanning, no manual list.
    """
    from ...runtime.tool_registry import get_builtin_tool_funcs

    return get_builtin_tool_funcs()


__all__ = [
    "discover_builtin_tool_funcs",
    "execute_shell_command",
    "read_file",
    "write_file",
    "edit_file",
    "append_file",
    "grep_search",
    "glob_search",
    "send_file_to_user",
    "desktop_screenshot",
    "view_image",
    "view_video",
    "browser_use",
    "get_current_time",
    "set_user_timezone",
    "get_token_usage",
    "delegate_external_agent",
    "list_agents",
    "chat_with_agent",
    "submit_to_agent",
    "check_agent_task",
    "spawn_subagent",
    "materialize_skill",
    "ast_search",
]
