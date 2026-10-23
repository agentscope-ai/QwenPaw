# -*- coding: utf-8 -*-
"""Run Telegram contracts outside repository-wide platform mocks."""

import pytest

from tests.isolated_pytest import run_isolated_pytest

_CARD_ACTOR_CASES = (
    "test_real_native_actor_display_and_compact_result_keep_owned_context or "
    "test_non_guard_native_callback_cannot_enqueue_or_edit_a_card or "
    "test_missing_actor_expires_without_cached_requester"
)


@pytest.mark.parametrize(
    "suite_name",
    [
        "telegram_contract_suite.py",
        "telegram_control_suite.py",
        "telegram_config_suite.py",
        "telegram_pure_suite.py",
        "telegram_business_suite.py",
        "telegram_route_suite.py",
        "telegram_media_suite.py",
        # Every card case creates a worker and binds the real host runtime,
        # starting a second worker. Bound aggregate work in two complementary
        # groups while preserving the existing RPC and wrapper timeouts.
        pytest.param(
            ("telegram_cards_suite.py", f"not ({_CARD_ACTOR_CASES})"),
            id="telegram_cards_suite.py-approval",
        ),
        pytest.param(
            ("telegram_cards_suite.py", _CARD_ACTOR_CASES),
            id="telegram_cards_suite.py-actor",
        ),
        "telegram_stream_suite.py",
        "telegram_reliability_suite.py",
        "telegram_polling_suite.py",
        "telegram_actual_agent_suite.py",
        "telegram_lifecycle_suite.py",
        "telegram_backoff_suite.py",
        "telegram_edge_suite.py",
        "telegram_fix1_suite.py",
        "telegram_legacy_oracle_suite.py",
    ],
)
def test_telegram_plugin(tmp_path, suite_name):
    test_filter = None
    if isinstance(suite_name, tuple):
        suite_name, test_filter = suite_name
    run_isolated_pytest(
        suite_name,
        env={
            "QWENPAW_WORKING_DIR": str(tmp_path / "host"),
            "QWENPAW_SECRET_DIR": str(tmp_path / "secrets"),
            "QWENPAW_BACKUP_DIR": str(tmp_path / "backups"),
        },
        timeout=120,
        test_filter=test_filter,
    )
