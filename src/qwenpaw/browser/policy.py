# -*- coding: utf-8 -*-
"""Platform policy projection for Browser in multi-user deployments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BrowserPolicy:
    allowed: bool
    locked: bool
    reason: str | None = None


def effective_browser_policy(config: Any, *, multi_user: bool) -> BrowserPolicy:
    if not multi_user:
        return BrowserPolicy(allowed=True, locked=False)
    if not bool(getattr(config, "multi_user_enabled", False)):
        return BrowserPolicy(
            allowed=False,
            locked=True,
            reason="browser_disabled_by_platform_policy",
        )
    return BrowserPolicy(allowed=True, locked=False)


def isolated_browser_config(config: Any, *, multi_user: bool) -> Any:
    """Return the only launch configuration permitted for many users."""
    if not multi_user:
        return config
    policy = effective_browser_policy(config, multi_user=True)
    if not policy.allowed:
        raise PermissionError(policy.reason)
    updates = {
        "identity": "guest",
        "backend": "launch",
        "context": "incognito",
        "headless": "true",
        "cdp_url": None,
        "cdp_port": 0,
        "user_data_dir": None,
        "use_system_default": False,
        "executable_path": None,
        "channel": None,
        "args": [],
    }
    copier = getattr(config, "model_copy", None)
    if callable(copier):
        return copier(update=updates)
    from types import SimpleNamespace

    values = dict(vars(config))
    values.update(updates)
    return SimpleNamespace(**values)
