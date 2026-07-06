# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.cli import doctor_connectivity
from qwenpaw.config.config import TelegramConfig


def test_probe_telegram_uses_custom_base_url(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_get_ok(url: str, timeout: float) -> None:
        captured["url"] = url
        captured["timeout"] = timeout

    monkeypatch.setattr(doctor_connectivity, "_http_get_ok", _fake_get_ok)

    # pylint: disable-next=protected-access
    result = doctor_connectivity._probe_telegram(
        "default",
        TelegramConfig(base_url=" https://tg-api.example.com/ "),
        3.0,
    )

    assert not result
    assert captured == {
        "url": "https://tg-api.example.com",
        "timeout": 3.0,
    }
