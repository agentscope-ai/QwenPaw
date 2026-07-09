# -*- coding: utf-8 -*-
"""Backend using the `desktop-notifier` library (cross-platform)."""

from __future__ import annotations

import logging
import webbrowser

from .base import NotificationBackend

logger = logging.getLogger(__name__)

_HAS_DESKTOP_NOTIFIER = False
_DesktopNotifier = None
_Sound = None

try:
    from desktop_notifier import DesktopNotifier as _DN, Sound as _S

    _HAS_DESKTOP_NOTIFIER = True
    _DesktopNotifier = _DN
    _Sound = _S
except ImportError:
    pass


class DesktopNotifierBackend(NotificationBackend):
    """Cross-platform backend powered by desktop-notifier."""

    def __init__(self) -> None:
        self._notifier = None
        self._authorized: bool | None = None
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
        url: str | None = None,
    ) -> bool:
        if self._notifier is None:
            return False
        try:
            if self._authorized is None:
                self._authorized = await self._notifier.has_authorisation()
            if not self._authorized:
                return False

            on_clicked = None
            if url:
                target_url = url

                def _open_url() -> None:
                    webbrowser.open(target_url)

                on_clicked = _open_url

            sound_obj = _Sound(name="default") if (sound and _Sound) else None
            await self._notifier.send(
                title=title,
                message=body,
                sound=sound_obj,
                on_clicked=on_clicked,
            )
            return True
        except Exception as exc:
            logger.debug("desktop-notifier send failed: %s", exc)
            return False
