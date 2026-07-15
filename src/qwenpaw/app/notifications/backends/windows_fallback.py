# -*- coding: utf-8 -*-
"""Windows fallback using PowerShell toast notifications."""

from __future__ import annotations

import asyncio
import logging
import sys

from .base import NotificationBackend

logger = logging.getLogger(__name__)

_PS_TEMPLATE = """
[Windows.UI.Notifications.ToastNotificationManager, `
  Windows.UI.Notifications, `
  ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, `
  Windows.Data.Xml.Dom.XmlDocument, `
  ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{title}</text>
      <text>{body}</text>
    </binding>
  </visual>
  {audio}
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$mgr = [Windows.UI.Notifications.ToastNotificationManager]
$notifier = $mgr::CreateToastNotifier("{app_id}")
$notifier.Show($toast)
"""


class WindowsFallbackBackend(NotificationBackend):
    """Fallback for Windows using PowerShell toast notifications.

    Uses the Windows.UI.Notifications WinRT API via PowerShell.
    Available on Windows 10+ without extra dependencies.
    """

    def is_available(self) -> bool:
        return sys.platform == "win32"

    @staticmethod
    def _escape_xml(text: str) -> str:
        """Escape text for XML content."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    async def send(
        self,
        title: str,
        body: str,
        *,
        sound: bool = True,
        group: str = "QwenPaw",
    ) -> bool:
        audio_xml = (
            '<audio src="ms-winsoundevent:' 'Notification.Default" />'
            if sound
            else '<audio silent="true" />'
        )
        script = _PS_TEMPLATE.format(
            title=self._escape_xml(title),
            body=self._escape_xml(body),
            audio=audio_xml,
            app_id=self._escape_xml(group),
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=10,
            )
            if proc.returncode != 0:
                logger.debug(
                    "PowerShell toast failed: %s",
                    stderr.decode(errors="replace"),
                )
                return False
            return True
        except Exception as exc:
            logger.debug(
                "Windows fallback notification error: %s",
                exc,
            )
            return False
