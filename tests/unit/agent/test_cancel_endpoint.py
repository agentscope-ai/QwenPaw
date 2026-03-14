# -*- coding: utf-8 -*-
"""
Bug Condition Exploration Test — Property 1: Bug Condition (Backend)

Tests that the backend has a /api/agent/cancel endpoint and that it
correctly cancels running asyncio tasks.

These tests are written BEFORE the fix and are EXPECTED TO FAIL
on unfixed code, confirming the bug exists.

Validates: Requirements 1.1, 1.3, 2.3
"""
import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copaw.app.routers.agent import router as agent_router


def _make_app() -> FastAPI:
    """Create a minimal FastAPI app with the agent router."""
    app = FastAPI()
    # The router already has prefix="/agent", so we only add "/api"
    app.include_router(agent_router, prefix="/api")
    return app


class TestCancelEndpointExists:
    """
    Test 2 (Backend): POST /api/agent/cancel should exist and return
    a proper response.

    On unfixed code this WILL FAIL — the endpoint does not exist (404).

    **Validates: Requirements 1.3, 2.3**
    """

    def test_cancel_endpoint_returns_non_404(self):
        """The /api/agent/cancel endpoint should exist (not return 404)."""
        app = _make_app()
        client = TestClient(app)

        response = client.post(
            "/api/agent/cancel",
            json={"session_id": "test-session-123"},
        )

        # On unfixed code, this will be 404 (endpoint doesn't exist)
        # On fixed code, this should be 200
        assert response.status_code != 404, (
            f"Expected /api/agent/cancel to exist, but got 404. "
            f"The cancel endpoint has not been implemented yet."
        )
        assert response.status_code == 200
