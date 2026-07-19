# -*- coding: utf-8 -*-
"""Tests for NotificationService — formatting, rate-limit, backends."""

# pylint: disable=protected-access
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.notifications.service import (
    NotificationService,
    _t,
)
from qwenpaw.config.config import (
    NotificationConfig,
    NotificationSourceToggles,
)


def _cfg(**overrides):
    defaults = {
        "enabled": True,
        "sound": True,
        "min_interval_seconds": 5,
        "sources": NotificationSourceToggles(),
        "language": "en",
        "agent_ids": None,
        "rules": [],
    }
    defaults.update(overrides)
    return NotificationConfig(**defaults)


# ── _t (i18n helper) ─────────────────────────────────────────────


class TestI18n:
    def test_english_key(self):
        assert _t("en", "test_title") == "QwenPaw Test"

    def test_chinese_key(self):
        assert _t("zh", "test_body") == "系统通知功能正常！"

    def test_fallback_to_base_lang(self):
        result = _t("zh-CN", "test_title")
        assert result == "QwenPaw 测试"

    def test_unknown_lang_fallback_to_en(self):
        result = _t("ko", "test_title")
        assert result == "QwenPaw Test"

    def test_format_substitution(self):
        result = _t("en", "new_inbox_messages", count=3)
        assert result == "3 new inbox messages"

    def test_missing_key_returns_key(self):
        result = _t("en", "nonexistent_key_xyz")
        assert result == "nonexistent_key_xyz"


# ── _format_title / _format_body ─────────────────────────────────


class TestFormatting:
    def test_format_title_cron(self):
        event = {
            "source_type": "cron",
            "severity": "info",
        }
        title = NotificationService._format_title(event, "en")
        assert "Cron Job" in title
        assert "QwenPaw" in title

    def test_format_title_error_prefix(self):
        event = {
            "source_type": "heartbeat",
            "severity": "error",
        }
        title = NotificationService._format_title(event, "en")
        assert "[Error]" in title

    def test_format_title_warning_prefix(self):
        event = {
            "source_type": "memory",
            "severity": "warning",
        }
        title = NotificationService._format_title(event, "en")
        assert "[Warning]" in title

    def test_format_title_info_no_prefix(self):
        event = {
            "source_type": "cron",
            "severity": "info",
        }
        title = NotificationService._format_title(event, "en")
        assert "[Error]" not in title
        assert "[Warning]" not in title

    def test_format_title_unknown_source(self):
        event = {
            "source_type": "new_thing",
            "severity": "info",
        }
        title = NotificationService._format_title(event, "en")
        assert "new_thing" in title

    def test_format_body_strips_cron_result_prefix(self):
        event = {
            "title": "Cron result: my-job",
            "body": "Hello world",
        }
        body = NotificationService._format_body(event)
        assert body == "my-job\nHello world"

    def test_format_body_strips_delivery_prefix(self):
        event = {
            "title": "Cron result not delivered: job-x",
            "body": "delivery failed",
        }
        body = NotificationService._format_body(event)
        assert body == "job-x\ndelivery failed"

    def test_format_body_heartbeat_hides_generic_title(self):
        event = {
            "title": "Heartbeat result",
            "body": "All systems OK",
        }
        body = NotificationService._format_body(event)
        assert body == "All systems OK"

    def test_format_body_truncates_long_text(self):
        event = {
            "title": "",
            "body": "x" * 300,
        }
        body = NotificationService._format_body(event)
        assert len(body) == 200
        assert body.endswith("...")

    def test_format_body_no_content_fallback(self):
        event = {"title": "", "body": ""}
        body = NotificationService._format_body(event)
        assert body == "New notification"


# ── Rate-limiting ────────────────────────────────────────────────


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_first_event_sent_immediately(self):
        svc = NotificationService()
        mock_backend = AsyncMock()
        mock_backend.send = AsyncMock(return_value=True)
        mock_backend.is_available = lambda: True
        svc._backends = [mock_backend]

        config = _cfg(min_interval_seconds=60)
        event = {
            "source_type": "approval",
            "agent_id": "default",
            "severity": "info",
            "title": "Test",
            "body": "body",
        }
        await svc.notify_event(event, config)
        mock_backend.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_second_event_within_interval_batched(self):
        svc = NotificationService()
        mock_backend = AsyncMock()
        mock_backend.send = AsyncMock(return_value=True)
        mock_backend.is_available = lambda: True
        svc._backends = [mock_backend]

        config = _cfg(min_interval_seconds=60)
        event = {
            "source_type": "approval",
            "agent_id": "default",
            "severity": "info",
            "title": "Test",
            "body": "body",
        }
        await svc.notify_event(event, config)
        assert mock_backend.send.call_count == 1

        await svc.notify_event(event, config)
        assert mock_backend.send.call_count == 1
        assert svc._pending_count == 1

    @pytest.mark.asyncio
    async def test_text_cron_skips_rate_limit(self):
        svc = NotificationService()
        mock_backend = AsyncMock()
        mock_backend.send = AsyncMock(return_value=True)
        mock_backend.is_available = lambda: True
        svc._backends = [mock_backend]

        config = _cfg(
            min_interval_seconds=60,
            sources=NotificationSourceToggles(cron_text=True),
        )
        event1 = {
            "source_type": "cron",
            "agent_id": "default",
            "severity": "info",
            "title": "reminder",
            "body": "Take a break",
            "payload": {"task_type": "text"},
        }
        await svc.notify_event(event1, config)
        await svc.notify_event(event1, config)
        assert mock_backend.send.call_count == 2

    @pytest.mark.asyncio
    async def test_disabled_config_blocks_event(self):
        svc = NotificationService()
        mock_backend = AsyncMock()
        mock_backend.send = AsyncMock(return_value=True)
        mock_backend.is_available = lambda: True
        svc._backends = [mock_backend]

        config = _cfg(enabled=False)
        event = {
            "source_type": "approval",
            "agent_id": "default",
        }
        await svc.notify_event(event, config)
        mock_backend.send.assert_not_called()


# ── Backend fallback chain ───────────────────────────────────────


class TestBackendFallback:
    @pytest.mark.asyncio
    async def test_tries_next_backend_on_failure(self):
        svc = NotificationService()
        fail_backend = AsyncMock()
        fail_backend.send = AsyncMock(return_value=False)
        ok_backend = AsyncMock()
        ok_backend.send = AsyncMock(return_value=True)
        svc._backends = [fail_backend, ok_backend]

        result = await svc._send(
            "title",
            "body",
            sound=True,
        )
        assert result is True
        fail_backend.send.assert_called_once()
        ok_backend.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_backends_fail(self):
        svc = NotificationService()
        fail1 = AsyncMock()
        fail1.send = AsyncMock(return_value=False)
        fail2 = AsyncMock()
        fail2.send = AsyncMock(return_value=False)
        svc._backends = [fail1, fail2]

        result = await svc._send(
            "title",
            "body",
            sound=True,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_no_backends_available(self):
        svc = NotificationService()
        svc._backends = []
        assert svc.available is False

        result = await svc.send_test(_cfg())
        assert result is False


# ── send_test ────────────────────────────────────────────────────


class TestSendTest:
    @pytest.mark.asyncio
    async def test_send_test_uses_config_language(self):
        svc = NotificationService()
        mock_backend = AsyncMock()
        mock_backend.send = AsyncMock(return_value=True)
        svc._backends = [mock_backend]

        config = _cfg(language="zh")
        result = await svc.send_test(config)
        assert result is True
        call_args = mock_backend.send.call_args
        title_arg = call_args[0][0]  # first positional arg
        assert "QwenPaw 测试" in title_arg


# ── notify_approval ──────────────────────────────────────────────


class TestNotifyApproval:
    @pytest.mark.asyncio
    async def test_approval_off_blocks(self):
        svc = NotificationService()
        mock_backend = AsyncMock()
        mock_backend.send = AsyncMock(return_value=True)
        svc._backends = [mock_backend]

        config = _cfg(
            sources=NotificationSourceToggles(approval=False),
        )
        await svc.notify_approval(
            config,
            tool_name="rm",
            severity="high",
            agent_id="default",
        )
        mock_backend.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_approval_agent_filter(self):
        svc = NotificationService()
        mock_backend = AsyncMock()
        mock_backend.send = AsyncMock(return_value=True)
        svc._backends = [mock_backend]

        config = _cfg(agent_ids=["agent-a"])
        await svc.notify_approval(
            config,
            tool_name="rm",
            severity="high",
            agent_id="agent-b",
        )
        mock_backend.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_approval_critical_prefix(self):
        svc = NotificationService()
        mock_backend = AsyncMock()
        mock_backend.send = AsyncMock(return_value=True)
        svc._backends = [mock_backend]

        config = _cfg(language="en")
        await svc.notify_approval(
            config,
            tool_name="rm",
            severity="critical",
            agent_id="default",
        )
        call_args = mock_backend.send.call_args
        title_arg = call_args[0][0]  # first positional arg
        assert "[Critical]" in title_arg
