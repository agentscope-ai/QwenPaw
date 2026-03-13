# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import sys
import types


MODULE_NAME = "copaw.app.crons.timezone_utils"


def _reload_timezone_utils(monkeypatch, env_value: str | None, tzlocal_module):
    monkeypatch.delenv("COPAW_TIMEZONE", raising=False)
    if env_value is not None:
        monkeypatch.setenv("COPAW_TIMEZONE", env_value)

    sys.modules.pop(MODULE_NAME, None)
    if tzlocal_module is None:
        sys.modules.pop("tzlocal", None)
    else:
        sys.modules["tzlocal"] = tzlocal_module

    return importlib.import_module(MODULE_NAME)


def test_get_default_timezone_prefers_env(monkeypatch) -> None:
    module = _reload_timezone_utils(
        monkeypatch,
        env_value="Asia/Shanghai",
        tzlocal_module=types.SimpleNamespace(
            get_localzone_name=lambda: "America/New_York",
        ),
    )

    assert module.get_default_timezone() == "Asia/Shanghai"


def test_get_default_timezone_uses_tzlocal_name(monkeypatch) -> None:
    module = _reload_timezone_utils(
        monkeypatch,
        env_value=None,
        tzlocal_module=types.SimpleNamespace(
            get_localzone_name=lambda: "Asia/Shanghai",
        ),
    )

    assert module.get_default_timezone() == "Asia/Shanghai"


def test_get_default_timezone_uses_tzlocal_zone_key(monkeypatch) -> None:
    module = _reload_timezone_utils(
        monkeypatch,
        env_value=None,
        tzlocal_module=types.SimpleNamespace(
            get_localzone_name=lambda: "",
            get_localzone=lambda: types.SimpleNamespace(key="Europe/Berlin"),
        ),
    )

    assert module.get_default_timezone() == "Europe/Berlin"


def test_get_default_timezone_falls_back_to_utc(monkeypatch) -> None:
    module = _reload_timezone_utils(
        monkeypatch,
        env_value=None,
        tzlocal_module=types.SimpleNamespace(
            get_localzone_name=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        ),
    )

    assert module.get_default_timezone() == module.DEFAULT_TIMEZONE


def test_schedule_spec_defaults_to_detected_timezone(monkeypatch) -> None:
    _reload_timezone_utils(
        monkeypatch,
        env_value="Asia/Shanghai",
        tzlocal_module=None,
    )
    sys.modules.pop("copaw.app.crons.models", None)
    from copaw.app.crons.models import ScheduleSpec

    spec = ScheduleSpec(cron="0 10 * * *")

    assert spec.timezone == "Asia/Shanghai"


def test_schedule_spec_keeps_explicit_timezone(monkeypatch) -> None:
    _reload_timezone_utils(
        monkeypatch,
        env_value="Asia/Shanghai",
        tzlocal_module=None,
    )
    sys.modules.pop("copaw.app.crons.models", None)
    from copaw.app.crons.models import ScheduleSpec

    spec = ScheduleSpec(cron="0 10 * * *", timezone="UTC")

    assert spec.timezone == "UTC"


def test_build_spec_from_cli_uses_detected_timezone(monkeypatch) -> None:
    _reload_timezone_utils(
        monkeypatch,
        env_value="Asia/Shanghai",
        tzlocal_module=None,
    )
    sys.modules.pop("copaw.cli.cron_cmd", None)
    from copaw.cli.cron_cmd import _build_spec_from_cli

    spec = _build_spec_from_cli(
        task_type="text",
        name="daily check",
        cron="0 10 * * *",
        channel="console",
        target_user="u1",
        target_session="s1",
        text="hello",
        timezone=None,
        enabled=True,
        mode="final",
    )

    assert spec["schedule"]["timezone"] == "Asia/Shanghai"


def test_get_default_timezone_uses_datetime_zone_key(monkeypatch) -> None:
    module = _reload_timezone_utils(
        monkeypatch,
        env_value=None,
        tzlocal_module=None,
    )

    class _FakeDateTime:
        @staticmethod
        def now():
            return types.SimpleNamespace(
                astimezone=lambda: types.SimpleNamespace(
                    tzinfo=types.SimpleNamespace(key="America/Los_Angeles"),
                ),
            )

    monkeypatch.setattr(module, "datetime", _FakeDateTime)

    assert module.get_default_timezone() == "America/Los_Angeles"


def test_build_spec_from_cli_keeps_explicit_timezone(monkeypatch) -> None:
    _reload_timezone_utils(
        monkeypatch,
        env_value="Asia/Shanghai",
        tzlocal_module=None,
    )
    sys.modules.pop("copaw.cli.cron_cmd", None)
    from copaw.cli.cron_cmd import _build_spec_from_cli

    spec = _build_spec_from_cli(
        task_type="text",
        name="daily check",
        cron="0 10 * * *",
        channel="console",
        target_user="u1",
        target_session="s1",
        text="hello",
        timezone="UTC",
        enabled=True,
        mode="final",
    )

    assert spec["schedule"]["timezone"] == "UTC"
