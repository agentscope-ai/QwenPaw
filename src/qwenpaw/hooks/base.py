# -*- coding: utf-8 -*-
"""``LifecycleHook`` base class.

Marker subclass of :class:`HookBase` used by always-on, cross-mode
hooks (session load/save, bootstrap, skill env, context-var cleanup,
cron triggers …). The distinction from
:class:`qwenpaw.modes.base.ModeGatedHook`:

* ``LifecycleHook`` — runs on every request that reaches its phase.
* ``ModeGatedHook`` — runs only when its owner mode reports
  ``is_active(ctx)``.

Splitting them at the class level lets new authors pick the right base
by intent alone, without having to remember to write a gate by hand.
"""

from __future__ import annotations

from ..runtime.hooks import HookBase


class LifecycleHook(HookBase):
    """Base class for hooks that should run regardless of active mode."""


__all__ = ["LifecycleHook"]
