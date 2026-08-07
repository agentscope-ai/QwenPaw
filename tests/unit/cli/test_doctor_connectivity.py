# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.cli import doctor_connectivity
from qwenpaw.config.config import OneBotConfig, TelegramConfig


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


def _probe_onebot(cfg: OneBotConfig, monkeypatch) -> tuple[list[str], list]:
    """Run the OneBot probe with a stubbed TCP check.

    Returns the emitted notes and the hosts that were probed.
    """
    probed: list = []

    def _fake_tcp_check(host: str, port: int, timeout: float) -> None:
        # Returning None tells the probe that the port is reachable.
        probed.append((host, port, timeout))

    monkeypatch.setattr(doctor_connectivity, "_tcp_check", _fake_tcp_check)
    # pylint: disable-next=protected-access
    notes = doctor_connectivity._probe_onebot("default", cfg, 3.0)
    return notes, probed


def test_probe_onebot_warns_when_exposed_without_token(monkeypatch) -> None:
    notes, _ = _probe_onebot(
        OneBotConfig(enabled=True, ws_host="0.0.0.0", access_token=""),
        monkeypatch,
    )

    assert len(notes) == 1
    assert "access_token is empty" in notes[0]


@pytest.mark.parametrize(
    "ws_host, access_token",
    [
        ("127.0.0.1", ""),
        ("0.0.0.0", "s3cret-token"),
    ],
)
def test_probe_onebot_stays_quiet_when_safe(
    ws_host: str,
    access_token: str,
    monkeypatch,
) -> None:
    notes, _ = _probe_onebot(
        OneBotConfig(
            enabled=True,
            ws_host=ws_host,
            access_token=access_token,
        ),
        monkeypatch,
    )

    assert not notes


@pytest.mark.parametrize(
    "ws_host, expected",
    [
        ("0.0.0.0", "127.0.0.1"),
        ("", "127.0.0.1"),
        # Winsock rejects a wildcard connect target, so :: must be
        # probed via the loopback address of its own family.
        ("::", "::1"),
        ("[::1]", "::1"),
    ],
)
def test_probe_onebot_probe_target(
    ws_host: str,
    expected: str,
    monkeypatch,
) -> None:
    _, probed = _probe_onebot(
        OneBotConfig(
            enabled=True,
            ws_host=ws_host,
            access_token="s3cret-token",
        ),
        monkeypatch,
    )

    assert probed == [(expected, 6199, 3.0)]
