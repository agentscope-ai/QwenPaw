# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for notification-related config models."""

from unittest.mock import MagicMock, patch

from qwenpaw.config.config import (
    NotificationSourceToggles,
    _detect_notification_language,
)


# ── _detect_notification_language ─────────────────────────────────


class TestDetectNotificationLanguage:
    def test_chinese_locale(self):
        with patch(
            "locale.getlocale",
            return_value=("zh_CN", "UTF-8"),
        ):
            assert _detect_notification_language() == "zh"

    def test_english_locale(self):
        with patch(
            "locale.getlocale",
            return_value=("en_US", "UTF-8"),
        ):
            assert _detect_notification_language() == "en"

    def test_japanese_locale(self):
        with patch(
            "locale.getlocale",
            return_value=("ja_JP", "UTF-8"),
        ):
            assert _detect_notification_language() == "ja"

    def test_russian_locale(self):
        with patch(
            "locale.getlocale",
            return_value=("ru_RU", "UTF-8"),
        ):
            assert _detect_notification_language() == "ru"

    def test_portuguese_locale(self):
        with patch(
            "locale.getlocale",
            return_value=("pt_BR", "UTF-8"),
        ):
            assert _detect_notification_language() == "pt"

    def test_unsupported_locale_fallback(self):
        with patch(
            "locale.getlocale",
            return_value=("ko_KR", "UTF-8"),
        ):
            assert _detect_notification_language() == "en"

    def test_none_locale_fallback(self):
        with patch(
            "locale.getlocale",
            return_value=(None, None),
        ):
            assert _detect_notification_language() == "en"

    def test_exception_fallback(self):
        with patch(
            "locale.getlocale",
            side_effect=ValueError("bad locale"),
        ):
            assert _detect_notification_language() == "en"


# ── NotificationSourceToggles migration ──────────────────────────


class TestSourceTogglesMigration:
    def test_legacy_cron_field_migrated(self):
        toggles = NotificationSourceToggles(
            **{"cron": True, "approval": False},
        )
        assert toggles.cron_text is True
        assert toggles.cron_agent is True
        assert toggles.approval is False

    def test_legacy_cron_false(self):
        toggles = NotificationSourceToggles(
            **{"cron": False},
        )
        assert toggles.cron_text is False
        assert toggles.cron_agent is False

    def test_explicit_fields_not_overridden(self):
        toggles = NotificationSourceToggles(
            **{"cron": True, "cron_text": False},
        )
        assert toggles.cron_text is False
        assert toggles.cron_agent is True


# ── _resolve_system_notify ───────────────────────────────────────


class TestResolveSystemNotify:
    @staticmethod
    def _make_job(
        system_notify=None,
        save_result_to_inbox=None,
    ):
        job = MagicMock()
        job.system_notify = system_notify
        job.save_result_to_inbox = save_result_to_inbox
        return job

    def test_explicit_true(self):
        from qwenpaw.app.crons.manager import CronManager

        job = self._make_job(system_notify=True)
        assert CronManager._resolve_system_notify(job) is True

    def test_explicit_false(self):
        from qwenpaw.app.crons.manager import CronManager

        job = self._make_job(system_notify=False)
        assert CronManager._resolve_system_notify(job) is False

    def test_fallback_to_save_result_true(self):
        from qwenpaw.app.crons.manager import CronManager

        job = self._make_job(save_result_to_inbox=True)
        assert CronManager._resolve_system_notify(job) is True

    def test_fallback_to_save_result_false(self):
        from qwenpaw.app.crons.manager import CronManager

        job = self._make_job(save_result_to_inbox=False)
        assert CronManager._resolve_system_notify(job) is False

    def test_fallback_to_save_result_none(self):
        from qwenpaw.app.crons.manager import CronManager

        job = self._make_job(save_result_to_inbox=None)
        assert CronManager._resolve_system_notify(job) is False
