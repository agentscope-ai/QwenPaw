# -*- coding: utf-8 -*-
"""Built-in tool functions for QwenPaw agents.

Every tool function decorated with ``@tool_descriptor`` is automatically
collected into a global registry at import time.  Adding a new built-in
tool requires only two things:

1. Decorate the function with ``@tool_descriptor(...)`` (include
   governance / UI / default_policy metadata as needed).
2. Import the module here so that the decorator executes.
   ``__all__`` is generated automatically from collected descriptors.

:func:`discover_builtin_tool_funcs` returns all auto-collected built-in
tools — no manual list maintenance or filesystem scanning required.

Note: ``execute_python_code`` / ``view_text_file`` / ``write_text_file``
are intentionally not re-exported — qwenpaw's react_agent does not
register them. The literal names still appear in
``security/tool_guard`` guardians for backward compatibility with
pre-existing allowlists.
"""

# pylint: disable=wrong-import-position

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

from ...config import load_config
from ...config.config import _invalidate_builtin_tools_cache

logger = logging.getLogger(__name__)

# Each import triggers the @tool_descriptor decorator, which auto-
# collects the function into the global registry.
from .file_io import (  # noqa: E402
    read_file,
    write_file,
    edit_file,
    append_file,
)
from .file_search import grep_search, glob_search  # noqa: E402
from .shell import execute_shell_command  # noqa: E402
from .send_file import send_file_to_user  # noqa: E402
from .web_search import web_search, web_fetch  # noqa: E402
from .desktop_screenshot import desktop_screenshot  # noqa: E402
from .view_media import view_image, view_video  # noqa: E402
from .get_current_time import get_current_time, set_user_timezone  # noqa: E402
from .get_token_usage import get_token_usage  # noqa: E402
from .agent_management import (  # noqa: E402
    list_agents,
    chat_with_agent,
    submit_to_agent,
    check_agent_task,
    spawn_subagent,
)  # noqa: E402
from .delegate_external_agent import delegate_external_agent  # noqa: E402
from .make_skill_tools import materialize_skill  # noqa: E402
from .ast_tool import ast_search  # noqa: E402
from .run_tool_batch import run_tool_batch  # noqa: E402

_BETA_NOTICE_LOGGED = False


def _announce_experimental_browser() -> None:
    """Make the unified-browser beta and its rollback path discoverable."""
    global _BETA_NOTICE_LOGGED
    if _BETA_NOTICE_LOGGED:
        return
    logger.info(
        "Unified browser experimental beta is enabled (subprocess isolation; "
        "OS sandboxing is planned). Set browser.experimental=false to use "
        "the deprecated stable browser implementation.",
    )
    _BETA_NOTICE_LOGGED = True


_BROWSER_EXPERIMENTAL = load_config().browser.experimental


def browser_track_effective() -> bool:
    """Return the browser track actually imported into this process."""
    return _BROWSER_EXPERIMENTAL


if _BROWSER_EXPERIMENTAL:
    from .browser import browser

    _announce_experimental_browser()
else:
    from .deprecated_browser.browser_control import browser


_STABLE_BROWSER_MODULE = (
    "qwenpaw.agents.tools.deprecated_browser.browser_control"
)


def _loaded_stable_browser():
    """Return the stable browser module only when its track was imported."""
    return sys.modules.get(_STABLE_BROWSER_MODULE)


async def shutdown_browser_runtime() -> None:
    """Stop the selected browser track without importing its alternative."""
    stable = _loaded_stable_browser()
    if stable is not None:
        await stable.stop_all_browsers()
    unified_links = sys.modules.get("qwenpaw.browser.runtime.links")
    if unified_links is not None:
        for link in unified_links.registered_links():
            close_all = getattr(link, "close_all_sessions", None)
            if close_all is not None:
                await close_all()


async def shutdown_browsers_for_workspace_dirs(dirs: list[str]) -> None:
    """Stop selected-track browsers scoped to backup workspace directories."""
    stable = _loaded_stable_browser()
    if stable is not None:
        await stable.stop_browsers_for_workspace_dirs(list(dirs))
        return
    from ...browser.execution.kernel import get_default_kernel_manager
    from ...browser.tool_entrypoint import derive_workspace_id

    manager = get_default_kernel_manager()
    for workspace_dir in dirs:
        await manager.close_workspace(derive_workspace_id(Path(workspace_dir)))


# ``load_config()`` above may build ``ToolsConfig`` while this package is
# still importing. Refresh the descriptor-derived cache after the selected
# browser implementation has registered itself.
_invalidate_builtin_tools_cache()


def discover_builtin_tool_funcs() -> list[Callable]:
    """Return all built-in tool functions auto-collected by
    ``@tool_descriptor``.

    The decorator registers each function at import time.  This function
    simply returns the collected built-in tools — no ``pkgutil`` /
    ``importlib`` scanning, no manual list.
    """
    from ...runtime.tool_registry import get_builtin_tool_funcs

    return get_builtin_tool_funcs()


def _build_all() -> list[str]:
    """Build ``__all__`` from auto-collected ``@tool_descriptor`` tools."""
    from ...runtime.tool_registry import get_builtin_tool_funcs

    return ["discover_builtin_tool_funcs"] + [
        fn.__name__ for fn in get_builtin_tool_funcs()
    ]


# Must stay below all side-effect imports above so every @tool_descriptor
# has already appended to the global registry before __all__ is built.
__all__ = _build_all()
