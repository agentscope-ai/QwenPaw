# -*- coding: utf-8 -*-
"""Backend using the `desktop-notifier` library (cross-platform)."""

from __future__ import annotations

import logging

from .base import NotificationBackend

logger = logging.getLogger(__name__)

_HAS_DESKTOP_NOTIFIER = False
_DesktopNotifier = None
_Notification = None

try:
    from desktop_notifier import DesktopNotifier as _DN, Notification as _N

    _HAS_DESKTOP_NOTIFIER = True
    _DesktopNotifier = _DN
    _Notification = _N
except ImportError:
    pass


class DesktopNotifierBackend(NotificationBackend):
    """Cross-platform backend powered by desktop-notifier."""

    def __init__(self) -> None:
        self._notifier = None
        if _HAS_DESKTOP_NOTIFIER and _DesktopNotifier is not None:
            try:
                self._notifier = _DesktopNotifier(app_name="QwenPaw")
            except Exception as exc:
                logger.debug(
                    "Failed to instantiate DesktopNotifier: %s",
                    exc,
                )

    def is_available(self) -> bool:
        return self._notifier is not None

    async def send(
        self,
        title: str,
        body: str,
        *,
        sound: bool = True,
    ) -> bool:
        if self._notifier is None or _Notification is None:
            return False
        try:
            await self._notifier.send(
                _Notification(
                    title=title,
                    message=body,
                    sound=sound,
                ),
            )
            return True
        except Exception as exc:
            logger.debug("desktop-notifier send failed: %s", exc)
            return False
