# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def fake_driver_secret_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "qwenpaw.drivers.credentials.store.encrypt",
        lambda value: f"ENC:{value}",
    )
    monkeypatch.setattr(
        "qwenpaw.drivers.credentials.store.decrypt",
        lambda value: value.removeprefix("ENC:"),
    )
    monkeypatch.setattr(
        "qwenpaw.drivers.credentials.store.is_encrypted",
        lambda value: isinstance(value, str) and value.startswith("ENC:"),
    )
