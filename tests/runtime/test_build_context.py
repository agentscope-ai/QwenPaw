# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for Runtime._build_context agent_id resolution."""

from types import SimpleNamespace

import pytest

from qwenpaw.runtime.runtime import Runtime
from qwenpaw.schemas import AgentRequest


@pytest.fixture
def runtime_factory():
    """Return a Runtime factory for the given workspace agent_id."""

    def _make(agent_id: str | None = None):
        workspace = SimpleNamespace(
            agent_id=agent_id,
            workspace_dir="/tmp/test_workspace",
        )
        return Runtime(workspace=workspace, app_services=None)

    return _make


def test_build_context_uses_workspace_agent_id(runtime_factory):
    """Channel-built requests without agent_id should use the workspace id."""
    runtime = runtime_factory("my_agent")
    request = AgentRequest()

    ctx = runtime._build_context(request)

    assert ctx.agent_id == "my_agent"
    assert ctx.root_agent_id == "my_agent"


def test_build_context_request_agent_id_takes_precedence(runtime_factory):
    """An explicit request.agent_id must override the workspace fallback."""
    runtime = runtime_factory("workspace_agent")
    request = AgentRequest()
    request.agent_id = "request_agent"

    ctx = runtime._build_context(request)

    assert ctx.agent_id == "request_agent"
    assert ctx.root_agent_id == "request_agent"


def test_build_context_falls_back_to_default(runtime_factory):
    """If neither request nor workspace provide an id, fall back to default."""
    runtime = runtime_factory(None)
    request = AgentRequest()

    ctx = runtime._build_context(request)

    assert ctx.agent_id == "default"
    assert ctx.root_agent_id == "default"


def test_build_context_root_agent_id_from_request(runtime_factory):
    """An explicit request.root_agent_id is preserved."""
    runtime = runtime_factory("workspace_agent")
    request = AgentRequest()
    request.root_agent_id = "root_agent"

    ctx = runtime._build_context(request)

    assert ctx.agent_id == "workspace_agent"
    assert ctx.root_agent_id == "root_agent"
