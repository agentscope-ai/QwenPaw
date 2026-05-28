# -*- coding: utf-8 -*-
"""Shim for ``agentscope_runtime.engine.app.AgentApp``.

In agentscope 1.x ``AgentApp`` was a thin builder that exposed a
FastAPI :class:`~fastapi.APIRouter` driving a user-supplied ``runner``
(``stream_query`` / ``query_handler`` etc.).  qwenpaw mounted that router
under ``/api/agent`` for external clients that speak the runner protocol.

In 2.0 the equivalent is :func:`agentscope.app.create_app` which returns
a fully configured ``FastAPI`` app (built-in routers, storage, workspace
manager, middlewares).  Porting qwenpaw's :class:`DynamicMultiAgentRunner`
to drive it is non-trivial and orthogonal to getting the console UI
working, so we expose a minimal stand-in: ``AgentApp(...).router`` is an
empty :class:`~fastapi.APIRouter` and the constructor accepts (and
ignores) the old kwargs.

TODO(as2-migration): replace with a real ``create_app`` integration
once the multi-agent runner is rewritten against the 2.0 storage /
workspace abstractions, then delete this file.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter


class AgentApp:  # pragma: no cover - migration shim
    """Stand-in for the deleted ``agentscope_runtime`` ``AgentApp`` builder."""

    def __init__(
        self,
        app_name: str | None = None,
        app_description: str | None = None,
        runner: Any = None,
        **_ignored: Any,
    ) -> None:
        self.app_name = app_name
        self.app_description = app_description
        self.runner = runner
        # Empty router — the /api/agent surface is dark until we port to
        # ``agentscope.app.create_app``.
        self.router = APIRouter()
