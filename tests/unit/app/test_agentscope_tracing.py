# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from types import SimpleNamespace

from qwenpaw.app import _app as app_module


def test_agentscope_tracing_skips_when_url_missing(monkeypatch):
    calls = []

    monkeypatch.delenv("AGENTSCOPE_TRACING_URL", raising=False)
    monkeypatch.setitem(
        app_module.sys.modules,
        "agentscope",
        SimpleNamespace(init=lambda **kwargs: calls.append(kwargs)),
    )

    assert app_module._init_agentscope_tracing_from_env() is False
    assert not calls


def test_agentscope_tracing_init_reads_env(monkeypatch):
    calls = []

    monkeypatch.setenv("AGENTSCOPE_TRACING_URL", " http://phoenix/v1/traces ")
    monkeypatch.setenv("AGENTSCOPE_TRACING_PROJECT", " demo-project ")
    monkeypatch.setenv("AGENTSCOPE_TRACING_NAME", " desktop ")
    monkeypatch.setenv("AGENTSCOPE_TRACING_RUN_ID", " run-1 ")
    monkeypatch.setenv("QWENPAW_LOG_LEVEL", "debug")
    monkeypatch.setitem(
        app_module.sys.modules,
        "agentscope",
        SimpleNamespace(init=lambda **kwargs: calls.append(kwargs)),
    )

    assert app_module._init_agentscope_tracing_from_env() is True
    assert calls == [
        {
            "project": "demo-project",
            "name": "desktop",
            "run_id": "run-1",
            "logging_level": "DEBUG",
            "tracing_url": "http://phoenix/v1/traces",
        },
    ]


def test_agentscope_tracing_uses_defaults(monkeypatch):
    calls = []

    monkeypatch.setenv("AGENTSCOPE_TRACING_URL", "http://phoenix/v1/traces")
    monkeypatch.delenv("AGENTSCOPE_TRACING_PROJECT", raising=False)
    monkeypatch.delenv("AGENTSCOPE_TRACING_NAME", raising=False)
    monkeypatch.delenv("AGENTSCOPE_TRACING_RUN_ID", raising=False)
    monkeypatch.delenv("QWENPAW_LOG_LEVEL", raising=False)
    monkeypatch.setitem(
        app_module.sys.modules,
        "agentscope",
        SimpleNamespace(init=lambda **kwargs: calls.append(kwargs)),
    )

    assert app_module._init_agentscope_tracing_from_env() is True
    assert calls == [
        {
            "project": "QwenPaw",
            "name": "qwenpaw-app",
            "run_id": None,
            "logging_level": "INFO",
            "tracing_url": "http://phoenix/v1/traces",
        },
    ]
