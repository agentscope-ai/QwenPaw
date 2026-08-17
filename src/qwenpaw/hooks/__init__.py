# -*- coding: utf-8 -*-
"""Business-layer lifecycle hooks.

Concrete hooks registered at startup via ``builtin_hook_clses``:
- SessionLoadHook / SessionSaveHook / SessionEarlySaveHook — session
  persistence (load, POST_RESPONSE save, PRE_EXECUTE early save)
- BootstrapHook — BOOTSTRAP.md first-interaction guidance
- SkillEnvHook / SkillEnvCleanupHook — skill env-var overrides
- ContextVarsSetupHook — per-request ContextVar injection (PRE_DISPATCH)
- AgentContextVarsSetupHook — agent-scoped toolkit/state ContextVars
  (POST_AGENT_BUILD)
- MediaProcessHook — file/media block processing
- ErrorNormalizeHook / CancelCleanupHook — error handling
"""

from __future__ import annotations

from .base import LifecycleHook

__all__ = ["LifecycleHook"]
