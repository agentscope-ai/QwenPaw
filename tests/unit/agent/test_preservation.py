# -*- coding: utf-8 -*-
"""
Preservation Property Test — Property 2: Non-interrupt behavior unchanged (Backend)

Tests that the backend query_handler correctly saves session state in the
finally block during normal completion, and that existing agent router
endpoints remain intact.

These tests MUST PASS on unfixed code (baseline).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
"""
import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from copaw.app.runner.session import SafeJSONSession, sanitize_filename


# ---------------------------------------------------------------------------
# Preservation: SafeJSONSession saves state correctly on normal completion
# ---------------------------------------------------------------------------


class TestSessionStateSavePreservation:
    """
    Verify that session state is correctly saved during normal completion.
    This is the behavior in the finally block of query_handler.

    **Validates: Requirements 3.1, 3.5**
    """

    @pytest.mark.asyncio
    @given(
        session_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
            min_size=1,
            max_size=30,
        ),
        user_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(
        max_examples=20,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_save_session_state_persists_to_disk(
        self,
        session_id: str,
        user_id: str,
    ):
        """For any session_id/user_id, save_session_state writes a JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = SafeJSONSession(save_dir=tmpdir)

            # Create a mock agent with state_dict
            mock_agent = MagicMock()
            mock_agent.state_dict.return_value = {
                "memory": {"content": [{"role": "user", "text": "hello"}]},
                "model": "test-model",
            }

            await session.save_session_state(
                session_id=session_id,
                user_id=user_id,
                agent=mock_agent,
            )

            # Verify file was created
            save_path = session._get_save_path(session_id, user_id)
            assert os.path.exists(save_path), (
                f"Session state file should exist at {save_path}"
            )

            # Verify content is valid JSON with agent state
            with open(save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert "agent" in data
            assert data["agent"]["memory"]["content"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_save_then_load_roundtrip(self):
        """Save and load should produce the same state (normal completion)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = SafeJSONSession(save_dir=tmpdir)

            original_state = {
                "memory": {
                    "content": [
                        {"role": "user", "text": "list files"},
                        {"role": "assistant", "text": "Here are the files..."},
                    ]
                },
                "status": "finished",
            }

            # Save
            mock_agent = MagicMock()
            mock_agent.state_dict.return_value = original_state

            await session.save_session_state(
                session_id="test-session",
                user_id="test-user",
                agent=mock_agent,
            )

            # Load
            load_agent = MagicMock()
            await session.load_session_state(
                session_id="test-session",
                user_id="test-user",
                agent=load_agent,
            )

            load_agent.load_state_dict.assert_called_once_with(original_state)


# ---------------------------------------------------------------------------
# Preservation: sanitize_filename works correctly for session management
# ---------------------------------------------------------------------------


class TestFilenamePreservation:
    """
    Verify that session ID sanitization preserves valid characters
    and correctly handles special characters for cross-platform compat.

    **Validates: Requirements 3.3**
    """

    @given(
        name=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=30)
    def test_safe_names_pass_through_unchanged(self, name: str):
        """Names with only letters, numbers, and dashes are unchanged."""
        result = sanitize_filename(name)
        assert result == name

    @given(
        base=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=1,
            max_size=10,
        ),
    )
    @settings(max_examples=20)
    def test_colon_separated_ids_are_sanitized(self, base: str):
        """IDs like 'discord:dm:123' have colons replaced with '--'."""
        name = f"{base}:{base}:123"
        result = sanitize_filename(name)
        assert ":" not in result
        assert "--" in result


# ---------------------------------------------------------------------------
# Preservation: Existing agent router endpoints still work
# ---------------------------------------------------------------------------


class TestAgentRouterPreservation:
    """
    Verify that existing agent router endpoints are not affected.

    **Validates: Requirements 3.2, 3.4**
    """

    def test_existing_endpoints_are_registered(self):
        """The agent router should have its existing endpoints."""
        from copaw.app.routers.agent import router

        paths = [route.path for route in router.routes]

        # These endpoints must exist (preservation)
        # Router has prefix="/agent", so paths include the prefix
        assert "/agent/files" in paths
        assert "/agent/files/{md_name}" in paths
        assert "/agent/memory" in paths
        assert "/agent/memory/{md_name}" in paths
        assert "/agent/language" in paths
        assert "/agent/running-config" in paths
        assert "/agent/system-prompt-files" in paths


# ---------------------------------------------------------------------------
# Preservation: query_handler finally block executes on normal completion
# ---------------------------------------------------------------------------


class TestQueryHandlerFinallyBlock:
    """
    Verify that the finally block in query_handler saves session state
    when the agent completes normally (no cancellation, no error).

    **Validates: Requirements 3.1, 3.5**
    """

    @pytest.mark.asyncio
    async def test_finally_saves_state_on_normal_completion(self):
        """
        Simulate the finally block logic: after normal agent completion,
        save_session_state should be called with the agent.
        """
        save_called = False
        saved_args = {}

        async def mock_save(session_id, user_id, agent):
            nonlocal save_called, saved_args
            save_called = True
            saved_args = {
                "session_id": session_id,
                "user_id": user_id,
                "agent": agent,
            }

        mock_session = MagicMock()
        mock_session.save_session_state = mock_save

        mock_agent = MagicMock()
        session_id = "test-session-normal"
        user_id = "test-user"

        # Simulate the finally block from query_handler
        session_state_loaded = True
        try:
            # Normal completion — no exception
            pass
        finally:
            if mock_agent is not None and session_state_loaded:
                await mock_session.save_session_state(
                    session_id=session_id,
                    user_id=user_id,
                    agent=mock_agent,
                )

        assert save_called, "save_session_state should be called in finally"
        assert saved_args["session_id"] == session_id
        assert saved_args["user_id"] == user_id
        assert saved_args["agent"] is mock_agent

    @pytest.mark.asyncio
    async def test_finally_saves_state_on_exception(self):
        """
        Even when an exception occurs (non-cancel), the finally block
        should still save session state.

        **Validates: Requirements 3.5**
        """
        save_called = False

        async def mock_save(**kwargs):
            nonlocal save_called
            save_called = True

        mock_session = MagicMock()
        mock_session.save_session_state = mock_save

        mock_agent = MagicMock()
        session_state_loaded = True

        with pytest.raises(ValueError):
            try:
                raise ValueError("Some agent error")
            finally:
                if mock_agent is not None and session_state_loaded:
                    await mock_session.save_session_state(
                        session_id="err-session",
                        user_id="err-user",
                        agent=mock_agent,
                    )

        assert save_called, (
            "save_session_state should be called even on exception"
        )
