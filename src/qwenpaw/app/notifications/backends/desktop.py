# -*- coding: utf-8 -*-
"""Backend using the `desktop-notifier` library (cross-platform)."""

from __future__ import annotations

import logging
import time

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

_AUTH_RECHECK_INTERVAL = 120  # seconds


class DesktopNotifierBackend(NotificationBackend):
    """Cross-platform backend powered by desktop-notifier."""

    def __init__(self) -> None:
        self._notifier = None
        self._authorized: bool | None = None
        self._auth_checked_at: float = 0.0
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

    async def _check_authorisation(self) -> bool:
        """Check notification authorisation.

        desktop-notifier 6.x may raise ``InvalidStateError`` in an
        Objective-C callback when macOS denies authorisation.  We
        catch all exceptions and treat them as "not authorised".
        """
        try:
            return await self._notifier.has_authorisation()
        except Exception:
            logger.debug(
                "Authorisation check failed (expected on "
                "macOS when permission is denied)",
                exc_info=True,
            )
            return False

    async def send(
        self,
        title: str,
        body: str,
        *,
        sound: bool = True,
        group: str = "QwenPaw",
    ) -> bool:
        if self._notifier is None:
            return False
        try:
            now = time.monotonic()
            if self._authorized is None or (
                not self._authorized
                and now - self._auth_checked_at >= _AUTH_RECHECK_INTERVAL
            ):
                self._authorized = await self._check_authorisation()
                self._auth_checked_at = now
            if not self._authorized:
                return False

            sound_obj = _Sound(name="default") if (sound and _Sound) else None
            await self._notifier.send(
                title=title,
                message=body,
                sound=sound_obj,
            )
            return True
        except Exception as exc:
            logger.debug("desktop-notifier send failed: %s", exc)
            return False
