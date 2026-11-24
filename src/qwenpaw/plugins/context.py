# -*- coding: utf-8 -*-
"""Read-only request identity, captured by the host at invocation time."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    workspace_id: str = ""
    session_id: str = ""
    channel: str = ""
    user_id: str = ""
