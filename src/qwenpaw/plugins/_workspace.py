# -*- coding: utf-8 -*-
"""
Resolve SDK workspace identity from host ownership, never directory names.
"""

from contextvars import ContextVar
from pathlib import Path

from .errors import SDKError

workspace_id = ContextVar("sdk_workspace_id", default=None)


def current_workspace_id():
    from ..app.agent_context import peek_current_agent_id
    from ..config.context import get_current_workspace_dir

    explicit = workspace_id.get() or peek_current_agent_id()
    if explicit:
        return explicit
    directory = get_current_workspace_dir()
    if directory is None:
        # Registration/discovery without a request has plugin scope only.
        return ""
    return configured_workspace_id(directory)


def configured_workspace_id(directory):
    from ..config.utils import load_config

    directory = Path(directory).expanduser().resolve()
    matches = [
        name
        for name, profile in load_config().agents.profiles.items()
        if Path(profile.workspace_dir).expanduser().resolve() == directory
    ]
    if len(matches) != 1:
        raise SDKError("Workspace directory has no unique configured identity")
    return matches[0]
