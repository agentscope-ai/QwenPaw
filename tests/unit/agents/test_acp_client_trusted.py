# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for ACPHostedClient trusted auto-approve logic."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.acp.client import ACPHostedClient
from qwenpaw.config.config import ACPAgentConfig


class TestACPHostedClientTrustedAutoApprove:
    """Verify trusted runner auto-approves non-hard-blocked tool calls."""

    def _make_client(self, *, trusted: bool = True) -> ACPHostedClient:
        config = ACPAgentConfig(
            enabled=True,
            command="test",
            trusted=trusted,
            tool_parse_mode="call_title",
        )
        return ACPHostedClient(
            agent_name="test-agent",
            agent_config=config,
            cwd="/tmp",
        )

    @pytest.mark.asyncio
    async def test_trusted_auto_approves_safe_command(self) -> None:
        client = self._make_client(trusted=True)
        client._on_message = AsyncMock()  # noqa: W0212

        options = [
            {"optionId": "allow_once", "label": "Allow once"},
            {"optionId": "deny", "label": "Deny"},
        ]
        tool_call = {
            "title": "Execute",
            "kind": "execute",
            "rawInput": {"command": "ls -la"},
        }

        response = await client.request_permission(
            options=options,
            session_id="sess-1",
            tool_call=tool_call,
        )

        # Should auto-approve without suspending
        assert response.outcome.outcome == "selected"
        assert response.outcome.option_id == "allow_once"
        # Should NOT have set pending permission (no suspend)
        assert client._pending_permission is None  # noqa: W0212

    @pytest.mark.asyncio
    async def test_trusted_still_blocks_destructive_command(self) -> None:
        client = self._make_client(trusted=True)
        client._on_message = AsyncMock()  # noqa: W0212

        options = [
            {"optionId": "allow_once", "label": "Allow once"},
        ]
        tool_call = {
            "title": "Execute",
            "kind": "execute",
            "rawInput": {"command": "rm -rf /"},
        }

        response = await client.request_permission(
            options=options,
            session_id="sess-1",
            tool_call=tool_call,
        )

        # Hard-block should intercept even for trusted
        assert response.outcome.outcome == "cancelled"

    @pytest.mark.asyncio
    async def test_untrusted_suspends_for_user_confirmation(self) -> None:
        client = self._make_client(trusted=False)
        client._on_message = AsyncMock()  # noqa: W0212

        options = [
            {"optionId": "allow_once", "label": "Allow once"},
        ]
        tool_call = {
            "title": "Execute",
            "kind": "execute",
            "rawInput": {"command": "ls -la"},
        }

        # Start request_permission in a task since it will suspend
        task = asyncio.create_task(
            client.request_permission(
                options=options,
                session_id="sess-1",
                tool_call=tool_call,
            ),
        )

        # Wait for the permission request to be emitted
        await asyncio.sleep(0.05)

        # Should have suspended (pending permission set)
        assert client._pending_permission is not None  # noqa: W0212

        # Resolve the permission to complete the task
        client.resolve_permission("allow_once")
        response = await task

        assert response.outcome.outcome == "selected"

    def test_pick_allow_option_prefers_allow_once(self) -> None:
        client = self._make_client(trusted=True)
        options = [
            {"optionId": "deny", "label": "Deny"},
            {"optionId": "allow_always", "label": "Always"},
            {"optionId": "allow_once", "label": "Once"},
        ]
        selected = client._pick_allow_option(options)  # noqa: W0212
        assert selected is not None
        assert selected["optionId"] == "allow_once"

    def test_pick_allow_option_fallback_to_allow_in_id(self) -> None:
        client = self._make_client(trusted=True)
        options = [
            {"optionId": "deny", "label": "Deny"},
            {"optionId": "custom_allow_action", "label": "Custom"},
        ]
        selected = client._pick_allow_option(options)  # noqa: W0212
        assert selected is not None
        assert selected["optionId"] == "custom_allow_action"

    def test_pick_allow_option_returns_none_when_no_allow(self) -> None:
        client = self._make_client(trusted=True)
        options = [
            {"optionId": "deny", "label": "Deny"},
            {"optionId": "cancel", "label": "Cancel"},
        ]
        selected = client._pick_allow_option(options)  # noqa: W0212
        assert selected is None
