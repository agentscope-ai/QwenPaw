# -*- coding: utf-8 -*-
"""NotificationService — orchestrates backend selection and rate-limiting."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from qwenpaw.config.config import NotificationConfig

from .backends.base import NotificationBackend
from .backends.desktop import DesktopNotifierBackend
from .backends.linux_fallback import LinuxFallbackBackend
from .backends.macos_fallback import MacOSFallbackBackend
from .backends.macos_terminal_notifier import TerminalNotifierBackend
from .matcher import event_matches_rules

logger = logging.getLogger(__name__)

_I18N: dict[str, dict[str, str]] = {
    "en": {
        "approval_required": "Approval Required",
        "critical": "[Critical] ",
        "warning": "[Warning] ",
        "error": "[Error] ",
        "tool": "Tool",
        "new_inbox_messages": "{count} new inbox messages",
        "approval_pending": "{count} approval requests pending",
        "test_title": "QwenPaw Test",
        "test_body": "System notifications are working!",
        "source_cron": "Cron Job",
        "source_heartbeat": "Heartbeat",
        "source_memory": "Memory",
        "source_skill_autoupdate": "Skill Update",
    },
    "zh": {
        "approval_required": "需要审批",
        "critical": "[严重] ",
        "warning": "[警告] ",
        "error": "[错误] ",
        "tool": "工具",
        "new_inbox_messages": "{count} 条新收件箱消息",
        "approval_pending": "{count} 条审批请求待处理",
        "test_title": "QwenPaw 测试",
        "test_body": "系统通知功能正常！",
        "source_cron": "定时任务",
        "source_heartbeat": "心跳",
        "source_memory": "记忆",
        "source_skill_autoupdate": "技能更新",
    },
    "ja": {
        "approval_required": "承認が必要",
        "critical": "[重大] ",
        "warning": "[警告] ",
        "error": "[エラー] ",
        "tool": "ツール",
        "new_inbox_messages": "{count} 件の新しい受信メッセージ",
        "approval_pending": "{count} 件の承認リクエスト待ち",
        "test_title": "QwenPaw テスト",
        "test_body": "システム通知は正常に動作しています！",
        "source_cron": "定期タスク",
        "source_heartbeat": "ハートビート",
        "source_memory": "メモリ",
        "source_skill_autoupdate": "スキル更新",
    },
    "ru": {
        "approval_required": "Требуется подтверждение",
        "critical": "[Критич.] ",
        "warning": "[Предупр.] ",
        "error": "[Ошибка] ",
        "tool": "Инструмент",
        "new_inbox_messages": "{count} новых сообщений",
        "approval_pending": "{count} запросов на подтверждение",
        "test_title": "QwenPaw Тест",
        "test_body": "Системные уведомления работают!",
        "source_cron": "Задача",
        "source_heartbeat": "Пульс",
        "source_memory": "Память",
        "source_skill_autoupdate": "Обновление",
    },
    "pt-BR": {
        "approval_required": "Aprovação Necessária",
        "critical": "[Crítico] ",
        "warning": "[Alerta] ",
        "error": "[Erro] ",
        "tool": "Ferramenta",
        "new_inbox_messages": "{count} novas mensagens",
        "approval_pending": "{count} solicitações de aprovação",
        "test_title": "QwenPaw Teste",
        "test_body": "Notificações do sistema funcionando!",
        "source_cron": "Tarefa",
        "source_heartbeat": "Heartbeat",
        "source_memory": "Memória",
        "source_skill_autoupdate": "Atualização",
    },
}


def _t(lang: str, key: str, **kwargs: Any) -> str:
    """Get translated string by language key."""
    if lang in _I18N:
        base = lang
    else:
        base = lang.split("-")[0]
        if base not in _I18N:
            base = "en"
    text = _I18N[base].get(key, _I18N["en"].get(key, key))
    if kwargs:
        text = text.format(**kwargs)
    return text


class NotificationService:
    """Singleton-style service that manages notification dispatch.

    Handles:
    - Backend auto-selection with fallback chain
    - Rate-limiting to prevent notification storms
    - Batching excess events into a summary notification
    """

    def __init__(self) -> None:
        self._backends: list[NotificationBackend] = []
        self._last_sent_at: float = 0.0
        self._pending_count: int = 0
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_lang: str = "zh"
        self._flush_sound: bool = True
        self._init_backends()

    def _init_backends(self) -> None:
        """Build the ordered backend list for the current platform."""
        desktop = DesktopNotifierBackend()
        if desktop.is_available():
            self._backends.append(desktop)

        tn = TerminalNotifierBackend()
        if tn.is_available():
            self._backends.append(tn)

        macos_fb = MacOSFallbackBackend()
        if macos_fb.is_available():
            self._backends.append(macos_fb)

        linux_fb = LinuxFallbackBackend()
        if linux_fb.is_available():
            self._backends.append(linux_fb)

    @property
    def available(self) -> bool:
        """Whether at least one backend can deliver notifications."""
        return len(self._backends) > 0

    async def notify_event(
        self,
        event: dict[str, Any],
        config: NotificationConfig,
    ) -> None:
        """Check rules, rate-limit, and dispatch notification for *event*."""
        if not config.enabled:
            return
        if not self._backends:
            return
        if not event_matches_rules(event, config):
            return

        now = time.time()
        min_interval = config.min_interval_seconds
        lang = config.language
        self._flush_lang = lang
        self._flush_sound = config.sound

        source_type = event.get("source_type", "")
        payload = event.get("payload") or {}
        task_type = payload.get("task_type", "")
        skip_rate_limit = source_type == "cron" and task_type == "text"

        if not skip_rate_limit and now - self._last_sent_at < min_interval:
            self._pending_count += 1
            self._schedule_flush(min_interval)
            return

        if self._pending_count > 0 and not skip_rate_limit:
            title = "QwenPaw"
            body = _t(
                lang,
                "new_inbox_messages",
                count=self._pending_count + 1,
            )
            self._pending_count = 0
        else:
            title = self._format_title(event, lang)
            body = self._format_body(event)

        self._last_sent_at = now
        self._cancel_flush()
        await self._send(title, body, sound=config.sound)

    def _schedule_flush(self, delay: float) -> None:
        """Schedule a delayed flush to send accumulated notifications."""
        if self._flush_task and not self._flush_task.done():
            return
        self._flush_task = asyncio.create_task(
            self._delayed_flush(delay),
            name="notification-flush",
        )

    def _cancel_flush(self) -> None:
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            self._flush_task = None

    async def _delayed_flush(self, delay: float) -> None:
        """Wait then send accumulated notification count."""
        await asyncio.sleep(delay + 0.5)
        if self._pending_count > 0:
            title = "QwenPaw"
            body = _t(
                self._flush_lang,
                "new_inbox_messages",
                count=self._pending_count,
            )
            self._pending_count = 0
            self._last_sent_at = time.time()
            await self._send(title, body, sound=self._flush_sound)

    async def notify_approval(
        self,
        config: NotificationConfig,
        *,
        tool_name: str,
        severity: str,
        agent_id: str,
        findings_summary: str = "",
    ) -> None:
        """Send a system notification for a pending security approval.

        Approvals always send individually (no batching with inbox events)
        but still respect a short rate-limit to avoid duplicates.
        """
        if not config.enabled:
            return
        if not config.sources.approval:
            return
        if not self._backends:
            return

        if config.agent_ids is not None:
            if agent_id not in config.agent_ids:
                return

        lang = config.language
        prefix = ""
        if severity in ("critical", "high"):
            prefix = _t(lang, "critical")
        elif severity == "medium":
            prefix = _t(lang, "warning")

        title = f"{prefix}QwenPaw - {_t(lang, 'approval_required')}"
        body = f"{_t(lang, 'tool')}: {tool_name}"
        if findings_summary:
            body += f"\n{findings_summary}"
        if len(body) > 200:
            body = body[:197] + "..."

        await self._send(title, body, sound=config.sound)

    async def send_test(self, config: NotificationConfig) -> bool:
        """Send a test notification, bypassing rules and rate-limit."""
        if not self._backends:
            return False
        lang = config.language
        return await self._send(
            title=_t(lang, "test_title"),
            body=_t(lang, "test_body"),
            sound=config.sound,
        )

    async def _send(
        self,
        title: str,
        body: str,
        *,
        sound: bool,
    ) -> bool:
        """Try backends in order until one succeeds."""
        for backend in self._backends:
            try:
                ok = await backend.send(title, body, sound=sound)
                if ok:
                    return True
            except Exception as exc:
                logger.debug(
                    "Backend %s failed: %s",
                    type(backend).__name__,
                    exc,
                )
        return False

    @staticmethod
    def _format_title(event: dict[str, Any], lang: str) -> str:
        source = event.get("source_type", "")
        source_label = _t(lang, f"source_{source}")
        if source_label == f"source_{source}":
            source_label = source
        severity = event.get("severity", "info")
        prefix = ""
        if severity == "error":
            prefix = _t(lang, "error")
        elif severity == "warning":
            prefix = _t(lang, "warning")
        return f"{prefix}QwenPaw - {source_label}"

    @staticmethod
    def _format_body(event: dict[str, Any]) -> str:
        title = event.get("title", "")
        body = event.get("body", "")
        title = re.sub(
            r"^(?:Cron result|Cron result not delivered):\s*",
            "",
            title,
        )
        # Generic heartbeat titles are redundant when we have body
        if body and title in (
            "Heartbeat result",
            "Heartbeat timed out",
            "Heartbeat execution failed",
        ):
            title = ""
        if title and body:
            combined = f"{title}\n{body}"
        else:
            combined = title or body or "New notification"
        if len(combined) > 200:
            combined = combined[:197] + "..."
        return combined


_service: NotificationService | None = None


def get_notification_service() -> NotificationService:
    """Get or create the global NotificationService instance."""
    global _service
    if _service is None:
        _service = NotificationService()
    return _service
