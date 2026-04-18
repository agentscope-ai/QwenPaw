# -*- coding: utf-8 -*-
"""
Channel Unit Test Fixtures

Provides common fixtures for channel unit testing.
"""

from __future__ import annotations

import asyncio
from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_process_handler() -> AsyncMock:
    """Mock process handler that yields simple events."""

    async def mock_process(*_args, **_kwargs):
        mock_event = MagicMock()
        mock_event.object = "message"
        mock_event.status = "completed"
        mock_event.type = "text"
        yield mock_event

    return AsyncMock(side_effect=mock_process)


@pytest.fixture
def mock_enqueue() -> MagicMock:
    """Mock enqueue callback."""
    return MagicMock()


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_media_dir(tmp_path) -> str:
    """Temporary directory for media files."""
    media_dir = tmp_path / ".copaw" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    return str(media_dir)
