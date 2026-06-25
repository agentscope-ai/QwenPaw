# -*- coding: utf-8 -*-
"""Business-layer lifecycle hooks.

Concrete hooks registered at startup via ``builtin_hook_clses``:
- SessionLoadHook / SessionSaveHook — session persistence
- BootstrapHook — BOOTSTRAP.md first-interaction guidance
- SkillEnvHook / SkillEnvCleanupHook — skill env-var overrides
- ContextVarsSetupHook — per-request ContextVar injection
- MediaProcessHook — file/media block processing
- ErrorNormalizeHook / CancelCleanupHook — error handling
"""

from __future__ import annotations

from .base import LifecycleHook

__all__ = ["LifecycleHook"]
