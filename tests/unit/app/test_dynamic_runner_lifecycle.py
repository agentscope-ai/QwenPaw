# -*- coding: utf-8 -*-
"""Unit tests for DynamicMultiAgentRunner lifecycle compatibility."""

import asyncio

from copaw.app._app import DynamicMultiAgentRunner


def test_dynamic_runner_exposes_start_stop() -> None:
    """Dynamic runner should provide lifecycle hooks used by app startup."""
    runner = DynamicMultiAgentRunner()

    assert asyncio.run(runner.start()) is None
    assert asyncio.run(runner.stop()) is None


