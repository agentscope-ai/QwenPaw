# -*- coding: utf-8 -*-
"""Mail integration helpers.

Keep the monitor import lazy: DriverCard configuration does not require the
optional ``qwenpawmail_mcp`` runtime package during module discovery.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .monitor import MailMonitorService

__all__ = ["MailMonitorService"]


def __getattr__(name: str):
    if name == "MailMonitorService":
        from .monitor import MailMonitorService

        return MailMonitorService
    raise AttributeError(name)
