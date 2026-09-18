# -*- coding: utf-8 -*-
"""Unit tests for safe plugin hook execution.

Verifies:
1. Sync hooks are offloaded to threads, avoiding event loop freeze.
2. Hook timeouts are enforced, preventing hangs during startup/shutdown.
"""

import asyncio
import threading
import time
import pytest
from qwenpaw.plugins.registry import HookRegistration
from qwenpaw.app._app import _safe_execute_plugin_hook


@pytest.mark.asyncio
async def test_safe_execute_sync_hook_in_thread():
    """Test that a synchronous hook runs in a thread without freezing
    the loop.
    """
    called_thread_ids = []

    def sync_hook():
        import threading
        called_thread_ids.append(threading.get_ident())
        time.sleep(0.05)
        return "done"

    hook = HookRegistration(
        plugin_id="test-plugin",
        hook_name="test_sync",
        callback=sync_hook,
    )

    loop_thread_id = (
        threading.get_ident() if hasattr(threading, "get_ident") else None
    )
    await _safe_execute_plugin_hook(hook, hook_type="startup", timeout_sec=1.0)

    assert len(called_thread_ids) == 1
    # Hook must run in a separate worker thread, not the loop thread
    assert called_thread_ids[0] != loop_thread_id


@pytest.mark.asyncio
async def test_safe_execute_hook_timeout():
    """Test that an excessively long hook is timed out gracefully without
    crashing.
    """
    def hanging_hook():
        time.sleep(1.0)

    hook = HookRegistration(
        plugin_id="hanging-plugin",
        hook_name="hang",
        callback=hanging_hook,
    )

    t0 = time.time()
    # Execute with a tight 0.1s timeout
    await _safe_execute_plugin_hook(hook, hook_type="startup", timeout_sec=0.1)
    elapsed = time.time() - t0

    # Should have timed out and returned well before 1.0s
    assert elapsed < 0.5
