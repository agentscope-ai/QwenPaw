# -*- coding: utf-8 -*-
"""Multi-user Browser policy and capacity contracts."""

import asyncio
from types import SimpleNamespace

import pytest

from qwenpaw.browser.execution.limits import BrowserSessionLimiter
from qwenpaw.browser.policy import effective_browser_policy, isolated_browser_config


def _config(**overrides):
    values = {
        "multi_user_enabled": False,
        "multi_user_global_limit": 2,
        "multi_user_per_user_limit": 1,
        "multi_user_queue_timeout_seconds": 0.01,
        "session_idle_ttl_seconds": 900.0,
        "identity": "auto",
        "backend": "connect_cdp",
        "context": "profile",
        "headless": "false",
        "cdp_url": "http://real-browser",
        "cdp_port": 9222,
        "user_data_dir": "/profile",
        "use_system_default": True,
        "executable_path": "system-chrome",
        "channel": "chrome",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_multi_user_browser_is_locked_by_default() -> None:
    policy = effective_browser_policy(_config(), multi_user=True)

    assert not policy.allowed
    assert policy.locked
    assert policy.reason == "browser_disabled_by_platform_policy"


def test_single_user_browser_keeps_existing_behavior() -> None:
    policy = effective_browser_policy(_config(), multi_user=False)

    assert policy.allowed
    assert not policy.locked


def test_multi_user_allowed_config_forces_isolated_guest_runtime() -> None:
    safe = isolated_browser_config(
        _config(multi_user_enabled=True),
        multi_user=True,
    )

    assert safe.identity == "guest"
    assert safe.backend == "launch"
    assert safe.context == "incognito"
    assert safe.headless == "true"
    assert safe.cdp_url is None
    assert safe.cdp_port == 0
    assert safe.user_data_dir is None
    assert safe.use_system_default is False
    assert safe.executable_path is None
    assert safe.channel is None


@pytest.mark.asyncio
async def test_limiter_enforces_per_user_and_releases_session() -> None:
    limiter = BrowserSessionLimiter(global_limit=2, per_user_limit=1, idle_ttl=60)

    assert await limiter.acquire("workspace/a", "user-a", timeout=0.01)
    assert not await limiter.acquire("workspace/b", "user-a", timeout=0.01)
    assert await limiter.acquire("workspace/c", "user-b", timeout=0.01)

    await limiter.release("workspace/a")
    assert await limiter.acquire("workspace/b", "user-a", timeout=0.01)


@pytest.mark.asyncio
async def test_limiter_same_session_is_idempotent_and_idle_lease_expires() -> None:
    limiter = BrowserSessionLimiter(global_limit=1, per_user_limit=1, idle_ttl=0.01)

    assert await limiter.acquire("workspace/a", "user-a", timeout=0.01)
    assert await limiter.acquire("workspace/a", "user-a", timeout=0.01)
    await asyncio.sleep(0.02)
    assert await limiter.acquire("workspace/b", "user-b", timeout=0.02)


@pytest.mark.asyncio
async def test_limiter_releases_all_sessions_for_workspace() -> None:
    limiter = BrowserSessionLimiter(global_limit=2, per_user_limit=2, idle_ttl=60)
    assert await limiter.acquire("workspace-a/chat-1", "user-a", timeout=0.01)
    assert await limiter.acquire("workspace-a/chat-2", "user-a", timeout=0.01)

    await limiter.release_workspace("workspace-a")

    assert await limiter.acquire("workspace-b/chat-1", "user-b", timeout=0.01)
